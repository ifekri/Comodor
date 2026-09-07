"""The operations a client may ask for, without knowing how it asked.

Comodor grew four front ends — a terminal, a browser, an editor protocol and
an OpenAI-shaped API — and each of them assembles the agent itself. The same
eight objects, in the same order, in seven different files: gateway, learning
engine, permission engine, skills, MCP, plugins, tools, loop. Nothing was
wrong with any one copy. What was wrong is that "open a session" had no owner,
so a fifth front end meant an eighth copy, and a change to how a session is
built meant finding all of them.

This is that owner. Two pieces:

`assemble` builds the agent for one session, once, in one place. It is the
block that used to live inside the headless CLI path, lifted out unchanged so
that both it and anything new run the same wiring rather than two wirings that
look alike.

`CoreService` is the small set of verbs — create a session, send to it, cancel
it, change its mode, answer its questions — that a client actually needs. It
is deliberately not a mirror of every internal class. A method here exists
because something calls it; the way to get a hundred speculative operations is
to write them before anything needs them.

**Nothing in here knows about a wire format.** No JSON, no framing, no
envelope. `comodor.transport` binds this to the protocol; a future socket or
an in-process client binds to the same verbs. That direction — frontend to
protocol to application to core — is the one dependency rule this package
exists to hold.
"""

from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..events import Event, EventBus, Kind, Request
from ..safety.modes import ALL as MODE_NAMES
from ..safety.modes import known as known_mode

__all__ = ["Assembly", "assemble", "CoreService", "SessionHandle"]


@dataclass
class Assembly:
    """Everything one session needs, wired together.

    Held as a record rather than hidden inside a builder so a caller that
    needs one piece — a test scripting a provider, the CLI printing progress —
    can reach it without the assembly growing an accessor per field.
    """

    config: Config
    bus: EventBus
    gateway: Any
    memory: Any
    permissions: Any
    skills: Any
    mcp: Any
    tools: Any
    agent: Any

    def close(self) -> None:
        """Shut the assembly down, in the order the pieces expect.

        The order was previously written out at each call site, which is the
        kind of thing that stays right until somebody adds a piece. Every step
        is guarded because closing is what happens on the way out of a process
        that may already be failing, and a teardown that raises hides whatever
        went wrong first.
        """
        for piece in (self.tools, self.memory, self.gateway, self.mcp):
            if piece is None:
                continue
            closer = getattr(piece, "close", None)
            if closer is None:
                continue
            try:
                closer()
            except Exception:
                pass


def assemble(config: Config, *, bus: EventBus | None = None,
             plugins: Any = None) -> Assembly:
    """Build the agent for one session.

    Lifted out of `cli.py` rather than written afresh: this is the wiring the
    headless path already used and the interactive path mirrors, so the two
    cannot drift while both call it.
    """
    from ..agent import AgentLoop, Conversation
    from ..agent.spawn import spawner
    from ..learning import LearningEngine
    from ..mcp import MCPManager
    from ..providers.gateway import Gateway
    from ..safety import CheckpointStore, PermissionEngine, Redactor, make_assessor
    from ..skills import load_for as load_skills
    from ..tools import ToolRegistry

    bus = bus or EventBus()
    gateway = Gateway(config)
    memory = LearningEngine(
        config, bus, gateway,
        checkpoints=CheckpointStore(config.paths.checkpoints),
        redact=Redactor([entry.api_key for entry in config.providers.values()
                         if entry.api_key]),
    )
    permissions = PermissionEngine(config, bus)
    permissions.assess = make_assessor(config, gateway)
    permissions.on_denied = memory.on_denied

    skills = load_skills(config)
    mcp = MCPManager(config.mcp.servers) if config.mcp.enabled else None

    cron_store = None
    if config.cron.enabled:
        from ..cron.jobs import JobStore

        cron_store = JobStore(config.paths.user / "cron")

    tools = ToolRegistry(skills=skills, mcp=mcp, config=config,
                         spawn=spawner(config, gateway, bus, skills=skills,
                                       mcp=mcp),
                         cron_store=cron_store,
                         memory=getattr(memory, "facts", None),
                         plugins=plugins)
    agent = AgentLoop(config, gateway, tools, bus, permissions, Conversation(),
                      memory, skills=skills)
    return Assembly(config=config, bus=bus, gateway=gateway, memory=memory,
                    permissions=permissions, skills=skills, mcp=mcp,
                    tools=tools, agent=agent)


