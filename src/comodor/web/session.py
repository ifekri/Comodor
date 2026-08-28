"""One agent, driven from a browser instead of a terminal.

The interesting part is how little there is here, and that is not an accident:
the terminal interface was never the agent. Everything that happens — a token
of an answer, a tool starting, a permission being asked for, the cost changing
— is already published on an event bus, and the TUI is one subscriber that
happens to draw. A browser is a second subscriber that happens to send JSON.

So this holds the same objects `comodor` holds — a gateway, a brain, a tool
registry, one loop — and does three things the terminal does differently:

* **It keeps the events.** A browser can reload, or be opened a minute after
  the work started, and it needs the transcript rather than whatever arrives
  next. Every event is appended to a log with a sequence number, and a client
  says where it got to.
* **It runs one turn at a time.** A terminal enforces that by having one
  keyboard. Nothing stops two tabs from both hitting send, so a lock does.
* **It answers permission prompts by id.** The worker thread blocks on a
  `Request` exactly as it does for the TUI; the browser posts the choice.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..agent import AgentLoop, Conversation
from ..agent.spawn import spawner
from ..config import Config
from ..events import Event, EventBus, Kind, Request
from ..learning import LearningEngine
from ..mcp import MCPManager
from ..paths import Paths
from ..providers.base import Message
from ..providers.gateway import Gateway
from ..questions import CANCELLED, decode_answers
from ..safety import CheckpointStore, PermissionEngine, Redactor
from ..session import SessionIndex, SessionMeta, SessionStore, derive_title, new_session_id
from ..skills import load_for as load_skills
from ..tools import ToolRegistry

#: How many events are kept for a reloading browser. A long session produces
#: tens of thousands; what a reader needs is the recent past, and the session
#: transcript on disk is the record.
HISTORY = 4_000


class Session:
    """The agent, plus what a disconnected browser needs to catch up on."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.bus = EventBus()
        self.gateway = Gateway(config)
        self.checkpoints = CheckpointStore(config.paths.checkpoints)
        self.memory = LearningEngine(
            config, self.bus, self.gateway, checkpoints=self.checkpoints,
            redact=Redactor([entry.api_key for entry in config.providers.values()
                             if entry.api_key]),
        )
        self.permissions = PermissionEngine(config, self.bus)
        self.permissions.on_denied = self.memory.on_denied
        self.skills = load_skills(config)
        self.mcp = MCPManager(config.mcp.servers) if config.mcp.enabled else None
        #: The most recent screenshot, and a number that changes with it, so a
        #: browser can tell whether the one it is showing is still current.
        self._screen: str = ""
        self._frames: int = 0
        self.conversation = Conversation()
        self.agent = AgentLoop(
            config, self.gateway,
            ToolRegistry(skills=self.skills, mcp=self.mcp, config=config,
                         spawn=spawner(config, self.gateway, self.bus,
                                       skills=self.skills, mcp=self.mcp)),
            self.bus, self.permissions, self.conversation, self.memory,
            skills=self.skills,
        )

        # Where conversations live. The same folder the terminal uses, on
        # purpose: a chat begun at the prompt should be openable in the browser
        # and the other way round, and two stores would have made the sidebar
        # a list of half the work.
        self.store = SessionStore(config.paths.user / "sessions")
        self.meta = SessionMeta(
            id=new_session_id(), cwd=str(config.paths.project),
            provider=config.provider, model=config.active_model(),
        )
        #: How much of the conversation is already on disk, so appending is
        #: appending rather than writing the whole thing again every turn.
        self._saved = 0
        #: Built on first use. Indexing every transcript takes a moment, and
        #: paying it at startup would delay a page that may never be searched.
        self._index: SessionIndex | None = None
        #: A sign-in in progress, when one is. At most one at a time: a
        #: second would leave the first holding a verifier for a code nobody
        #: is going to redeem.
        self._flow: Any = None
        #: Where in the event log this chat started. A page that reloads
        #: replays from here: zero while nobody has switched chats, so the
        #: whole session comes back, and the switch point afterwards, so one
        #: chat's events are not drawn into another's transcript.
        self._chat_from = 0

        self._log: list[dict[str, Any]] = []
        self._sequence = 0
        self._lock = threading.Lock()
        self._arrived = threading.Condition(self._lock)
        self._pending: dict[str, Request] = {}
        #: Downloads in flight, by model id. A download outlives the request
        #: that started it — minutes to an hour — so its state cannot live in
        #: the request, and the page reads it back from `local_shelf`.
        self._downloads: dict[str, dict[str, Any]] = {}
        self._turn = threading.Lock()
        self.busy = False

        self.bus.subscribe(self._record)

    # -- taking events off the bus ----------------------------------------- #

    def _record(self, event: Event) -> None:
        """Called on whatever thread emitted. Cheap, and never raises."""
        try:
            frame = self._as_json(event)
        except Exception:
            return
        if frame is None:
            return
        with self._arrived:
            self._sequence += 1
            frame["seq"] = self._sequence
            self._log.append(frame)
            if len(self._log) > HISTORY:
                del self._log[:len(self._log) - HISTORY]
            self._arrived.notify_all()

    def _as_json(self, event: Event) -> dict[str, Any] | None:
        kind = event.kind
        payload = {key: value for key, value in event.payload.items()
                   if key != "request"}

        if kind is Kind.SCREEN and payload.get("frame"):
            # Held aside rather than logged. The log keeps hundreds of events
            # and a browser re-reads it from a cursor; a megabyte of base64 in
            # there would be downloaded again every time somebody reconnected.
            with self._lock:
                self._frames += 1
                self._screen = payload.pop("frame")
                payload["frame"] = self._frames

        if kind is Kind.REQUEST:
            request: Request | None = event.payload.get("request")
            if request is None:
                return None
            # Held so the answer can find it. The worker thread is blocked on
            # this object right now.
            self._pending[request.id] = request
            payload = {"id": request.id, "prompt": request.prompt,
                       "options": list(request.options), "detail": request.detail,
                       # Not "kind": a Request has one of its own, and spread
                       # into the frame it silently overwrote the event's,
                       # turning every permission prompt into an event of kind
                       # "permission" that the page was not listening for.
                       "about": request.kind}
            # A question form is the whole point of its request and cannot be
            # rebuilt from prompt and options, so it rides along.
            if request.kind == "questions":
                payload["questions"] = request.meta.get("questions", [])

        return {**_plain(payload), "kind": kind.value, "at": time.time()}

    # -- what a browser asks for ------------------------------------------- #

    def screen(self) -> tuple[bytes, int]:
        """The latest frame as PNG bytes, and its number."""
        import base64

        with self._lock:
            data, number = self._screen, self._frames
        if not data:
            return b"", 0
        try:
            return base64.b64decode(data), number
        except Exception:
            return b"", number

    @property
    def cursor(self) -> int:
        """How far the event log has got, for a page that is about to redraw."""
        with self._lock:
            return self._sequence

    def since(self, cursor: int) -> list[dict[str, Any]]:
        with self._lock:
            return [frame for frame in self._log if frame["seq"] > cursor]

    def wait_for(self, cursor: int, timeout: float = 25.0) -> list[dict[str, Any]]:
        """Events after ``cursor``, waiting for one if there are none.

        The wait has a ceiling so the response ends by itself: a stream held
        open forever is a stream a proxy eventually kills, and a client that
        cannot tell a dead connection from a quiet one reconnects too late.
        """
        deadline = time.monotonic() + timeout
        with self._arrived:
            while True:
                ready = [frame for frame in self._log if frame["seq"] > cursor]
                if ready:
                    return ready
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._arrived.wait(remaining)

    def state(self) -> dict[str, Any]:
        usage = self.conversation.usage
        return {
            "provider": self.config.provider,
            "model": self.config.active_model(),
            "mode": self.config.agent.mode,
            "loop": self.config.agent.loop,
            "busy": self.busy,
            "cursor": self._chat_from,
            "usage": {
                "prompt": usage.prompt_tokens,
                "output": usage.output_tokens,
                "cached": usage.cached_tokens,
                "cost": round(usage.cost_usd, 4),
                "hit_rate": round(usage.cache_hit_rate, 3),
            },
            "context": {
                "limit": self.config.agent.context_limit,
                "used": usage.prompt_tokens,
            },
            "project": str(self.config.paths.project),
            "needs_setup": self.setup_needed(),
            "chat": {"id": self.meta.id, "title": self.meta.title,
                     "messages": len(self.conversation.messages)},
        }

    # -- chats -------------------------------------------------------------- #

    def _persist(self) -> None:
        """Write whatever the agent has said since the last time.

        Called after every turn and again at shutdown, because a turn that
        ends by the process being killed is exactly the one worth keeping.
        """
        messages = self.conversation.messages
        for message in messages[self._saved:]:
            try:
                self.store.append(self.meta.id, message)
            except OSError:
                return                      # a full disk must not kill the turn
        self._saved = len(messages)
        self.meta.messages = len(messages)
        self.meta.cost_usd = self.conversation.usage.cost_usd
        self.meta.model = self.config.active_model()
        self.meta.provider = self.config.provider
        self.meta.updated_at = time.time()
        try:
            self.store.save_meta(self.meta)
        except OSError:
            pass

    def chats(self, query: str = "", limit: int = 40) -> list[dict[str, Any]]:
        """The sidebar's list: recent chats, or the ones matching a search."""
        if query.strip():
            return self._search(query.strip(), limit)
        return [self._as_card(meta) for meta in self.store.list_sessions(limit)]

    def _search(self, query: str, limit: int) -> list[dict[str, Any]]:
        if self._index is None:
            self._index = SessionIndex(self.store)
            self._index.refresh()
        seen: dict[str, dict[str, Any]] = {}
        for hit in self._index.search(query, limit=limit * 3):
            if hit.session_id in seen:
                continue
            meta = self.store.load_meta(hit.session_id)
            card = self._as_card(meta) if meta else {
                "id": hit.session_id, "title": hit.session_id, "when": hit.when,
                "messages": 0, "cost": 0.0, "model": "", "current": False,
            }
            card["snippet"] = hit.snippet()
            seen[hit.session_id] = card
            if len(seen) >= limit:
                break
        return list(seen.values())

    def _as_card(self, meta: SessionMeta) -> dict[str, Any]:
        return {
            "id": meta.id,
            "title": meta.title or "Untitled",
            "when": meta.when,
            "updated_at": meta.updated_at,
            "messages": meta.messages,
            "cost": round(meta.cost_usd, 4),
            "model": meta.model,
            "current": meta.id == self.meta.id,
        }

    def new_chat(self) -> tuple[bool, str]:
        """Put the current conversation away and start an empty one."""
        if self.busy:
            return False, "a turn is running"
        self._persist()
        self.conversation.clear()
        self._saved = 0
        self.meta = SessionMeta(
            id=new_session_id(), cwd=str(self.config.paths.project),
            provider=self.config.provider, model=self.config.active_model(),
        )
        self._chat_from = self.cursor
        return True, ""

    def open_chat(self, session_id: str) -> tuple[bool, str, list[dict[str, Any]]]:
        """Load a stored chat, and hand the browser what to draw.

        The event log is the *live* stream and a resumed transcript was never
        in it, so the messages come back in this response rather than through
        the poll. The page redraws from them and carries on from the cursor it
        already has.
        """
        if self.busy:
            return False, "a turn is running", []
        meta = self.store.load_meta(session_id)
        if meta is None:
            return False, "no such chat", []
        messages = self.store.load(session_id)
        self._persist()
        self.conversation.clear()
        self.conversation.extend(messages)
        self.meta = meta
        self._saved = len(messages)
        self._chat_from = self.cursor
        return True, "", [_as_turn(message) for message in messages]

    def delete_chat(self, session_id: str) -> tuple[bool, str]:
        if session_id == self.meta.id:
            return False, "that is the chat you are in"
        if not self.store.delete(session_id):
            return False, "no such chat"
        if self._index is not None:
            self._index.forget(session_id)
        return True, ""

    # -- setting up ----------------------------------------------------------- #

    def setup_needed(self) -> bool:
        return bool(self.config.needs_setup)

    def offer(self) -> dict[str, Any]:
        """What could be set up, and what is already."""
        from .. import catalogue

        def card(spec: Any) -> dict[str, Any]:
            entry = self.config.providers.get(spec.id)
            return {
                "id": spec.id,
                "label": spec.label,
                "blurb": spec.blurb,
                "model": spec.default_model,
                "models": list(spec.models),
                "needs_key": bool(spec.needs_key),
                "can_sign_in": self.can_sign_in(spec.id),
                "keys_url": spec.keys_url,
                "base_url": spec.base_url,
                "ready": bool(entry and entry.ready),
            }

        found_running, found_keys = _what_is_already_here()
        return {
            "needed": self.setup_needed(),
            "providers": [card(spec) for spec in catalogue.offered()],
            "config_file": str(self.config.paths.config_file),
            # What the machine already has, so the first offer is not a list
            # of billing pages when the answer is a port that is already open.
            "running": [{"provider": item.provider, "label": item.label,
                         "models": item.models, "summary": item.summary,
                         "usable": item.usable}
                        for item in found_running],
            "exported": [{"provider": item.provider, "label": item.label,
                          "variable": item.variable}
                         for item in found_keys],
        }

    def set_up(self, provider: str, api_key: str = "", model: str = "",
               base_url: str = "") -> tuple[bool, str]:
        """Save a provider, the way the wizard does, and start using it."""
        from .. import catalogue
        from ..providers import registry

        spec = catalogue.get(provider)
        if spec is None and provider not in self.config.providers:
            return False, "no such provider"
        if spec is not None and spec.needs_key and not api_key.strip():
            return False, f"{spec.label} needs an API key"
        if spec is not None and not spec.base_url and not base_url.strip():
            return False, "that provider needs a URL"

        chosen = model.strip() or (spec.default_model if spec else "")
        if not chosen:
            return False, "which model?"

        try:
            self.config.use(provider, api_key=api_key.strip(),
                            model=chosen, base_url=base_url.strip())
            if registry.knows(chosen):
                window = registry.lookup(chosen).context
                if window:
                    self.config.agent.context_limit = window
            self.config.save()
        except OSError as error:
            return False, f"could not write the settings: {error}"

        self.config.first_run = False
        self.meta.provider = self.config.provider
        self.meta.model = self.config.active_model()
        # The gateway holds a client built from the old settings, and a client
        # built for no provider is a client that cannot answer.
        try:
            self.gateway.close()
        except Exception:
            pass
        self.gateway = Gateway(self.config)
        self.agent.gateway = self.gateway
        self.bus.emit(Kind.STATUS, provider=self.config.provider,
                      model=self.config.active_model())
        return True, ""

    # -- signing in instead of pasting a key ----------------------------------- #

    def can_sign_in(self, provider: str) -> bool:
        from ..providers import oauth

        return oauth.supports(provider)

    def sign_in_start(self, provider: str, browser: bool = True) -> dict[str, Any]:
        """Open a sign-in and hand back where to send the person.

        Two shapes. With a browser, a loopback server catches the redirect and
        the page polls until it lands. Without one — over SSH, in a container —
        no callback is given, OpenRouter shows the code, and it is pasted back.
        """
        from ..providers import oauth

        if not oauth.supports(provider):
            return {"ok": False, "error": "that provider has no sign-in"}

        self._end_any_sign_in()
        flow = oauth.begin_with_a_browser() if browser else None
        if flow is None:
            flow = oauth.begin()
        self._flow = flow
        return {
            "ok": True,
            "url": flow.url,
            # A headless flow needs the code typing back; the other resolves
            # itself and the page only has to wait.
            "paste_the_code": flow.headless,
            "expires_in": oauth.GOOD_FOR,
        }

    def sign_in_finish(self, code: str = "") -> tuple[bool, str]:
        """Redeem whatever the flow has, and save the key it returns."""
        from ..providers import oauth

        flow = self._flow
        if flow is None:
            return False, "no sign-in is in progress"
        if flow.error:
            self._end_any_sign_in()
            return False, f"OpenRouter refused: {flow.error}"

        try:
            key = oauth.redeem(flow, code)
        except oauth.OAuthError as error:
            if not flow.headless or code:
                self._end_any_sign_in()
            return False, str(error)
        finally:
            if flow is self._flow and (code or flow.code):
                self._end_any_sign_in()

        done, why = self.set_up(flow.provider, api_key=key)
        return (True, "") if done else (False, why)

    def sign_in_state(self) -> dict[str, Any]:
        """Whether the browser has come back yet."""
        flow = self._flow
        if flow is None:
            return {"waiting": False, "ready": False, "error": ""}
        return {
            "waiting": not flow.code and not flow.error and not flow.expired,
            "ready": bool(flow.code),
            "error": flow.error or ("that took longer than ten minutes"
                                    if flow.expired else ""),
        }

    def _end_any_sign_in(self) -> None:
        flow, self._flow = self._flow, None
        if flow is not None:
            flow.close()

    # -- what a provider can actually run ------------------------------------- #

    def models_for(self, provider: str, refresh: bool = False) -> dict[str, Any]:
        """Every model this provider offers, from the provider.

        The catalogue's handful of names is a default for somebody who has not
        chosen, and it was being used as the list of what exists — six names
        where OpenRouter publishes four hundred, and will say so to anybody who
        asks without a key.
        """
        from ..providers import models as model_list

        entry = self.config.providers.get(provider)
        try:
            found = model_list.listing(
                provider,
                api_key=entry.api_key if entry else "",
                base_url=entry.base_url if entry else "",
                cache_root=self.config.paths.user,
                refresh=refresh)
        except Exception as error:
            return {"provider": provider, "models": [], "source": "catalogue",
                    "error": f"{type(error).__name__}", "age_seconds": 0}
        return found.as_dict()

    # -- where the agent works ------------------------------------------------ #

    def folder(self) -> dict[str, Any]:
        """The folder in use, and what is beside it to move to."""
        here = Path(self.config.paths.project)
        siblings: list[dict[str, Any]] = []
        for candidate in (here.parent, Path.home()):
            try:
                for child in sorted(candidate.iterdir()):
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    siblings.append({"path": str(child), "name": child.name,
                                     "marked": _looks_like_a_project(child)})
                    if len(siblings) >= 60:
                        break
            except OSError:
                continue
            if siblings:
                break

        return {
            "current": str(here),
            "name": here.name,
            "is_project": _looks_like_a_project(here),
            "parent": str(here.parent),
            "home": str(Path.home()),
            "siblings": siblings,
            "confined": bool(self.config.safety.workspace_only),
            "messages": len(self.conversation.messages),
        }

    def change_folder(self, where: str) -> tuple[bool, str, dict[str, Any]]:
        """Work somewhere else, which means work on something else.

        A different folder is a different project: its own learned rules, its
        own checkpoints, its own conversation. So this is not a setting that is
        edited in place — the chat is saved, the brain is re-scoped, and a new
        conversation starts. The page asks before calling it, because losing
        your place is not something to discover afterwards.
        """
        if self.busy:
            return False, "a turn is running", {}

        if not (where or "").strip():
            # `Path("").resolve()` is the current directory, so an empty field
            # would move the agent to wherever the process was started rather
            # than being refused.
            return False, "no folder given", {}

        target = Path(where).expanduser()
        try:
            target = target.resolve(strict=True)
        except (OSError, RuntimeError):
            return False, "there is no folder there", {}
        if not target.is_dir():
            return False, "that is a file, not a folder", {}
        if target == Path(self.config.paths.project).resolve():
            return True, "", self.folder()

        # Everything said so far belongs to the folder it was said in.
        self._persist()

        self.config.paths = Paths(user=self.config.paths.user, project=target)

        # The brain is scoped by project and reads that scope once, when it is
        # built. Rebuilding it is what makes the move a move rather than a new
        # label on the old memory.
        try:
            self.memory.close()
        except Exception:
            pass
        self.memory = LearningEngine(
            self.config, self.bus, self.gateway, checkpoints=self.checkpoints,
            redact=Redactor([entry.api_key for entry in self.config.providers.values()
                             if entry.api_key]),
        )
        self.permissions.on_denied = self.memory.on_denied
        self.skills = load_skills(self.config)

        self.conversation.clear()
        self._saved = 0
        self.meta = SessionMeta(
            id=new_session_id(), cwd=str(target),
            provider=self.config.provider, model=self.config.active_model(),
        )
        self._chat_from = self.cursor

        self.agent = AgentLoop(
            self.config, self.gateway,
            ToolRegistry(skills=self.skills, mcp=self.mcp, config=self.config,
                         spawn=spawner(self.config, self.gateway, self.bus,
                                       skills=self.skills, mcp=self.mcp)),
            self.bus, self.permissions, self.conversation, self.memory,
            skills=self.skills,
        )
        self.bus.emit(Kind.STATUS, project=str(target))
        return True, "", self.folder()

    # -- skills ---------------------------------------------------------------- #


    # -- models that run here ---------------------------------------------- #
    #
    # A download is minutes long, so it cannot happen inside the request that
    # starts it: the browser would sit on an open connection for an hour and
    # any proxy in between would give up long before that. It runs on its own
    # thread and reports through the same event stream the agent uses, so the
    # page draws a bar from events rather than by polling.

    def local_shelf(self) -> dict[str, Any]:
        """The model list, what is downloaded, and what this machine can take."""
        from .. import local as local_models

        try:
            catalogue = local_models.load(Path(self.config.paths.user))
        except Exception as problem:
            return {"ok": False, "error": str(problem), "models": []}

        store = local_models.store_for(Path(self.config.paths.user))
        ram = local_models.memory_gb()
        free = store.free_bytes()
        active = (self.config.provider == "local", self.config.active_model())

        models = []
        for model in catalogue:
            held = store.have(model)
            partial = store.partial_bytes(model)
            downloading = self._downloads.get(model.id)
            models.append({
                "id": model.id,
                "name": model.name,
                "description": model.description,
                "size": model.size,
                "gigabytes": round(model.gigabytes, 2),
                "context": model.context,
                "parameters": model.parameters,
                "quantization": model.quantization,
                "needs_ram_gb": model.needs_ram_gb,
                "license": model.license,
                "good_at": list(model.good_at),
                "tools": model.tools,
                "vision": model.vision,
                "url": model.url,
                "downloaded": bool(held and held.complete),
                "partial_bytes": partial,
                "fits": model.fits(ram),
                "room": store.room_for(model),
                "busy": bool(downloading and not downloading.get("finished")),
                "active": active[0] and active[1] == model.id,
            })

        return {
            "ok": True,
            "models": models,
            "source": catalogue.source,
            "updated": catalogue.updated,
            "memory_gb": round(ram, 1) if ram else None,
            "free_bytes": free,
            "used_bytes": store.bytes_used(),
            "directory": str(store.root),
            # Whether anything on this machine can actually run a downloaded
            # file. Worth saying before somebody spends an hour on one.
            "runtime": str(local_models.find_binary() or ""),
        }

    def local_get(self, model_id: str) -> tuple[bool, str]:
        """Start downloading a model. Returns immediately."""
        import threading

        from .. import local as local_models

        with self._lock:
            running = self._downloads.get(model_id)
            if running and not running.get("finished"):
                return False, "that one is already downloading"

        try:
            catalogue = local_models.load(Path(self.config.paths.user),
                                          allow_network=False)
        except Exception as problem:
            return False, str(problem)
        model = catalogue.get(model_id)
        if model is None:
            return False, f"no model called {model_id!r}"

        store = local_models.store_for(Path(self.config.paths.user))
        if store.room_for(model) is False:
            free = store.free_bytes() or 0
            return False, (f"not enough disk: {model.gigabytes:.1f} GB needed, "
                           f"{local_models.human_bytes(free)} free")

        with self._lock:
            self._downloads[model_id] = {"finished": False, "cancelled": False}

        def work() -> None:
            def watch(progress) -> None:
                self.bus.emit(Kind.NOTICE, what="download",
                              model=model.id, name=model.name,
                              **progress.as_dict())

            try:
                local_models.fetch(
                    model.url, store.path_for(model),
                    expect_size=model.size, expect_sha256=model.sha256,
                    watch=watch,
                    should_stop=lambda: self._downloads.get(
                        model.id, {}).get("cancelled", False))
            except Exception as problem:
                self.bus.emit(Kind.NOTICE, what="download", model=model.id,
                              name=model.name, failed=True, error=str(problem))
            else:
                self.bus.emit(Kind.NOTICE, what="download", model=model.id,
                              name=model.name, finished=True,
                              done_bytes=model.size, total=model.size,
                              percent=100.0)
            finally:
                with self._lock:
                    entry = self._downloads.get(model.id)
                    if entry is not None:
                        entry["finished"] = True

        threading.Thread(target=work, name=f"comodor-get-{model.id}",
                         daemon=True).start()
        return True, ""

    def local_cancel(self, model_id: str) -> tuple[bool, str]:
        """Stop a download. What has arrived is kept and can be resumed."""
        with self._lock:
            entry = self._downloads.get(model_id)
            if entry is None or entry.get("finished"):
                return False, "nothing is downloading"
            entry["cancelled"] = True
        return True, ""

    def local_remove(self, model_id: str) -> tuple[bool, str]:
        from .. import local as local_models

        try:
            catalogue = local_models.load(Path(self.config.paths.user),
                                          allow_network=False)
        except Exception as problem:
            return False, str(problem)
        model = catalogue.get(model_id)
        if model is None:
            return False, f"no model called {model_id!r}"
        store = local_models.store_for(Path(self.config.paths.user))
        return (True, "") if store.remove(model) else (False, "it was not here")

    def local_use(self, model_id: str) -> tuple[bool, str]:
        """Make a downloaded model the one the agent talks to."""
        from .. import config as config_mod
        from .. import local as local_models

        try:
            catalogue = local_models.load(Path(self.config.paths.user),
                                          allow_network=False)
        except Exception as problem:
            return False, str(problem)
        model = catalogue.get(model_id)
        if model is None:
            return False, f"no model called {model_id!r}"

        store = local_models.store_for(Path(self.config.paths.user))
        held = store.have(model)
        if not (held and held.complete):
            return False, f"{model.name} is not downloaded yet"

        entry = self.config.use("local", model=model.id)
        entry.label = "Local"
        entry.configured = True
        config_mod.save_user_config(self.config)
        # The gateway holds a client built from the previous provider, and one
        # built for a different provider cannot answer for this one.
        try:
            self.gateway.close()
        except Exception:
            pass
        self.gateway = Gateway(self.config)
        self.agent.gateway = self.gateway
        self.bus.emit(Kind.STATUS, provider="local", model=model.id)
        return True, ""

    def skill_shelf(self, refresh: bool = False) -> dict[str, Any]:
        """What is installed, what is available, and what is switched off."""
        from ..skills import catalogue as library

        disabled = set(self.config.skills.disabled)
        root = self.config.paths.skills

        mine: dict[str, dict[str, Any]] = {}
        for skill in self.skills.skills.values():
            mine[skill.name] = {
                "id": skill.name,
                "name": skill.name,
                "description": skill.description,
                "scope": skill.scope,
                "installed": True,
                # Both, because the file itself can say `enabled: false` and
                # the setting can too, and a panel that showed only one of
                # them would have a switch that appears not to work.
                "enabled": bool(skill.enabled) and skill.name not in disabled,
                "managed": False,
                "available": False,
            }

        offered: list[dict[str, Any]] = []
        error = ""
        try:
            shelf = library.fetch(self.config.skills.catalogue_url,
                                  cache_root=self.config.paths.user,
                                  timeout=(4.0, 8.0))
        except Exception as problem:
            shelf, error = None, f"{type(problem).__name__}"

        if shelf is not None:
            for entry in shelf.skills:
                state = library.installed(root, entry.id)
                card = {
                    "id": entry.id,
                    "name": entry.id,
                    "description": entry.description,
                    "scope": "user",
                    "installed": bool(state.present),
                    "enabled": entry.id not in disabled,
                    "managed": bool(state.managed),
                    "available": True,
                }
                if entry.id in mine:
                    mine[entry.id].update({"available": True,
                                           "managed": bool(state.managed),
                                           "description": entry.description
                                           or mine[entry.id]["description"]})
                else:
                    offered.append(card)

        return {
            "skills": sorted(mine.values(), key=lambda item: item["id"]) + offered,
            "error": error,
            "folder": str(root),
        }

    def skill(self, action: str, name: str) -> tuple[bool, str]:
        """Install, remove, or switch one off."""
        from ..skills import catalogue as library

        name = (name or "").strip()
        if not name:
            return False, "which skill?"

        if action in ("enable", "disable"):
            disabled = [item for item in self.config.skills.disabled if item != name]
            if action == "disable":
                disabled.append(name)
            self.config.skills.disabled = sorted(set(disabled))
            try:
                self.config.save()
            except OSError as error:
                return False, f"could not write the settings: {error}"
            self._reload_skills()
            return True, ""

        if action == "install":
            try:
                shelf = library.fetch(self.config.skills.catalogue_url,
                                      cache_root=self.config.paths.user)
                entry = shelf.get(name)
                if entry is None:
                    return False, "no such skill in the library"
                self.config.paths.skills.mkdir(parents=True, exist_ok=True)
                library.install(entry, shelf, self.config.paths.skills)
            except Exception as error:
                return False, f"{error}"
            self._reload_skills()
            return True, ""

        if action == "remove":
            # Only what this program installed. A folder somebody wrote by
            # hand is not ours to delete, and the stamp is how they are told
            # apart.
            if not library.remove(self.config.paths.skills, name):
                return False, ("that one was not installed by Comodor — "
                               "switch it off instead, or delete the folder "
                               "yourself")
            self._reload_skills()
            return True, ""

        return False, f"{action!r} is not something to do to a skill"

    def _reload_skills(self) -> None:
        """Re-read the folder and hand the new set to the running agent."""
        self.skills = load_skills(self.config)
        try:
            self.agent.skills = self.skills
            self.agent.tools.skills = self.skills
        except Exception:
            pass

    # -- rules ---------------------------------------------------------------- #

    def rules(self) -> dict[str, Any]:
        """Every house rule, and enough about each to judge it.

        Both kinds together, sorted with the ones the user wrote first: those
        are not a guess about how somebody works, they are an instruction, and
        burying them under forty counted observations reads as the agent
        having opinions of its own.
        """
        try:
            found = self.memory.all_rules()
        except Exception:
            return {"rules": [], "active": 0, "enabled": False}

        def card(rule: Any) -> dict[str, Any]:
            return {
                "id": rule.id,
                "statement": rule.statement,
                "detail": rule.detail,
                "category": rule.category,
                "scope": rule.scope,
                "source": rule.source,
                "support": rule.support,
                "against": rule.against,
                "strength": round(rule.strength, 2),
                "confident": rule.confident,
                "pinned": rule.pinned,
                "active": rule.active,
                "mine": rule.source == "user",
            }

        cards = [card(rule) for rule in found]
        cards.sort(key=lambda item: (not item["mine"], not item["confident"],
                                     -item["support"]))
        return {
            "rules": cards,
            "active": sum(1 for item in cards if item["confident"]
                          and item["active"]),
            "enabled": bool(self.config.learning.enabled
                            and self.config.learning.rules),
        }

    def rule(self, action: str, **fields: Any) -> tuple[bool, str, Any]:
        """Write, drop, pin or switch off one rule.

        Returns whether it took, why not, and whatever the caller needs back —
        the stored rule for a write, the path for an export.
        """
        if action == "teach":
            statement = str(fields.get("statement") or "").strip()
            if not statement:
                return False, "a rule needs something to say", None
            if len(statement) > 300:
                return False, "that is longer than a rule should be", None
            written = self.memory.teach_rule(statement)
            return True, "", {"id": written.id, "statement": written.statement}

        try:
            rule_id = int(fields.get("id"))
        except (TypeError, ValueError):
            return False, "which rule?", None

        if action == "forget":
            return (True, "", None) if self.memory.forget_rule(rule_id) \
                else (False, "no such rule", None)
        if action in ("pin", "unpin"):
            done = self.memory.set_rule(rule_id, pinned=action == "pin")
            return (True, "", None) if done else (False, "no such rule", None)
        if action in ("enable", "disable"):
            # Off, not gone. A rule that is right in general and wrong for this
            # project is not a rule to delete, and deleting was the only thing
            # on offer.
            done = self.memory.set_rule(rule_id, active=action == "enable")
            return (True, "", None) if done else (False, "no such rule", None)

        return False, f"{action!r} is not something to do to a rule", None

    def export_rules(self) -> tuple[bool, str, str]:
        """Write them where a team can read and commit them."""
        try:
            where = self.memory.export_rules()
        except Exception as error:
            return False, f"{type(error).__name__}: {error}", ""
        return True, "", str(where)

    # -- what the agent is, right now ---------------------------------------- #

    def admin(self) -> dict[str, Any]:
        """Everything the Admin panel shows, gathered once.

        Read-only apart from what `setting` accepts. Nothing here may raise:
        the panel describing the agent must not be the thing that breaks it,
        so each part that can fail is guarded and simply says less.
        """
        from .. import catalogue
        from .._version import __version__

        entry = self.config.providers.get(self.config.provider)
        spec = catalogue.get(self.config.provider)
        safety = self.config.safety

        try:
            models = sorted({
                *(spec.models if spec else ()),
                *( (entry.model,) if entry and entry.model else () ),
                self.config.active_model(),
            })
        except Exception:
            models = [self.config.active_model()]

        try:
            tools = [{"name": tool.name, "risk": int(tool.risk),
                      "description": (tool.description or "").strip().split("\n")[0]}
                     for tool in sorted(self.agent.tools.all(),
                                        key=lambda item: item.name)]
        except Exception:
            tools = []

        try:
            reflex = self.memory.stats()
        except Exception:
            reflex = {}

        return {
            "app": {"version": __version__, "python": _python(),
                    "platform": _platform()},
            "model": {
                "provider": self.config.provider,
                "provider_label": entry.display if entry else self.config.provider,
                "model": self.config.active_model(),
                "models": models,
                "providers": [{"id": name, "label": item.display,
                               "model": item.model, "ready": item.ready}
                              for name, item in self.config.providers.items()],
                # Whether there is one, never what it is.
                "has_key": bool(entry and entry.api_key),
                "can_sign_in": self.can_sign_in(self.config.provider),
            },
            "agent": {
                "mode": self.config.agent.mode,
                "loop": self.config.agent.loop,
                "max_steps": self.config.agent.max_steps,
                "max_seconds": self.config.agent.max_seconds,
                "max_cost_usd": self.config.agent.max_cost_usd,
                "context_limit": self.config.agent.context_limit,
                "compact_at": self.config.agent.compact_at,
            },
            "tools": tools,
            "skills": [{"name": skill.name,
                        "description": (getattr(skill, "description", "") or "")}
                       for skill in self.skills.skills.values()],
            "mcp": {
                "enabled": bool(self.config.mcp.enabled),
                "servers": list(getattr(self.config.mcp, "servers", {})),
            },
            # Whether it is set up, and nothing else. Not the token, which is a
            # credential, and not the account ids, which name people — this
            # panel is served over a URL that can be shared by accident.
            "telegram": {
                "connected": bool(self.config.telegram.token),
                "paired": len(self.config.telegram.allowed),
                "enabled": bool(self.config.telegram.enabled),
                "writes": bool(self.config.telegram.allow_writes),
            },
            "reflex": {
                "lessons": reflex.get("lessons", 0),
                "rules": reflex.get("rules", 0),
                "rules_active": reflex.get("rules_active", 0),
                "skills": reflex.get("skills", 0),
                "episodes": reflex.get("episodes", 0),
                "signals": reflex.get("signals", 0),
                "success_rate": round(float(reflex.get("success_rate", 0.0)), 3),
                # Rules learned in other folders. Counted separately and named
                # as such: the strip used to add them to this folder's total,
                # so it said eight while the panel beside it, correctly scoped,
                # listed none.
                "rules_elsewhere": max(0, int(reflex.get("rules_everywhere", 0))
                                       - int(reflex.get("rules_active", 0))),
            },
            "safety": {
                "auto_approve_safe": safety.auto_approve_safe,
                "auto_approve_writes": safety.auto_approve_writes,
                "auto_approve_shell": safety.auto_approve_shell,
                "checkpoints": safety.checkpoints,
                "workspace_only": safety.workspace_only,
                "grants": self.permissions.grants,
                "denied": len(self.permissions.denials),
            },
            "paths": {
                "project": str(self.config.paths.project),
                "config": str(self.config.paths.config_file),
                "sessions": str(self.store.root),
                "brain": str(self.config.paths.brain_db),
            },
        }

    def setting(self, key: str, value: Any) -> tuple[bool, str]:
        """Change one thing from the browser.

        Deliberately short. The three settings here change *which model
        answers and how far it may go on its own* - the questions somebody
        managing a run actually asks. What is missing is as considered as what
        is here: nothing that widens what the agent may do to the machine can
        be switched on from a web page, because the page is reachable by
        anyone holding the token and the permission prompts already offer that
        choice per action, in front of the person about to live with it.
        """
        if key == "mode":
            return (True, "") if self.set_mode(str(value)) else (False, "unknown mode")

        if key == "loop":
            self.config.agent.loop = bool(value)
            self.bus.emit(Kind.STATUS, loop=self.config.agent.loop)
            return True, ""

        if key == "model":
            model = str(value).strip()
            if not model:
                return False, "no model given"
            self.config.model = model
            self.meta.model = model
            self._follow_the_window(model)
            self.bus.emit(Kind.STATUS, model=model)
            return True, ""

        if key == "api_key":
            # Set for whichever provider is active. Somebody who set Comodor
            # up with the wrong key, or rotated one, had to find a terminal.
            new_key = str(value).strip()
            if not new_key:
                return False, "a key with nothing in it is not a key"
            entry = self.config.providers.get(self.config.provider)
            if entry is None:
                return False, "no provider is selected"
            entry.api_key = new_key
            entry.configured = True
            try:
                self.config.save()
            except OSError as error:
                return False, f"could not write the settings: {error}"
            # The gateway holds a client built with the old key.
            try:
                self.gateway.close()
            except Exception:
                pass
            self.gateway = Gateway(self.config)
            self.agent.gateway = self.gateway
            return True, ""

        if key == "provider":
            entry = self.config.providers.get(str(value))
            if entry is None:
                return False, "unknown provider"
            if not entry.ready:
                return False, f"{entry.display} has no API key yet"
            self.config.provider = str(value)
            self.config.model = entry.model
            self.meta.provider = str(value)
            self.meta.model = entry.model
            self._follow_the_window(entry.model)
            self.bus.emit(Kind.STATUS, provider=entry.display, model=entry.model)
            return True, ""

        return False, f"{key!r} is not something this page may change"

    def _follow_the_window(self, model: str) -> None:
        """The context window belongs to the model, not to the configuration.

        Left at the previous model's number after a switch, the loop never
        compacts and the run dies at the provider's real ceiling instead.
        """
        from ..providers import registry

        if not registry.knows(model):
            return                          # invented defaults are worse
        window = registry.lookup(model).context
        if window:
            self.config.agent.context_limit = window

    # -- what a browser does ------------------------------------------------ #

    def send(self, text: str) -> bool:
        """Start a turn. False if one is already running."""
        if not text.strip():
            return False
        if not self._turn.acquire(blocking=False):
            return False

        if not self.meta.title:
            self.meta.title = derive_title(text)

        def work() -> None:
            self.busy = True
            self.bus.emit(Kind.STATUS, busy=True)
            try:
                self.agent.run(text)
            except Exception as error:                # never lose the worker
                self.bus.emit(Kind.ERROR, text=f"{type(error).__name__}: {error}")
            finally:
                self.busy = False
                # Saved before the lock is released, so the next turn cannot
                # start writing messages into a store that is mid-append.
                try:
                    self._persist()
                except Exception:
                    pass
                self.bus.emit(Kind.STATUS, busy=False)
                self._turn.release()

        threading.Thread(target=work, name="comodor-web-turn", daemon=True).start()
        return True

    def answer(self, request_id: str, choice: str) -> tuple[bool, str]:
        """Answer a waiting prompt. Returns whether it took, and why not.

        The choice has to be one the request offered. Accepting anything else
        and reporting success is the worst available behaviour: the permission
        engine does not recognise the word, treats the turn as refused, and the
        caller is told it worked.
        """
        request = self._pending.get(request_id)
        if request is None:
            return False, "nothing is waiting on that"
        if request.answered:
            return False, "that was already answered"
        # A form answers with a JSON document rather than one of a fixed set,
        # so there is nothing to check membership against — the request carries
        # no options at all. What it does need is to be readable: an answer
        # that fails to parse would reach the tool as "cancelled" while the
        # browser was told it had been sent.
        if request.kind == "questions":
            if decode_answers(choice) is None and choice != CANCELLED:
                return False, "those answers could not be read"
        elif request.options and choice not in request.options:
            return False, (f"{choice!r} is not one of the choices: "
                           f"{', '.join(request.options)}")

        self._pending.pop(request_id, None)
        request.answer(choice)
        return True, ""

    def interrupt(self) -> None:
        self.agent.interrupt()

    def set_mode(self, mode: str) -> bool:
        if mode not in ("act", "plan", "chat"):
            return False
        self.config.agent.mode = mode
        self.bus.emit(Kind.STATUS, mode=mode)
        return True

    def close(self) -> None:
        self._end_any_sign_in()
        # The transcript first: a session ended by the process going away is
        # exactly the one somebody wanted to come back to.
        try:
            self._persist()
        except Exception:
            pass
        if self._index is not None:
            try:
                self._index.close()
            except Exception:
                pass
        # Deny anything still waiting, or a worker thread blocks until timeout.
        for request in list(self._pending.values()):
            if not request.answered:
                request.answer(request.options[-1] if request.options else "no")
        self._pending.clear()
        try:
            self.agent.tools.close()
        except Exception:
            pass
        try:
            self.memory.close()
        except Exception:
            pass
        if self.mcp is not None:
            try:
                self.mcp.close()
            except Exception:
                pass


