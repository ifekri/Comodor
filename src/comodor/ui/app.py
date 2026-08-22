"""The application: input, state, and the frame loop.

Three threads share the work and never share memory. The **input thread** reads
the terminal and posts events. A **worker thread** runs the agent and posts
events. The **main thread** owns every piece of state and does all the drawing.
Everything crossing a thread boundary is an event object, which is why a
three-minute shell command cannot freeze the interface.

Frames are drawn only when something changed and at most ``max_fps`` times a
second. A streaming answer produces hundreds of deltas per second; coalescing
them into ~20 repaints keeps the terminal responsive and the CPU quiet.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from rich.live import Live

from ..agent import AgentLoop, Conversation
from ..agent.spawn import spawner
from ..config import Config, save_user_config
from ..events import Cancelled, EventBus, EventQueue, Kind, Request
from ..learning import LearningEngine
from ..mcp import MCPManager
from ..mcp.manager import SEPARATOR
from ..providers import registry
from ..providers.fake import demo_scripts
from ..providers.gateway import Gateway
from ..safety import CheckpointStore, PermissionEngine, Redactor
from ..session import SessionIndex, SessionMeta, SessionStore, derive_title, new_session_id
from ..skills import candidates as skill_candidates
from ..skills import load_for as skills_for
from ..tools import ToolRegistry
from ..tools.delegate import Delegate
from . import banner
from . import console as console_module
from . import layout as layout_module
from .input import KeyEvent, MouseEvent, PasteEvent, TerminalInput
from .screen import Screen, ScreenState
from .widgets.chat import Entry, entries_from
from .widgets.history import SessionRef
from .widgets.overlay import info_overlay, permission_overlay, select_overlay
from .widgets.statusbar import StatusModel

#: How long quitting waits for a turn in flight. Quitting mid-task should give
#: the agent a moment to stop rather than abandoning it, so shutting down can
#: legitimately take this long — which is what anything timing the exit has to
#: allow for.
SHUTDOWN_JOIN_SECONDS = 2.0
IDLE_SLEEP = 0.02
SPINNER_INTERVAL = 0.1
# How long the prompt must sit still before recall is warmed for the draft.
PREFETCH_IDLE = 0.15


class App:
    """One running instance of Comodor."""

    def __init__(self, config: Config, demo: bool = False,
                 resume: str | None = None) -> None:
        self.config = config
        self.demo = demo

        self.theme = console_module.prepare_theme(
            config.ui.theme, config.ui.ascii_borders, no_color=False,
            syntax=config.ui.syntax_theme)
        self.console = console_module.build(self.theme)
        self.screen = Screen(self.console, self.theme)

        self.bus = EventBus()
        self.events = EventQueue(self.bus)
        self.gateway = Gateway(config, scripts=demo_scripts() if demo else None)
        self.permissions = PermissionEngine(config, self.bus)

        # Reflex needs the checkpoint journal: it is what records the exact bytes
        # the agent left in each file, so a later hand-edit can be recognised.
        self.checkpoints = CheckpointStore(config.paths.checkpoints)
        self.memory = LearningEngine(
            config, self.bus, self.gateway,
            checkpoints=self.checkpoints,
            redact=Redactor([entry.api_key for entry in config.providers.values()
                             if entry.api_key]),
        )
        # A refusal is a preference, so route it into the brain rather than
        # letting it end at "no".
        self.permissions.on_denied = self.memory.on_denied
        self.conversation = Conversation()

        # Authored skills: the user's own procedures, loaded from their folder
        # and from the project's. Separate from the learned brain on purpose —
        # one is written by hand, the other is inferred.
        self.sessions = SessionStore(config.paths.user / "sessions")
        self.session = SessionMeta(
            id=new_session_id(), cwd=str(config.paths.project),
            provider=config.provider, model=config.active_model(),
        )

        # Everything ever said, searchable. Built from the transcripts already
        # on disk, so it costs nothing to have and can be deleted at any time.
        self.history = SessionIndex(self.sessions)
        self.history.refresh()

        # MCP servers, if any are enabled. Nothing is spawned here: the manager
        # connects the first time a tool list is asked for, so a server the
        # user never uses costs nothing and a slow one does not delay startup.
        self.mcp = MCPManager(config.mcp.servers) if config.mcp.enabled else None

        # Authored skills: the user's own procedures, loaded from their folder
        # and from the project's. Separate from the learned brain on purpose —
        # one is written by hand, the other is inferred.
        self._load_skills()

        self.tools.add(Delegate(spawner(config, self.gateway, self.bus,
                                        skills=self.skills, mcp=self.mcp)))
        self.agent = AgentLoop(config, self.gateway, self.tools, self.bus,
                               self.permissions, self.conversation, self.memory,
                               skills=self.skills)

        self.state = ScreenState()
        self.state.slash_commands = [(name, spec[1]) for name, spec in COMMANDS.items()]
        self.state.status = StatusModel(
            provider=self._provider_label(), model=config.active_model(),
            connected=self._connected(), mode=config.agent.mode,
            loop=config.agent.loop, gateway=self.gateway.describe(),
            context_limit=config.agent.context_limit,
            rules=len(self.memory.active_rules()),
        )

        self.running = False
        self.dirty = True
        self.worker: threading.Thread | None = None
        self.pending_requests: list[Request] = []
        self._streaming: Entry | None = None
        self._tool_entries: dict[str, Entry] = {}
        self._last_frame = 0.0
        self._quit_armed = 0.0
        self._saved_count = 0            # messages already written to the session file
        self._prefetch_draft = ""
        self._last_keystroke = 0.0

        if resume:
            self._resume(resume)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def run(self) -> int:
        """Draw the interface until the user quits."""
        self.running = True
        self._greet()
        self._complain_about_the_config()
        self._refresh_sessions()
        # Read the project's existing conventions once, in the background, so
        # the first answer already matches how this codebase is written.
        self.memory.bootstrap_project()

        with TerminalInput(mouse=self.config.ui.mouse) as terminal, Live(
            self._frame(), console=self.console, screen=True, auto_refresh=False,
            transient=False,
        ) as live:
            self.terminal = terminal
            interval = 1.0 / max(4, self.config.ui.max_fps)
            while self.running:
                changed = self._pump_input(terminal)
                changed |= self._pump_events()
                changed |= self.state.toasts.prune()

                if self.state.status.busy:
                    frame = int(time.monotonic() / SPINNER_INTERVAL)
                    if frame != self.state.spinner:
                        self.state.spinner = frame
                        changed = True

                now = time.monotonic()
                if (changed or self.dirty) and now - self._last_frame >= interval:
                    live.update(self._frame(), refresh=True)
                    self._last_frame = now
                    self.dirty = False
                elif not changed:
                    self._maybe_prefetch()
                    time.sleep(IDLE_SLEEP)

        self._shutdown()
        return 0

    def _load_skills(self) -> int:
        """Discover skills, creating the folder with examples on a first run.

        The tool set is rebuilt with them, because whether `read_skill_file` is
        offered depends on whether any loaded skill actually bundles files.
        """
        self.skills = skills_for(self.config)
        self.tools = ToolRegistry(skills=self.skills, history=self.history,
                                  session_id=self.session.id, mcp=self.mcp)
        return len(self.skills)

    def _complain_about_the_config(self) -> None:
        """Anything the config asked for and did not get, said once, at the top.

        A setting that does nothing and says nothing is worse than one that is
        rejected loudly: the first teaches people the file is not read.
        """
        for note in self.config.complaints:
            self.state.toasts.add(f"config: {note}")
        refused = self.config.project_refused
        if refused:
            listed = ", ".join(sorted(refused)[:6])
            more = f" (+{len(refused) - 6} more)" if len(refused) > 6 else ""
            self.state.toasts.add(
                f"this project's config cannot set {listed}{more} — "
                f"only your own can")

    def _greet(self) -> None:
        """The wordmark, and what the brain has accumulated.

        Printed before the full-screen loop takes over, so it lands in the
        scrollback the user can scroll back to rather than being painted over
        by the first frame.
        """
        from .. import __version__ as release

        banner.show(
            self.console, self.theme, self.config,
            version=release, model=self.config.active_model(),
            project=str(self.config.paths.project),
            standing=banner.gather(self.memory, self.skills),
        )

    def _shutdown(self) -> None:
        self.agent.interrupt()
        self.tools.close()
        self.history.close()
        if self.mcp is not None:
            self.mcp.close()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=SHUTDOWN_JOIN_SECONDS)
        # Flush whatever the agent produced after the last event we pumped —
        # quitting mid-turn must not lose the transcript.
        self._persist_new_messages()
        if self.conversation.messages:
            self.session.messages = len(self.conversation.messages)
            self.session.cost_usd = self.conversation.usage.cost_usd
            self.sessions.save_meta(self.session)
        try:
            self.memory.consolidate()
        except Exception:
            pass
        self.memory.close()
        self.gateway.close()
        self.bus.close()

    def _frame(self) -> Any:
        geometry = layout_module.compute(
            self.console.size.width, self.console.size.height,
            sidebar=self.state.sidebar_visible and self.config.ui.sidebar,
        )
        self.geometry = geometry
        return self.screen.render(self.state, geometry)

    # ------------------------------------------------------------------ #
    # input
    # ------------------------------------------------------------------ #

    def _maybe_prefetch(self) -> None:
        """Warm recall for the draft while the user is still typing.

        This is what makes memory free: the ranking runs during the pause
        between keystrokes, so pressing Enter starts the model call immediately
        instead of waiting on a lookup. If the draft changes, the prefetch is
        simply discarded.
        """
        if not self.config.learning.prefetch or self.state.status.busy:
            return
        draft = self.state.editor.text.strip()
        if len(draft) < 8 or draft.startswith(("/", "!")):
            return
        if draft == self._prefetch_draft:
            return
        if time.monotonic() - self._last_keystroke < PREFETCH_IDLE:
            return

        self._prefetch_draft = draft
        threading.Thread(target=self.memory.prefetch, args=(draft,),
                         daemon=True, name="comodor-prefetch").start()

    def _pump_input(self, terminal: TerminalInput) -> bool:
        changed = False
        for event in terminal.poll():
            if isinstance(event, KeyEvent):
                self._last_keystroke = time.monotonic()
                changed |= self._on_key(event)
            elif isinstance(event, MouseEvent):
                changed |= self._on_mouse(event)
            elif isinstance(event, PasteEvent):
                self.state.editor.insert(event.text)
                changed = True
        return changed

    def _on_key(self, event: KeyEvent) -> bool:
        if self.state.overlay is not None:
            return self._overlay_key(event)

        # Global bindings first — these work regardless of focus.
        if event.matches("ctrl+c"):
            return self._on_interrupt()
        if event.matches("ctrl+d"):
            self.running = False
            return True
        if event.key == "escape":
            if self.state.status.busy:
                self.agent.interrupt()
                self._toast("stopping…", "warn")
                return True
            if self.state.scroll:
                self.state.scroll = 0
                return True
            return False
        if event.matches("f1"):
            return self._command("/help", "")
        if event.matches("f2"):
            self.state.sidebar_visible = not self.state.sidebar_visible
            return True
        if event.matches("f3"):
            return self._cycle_mode()
        if event.matches("f4"):
            return self._command("/loop", "")
        if event.matches("f5"):
            return self._command("/gw", "")
        if event.matches("ctrl+o"):
            return self._command("/attach", "")
        if event.matches("ctrl+l"):
            return self._command("/clear", "")
        if event.key in ("pgup", "pgdn"):
            step = max(3, self.geometry.chat.height - 3)
            self.state.scroll = max(0, self.state.scroll +
                                    (step if event.key == "pgup" else -step))
            return True
        if event.key in ("up", "down") and event.ctrl:
            self.state.scroll = max(0, self.state.scroll + (1 if event.key == "up" else -1))
            return True

        return self._editor_key(event)

    def _editor_key(self, event: KeyEvent) -> bool:
        editor = self.state.editor
        matches = self._completions()

        if event.key == "enter":
            if event.alt:
                editor.insert("\n")
                return True
            # A fully typed command runs on Enter. Only an unfinished one is
            # completed by it — otherwise `/help` + Enter would just tidy the
            # text and make the user press Enter a second time.
            if matches and editor.text.strip() not in {name for name, _ in matches}:
                self._accept_completion(matches)
                return True
            return self._submit()
        if event.matches("ctrl+j"):
            editor.insert("\n")
            return True
        if event.key == "tab":
            if matches:
                self._accept_completion(matches)
                return True
            self.state.focus = {"prompt": "chat", "chat": "sidebar",
                                "sidebar": "prompt"}.get(self.state.focus, "prompt")
            return True
        if event.key == "backspace":
            editor.delete_word() if event.ctrl or event.alt else editor.backspace()
            return True
        if event.key == "delete":
            editor.delete()
            return True
        if event.key == "left":
            editor.word_left() if event.ctrl else editor.left()
            return True
        if event.key == "right":
            editor.word_right() if event.ctrl else editor.right()
            return True
        if event.key == "up":
            if matches:
                self.state.completion_index = max(0, self.state.completion_index - 1)
                return True
            if not editor.up():
                editor.previous()
            return True
        if event.key == "down":
            if matches:
                self.state.completion_index = min(len(matches) - 1,
                                                  self.state.completion_index + 1)
                return True
            if not editor.down():
                editor.next()
            return True
        if event.key == "home":
            editor.home()
            return True
        if event.key == "end":
            editor.end()
            return True
        if event.matches("ctrl+u"):
            editor.delete_to_start()
            return True
        if event.matches("ctrl+k"):
            editor.delete_to_end()
            return True
        if event.matches("ctrl+w"):
            editor.delete_word()
            return True
        if event.key == "char" and not event.ctrl:
            editor.insert(event.char)
            self.state.completion_index = 0
            return True
        return False

    def _on_mouse(self, event: MouseEvent) -> bool:
        if event.action == "scroll_up":
            self.state.scroll += 3
            return True
        if event.action == "scroll_down":
            self.state.scroll = max(0, self.state.scroll - 3)
            return True
        if event.action != "press":
            return False

        region = self.geometry.hit(event.x, event.y)
        if region.startswith("button:"):
            return self._on_button(region.split(":", 1)[1])
        if region == "status":
            return self._command("/settings", "")
        if region in ("chat", "sidebar", "prompt"):
            self.state.focus = region
            return True
        return False

    def _on_button(self, name: str) -> bool:
        if name == "send":
            if self.state.status.busy:
                self.agent.interrupt()
                self._toast("stopping…", "warn")
                return True
            return self._submit()
        if name == "attach":
            return self._command("/attach", "")
        if name == "mode":
            return self._cycle_mode()
        return False

    def _on_interrupt(self) -> bool:
        """Ctrl+C: stop the agent if it is working, quit if pressed twice."""
        if self.state.status.busy:
            self.agent.interrupt()
            self._toast("stopping…", "warn")
            return True
        now = time.monotonic()
        if now - self._quit_armed < 2.0:
            self.running = False
            return True
        self._quit_armed = now
        self._toast("press ctrl+c again to quit", "warn")
        return True

    # -- completions ------------------------------------------------------ #

    def _completions(self) -> list[tuple[str, str]]:
        from .widgets.prompt import completions

        return completions(self.state.editor.text, self.state.slash_commands)

    def _accept_completion(self, matches: list[tuple[str, str]]) -> None:
        index = min(self.state.completion_index, len(matches) - 1)
        name = matches[index][0]
        self.state.editor.text = name + " "
        self.state.editor.cursor = len(self.state.editor.text)
        self.state.completion_index = 0

    # ------------------------------------------------------------------ #
    # overlays
    # ------------------------------------------------------------------ #

    def _overlay_key(self, event: KeyEvent) -> bool:
        overlay = self.state.overlay
        if overlay is None:
            return False

        if event.key == "escape":
            self._close_overlay(cancelled=True)
            return True

        if overlay.kind == "permission":
            for choice in overlay.choices:
                if event.matches(choice.key):
                    self._answer_permission(choice.value)
                    return True
            if event.key == "enter":
                self._answer_permission(overlay.choices[0].value)
                return True
            return False

        if overlay.kind == "select":
            if event.key == "up":
                overlay.move(-1)
                return True
            if event.key == "down":
                overlay.move(1)
                return True
            if event.key == "enter":
                value = overlay.current()
                handler = overlay.on_select
                self._close_overlay()
                if handler and value:
                    handler(value)
                return True
            if event.key == "backspace":
                overlay.filter_text = overlay.filter_text[:-1]
                overlay.selected = 0
                return True
            if event.key == "char" and not event.ctrl:
                overlay.filter_text += event.char
                overlay.selected = 0
                return True
            return False

        if event.key in ("enter", "char"):
            self._close_overlay()
            return True
        return False

    def _close_overlay(self, cancelled: bool = False) -> None:
        overlay = self.state.overlay
        if overlay is not None and overlay.request is not None and cancelled:
            overlay.request.answer("deny")
        self.state.overlay = None
        self._next_request()

    def _answer_permission(self, value: str) -> None:
        overlay = self.state.overlay
        if overlay is not None and overlay.request is not None:
            overlay.request.answer(value)
        self.state.overlay = None
        self._next_request()

    def _next_request(self) -> None:
        while self.pending_requests:
            request = self.pending_requests.pop(0)
            if not request.answered:
                self.state.overlay = permission_overlay(request)
                return

    # ------------------------------------------------------------------ #
    # agent events
    # ------------------------------------------------------------------ #

    def _pump_events(self) -> bool:
        changed = False
        for event in self.events.drain():
            changed = True
            kind = event.kind

            if kind is Kind.ASSISTANT_START:
                self._streaming = Entry("assistant", "", streaming=True)
                self.state.entries.append(self._streaming)
            elif kind is Kind.ASSISTANT_DELTA:
                if self._streaming is None:
                    self._streaming = Entry("assistant", "", streaming=True)
                    self.state.entries.append(self._streaming)
                self._streaming.text += event.text
            elif kind is Kind.ASSISTANT_END:
                if self._streaming is not None:
                    self._streaming.streaming = False
                    if not self._streaming.text.strip():
                        self.state.entries.remove(self._streaming)
                    self._streaming = None
                self._persist_new_messages()
            elif kind is Kind.TOOL_START:
                entry = Entry("tool", event.get("name", ""), meta={
                    "summary": event.get("summary", ""), "running": True, "ok": True,
                })
                self._tool_entries[event.get("id", "")] = entry
                self.state.entries.append(entry)
                self.state.status.activity = event.get("summary", "")
            elif kind is Kind.TOOL_END:
                entry = self._tool_entries.pop(event.get("id", ""), None)
                if entry is not None:
                    meta = event.get("meta") or {}
                    entry.meta.update({
                        "running": False,
                        "ok": event.get("ok", True),
                        "elapsed": event.get("elapsed", 0.0),
                        "preview": event.get("display", ""),
                        "diff": bool(meta.get("diff")),
                    })
                self._persist_new_messages()
            elif kind is Kind.TOOL_OUTPUT:
                self.state.status.activity = event.text[:80]
            elif kind is Kind.TODO:
                self.state.history.todos = event.get("items", [])
            elif kind is Kind.USAGE:
                status = self.state.status
                status.context_used = event.get("context_used", status.context_used)
                status.context_limit = event.get("context_limit", status.context_limit)
                status.cost_usd = event.get("cost_usd", status.cost_usd)
                status.input_tokens = event.get("input_tokens", 0)
                status.output_tokens = event.get("output_tokens", 0)
            elif kind is Kind.MEMORY:
                self._on_memory(event.payload)
            elif kind is Kind.NOTICE:
                self.state.entries.append(Entry("notice", event.text))
            elif kind is Kind.ERROR:
                self.state.entries.append(Entry("error", event.text))
                self.state.status.connected = False
            elif kind is Kind.REQUEST:
                request = event.get("request")
                if isinstance(request, Request):
                    if self.state.overlay is None:
                        self.state.overlay = permission_overlay(request)
                    else:
                        self.pending_requests.append(request)
            elif kind is Kind.TURN_START:
                self.state.status.busy = True
                self.state.status.activity = "thinking…"
                self.state.scroll = 0
            elif kind is Kind.TURN_END:
                self.state.status.busy = False
                self.state.status.activity = ""
                self._on_turn_end(event.payload)
            elif kind is Kind.CANCELLED:
                self.state.entries.append(Entry("notice", "stopped"))
        return changed

    def _on_memory(self, payload: dict[str, Any]) -> None:
        action = payload.get("action")
        items = payload.get("items") or []
        if action == "rule" and items:
            # The moment a rule takes hold is the moment the user should see it.
            # Silent adaptation is the version of this feature nobody trusts.
            for rule in items:
                self.state.entries.append(Entry(
                    "memory", f"learned: {rule.get('statement', '')}",
                    meta={"rule": rule, "id": rule.get("id"),
                          "hint": f"/rules forget {rule.get('id')} to undo"}))
            self.state.status.rules = len(self.memory.active_rules())
            self._toast(f"learned {len(items)} rule(s) from your edits", "good", ttl=6.0)
        elif action == "skills" and items:
            names = ", ".join(str(item.get("name", "")) for item in items)
            self.state.entries.append(Entry(
                "memory", f"skill: {names}",
                meta={"items": items, "hint": "/skills to see them"}))
        elif action == "recalled" and items:
            self.state.entries.append(Entry(
                "memory", f"recalled {len(items)} lesson(s)",
                meta={"items": items, "expanded": False}))
            self.state.status.lessons = len(items)
        elif action == "learned":
            learned = len(items)
            merged = payload.get("merged", 0)
            parts = []
            if learned:
                parts.append(f"learned {learned} lesson(s)")
            if merged:
                parts.append(f"reinforced {merged}")
            if payload.get("skill"):
                parts.append(f"saved skill {payload['skill']}")
            if parts:
                self._toast(" · ".join(parts), "good")
        elif action == "taught":
            self._toast("noted — I'll remember that", "good")

    def _on_turn_end(self, payload: dict[str, Any]) -> None:
        stopped = payload.get("stopped", "done")
        if stopped == "error":
            self._toast(payload.get("error", "the request failed"), "bad", ttl=8.0)
        elif stopped in ("max_steps", "budget"):
            self._toast(f"stopped: {stopped.replace('_', ' ')}", "warn")
        else:
            self.state.status.connected = True
        self._persist_new_messages()
        self.session.messages = len(self.conversation.messages)
        self.session.cost_usd = self.conversation.usage.cost_usd
        self.sessions.save_meta(self.session)
        self._refresh_sessions()

    # ------------------------------------------------------------------ #
    # submitting work
    # ------------------------------------------------------------------ #

    def _submit(self) -> bool:
        text = self.state.editor.text.strip()
        if not text:
            return False
        if self.state.status.busy:
            self._toast("still working — press esc to stop first", "warn")
            return True

        self.state.editor.remember(text)
        self.state.editor.clear()

        if text.startswith("/"):
            name, _, rest = text.partition(" ")
            return self._command(name, rest.strip())
        if text.startswith("!"):
            return self._run_shell_directly(text[1:].strip())

        self.state.entries.append(Entry("user", text))
        self.state.scroll = 0
        if not self.session.title:
            self.session.title = derive_title(text)
        self._start_agent(text)
        return True

    def _start_agent(self, text: str) -> None:
        self.state.status.busy = True
        self.state.status.activity = "thinking…"

        def work() -> None:
            try:
                self.agent.run(text)
            except Cancelled:
                pass
            except Exception as exc:                    # never lose the UI
                self.bus.emit(Kind.ERROR, text=f"{type(exc).__name__}: {exc}")
                self.bus.emit(Kind.TURN_END, stopped="error", error=str(exc))

        self.worker = threading.Thread(target=work, daemon=True, name="comodor-agent")
        self.worker.start()

    def _run_shell_directly(self, command: str) -> bool:
        """``!ls`` — run a command without involving the model."""
        if not command:
            return True
        self.state.entries.append(Entry("user", f"!{command}"))

        def work() -> None:
            from ..tools.shell import RunShell

            context = self.agent._tool_context()
            entry_id = f"direct-{time.time()}"
            self.bus.emit(Kind.TOOL_START, id=entry_id, name="run_shell",
                          summary=f"run: {command}")
            result = RunShell().invoke(context, {"command": command})
            self.bus.emit(Kind.TOOL_END, id=entry_id, name="run_shell", ok=result.ok,
                          content=result.content, display=result.rendered,
                          elapsed=result.elapsed, meta=result.meta)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _persist_new_messages(self) -> None:
        """Append anything the agent added since the last save."""
        saved = self._saved_count
        for message in self.conversation.messages[saved:]:
            self.sessions.append(self.session.id, message)
        self._saved_count = len(self.conversation.messages)

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #

    def _command(self, name: str, args: str) -> bool:
        spec = COMMANDS.get(name)
        if spec is None:
            self._toast(f"unknown command {name} — try /help", "bad")
            return True
        handler = getattr(self, spec[0])
        try:
            handler(args)
        except Exception as exc:
            self._toast(f"{name} failed: {exc}", "bad")
        return True

    # -- individual commands ---------------------------------------------- #

    def cmd_help(self, args: str) -> None:
        lines = ["**Commands**", ""]
        for name, (_, description) in COMMANDS.items():
            lines.append(f"- `{name}` — {description}")
        lines += ["", "**Keys**", "",
                  "- `Enter` send · `Ctrl+J` newline · `Esc` stop",
                  "- `F1` help · `F2` sidebar · `F3` mode · `F4` loop · `F5` gateway",
                  "- `Ctrl+O` attach · `Ctrl+L` clear · `PgUp/PgDn` scroll",
                  "- `!command` run a shell command directly",
                  "- `Ctrl+C` stop, twice to quit"]
        self.state.overlay = info_overlay("Help", "\n".join(lines))

    def cmd_model(self, args: str) -> None:
        if args:
            self._pick_model(args.strip())
            return
        provider = self.gateway.provider(self.config.provider)
        models = provider.list_models() or [self.config.active_model()]
        items = [(model, "") for model in models]
        self.state.overlay = select_overlay("Model", items, self._pick_model)

    def _pick_model(self, model: str) -> None:
        """One path, whether the model was typed or chosen from the list.

        They had drifted: typing `/model x` left the session record naming the
        old one, so a transcript said whichever model had been chosen the other
        way.
        """
        self.config.model = model
        self.state.status.model = model
        self.session.model = model
        self._follow_the_models_context_window(model)
        self._toast(f"model: {model}", "good")

    def _follow_the_models_context_window(self, model: str) -> None:
        """The window belongs to the model, not to the configuration.

        It is set once by the setup wizard and then read by the loop, which
        compacts the conversation at a fraction of it. Left at a million after
        a switch to a 128k model, the agent never compacts and the run fails at
        the provider's real ceiling -- with the gauge in the corner still
        reading a million on the way there.
        """
        from ..providers import registry

        # `lookup` never fails - it invents safe defaults for a model it has
        # not heard of. Taking those would drop the window to a made-up 128k
        # the moment somebody switched to a local model, which is worse than
        # leaving the number they had.
        if not registry.knows(model):
            return
        window = registry.lookup(model).context
        if not window or window == self.config.agent.context_limit:
            return
        self.config.agent.context_limit = window
        self.state.status.context_limit = window

    def cmd_provider(self, args: str) -> None:
        items = [
            (entry.name, f"{entry.display}  ·  {entry.model}"
                         + ("" if entry.ready else "  (no key)"))
            for entry in self.config.providers.values()
        ]
        if args:
            self._pick_provider(args)
            return
        self.state.overlay = select_overlay("Provider", items, self._pick_provider)

    def _pick_provider(self, name: str) -> None:
        entry = self.config.providers.get(name)
        if entry is None:
            self._toast(f"unknown provider {name}", "bad")
            return
        if not entry.ready:
            self._toast(f"{entry.display} has no API key — run `comodor setup` to add one",
                        "bad")
            return
        self.config.provider = name
        self.config.model = entry.model
        self.session.model = entry.model
        self.state.status.provider = entry.display
        self.state.status.model = entry.model
        self.state.status.connected = True
        # A different provider means a different model, and a different model
        # means a different window.
        self._follow_the_models_context_window(entry.model)
        self._toast(f"provider: {entry.display}", "good")

    def cmd_mode(self, args: str) -> None:
        if args:
            mode = args.strip().lower()
            if mode not in ("act", "plan", "chat"):
                self._toast("mode must be act, plan or chat", "bad")
                return
            self._set_mode(mode)
            return
        self._cycle_mode()

    def _cycle_mode(self) -> bool:
        order = ["act", "plan", "chat"]
        current = self.config.agent.mode.lower()
        index = order.index(current) if current in order else 0
        self._set_mode(order[(index + 1) % len(order)])
        return True

    def _set_mode(self, mode: str) -> None:
        self.config.agent.mode = mode
        self.state.status.mode = mode
        note = {"act": "full tools", "plan": "read-only", "chat": "no tools"}[mode]
        self._toast(f"mode: {mode} ({note})", "accent")

    def cmd_loop(self, args: str) -> None:
        self.config.agent.loop = not self.config.agent.loop
        self.state.status.loop = self.config.agent.loop
        self._toast(f"loop: {'on' if self.config.agent.loop else 'off'}", "accent")

    def cmd_gateway(self, args: str) -> None:
        gateway = self.config.gateway
        if args in ("cost", "speed", "quality"):
            gateway.enabled = True
            gateway.policy = args
        else:
            gateway.enabled = not gateway.enabled
        self.state.status.gateway = self.gateway.describe()
        self._toast(f"gateway: {self.gateway.describe().lower()}", "accent")

    def cmd_memory(self, args: str) -> None:
        lessons = self.memory.search(args, limit=40)
        if not lessons:
            self.state.overlay = info_overlay(
                "Memory", "Nothing learned yet.\n\n"
                          "Comodor records a lesson when a task teaches it something "
                          "durable, or when you use `/teach`.")
            return
        items = [
            (f"#{lesson.id} {lesson.trigger}",
             f"{lesson.guidance[:70]}  [{lesson.kind} "
             f"{lesson.effective_confidence():.0%}{' pinned' if lesson.pinned else ''}]")
            for lesson in lessons
        ]
        self.state.overlay = select_overlay(
            f"Memory ({len(lessons)})", items, self._memory_action)

    def _memory_action(self, label: str) -> None:
        try:
            lesson_id = int(label.split()[0].lstrip("#"))
        except (ValueError, IndexError):
            return
        self.state.overlay = select_overlay(
            f"Lesson #{lesson_id}",
            [("pin", "always include this"), ("unpin", "back to normal ranking"),
             ("forget", "delete it permanently")],
            lambda action: self._apply_memory_action(lesson_id, action),
        )

    def _apply_memory_action(self, lesson_id: int, action: str) -> None:
        if action == "forget":
            self.memory.forget(lesson_id)
            self._toast(f"forgot lesson #{lesson_id}", "warn")
        elif action in ("pin", "unpin"):
            self.memory.pin(lesson_id, action == "pin")
            self._toast(f"{action}ned lesson #{lesson_id}", "good")

    def cmd_teach(self, args: str) -> None:
        if not args:
            self._toast("usage: /teach when X happens: do Y", "warn")
            return
        self.memory.teach(args)

    def _proposals(self) -> list:
        """Learned procedures that have earned an offer to become real skills."""
        try:
            return skill_candidates(self.memory.store.all_skills(), self.skills)
        except Exception:
            return []

    def cmd_skills(self, args: str) -> None:
        """Skills you wrote, and procedures Comodor worked out for itself."""
        words = args.strip().split()
        verb = words[0].lower() if words else ""

        if verb in ("draft", "drafts", "propose"):
            self._show_proposals()
            return

        if verb == "adopt":
            self._adopt_proposal(" ".join(words[1:]).strip())
            return

        if args.strip().lower() in ("reload", "refresh"):
            count = self._load_skills()
            # The agent holds what it was built with, so re-reading the folder
            # has to reach it too, or /skills reload would report a change that
            # the next turn does not see.
            self.agent.skills = self.skills
            self.agent.tools = self.tools
            self._toast(f"reloaded {count} skill(s)", "good")
            return

        authored = self.skills.all()
        learned = self.memory.store.all_skills()

        body: list[str] = []

        body.append("## Your skills")
        body.append("")
        if authored:
            for skill in authored:
                where = "project" if skill.scope == "project" else "you"
                state = "" if skill.enabled else "  *(disabled)*"
                always = "  *(always applies)*" if skill.always else ""
                body.append(f"- **{skill.name}** — {skill.description}  "
                            f"<sub>{where}{state}{always}</sub>")
        else:
            body.append("None yet. Drop a Markdown file in either folder below and")
            body.append("Comodor will apply it whenever it fits what you asked.")
        body.append("")
        body.append(f"- yours: `{self.config.paths.skills}`")
        body.append(f"- this project: `{self.config.paths.project_skills}`")

        if self.skills.errors:
            body += ["", "### Files that would not load", ""]
            for path, message in self.skills.errors[:5]:
                body.append(f"- `{Path(path).name}` — {message}")

        body += ["", "## Learned procedures", ""]
        if learned:
            for skill in learned:
                body.append(f"- **{skill.name}** — {skill.description} "
                            f"({skill.uses} uses, {skill.success_rate:.0%} success)")
        else:
            body.append("None yet. Comodor saves one when a multi-step task looks")
            body.append("like it will recur.")

        pending = self._proposals()
        if pending:
            body += ["", "### Drafts waiting for you", ""]
            for offer in pending:
                body.append(f"- **{offer.name}** — {offer.evidence}. "
                            f"`/skills adopt {offer.name}`")

        body += ["", "`/skills reload` re-reads both folders · "
                     "`/skills draft` shows what Comodor would like to save."]
        self.state.overlay = info_overlay("Skills", "\n".join(body))

    def cmd_search(self, args: str) -> None:
        """Find something in an earlier conversation."""
        query = args.strip()
        if not query:
            stats = self.history.stats()
            self._toast(
                f"/search <words> — {stats['turns']} messages across "
                f"{stats['sessions']} sessions are indexed", "accent", ttl=6.0)
            return

        self.history.refresh()
        hits = self.history.search(query, limit=10,
                                   exclude_session=self.session.id)

        if not hits:
            self._toast(f"nothing earlier matches {query!r}", "warn")
            return

        body = [f"## {len(hits)} match(es) for *{query}*", ""]
        for hit in hits:
            speaker = "you" if hit.role == "user" else "Comodor"
            body.append(f"**{speaker}** · {hit.when} · `{hit.session_id}`")
            body.append("")
            body.append(f"> {hit.snippet(320)}")
            body.append("")
        body.append("`/resume` reopens a session by id.")
        self.state.overlay = info_overlay("History", "\n".join(body))

    def _show_proposals(self) -> None:
        """What Comodor would like to write down, and exactly what it would say."""
        offers = self._proposals()
        if not offers:
            self._toast(
                "nothing to propose yet — a procedure has to work several times first",
                "dim", ttl=6.0)
            return

        body = ["## Drafts Comodor would like to save", ""]
        body.append("Each is a procedure it worked out and then repeated. Nothing is")
        body.append("written until you say so.")
        body.append("")
        for offer in offers:
            body.append(f"### {offer.name}")
            body.append(f"*{offer.evidence}*")
            body.append("")
            body.append("```markdown")
            body.append(offer.render().strip())
            body.append("```")
            body.append(f"`/skills adopt {offer.name}` to keep it.")
            body.append("")
        self.state.overlay = info_overlay("Skill drafts", "\n".join(body))

    def _adopt_proposal(self, name: str) -> None:
        offers = self._proposals()
        if not name:
            names = ", ".join(offer.name for offer in offers) or "none available"
            self._toast(f"/skills adopt <name> — {names}", "accent", ttl=6.0)
            return

        chosen = next((offer for offer in offers if offer.name == name), None)
        if chosen is None:
            self._toast(f"no draft named {name!r} — /skills draft lists them", "warn")
            return

        try:
            path = chosen.write(self.config.paths.skills)
        except (FileExistsError, OSError) as error:
            self._toast(str(error), "bad", ttl=6.0)
            return

        count = self._load_skills()
        self.agent.skills = self.skills
        self.agent.tools = self.tools
        self._toast(f"saved {chosen.name} — {count} skill(s) now", "good", ttl=6.0)
        self.state.entries.append(
            Entry("notice", f"skill saved: {path}  (edit it freely; it is yours)"))

    def cmd_mcp(self, args: str) -> None:
        """Which MCP servers are connected, and what they brought."""
        if self.mcp is None:
            self._toast("MCP is switched off (mcp.enabled is false)", "warn")
            return

        words = args.strip().split()
        verb = words[0].lower() if words else ""

        if verb in ("reload", "refresh", "connect"):
            self.mcp.close()
            self.mcp = MCPManager(self.config.mcp.servers)
            count = self._load_skills()          # rebuilds the tool set with it
            self.agent.tools = self.tools
            offered = sum(1 for tool in self.tools.all()
                          if SEPARATOR in tool.name)
            self._toast(f"reconnected · {offered} MCP tool(s), {count} skill(s)",
                        "good", ttl=6.0)
            return

        body = ["## MCP servers", ""]
        rows = self.mcp.report()
        if not rows:
            body.append("None configured yet. From a terminal:")
            body.append("")
            body.append("```")
            body.append("comodor mcp catalogue      what Comodor can set up for you")
            body.append("comodor mcp add github     add one of them")
            body.append("comodor mcp custom <name> <command> [args...]")
            body.append("```")
            self.state.overlay = info_overlay("MCP", "\n".join(body))
            return

        for name, status, detail in rows:
            mark = {"ready": "●", "failed": "✗", "off": "○"}.get(status, "◐")
            body.append(f"- {mark} **{name}** — {status}. {detail}")

        tools = [tool for tool in self.tools.all() if SEPARATOR in tool.name]
        body += ["", f"### {len(tools)} tool(s) available", ""]
        for tool in tools[:30]:
            first = tool.description.split("\n")[0][:70]
            body.append(f"- `{tool.name}` — {first}")
        if len(tools) > 30:
            body.append(f"- … and {len(tools) - 30} more")

        body += ["", "`/mcp reload` reconnects after changing the configuration.",
                 "`comodor mcp add <name>` adds one from a terminal."]
        self.state.overlay = info_overlay("MCP", "\n".join(body))

    def cmd_good(self, args: str) -> None:
        self.memory.feedback(self.agent._recalled, good=True, note=args)
        self._toast("thanks — reinforced", "good")

    def cmd_bad(self, args: str) -> None:
        self.memory.feedback(self.agent._recalled, good=False, note=args)
        self._toast("noted — those lessons lost confidence", "warn")

    def cmd_undo(self, args: str) -> None:
        count = int(args) if args.isdigit() else 1
        restored = self.checkpoints.undo_last(count)
        if restored:
            names = ", ".join(Path(path).name for path in restored)
            self._toast(f"restored {names}", "good")
            self.state.entries.append(Entry("notice", f"undo: restored {names}"))
            # An undo is a rejection of what the agent produced — record it.
            self.memory.on_undo(restored)
        else:
            self._toast("nothing to undo", "warn")

    def cmd_rules(self, args: str) -> None:
        """Browse, teach, export or drop the learned house rules."""
        command, _, rest = args.strip().partition(" ")
        command = command.lower()

        if command == "export":
            path = self.memory.export_rules()
            self._toast(f"rules written to {path}", "good", ttl=8.0)
            return
        if command == "teach" and rest:
            rule = self.memory.teach_rule(rest.strip())
            self._toast(f"noted: {rule.statement}", "good")
            return
        if command == "forget" and rest.strip().isdigit():
            removed = self.memory.forget_rule(int(rest.strip()))
            self._toast("rule dropped" if removed else "no such rule",
                        "warn" if removed else "bad")
            return

        rules = self.memory.all_rules()
        if not rules:
            self.state.overlay = info_overlay(
                "House rules",
                "Nothing learned yet.\n\nComodor watches how this project is "
                "written, and what you change about its output. Rules appear "
                "here once there is enough evidence.\n\n"
                "`/rules teach <rule>` states one directly.\n"
                "`/rules export` writes them to `.comodor/house-rules.md`.")
            return

        items = [
            (f"#{rule.id} {rule.statement}",
             f"{rule.detail or rule.source} · {rule.support}/{rule.total or 1} "
             f"· {'active' if rule.confident else 'gathering evidence'}")
            for rule in rules
        ]
        self.state.overlay = select_overlay(
            f"House rules ({len(rules)})", items, self._rule_action)

    def _rule_action(self, label: str) -> None:
        try:
            rule_id = int(label.split()[0].lstrip("#"))
        except (ValueError, IndexError):
            return
        self.state.overlay = select_overlay(
            f"Rule #{rule_id}",
            [("pin", "always apply, whatever the evidence says"),
             ("disable", "stop applying it, keep the record"),
             ("forget", "delete it permanently"),
             ("export", "write all rules to .comodor/house-rules.md")],
            lambda action: self._apply_rule_action(rule_id, action),
        )

    def _apply_rule_action(self, rule_id: int, action: str) -> None:
        if action == "forget":
            self.memory.forget_rule(rule_id)
            self._toast(f"forgot rule #{rule_id}", "warn")
        elif action == "pin":
            self.memory.set_rule(rule_id, pinned=True, active=True)
            self._toast(f"pinned rule #{rule_id}", "good")
        elif action == "disable":
            self.memory.set_rule(rule_id, active=False)
            self._toast(f"disabled rule #{rule_id}", "warn")
        elif action == "export":
            self._toast(f"rules written to {self.memory.export_rules()}", "good", ttl=8.0)

    def cmd_progress(self, args: str) -> None:
        """The evidence that this is working — or that it is not yet."""
        from ..learning.progress import analyse
        from .widgets.progress import render_progress

        stats = self.memory.stats()
        progress = analyse(
            self.memory.store.episodes(limit=300, scope=self.memory.project_scope),
            lessons=stats.get("lessons", 0),
            rules_active=stats.get("rules_active", 0),
        )
        overlay = info_overlay("Progress", "")
        overlay.meta["renderable"] = render_progress(
            progress, self.theme, width=max(60, self.console.size.width - 10))
        self.state.overlay = overlay

    def cmd_cost(self, args: str) -> None:
        usage = self.conversation.usage
        stats = self.memory.stats()
        body = [
            "**This session**", "",
            f"- prompt tokens: {usage.prompt_tokens:,}",
            f"- output tokens: {usage.output_tokens:,}",
            f"- served from cache: {usage.cached_tokens:,}"
            f" ({usage.cache_hit_rate:.0%} of the prompt)",
            f"- cost: ${usage.cost_usd:.4f}" if usage.cost_usd else
            "- cost: not published for this model",]
        # Reported from what the provider says it served, never from what we
        # asked it to cache — the two differ whenever a prefix has expired.
        if usage.cached_tokens and usage.cost_usd:
            full = registry.estimate_cost(
                self.state.status.model,
                usage.prompt_tokens, usage.output_tokens) or 0.0
            if full > usage.cost_usd:
                body.append(f"- saved by caching: ${full - usage.cost_usd:.4f}"
                            f" ({1 - usage.cost_usd / full:.0%})")
        body += [
            f"- context used: {self.state.status.context_used:,}"
            f" / {self.state.status.context_limit:,}",
            f"- compactions: {self.conversation.compactions}",
            "", "**Brain**", "",
            f"- lessons: {stats['lessons']}",
            f"- skills: {stats['skills']}",
            f"- episodes: {stats['episodes']}"
            f" ({stats['success_rate']:.0%} succeeded)",
        ]
        self.state.overlay = info_overlay("Usage", "\n".join(body))

    def cmd_export(self, args: str) -> None:
        fmt = (args or "md").strip().lower()
        target_dir = self.config.paths.exports
        secrets = [entry.api_key for entry in self.config.providers.values()
                   if entry.api_key]
        if fmt in ("json",):
            path = self.sessions.export_json(
                self.session.id, target_dir / f"{self.session.id}.json", secrets)
        else:
            path = self.sessions.export_markdown(
                self.session.id, target_dir / f"{self.session.id}.md", secrets)
        self._toast(f"exported to {path}", "good", ttl=8.0)

    def cmd_theme(self, args: str) -> None:
        from .theme import theme_names

        if args:
            self._apply_theme(args)
            return
        items = [(name, "") for name in theme_names()]
        self.state.overlay = select_overlay("Theme", items, self._apply_theme)

    def _apply_theme(self, name: str) -> None:
        from .theme import theme_names

        # The palette table falls back to Ember for anything it does not know,
        # so without this `/theme nonsense` reported success while the screen
        # showed something else entirely.
        known = theme_names()
        if name not in known:
            self._toast(f"no theme called {name} - try {', '.join(known)}", "bad")
            return
        self.config.ui.theme = name
        self.theme = console_module.prepare_theme(
            name, self.config.ui.ascii_borders, no_color=False,
            syntax=self.config.ui.syntax_theme)
        self.console.push_theme(self.theme.rich_theme())
        self.screen = Screen(self.console, self.theme)
        self._toast(f"theme: {name}", "good")

    def cmd_settings(self, args: str) -> None:
        config = self.config
        body = [
            "**Settings**", "",
            f"- provider: `{config.provider}` · model: `{config.active_model()}`",
            f"- mode: `{config.agent.mode}` · loop: `{config.agent.loop}`",
            f"- gateway: `{self.gateway.describe()}` (policy `{config.gateway.policy}`)",
            f"- auto-approve: writes `{config.safety.auto_approve_writes}`, "
            f"shell `{config.safety.auto_approve_shell}`",
            f"- checkpoints: `{config.safety.checkpoints}` · "
            f"workspace-only: `{config.safety.workspace_only}`",
            f"- learning: `{config.learning.enabled}` "
            f"(top {config.learning.top_k}, scope `{config.learning.share_scope}`)",
            f"- theme: `{config.ui.theme}` · mouse: `{config.ui.mouse}`",
            "",
            f"Config file: `{config.paths.config_file}`",
            f"Brain: `{config.paths.brain_db}`",
            "",
            "Change things with `/model`, `/provider`, `/mode`, `/gw`, `/theme`, "
            "`/approve`. `/save` writes the current settings to disk.",
        ]
        self.state.overlay = info_overlay("Settings", "\n".join(body))

    def cmd_approve(self, args: str) -> None:
        """Toggle auto-approval — the difference between watching and trusting."""
        safety = self.config.safety
        target = (args or "").strip().lower()
        if target in ("write", "writes"):
            safety.auto_approve_writes = not safety.auto_approve_writes
            state = safety.auto_approve_writes
        elif target in ("shell", "command", "commands"):
            safety.auto_approve_shell = not safety.auto_approve_shell
            state = safety.auto_approve_shell
        elif target in ("all", "everything"):
            state = not (safety.auto_approve_writes and safety.auto_approve_shell)
            safety.auto_approve_writes = safety.auto_approve_shell = state
        else:
            self._toast("usage: /approve writes | shell | all", "warn")
            return
        self._toast(f"auto-approve {target}: {'on' if state else 'off'}",
                    "warn" if state else "good")

    def cmd_save(self, args: str) -> None:
        path = save_user_config(self.config)
        self._toast(f"settings saved to {path}", "good", ttl=6.0)

    def cmd_clear(self, args: str) -> None:
        self.state.entries.clear()
        self.conversation.clear()
        self._saved_count = 0
        self.state.scroll = 0
        self._toast("conversation cleared", "accent")

    def cmd_resume(self, args: str) -> None:
        sessions = self.sessions.list_sessions()
        if not sessions:
            self._toast("no earlier sessions", "warn")
            return
        items = [(meta.id, f"{meta.title or 'untitled'}  ·  {meta.when}  ·  "
                           f"{meta.messages} messages") for meta in sessions]
        self.state.overlay = select_overlay("Resume", items, self._resume)

    def _resume(self, session_id: str) -> None:
        messages = self.sessions.load(session_id)
        if not messages:
            self._toast(f"session {session_id} is empty", "warn")
            return
        meta = self.sessions.load_meta(session_id)
        self.conversation.clear()
        self.conversation.extend(messages)
        self.state.entries = entries_from(messages)
        self._saved_count = len(messages)
        if meta:
            self.session = meta
        self.state.scroll = 0
        self._toast(f"resumed {len(messages)} messages", "good")

    def cmd_attach(self, args: str) -> None:
        """Pull a file into the prompt as an ``@path`` reference."""
        if args:
            self._attach(args)
            return
        root = self.config.paths.project
        candidates: list[tuple[str, str]] = []
        for path in sorted(root.rglob("*"))[:2000]:
            if path.is_file() and not any(part.startswith(".") or part in
                                          ("node_modules", "__pycache__", "venv")
                                          for part in path.parts):
                try:
                    relative = str(path.relative_to(root))
                except ValueError:
                    continue
                candidates.append((relative, f"{path.stat().st_size:,} B"))
            if len(candidates) >= 400:
                break
        if not candidates:
            self._toast("no files found to attach", "warn")
            return
        self.state.overlay = select_overlay("Attach file", candidates, self._attach)

    def _attach(self, relative: str) -> None:
        editor = self.state.editor
        prefix = "" if not editor.text or editor.text.endswith(" ") else " "
        editor.insert(f"{prefix}@{relative} ")
        self._toast(f"attached {relative}", "good")

    def cmd_quit(self, args: str) -> None:
        self.running = False

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def _toast(self, text: str, tone: str = "dim", ttl: float = 4.0) -> None:
        self.state.toasts.push(text, tone, ttl)
        self.dirty = True

    def _provider_label(self) -> str:
        entry = self.config.active()
        return entry.display if entry else "none"

    def _connected(self) -> bool:
        entry = self.config.active()
        return bool(entry and entry.ready) or self.demo

    def _refresh_sessions(self) -> None:
        refs = [
            SessionRef(id=meta.id, title=meta.title or "untitled", when=meta.when,
                       messages=meta.messages, current=meta.id == self.session.id)
            for meta in self.sessions.list_sessions(limit=12)
        ]
        self.state.history.sessions = refs


# --------------------------------------------------------------------------- #
# command table
# --------------------------------------------------------------------------- #

COMMANDS: dict[str, tuple[str, str]] = {
    "/help": ("cmd_help", "commands and keys"),
    "/model": ("cmd_model", "choose the model"),
    "/provider": ("cmd_provider", "choose the provider"),
    "/mode": ("cmd_mode", "act, plan or chat"),
    "/loop": ("cmd_loop", "autonomous iteration on or off"),
    "/gw": ("cmd_gateway", "model gateway and routing policy"),
    "/memory": ("cmd_memory", "browse what it has learned"),
    "/rules": ("cmd_rules", "house rules learned from your code and edits"),
    "/progress": ("cmd_progress", "proof that it is getting better"),
    "/teach": ("cmd_teach", "record something it should remember"),
    "/skills": ("cmd_skills", "saved procedures"),
    "/good": ("cmd_good", "that answer was right"),
    "/bad": ("cmd_bad", "that answer was wrong"),
    "/undo": ("cmd_undo", "restore the last file the agent changed"),
    "/cost": ("cmd_cost", "tokens, spend, and brain stats"),
    "/export": ("cmd_export", "write this session to a file"),
    "/theme": ("cmd_theme", "change the colours"),
    "/settings": ("cmd_settings", "current configuration"),
    "/approve": ("cmd_approve", "auto-approve writes or shell"),
    "/save": ("cmd_save", "persist settings"),
    "/attach": ("cmd_attach", "add a file to the prompt"),
    "/clear": ("cmd_clear", "start a fresh conversation"),
    "/resume": ("cmd_resume", "reopen an earlier session"),
    "/search": ("cmd_search", "find something in an earlier conversation"),
    "/mcp": ("cmd_mcp", "MCP servers and the tools they provide"),
    "/quit": ("cmd_quit", "exit"),
}