@dataclass
class SessionHandle:
    """One conversation, and the machinery under it."""

    id: str
    assembly: Assembly
    workspace: str
    title: str = ""
    busy: bool = False
    #: The turn currently streaming, so every `message.*` event for it carries
    #: one id a client can correlate on.
    message_id: str = ""
    _worker: threading.Thread | None = None
    _pending: dict[str, Request] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def mode(self) -> str:
        return str(self.assembly.config.agent.mode or "act").lower()

    def describe(self) -> dict[str, Any]:
        """The session as the protocol's `Session` shape.

        One place builds it, so `session.create`, `session.get` and every
        `session.updated` event describe a session the same way. A client
        resynchronising after a reconnect compares like with like.
        """
        body: dict[str, Any] = {
            "id": self.id,
            "mode": self.mode,
            "workspace": self.workspace,
            "busy": self.busy,
        }
        if self.title:
            body["title"] = self.title
        return body


class UnknownSession(KeyError):
    """No session with that id."""


class UnknownRequest(KeyError):
    """No question or permission waiting under that id."""


class Refused(ValueError):
    """The operation is not allowed, or its arguments do not make sense."""


class CoreService:
    """The verbs, and the sessions they act on.

    Thread-safe by one lock around the session table. Turns run on their own
    threads — the agent loop is synchronous and blocks for as long as a model
    and its tools take — so `send` returns as soon as the turn is accepted and
    everything after that arrives as events.
    """

    def __init__(self, config: Config, *,
                 on_event: Callable[[str, str, dict[str, Any]], None] | None = None,
                 assemble_with: Callable[..., Assembly] = assemble) -> None:
        self._config = config
        self._sessions: dict[str, SessionHandle] = {}
        self._lock = threading.RLock()
        self._assemble = assemble_with
        #: Called as (session_id, event_name, params) for every protocol event.
        #: Set by whatever is transporting; unset in a test that only calls verbs.
        self.on_event = on_event

    # -- sessions ---------------------------------------------------------- #

    def create_session(self, workspace: str = "", mode: str = "") -> dict[str, Any]:
        config = copy.deepcopy(self._config)
        if workspace:
            root = Path(workspace).expanduser()
            if not root.is_dir():
                raise Refused(f"no such directory: {workspace}")
            # `Paths` is frozen, and deliberately: the directories a run works
            # in are decided once, and code that could move them mid-session
            # is code that can write a checkpoint to one place and look for it
            # in another. A new one, rather than an assignment.
            config.paths = replace(config.paths, project=root.resolve())
        if mode:
            if not known_mode(mode):
                raise Refused(f"unknown mode {mode!r}; one of {', '.join(MODE_NAMES)}")
            config.agent.mode = mode

        handle = SessionHandle(
            id=uuid.uuid4().hex[:12],
            assembly=self._assemble(config),
            workspace=str(config.paths.project),
        )
        handle.assembly.bus.subscribe(_relay(self, handle))
        with self._lock:
            self._sessions[handle.id] = handle
        self._emit(handle, "session.created", {"session": handle.describe()})
        return handle.describe()

    def session(self, session_id: str) -> SessionHandle:
        with self._lock:
            handle = self._sessions.get(session_id)
        if handle is None:
            raise UnknownSession(session_id)
        return handle

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.session(session_id).describe()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [handle.describe() for handle in self._sessions.values()]

    def set_mode(self, session_id: str, mode: str) -> dict[str, Any]:
        """Change what a session may do.

        Validated here rather than trusted from the client, and applied to the
        session's own config — which is what the tool registry and the
        permission engine read. A client that never sends this, or sends it
        and ignores the answer, still cannot act outside the mode: the policy
        is consulted where a tool runs, not where a button is drawn.
        """
        if not known_mode(mode):
            raise Refused(f"unknown mode {mode!r}; one of {', '.join(MODE_NAMES)}")
        handle = self.session(session_id)
        handle.assembly.config.agent.mode = mode
        self._emit(handle, "mode.changed", {"session_id": handle.id, "mode": mode})
        self._emit(handle, "session.updated", {"session": handle.describe()})
        return handle.describe()

    # -- a turn ------------------------------------------------------------ #

    def send(self, session_id: str, text: str) -> dict[str, Any]:
        handle = self.session(session_id)
        with handle._lock:
            if handle.busy:
                raise Refused("that session is already working; cancel it first")
            handle.busy = True
        message_id = uuid.uuid4().hex[:12]
        handle.message_id = message_id

        def work() -> None:
            try:
                handle.assembly.agent.run(text)
            except Exception as problem:  # pragma: no cover - defensive
                self._emit(handle, "notification.created", {
                    "session_id": handle.id, "level": "error",
                    "text": f"the turn stopped: {problem}"})
            finally:
                with handle._lock:
                    handle.busy = False
                self._emit(handle, "session.updated",
                           {"session": handle.describe()})

        worker = threading.Thread(target=work, name=f"turn-{handle.id}",
                                  daemon=True)
        handle._worker = worker
        self._emit(handle, "session.updated", {"session": handle.describe()})
        worker.start()
        return {"accepted": True, "message_id": message_id}

    def cancel(self, session_id: str) -> dict[str, Any]:
        handle = self.session(session_id)
        if not handle.busy:
            return {"cancelled": False}
        handle.assembly.agent.interrupt("cancelled by the client")
        return {"cancelled": True}

    # -- what it answers with ---------------------------------------------- #

    def model(self) -> dict[str, Any]:
        """Which model answers, and whether it is configured.

        Never a key. `configured` is how a client shows "this provider needs
        setting up" without being told the secret it needs.
        """
        config = self._config
        provider = config.provider or ""
        entry = config.providers.get(provider)
        return {
            "provider": provider,
            "model": config.active_model() or "",
            # Whether a key exists, never the key. This is how a client shows
            # "this provider needs setting up" without being handed the secret
            # that would let it set anything up itself.
            "configured": bool(entry and entry.api_key),
        }

    def set_model(self, model: str, provider: str = "") -> dict[str, Any]:
        if not model:
            raise Refused("a model id is required")
        if provider and provider not in self._config.providers:
            raise Refused(f"no provider named {provider!r}")
        if provider:
            self._config.provider = provider
        self._config.model = model
        for handle in self.list_handles():
            handle.assembly.config.model = model
            if provider:
                handle.assembly.config.provider = provider
        answer = self.model()
        for handle in self.list_handles():
            self._emit(handle, "model.changed", answer)
        return answer

    def workspace(self) -> dict[str, Any]:
        root = Path(self._config.paths.project)
        return {"path": str(root), "name": root.name}

    def list_handles(self) -> list[SessionHandle]:
        with self._lock:
            return list(self._sessions.values())

    # -- answering what the agent asked ------------------------------------ #

    def answer_question(self, request_id: str, selected: list[str] | None = None,
                        custom: str = "", cancelled: bool = False) -> dict[str, Any]:
        handle, request = self._pending(request_id)
        from .. import questions as forms

        if cancelled:
            request.answer(forms.CANCELLED)
        else:
            request.answer(_encode_answer(selected or [], custom))
        handle._pending.pop(request_id, None)
        self._emit(handle, "question.resolved", {
            "id": request_id, "session_id": handle.id,
            "selected": list(selected or []), "custom": custom,
            "cancelled": cancelled})
        return {"ok": True}

    def reply_permission(self, request_id: str, choice: str) -> dict[str, Any]:
        handle, request = self._pending(request_id)
        if request.options and choice not in request.options:
            raise Refused(f"{choice!r} is not one of: {', '.join(request.options)}")
        request.answer(choice)
        handle._pending.pop(request_id, None)
        self._emit(handle, "permission.resolved", {
            "id": request_id, "session_id": handle.id, "choice": choice})
        return {"ok": True}

    def _pending(self, request_id: str) -> tuple[SessionHandle, Request]:
        for handle in self.list_handles():
            request = handle._pending.get(request_id)
            if request is not None:
                return handle, request
        raise UnknownRequest(request_id)

    # -- lifecycle --------------------------------------------------------- #

    def close(self) -> None:
        """Stop every session. Turns are daemon threads and do not hold exit."""
        for handle in self.list_handles():
            try:
                if handle.busy:
                    handle.assembly.agent.interrupt("shutting down")
            except Exception:
                pass
            try:
                handle.assembly.bus.close()
            except Exception:
                pass
        with self._lock:
            self._sessions.clear()

    # -- events ------------------------------------------------------------ #

    def _emit(self, handle: SessionHandle, name: str,
              params: dict[str, Any]) -> None:
        if self.on_event is not None:
            self.on_event(handle.id, name, params)


