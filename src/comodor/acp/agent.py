"""Comodor as an ACP agent, driven by an editor.

The third interface, and the least code of the three. That is the point of
having had an event bus from the beginning: the terminal draws the events, the
browser sends them as JSON, and this translates them into `session/update`
notifications. None of them is the agent — the agent is underneath, and it does
not know which one is watching.

What has to be got right is not the loop; it is four seams:

**stdout belongs to the protocol.** An editor parses every line it is handed,
so a banner, a warning or a stray `print` is a protocol error. The stream is
taken away from the rest of the program at start-up and replaced with stderr,
which the specification sets aside for logging.

**Permission is a request in the other direction.** Comodor blocks a worker
thread on a `Request` until somebody answers. ACP has the agent ask the client
and wait. Those are the same shape, so the permission engine is untouched: the
thing that answers the prompt is an editor rather than a keyboard.

**One session per conversation, and the editor names them.** ACP sessions map
onto the transcripts Comodor already keeps, so a session resumed in an editor
is the same conversation the terminal would resume.

**Cancellation arrives while the model is mid-sentence.** `session/cancel` is a
notification, which means it is read while the worker is busy — the same case
the terminal's escape key already handles.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .._version import __version__
from ..agent import AgentLoop, Conversation
from ..agent.spawn import spawner
from ..config import Config
from ..events import Event, EventBus, Kind, Request
from ..learning import LearningEngine
from ..mcp import MCPManager
from ..paths import Paths
from ..providers.gateway import Gateway
from ..safety import CheckpointStore, PermissionEngine, Redactor
from ..session import SessionMeta, SessionStore, derive_title, new_session_id
from ..skills import load_for as load_skills
from ..tools import ToolRegistry
from .jsonrpc import AUTH_REQUIRED, INVALID_PARAMS, Connection, RpcError

#: The version of ACP this speaks.
PROTOCOL_VERSION = 2

#: Comodor's tool names, in the vocabulary ACP uses to pick an icon. Anything
#: unlisted is `other`, which is honest: a wrong icon is worse than none.
TOOL_KINDS: dict[str, str] = {
    "read_file": "read", "list_files": "read", "glob": "search",
    "grep": "search", "search_web": "fetch", "fetch_url": "fetch",
    "write_file": "edit", "edit_file": "edit", "apply_patch": "edit",
    "delete_file": "delete", "move_file": "move", "rename_file": "move",
    "run_shell": "execute", "shell": "execute", "computer": "execute",
    "browser": "fetch", "browse": "fetch", "todo": "think",
    "delegate": "think", "memory": "think", "skills": "think",
}


def tool_kind(name: str) -> str:
    if name in TOOL_KINDS:
        return TOOL_KINDS[name]
    # A name this build has not seen — an MCP server's tool, or one added
    # later. Guessed from the verb, and `other` when there is no verb.
    lowered = name.lower()
    for verb, kind in (("read", "read"), ("get", "read"), ("list", "read"),
                       ("search", "search"), ("find", "search"),
                       ("write", "edit"), ("edit", "edit"), ("update", "edit"),
                       ("create", "edit"), ("delete", "delete"),
                       ("remove", "delete"), ("move", "move"),
                       ("run", "execute"), ("exec", "execute"),
                       ("fetch", "fetch"), ("http", "fetch")):
        if lowered.startswith(verb) or f"_{verb}" in lowered:
            return kind
    return "other"


class AcpSession:
    """One ACP session: a conversation, a worker, and the bus between them."""

    def __init__(self, session_id: str, config: Config, agent: "ComodorAgent",
                 cwd: Path) -> None:
        self.id = session_id
        self.agent = agent
        self.cwd = cwd
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
        self.conversation = Conversation()
        self.loop = AgentLoop(
            config, self.gateway,
            ToolRegistry(skills=self.skills, mcp=self.mcp, config=config,
                         spawn=spawner(config, self.gateway, self.bus,
                                       skills=self.skills, mcp=self.mcp)),
            self.bus, self.permissions, self.conversation, self.memory,
            skills=self.skills,
        )

        self.store = SessionStore(config.paths.user / "sessions")
        self.meta = SessionMeta(id=session_id, cwd=str(cwd),
                                provider=config.provider, model=config.active_model())
        self._saved = 0

        self.busy = False
        self._turn = threading.Lock()
        #: The message currently being streamed, so chunks carry its id.
        self._message_id = ""
        #: Tool calls seen this turn, so an update can name the one it means.
        self._tools: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, Request] = {}

        self.bus.subscribe(self._on_event)

    # -- talking to the editor ---------------------------------------------- #

    def update(self, body: dict[str, Any]) -> None:
        self.agent.rpc.notify("session/update",
                              {"sessionId": self.id, "update": body})

    def _on_event(self, event: Event) -> None:
        """Every event, translated. Called on whatever thread emitted it."""
        try:
            self._translate(event)
        except Exception as error:
            self.agent.rpc.warn(f"acp: {type(error).__name__}: {error}")

    def _translate(self, event: Event) -> None:
        kind = event.kind
        payload = event.payload

        if kind is Kind.USER_MESSAGE:
            self.update({"sessionUpdate": "user_message",
                         "messageId": f"msg_{int(time.time() * 1000)}",
                         "content": [{"type": "text",
                                      "text": str(payload.get("text") or "")}]})
            return

        if kind is Kind.ASSISTANT_START:
            self._message_id = f"msg_agent_{int(time.time() * 1000)}"
            return

        if kind is Kind.ASSISTANT_DELTA:
            text = str(payload.get("text") or "")
            if not text:
                return
            if not self._message_id:
                self._message_id = f"msg_agent_{int(time.time() * 1000)}"
            self.update({"sessionUpdate": "agent_message_chunk",
                         "messageId": self._message_id,
                         "content": {"type": "text", "text": text}})
            return

        if kind is Kind.ASSISTANT_END:
            self._message_id = ""
            return

        if kind is Kind.TOOL_START:
            call_id = str(payload.get("id") or "")
            name = str(payload.get("name") or "tool")
            summary = str(payload.get("summary") or "")
            self._tools[call_id] = {"name": name}
            self.update({"sessionUpdate": "tool_call_update",
                         "toolCallId": call_id,
                         "title": f"{name} {summary}".strip(),
                         "kind": tool_kind(name),
                         "status": "in_progress"})
            return

        if kind is Kind.TOOL_END:
            call_id = str(payload.get("id") or "")
            ok = payload.get("ok") is not False
            body: dict[str, Any] = {"sessionUpdate": "tool_call_update",
                                    "toolCallId": call_id,
                                    "status": "completed" if ok else "failed"}
            shown = str(payload.get("display") or "").strip()
            if shown:
                body["content"] = [{"type": "content",
                                    "content": {"type": "text",
                                                "text": shown[:8000]}}]
            self.update(body)
            self._tools.pop(call_id, None)
            return

        if kind is Kind.TODO:
            entries = payload.get("items") or []
            if not isinstance(entries, list):
                return
            self.update({"sessionUpdate": "plan_update",
                         "plan": {"type": "items", "planId": f"plan_{self.id}",
                                  "entries": [
                                      {"content": str(item.get("text") or item),
                                       "priority": "medium",
                                       "status": _plan_status(item)}
                                      for item in entries if item]}})
            return

        if kind is Kind.REQUEST:
            request = payload.get("request")
            if isinstance(request, Request):
                # On its own thread: the worker that raised it is blocked
                # waiting, and asking the editor from here would deadlock the
                # bus.
                threading.Thread(target=self._ask, args=(request,),
                                 name="comodor-acp-permission", daemon=True).start()
            return

        if kind is Kind.ERROR:
            self.update({"sessionUpdate": "agent_message_chunk",
                         "messageId": self._message_id
                         or f"msg_agent_{int(time.time() * 1000)}",
                         "content": {"type": "text",
                                     "text": f"\n\n{payload.get('text') or 'error'}"}})
            return

    # -- permission ---------------------------------------------------------- #

    def _ask(self, request: Request) -> None:
        """Put a permission prompt to the editor and answer the worker."""
        self._pending[request.id] = request
        if request.kind == "mode":
            # A proposed mode change: the modes are the options, labelled as
            # themselves. Every choice is "other" to ACP — none of them is an
            # allow or a reject — and the editor answers with the option id,
            # which is the mode name.
            options = [
                {"optionId": choice, "name": f"Mode: {choice}",
                 "kind": "other"}
                for choice in request.options
            ]
        else:
            options = [
                {"optionId": choice, "name": _option_label(choice),
                 "kind": _option_kind(choice)}
                for choice in (request.options or ["yes", "no"])
            ]
        try:
            answer = self.agent.rpc.call("session/request_permission", {
                "sessionId": self.id,
                "title": request.prompt or "Allow this?",
                "description": (request.detail or "")[:4000] or None,
                "options": options,
            })
        except RpcError as error:
            self.agent.rpc.warn(f"acp: permission not answered — {error}")
            answer = None

        chosen = ""
        if isinstance(answer, dict):
            outcome = answer.get("outcome")
            if isinstance(outcome, dict):
                if outcome.get("outcome") == "selected":
                    chosen = str(outcome.get("optionId") or "")
                # "cancelled" leaves `chosen` empty, which is a refusal.

        self._pending.pop(request.id, None)
        if not request.answered:
            # Refused when nobody said otherwise. The alternative — assuming
            # yes because an editor did not answer — is the wrong way for this
            # to fail.
            request.answer(chosen or (request.options[-1] if request.options
                                      else "no"))

    def refuse_everything_waiting(self) -> None:
        """Answer every open prompt, so no worker is left blocked."""
        for request in list(self._pending.values()):
            if not request.answered:
                request.answer(request.options[-1] if request.options else "no")
        self._pending.clear()

    # -- a turn --------------------------------------------------------------- #

    def prompt(self, blocks: list[Any]) -> None:
        """Start a turn. Returns as soon as it is accepted, as ACP wants."""
        text = _as_text(blocks)
        if not text.strip():
            raise RpcError(INVALID_PARAMS, "there is nothing in that prompt")
        if not self._turn.acquire(blocking=False):
            raise RpcError(INVALID_PARAMS, "this session is already working")

        if not self.meta.title:
            self.meta.title = derive_title(text)

        def work() -> None:
            self.busy = True
            self.update({"sessionUpdate": "state_update", "state": "running"})
            stop = "end_turn"
            try:
                self.loop.run(text)
            except Exception as error:
                stop = "refusal"
                self.agent.rpc.warn(f"acp: {type(error).__name__}: {error}")
                self.update({"sessionUpdate": "agent_message_chunk",
                             "messageId": f"msg_agent_{int(time.time() * 1000)}",
                             "content": {"type": "text",
                                         "text": f"\n\n{type(error).__name__}: {error}"}})
            finally:
                if self._cancelled:
                    stop = "cancelled"
                self._cancelled = False
                self.busy = False
                self._persist()
                self.update({"sessionUpdate": "state_update", "state": "idle",
                             "stopReason": stop})
                self._turn.release()

        threading.Thread(target=work, name=f"comodor-acp-{self.id}",
                         daemon=True).start()

    _cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self.loop.interrupt()
        self.refuse_everything_waiting()

    # -- the transcript -------------------------------------------------------- #

    def _persist(self) -> None:
        messages = self.conversation.messages
        for message in messages[self._saved:]:
            try:
                self.store.append(self.id, message)
            except OSError:
                return
        self._saved = len(messages)
        self.meta.messages = len(messages)
        self.meta.cost_usd = self.conversation.usage.cost_usd
        self.meta.updated_at = time.time()
        try:
            self.store.save_meta(self.meta)
        except OSError:
            pass

    def replay(self) -> None:
        """Send what was said before, for a client that asked to resume."""
        for message in self.conversation.messages:
            role = getattr(message.role, "value", str(message.role))
            if role not in ("user", "assistant") or not message.content:
                continue
            self.update({
                "sessionUpdate": "user_message" if role == "user" else "agent_message",
                "messageId": f"msg_{role}_{id(message)}",
                "content": [{"type": "text", "text": message.content}],
            })

    def close(self) -> None:
        self.refuse_everything_waiting()
        self._persist()
        for shut in (lambda: self.loop.tools.close(), self.memory.close,
                     self.gateway.close, self.bus.close):
            try:
                shut()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# the agent
# --------------------------------------------------------------------------- #


class ComodorAgent:
    """Every ACP method, and the sessions they act on."""

    def __init__(self, config: Config, rpc: Connection) -> None:
        self.config = config
        self.rpc = rpc
        self.sessions: dict[str, AcpSession] = {}
        self.initialised = False

        rpc.methods.update({
            "initialize": self.initialize,
            "auth/login": self.login,
            "auth/logout": self.logout,
            "session/new": self.session_new,
            "session/resume": self.session_resume,
            "session/list": self.session_list,
            "session/delete": self.session_delete,
            "session/close": self.session_close,
            "session/prompt": self.session_prompt,
        })
        rpc.notifications.update({"session/cancel": self.session_cancel})

    # -- setting up ---------------------------------------------------------- #

    def initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        # "If the Agent supports the requested version it MUST respond with
        # the same version. Otherwise it MUST respond with the latest it
        # supports." One version supported, so this is short.
        version = PROTOCOL_VERSION if asked == PROTOCOL_VERSION else PROTOCOL_VERSION
        self.initialised = True

        return {
            "protocolVersion": version,
            "capabilities": {
                "session": {
                    "prompt": {
                        # Text always; a resource block is read as its text,
                        # which is what an editor sends for an attached file.
                        "embeddedContext": {},
                    },
                    # MCP servers are configured in Comodor's own settings.
                    # Accepting them per session as well would give a session
                    # two sources of truth for what tools exist.
                },
            },
            "info": {"name": "comodor", "title": "Comodor",
                     "version": __version__.split("+")[0]},
            # Empty on purpose: Comodor authenticates to a model provider, not
            # to the editor, and the specification says a client must not call
            # login when this is empty.
            "authMethods": [],
        }

    def login(self, params: dict[str, Any]) -> dict[str, Any]:
        raise RpcError(INVALID_PARAMS,
                       "Comodor has no login of its own — it uses the provider "
                       "configured with `comodor setup`.")

    def logout(self, params: dict[str, Any]) -> dict[str, Any]:
        raise RpcError(INVALID_PARAMS, "there is nothing to log out of")

    # -- sessions -------------------------------------------------------------- #

    def _need_a_provider(self) -> None:
        if not self.config.needs_setup:
            return
        raise RpcError(AUTH_REQUIRED,
                       "No model provider is configured. Run `comodor setup` "
                       "in a terminal, or set an API key in the environment.")

    def _config_for(self, cwd: str) -> Config:
        """The configuration, pointed at the folder the editor is in.

        The editor decides the working directory per session — it is the
        project the person has open — and that is what confines every write.
        """
        where = Path(cwd).expanduser() if cwd else Path(self.config.paths.project)
        try:
            where = where.resolve(strict=True)
        except (OSError, RuntimeError):
            raise RpcError(INVALID_PARAMS, f"no folder at {cwd!r}") from None
        if not where.is_dir():
            raise RpcError(INVALID_PARAMS, f"{cwd!r} is not a folder")

        # A shallow copy so two sessions in two projects do not share a root.
        from copy import copy

        config = copy(self.config)
        config.paths = Paths(user=self.config.paths.user, project=where)
        return config

    def session_new(self, params: dict[str, Any]) -> dict[str, Any]:
        self._need_a_provider()
        config = self._config_for(str(params.get("cwd") or ""))
        session_id = new_session_id()
        self.sessions[session_id] = AcpSession(
            session_id, config, self, Path(config.paths.project))
        return {"sessionId": session_id}

    def session_resume(self, params: dict[str, Any]) -> dict[str, Any]:
        self._need_a_provider()
        session_id = str(params.get("sessionId") or "")
        if not session_id:
            raise RpcError(INVALID_PARAMS, "which session?")

        config = self._config_for(str(params.get("cwd") or ""))
        store = SessionStore(config.paths.user / "sessions")
        messages = store.load(session_id)
        meta = store.load_meta(session_id)
        if meta is None and not messages:
            raise RpcError(INVALID_PARAMS, "no session with that id")

        existing = self.sessions.pop(session_id, None)
        if existing is not None:
            existing.close()

        session = AcpSession(session_id, config, self,
                             Path(config.paths.project))
        session.conversation.extend(messages)
        session._saved = len(messages)
        if meta is not None:
            session.meta = meta
        self.sessions[session_id] = session

        replay = params.get("replayFrom")
        if isinstance(replay, dict) and replay.get("type") == "start":
            session.replay()
        return {"sessionId": session_id}

    def session_list(self, params: dict[str, Any]) -> dict[str, Any]:
        store = SessionStore(self.config.paths.user / "sessions")
        return {"sessions": [
            {"sessionId": meta.id, "title": meta.title or "Untitled",
             "cwd": meta.cwd,
             "updatedAt": _rfc3339(meta.updated_at)}
            for meta in store.list_sessions(limit=100)
        ]}

    def session_delete(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "")
        if not session_id:
            raise RpcError(INVALID_PARAMS, "which session?")
        session = self.sessions.pop(session_id, None)
        if session is not None:
            session.close()
        store = SessionStore(self.config.paths.user / "sessions")
        if not store.delete(session_id):
            raise RpcError(INVALID_PARAMS, "no session with that id")
        return {}

    def session_close(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self.sessions.pop(str(params.get("sessionId") or ""), None)
        if session is None:
            raise RpcError(INVALID_PARAMS, "no session with that id")
        session.close()
        return {}

    def _session(self, params: dict[str, Any]) -> AcpSession:
        session = self.sessions.get(str(params.get("sessionId") or ""))
        if session is None:
            raise RpcError(INVALID_PARAMS, "no session with that id")
        return session

    def session_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._session(params)
        blocks = params.get("prompt")
        session.prompt(blocks if isinstance(blocks, list) else [])
        # Empty, and that is the whole point of the v2 shape: the turn reports
        # itself through notifications rather than by holding this open.
        return {}

    def session_cancel(self, params: dict[str, Any]) -> None:
        session = self.sessions.get(str(params.get("sessionId") or ""))
        if session is not None:
            session.cancel()

    def close(self) -> None:
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _as_text(blocks: list[Any]) -> str:
    """Flatten ACP content blocks into the string the agent takes.

    An editor sends text and, when somebody attaches a file, a `resource`
    block carrying its contents. Both are prose to a model, so both become
    prose — with the resource labelled by its URI so the model knows what it
    is looking at rather than finding a wall of code in the middle of a
    sentence.
    """
    parts: list[str] = []
    for block in blocks or []:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource":
            resource = block.get("resource")
            if isinstance(resource, dict) and resource.get("text"):
                uri = str(resource.get("uri") or "attached file")
                parts.append(f"\n\n--- {uri}\n{resource['text']}\n---\n")
        elif kind == "resource_link":
            parts.append(str(block.get("uri") or ""))
    return "\n".join(part for part in parts if part).strip()


def _option_label(choice: str) -> str:
    return {"yes": "Allow once", "no": "Reject", "always": "Allow always",
            "never": "Reject always"}.get(choice, choice)


def _option_kind(choice: str) -> str:
    return {"yes": "allow_once", "always": "allow_always",
            "no": "reject_once", "never": "reject_always"}.get(choice, "other")


def _plan_status(item: Any) -> str:
    state = str((item or {}).get("status") or "").lower() if isinstance(item, dict) else ""
    if state in ("done", "completed"):
        return "completed"
    if state in ("doing", "in_progress", "active"):
        return "in_progress"
    return "pending"


def _rfc3339(when: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(when, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z")