#: Files that say "somebody works on something here" rather than "this is a
#: folder". Used only to mark a row in the folder picker, never to refuse one.
PROJECT_MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml",
                   "go.mod", "pom.xml", "build.gradle", "Makefile",
                   "composer.json", "Gemfile", ".comodor")


def _looks_like_a_project(where: Path) -> bool:
    try:
        return any((where / marker).exists() for marker in PROJECT_MARKERS)
    except OSError:
        return False


def _what_is_already_here() -> tuple[list[Any], list[Any]]:
    """Local runtimes and exported keys, and never an exception.

    This runs on the path that draws the first screen somebody sees. A
    provider probe that raises there is a blank page instead of a question.
    """
    try:
        from ..providers import discover

        return discover.running_here(), discover.keys_in_the_environment()
    except Exception:
        return [], []


def _as_turn(message: Message) -> dict[str, Any]:
    """One stored message, in the shape the page already draws live events in.

    Reusing the live shape means a resumed chat and a running one go through
    the same renderer, so they cannot drift apart in the way that leaves an
    old conversation looking subtly unlike a new one.
    """
    role = getattr(message.role, "value", str(message.role))
    if role == "tool":
        return {"kind": "tool", "name": message.name or "tool",
                "ok": not message.is_error,
                "text": (message.content or "")[:4000]}
    return {"kind": role, "text": message.content or ""}


def _python() -> str:
    import sys

    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _platform() -> str:
    import platform

    return f"{platform.system()} {platform.release()}".strip()


def _plain(value: Any) -> Any:
    """Whatever will survive `json.dumps`, and nothing that will not."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "as_dict"):
        try:
            return _plain(value.as_dict())
        except Exception:
            pass
    return str(value)