def _encode_answer(selected: list[str], custom: str) -> str:
    """What the `ask` tool expects back.

    The tool reads a plain string, so a structured answer is flattened here
    rather than the tool learning a second shape. Custom text wins when both
    arrive, because a person who typed something meant it.
    """
    if custom:
        return custom
    return ", ".join(selected)


def _relay(service: CoreService, handle: SessionHandle):
    """Turn one session's bus events into protocol events.

    The mapping is the whole adapter, and it is deliberately here rather than
    in the transport: it is a statement about what a Comodor session *does*,
    which is application knowledge, not framing. What the transport adds is
    JSON and a pipe.
    """

    def relay(event: Event) -> None:
        kind = event.kind
        session_id = handle.id
        message_id = handle.message_id or session_id

        if kind is Kind.ASSISTANT_START:
            service._emit(handle, "message.started", {
                "session_id": session_id, "message_id": message_id,
                "role": "assistant"})
        elif kind is Kind.ASSISTANT_DELTA:
            service._emit(handle, "message.delta", {
                "session_id": session_id, "message_id": message_id,
                "text": event.text})
        elif kind is Kind.REASONING_DELTA:
            # Same stream, named channel. A client that does not show
            # reasoning drops it on the name rather than guessing from prose.
            service._emit(handle, "message.delta", {
                "session_id": session_id, "message_id": message_id,
                "text": event.text, "channel": "reasoning"})
        elif kind is Kind.ASSISTANT_END:
            service._emit(handle, "message.completed", {
                "session_id": session_id, "message_id": message_id,
                "text": event.text})
        elif kind is Kind.TOOL_START:
            service._emit(handle, "tool.started", {
                "session_id": session_id,
                "call_id": str(event.get("id", "") or event.get("name", "")),
                "name": str(event.get("name", "")),
                "summary": str(event.get("summary", ""))})
        elif kind is Kind.TOOL_OUTPUT:
            # No call id: the core does not tag streamed output with the call
            # it came from, and tools can run in parallel. Inventing one from
            # "the most recent start" would be right until it was not.
            service._emit(handle, "tool.output", {
                "session_id": session_id, "text": event.text})
        elif kind is Kind.TOOL_END:
            call_id = str(event.get("id", "") or event.get("name", ""))
            if event.get("ok") is False:
                # The reason is in `content` — a failed `ToolResult` carries
                # its message there. There is no separate `error` key to read.
                service._emit(handle, "tool.failed", {
                    "session_id": session_id, "call_id": call_id,
                    "name": str(event.get("name", "")),
                    "error": str(event.get("content", "") or "the tool failed")})
            else:
                completed: dict[str, Any] = {
                    "session_id": session_id, "call_id": call_id,
                    "name": str(event.get("name", "")),
                    "summary": str(event.get("display", "") or ""),
                }
                elapsed = event.get("elapsed")
                if isinstance(elapsed, (int, float)):
                    completed["elapsed_ms"] = int(elapsed * 1000)
                service._emit(handle, "tool.completed", completed)
        elif kind is Kind.CANCELLED:
            service._emit(handle, "message.completed", {
                "session_id": session_id, "message_id": message_id,
                "cancelled": True})
        elif kind is Kind.REQUEST:
            _relay_request(service, handle, event)
        elif kind is Kind.ERROR:
            service._emit(handle, "notification.created", {
                "session_id": session_id, "level": "error", "text": event.text})
        elif kind is Kind.NOTICE:
            service._emit(handle, "notification.created", {
                "session_id": session_id, "level": "info", "text": event.text})

    return relay


def _relay_request(service: CoreService, handle: SessionHandle,
                   event: Event) -> None:
    """A permission prompt or a structured question, as a protocol primitive.

    The agent already publishes both through one `Request`, distinguished by
    its `kind`. Splitting them here is what lets a client draw a real control
    for each instead of printing a numbered list and parsing the reply.
    """
    request = event.get("request")
    if request is None:
        return
    handle._pending[request.id] = request

    if request.kind == "questions":
        service._emit(handle, "question.requested",
                      _question_shape(handle.id, request))
        return

    service._emit(handle, "permission.requested", {
        "id": request.id,
        "session_id": handle.id,
        "title": request.prompt,
        "detail": request.detail,
        "options": list(request.options),
    })


def _question_shape(session_id: str, request: Request) -> dict[str, Any]:
    """A `Request` from the `ask` tool in the protocol's question shape."""
    meta = request.meta or {}
    raw_options = meta.get("options") or request.options or []
    options: list[dict[str, Any]] = []
    for index, option in enumerate(raw_options):
        if isinstance(option, dict):
            options.append({
                "id": str(option.get("id", option.get("label", index))),
                "label": str(option.get("label", option.get("id", index))),
                **({"description": str(option["description"])}
                   if option.get("description") else {}),
            })
        else:
            options.append({"id": str(option), "label": str(option)})

    body: dict[str, Any] = {
        "id": request.id,
        "session_id": session_id,
        "title": request.prompt,
        "options": options,
        "multiple": bool(meta.get("multiple", False)),
    }
    if request.detail:
        body["description"] = request.detail
    if meta.get("allow_custom", True):
        body["allow_custom"] = True
    return body
