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
from ..safety.permissions import Risk
from .journal import Journal

__all__ = ["Assembly", "assemble", "CoreService", "Journal", "SessionHandle"]

#: What a client may say it can do. A capability it does not claim is one the
#: core answers on its behalf rather than waiting on.
CLIENT_CAPABILITIES = ("questions", "permissions")

#: The risk tiers by the names a client shows. The engine stores them as an
#: ordered integer; the wire carries the word, so no client has to know the
#: numbering to tell a write from a shell command.
RISK_NAMES: dict[int, str] = {
    Risk.SAFE: "safe",
    Risk.WRITE: "write",
    Risk.DANGEROUS: "dangerous",
}


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
    #: The turn's transcript. Held on the assembly because a session surface
    #: reads it — for titles, costs, persistence — and building a second one
    #: would split the transcript from the loop that writes it.
    conversation: Any = None
    #: The background-delegate manager, when this session can deliver a
    #: finished answer at a turn boundary. `None` for a wiring that has
    #: nowhere to deliver to — a headless run, a scheduled job — where the
    #: delegate tool refuses `background=true` outright rather than starting
    #: work whose answer would be dropped.
    delegates: Any = None

    def close(self) -> None:
        """Shut the assembly down, in the order the pieces expect.

        The order was previously written out at each call site, which is the
        kind of thing that stays right until somebody adds a piece. Every step
        is guarded because closing is what happens on the way out of a process
        that may already be failing, and a teardown that raises hides whatever
        went wrong first.
        """
        if self.delegates is not None:
            # Delegates first: a child still running uses the tools and the
            # gateway the loop below is about to take away. `closing` stops new
            # launches, `stop_all` asks the running ones to settle, and the wait
            # is the shared bounded one — a worker that will not stop delays
            # nobody's exit past it.
            try:
                from ..agent.background import SHUTDOWN_SECONDS

                self.delegates.closing()
                self.delegates.stop_all()
                self.delegates.wait(SHUTDOWN_SECONDS)
            except Exception:
                pass
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
             plugins: Any = None, delegates: bool = False) -> Assembly:
    """Build the agent for one session.

    Lifted out of `cli.py` rather than written afresh: this is the wiring the
    headless path already used and the interactive path mirrors, so the two
    cannot drift while both call it.

    `delegates` is opt-in and means "somebody will deliver a finished
    background answer at a turn boundary". A served session — one a transport
    drives — says yes and gets the manager the delegate tool launches on. A
    headless run says nothing and keeps the refusal: background work whose
    completion nobody drains is work whose answer is dropped, and the tool
    already refuses to start it.
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

    spawn = spawner(config, gateway, bus, skills=skills, mcp=mcp)

    manager = None
    if delegates:
        from ..agent.background import BackgroundDelegates

        # The same file the terminal and the web session keep their crash
        # record in: one honest account per machine of what was running when
        # the process died, whichever surface asks next.
        manager = BackgroundDelegates(
            config, bus, spawn,
            persist_path=config.paths.user / "delegates.json")

    tools = ToolRegistry(skills=skills, mcp=mcp, config=config,
                         spawn=spawn,
                         cron_store=cron_store,
                         memory=getattr(memory, "facts", None),
                         delegates=manager,
                         plugins=plugins)
    conversation = Conversation()
    agent = AgentLoop(config, gateway, tools, bus, permissions, conversation,
                      memory, skills=skills)
    agent.delegates = manager
    return Assembly(config=config, bus=bus, gateway=gateway, memory=memory,
                    permissions=permissions, skills=skills, mcp=mcp,
                    tools=tools, agent=agent, conversation=conversation,
                    delegates=manager)


@dataclass
class SessionHandle:
    """One conversation, and the machinery under it."""

    id: str
    assembly: Assembly
    workspace: str
    title: str = ""
    busy: bool = False
    #: The turn currently running. Every `message.*` and `tool.*` event it
    #: causes carries this, which is what `session.send` returns.
    #:
    #: A turn, not a message: one turn is several assistant messages with the
    #: tools it called between them, and F1's single id per turn made the
    #: second message look like a repeat of the first.
    turn_id: str = ""
    #: What the core knows about this session, and the counter that orders it.
    journal: Journal = field(default_factory=Journal)
    #: The mode clients were last told about.
    #:
    #: `set_mode` is not the only thing that can change a session's mode:
    #: `propose_mode` is a tool, and when the person accepts its card the tool
    #: writes the mode itself. A client caches the mode from events, so without
    #: this the bar would keep drawing the old one for the rest of the turn —
    #: showing PLAN, say, while the session is running under ACT and allowed to
    #: write. Compared after each tool rather than special-cased to that one,
    #: because "the mode moved" is a fact about the session and not about which
    #: tool happened to move it.
    _announced_mode: str = ""
    _worker: threading.Thread | None = None
    _pending: dict[str, Request] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    #: Held closed until the acceptance for this turn has been written. See
    #: `CoreService.send`.
    _released: threading.Event = field(default_factory=threading.Event)
    #: Set when the service is closing this session. A turn worker between
    #: turns checks it before delivering a background completion: starting a
    #: fresh agent turn on the way out of the process would run it against
    #: tools the teardown is already taking away.
    _closing: bool = False

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
                 on_event: Callable[[str, str, dict[str, Any], int], None] | None = None,
                 assemble_with: Callable[..., Assembly] = assemble) -> None:
        self._config = config
        self._sessions: dict[str, SessionHandle] = {}
        self._lock = threading.RLock()
        self._assemble = assemble_with
        #: Called as (session_id, event_name, params, seq) for every protocol
        #: event. Set by whatever is transporting; unset in a test that only
        #: calls verbs.
        self.on_event = on_event
        #: What the connected client said it can draw. Everything, until a
        #: handshake narrows it — an embedder calling the verbs directly is
        #: not a client that has declined anything.
        self.client_capabilities: tuple[str, ...] = CLIENT_CAPABILITIES

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
            # A served session can deliver a finished background answer at a
            # turn boundary, so it gets the delegate manager. See `assemble`.
            assembly=self._assemble(config, delegates=True),
            workspace=str(config.paths.project),
        )
        handle._announced_mode = handle.mode
        handle.assembly.bus.subscribe(_relay(self, handle))
        if handle.assembly.delegates is not None:
            # The manager loaded its crash record before anything was
            # subscribed: a delegate that was running when the process died is
            # already `lost`, and no event will ever announce it. Seeded into
            # the journal without spending a sequence number, so the first
            # snapshot a client can ask for tells the truth about the last
            # process's work.
            try:
                handle.journal.seed_delegates(handle.assembly.delegates.listing())
            except Exception:  # pragma: no cover - defensive
                pass
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

    def snapshot(self, session_id: str) -> dict[str, Any]:
        """Everything a client needs to draw a session it did not watch happen.

        Built under the journal's lock, so what comes back is a state that
        actually existed rather than one assembled across a streaming turn.
        The `revision` it carries is exactly the last event folded into it: a
        client applies what is above that number and drops what is not.
        """
        handle = self.session(session_id)
        return handle.journal.snapshot(handle.describe())

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
        handle._announced_mode = mode
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
        turn_id = uuid.uuid4().hex[:12]
        handle.turn_id = turn_id
        handle._released.clear()
        # The person's own message, which no event announces: `session.send`
        # is a method call, so without recording it here a client rebuilt from
        # a snapshot would recover every answer and none of the questions.
        handle.journal.said(turn_id, text)

        def work() -> None:
            # The turn waits for its own acceptance to be on the wire.
            #
            # Without this the worker can emit `message.started` and the first
            # deltas before `send` has returned — the transport holds events
            # raised on the *answering* thread, and this is a different one.
            # A client correlating on `message_id` would then see a stream
            # begin for a turn it has not been told about, and a client that
            # waits for the response before subscribing would drop the
            # opening of every fast answer.
            #
            # Bounded, so a caller that never releases — an embedder using the
            # service directly — degrades to a slightly late start rather than
            # a turn that never runs.
            handle._released.wait(timeout=5.0)
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
            # One turn past its end is the turn boundary: a background
            # delegate that finished while this turn ran is delivered here,
            # as turns of its own, never spliced into the one just ended.
            try:
                self._deliver_completions(handle)
            except Exception:  # pragma: no cover - delivery must not kill the worker
                pass

        worker = threading.Thread(target=work, name=f"turn-{handle.id}",
                                  daemon=True)
        handle._worker = worker
        self._emit(handle, "session.updated", {"session": handle.describe()})
        worker.start()
        if self.on_event is None:
            # Nobody is transporting, so nobody will call `release`.
            handle._released.set()
        return {"accepted": True, "turn_id": turn_id}

    def release(self) -> None:
        """Let any waiting turn begin.

        Called by the transport once a response has been written, which is
        what makes "a request is answered before the events it caused" true
        for `session.send` as well as for the calls that emit inline.
        """
        for handle in self.list_handles():
            handle._released.set()

    def cancel(self, session_id: str) -> dict[str, Any]:
        handle = self.session(session_id)
        if not handle.busy:
            return {"cancelled": False}
        handle.assembly.agent.interrupt("cancelled by the client")
        # An interrupt is a flag the loop checks between steps. A worker parked
        # in a permission prompt is not between steps — it is inside a wait
        # that only an answer ends. Without this the turn stays busy for the
        # whole prompt timeout after the person asked it to stop, and the card
        # on screen still looks like it is waiting on them.
        self._refuse_pending(handle)
        return {"cancelled": True}

    def _refuse_pending(self, handle: SessionHandle) -> None:
        """Answer everything waiting, so no worker stays parked on a person.

        Each request goes through the same path a real reply takes, so every
        one of them emits its resolution and a client watching sees the prompts
        it is displaying close rather than hang. The fallback is the request's
        own last option — `deny` for a permission, a cancelled form for a
        question — which is the same answer a timeout gives.
        """
        for request_id, request in list(handle._pending.items()):
            try:
                if request.kind == "questions":
                    self.answer_question(request_id, cancelled=True)
                else:
                    self.reply_permission(request_id, request.fallback)
            except Exception:
                # Already resolved by its own timeout, or answered in the
                # instant this ran. Either way nothing is waiting on it now.
                pass

    # -- background delegates ------------------------------------------------ #

    def stop_delegate(self, session_id: str, delegate_id: str) -> dict[str, Any]:
        """Ask one background delegate to stop. The core decides.

        The answer is whether there was a running delegate to stop — `false`
        is honest, not an error: it may have settled in the instant the
        request arrived, or never have existed. What the delegate actually
        becomes arrives as the manager's own announcements, relayed like
        everything else: `stopping` when the stop took, then the terminal
        state the worker settles on. Nothing here fabricates a final state
        ahead of the worker, and a client must not either.
        """
        handle = self.session(session_id)
        manager = getattr(handle.assembly, "delegates", None)
        if manager is None:
            raise Refused("this session has no background delegates")
        return {"stopped": bool(manager.stop(str(delegate_id)))}

    def _deliver_completions(self, handle: SessionHandle) -> None:
        """Finished background delegates become turns of their own.

        The same boundary rule the terminal and the web session follow: one
        turn past its end is the turn boundary, and a completion joins the
        conversation there as a user turn the agent answers with the full
        turn machinery — never spliced into the middle of the turn that just
        ended. Each delivered turn drains again, so several children that
        finished together arrive in order rather than all at once.

        A message the person sent in the meantime took `busy` first, and then
        the records go back to pending for the boundary after that one rather
        than being dropped. A session on its way out takes nothing: a turn
        started during teardown would run against tools already being closed,
        and the manager's persistence describes the outcome honestly to
        whichever process asks next.
        """
        manager = getattr(handle.assembly, "delegates", None)
        if manager is None:
            return
        from ..agent.background import completion_turn

        summary_max = handle.assembly.config.delegation.completion_summary_max
        while not handle._closing:
            records = manager.take_pending()
            if not records:
                return
            with handle._lock:
                if handle.busy or handle._closing:
                    manager.restore([str(record.get("id", ""))
                                     for record in records])
                    return
                handle.busy = True
            text = "\n\n".join(
                completion_turn(record, summary_max) for record in records)
            turn_id = uuid.uuid4().hex[:12]
            handle.turn_id = turn_id
            # The completion text is this turn's user message: recorded so a
            # client rebuilt from a snapshot sees what the agent is answering.
            # Live clients get one short notice per delegate — the full text
            # can be twenty-four thousand characters, which is a conversation
            # message and not a notification.
            handle.journal.said(turn_id, text)
            for record in records:
                self._emit(handle, "notification.created", {
                    "session_id": handle.id, "level": "info",
                    "text": f"background task {record.get('id')} — "
                            f"{record.get('state', 'done')}"})
            self._emit(handle, "session.updated",
                       {"session": handle.describe()})
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
            # Whether it could answer right now, never the key. `ready` and
            # not `api_key`: a model on this machine has no key by design, and
            # reading credential presence alone told a client to send somebody
            # to set up a provider that was already working.
            "configured": bool(entry and entry.ready),
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

    def answer_question(self, request_id: str,
                        answers: list[dict[str, Any]] | None = None,
                        cancelled: bool = False) -> dict[str, Any]:
        handle, request = self._pending(request_id)
        from .. import questions as forms

        # Claimed rather than assigned: a form that timed out, or was cancelled
        # by a `session.cancel` a moment ago, has already been acted on. Saying
        # "ok" to a second answer would tell a client its reply landed when the
        # agent moved on without it.
        if not request.answer(forms.CANCELLED if cancelled
                              else _encode_answer(answers or [])):
            handle._pending.pop(request_id, None)
            raise UnknownRequest(request_id)
        handle._pending.pop(request_id, None)
        resolved: dict[str, Any] = {"id": request_id, "session_id": handle.id}
        if cancelled:
            resolved["cancelled"] = True
        else:
            resolved["answers"] = list(answers or [])
        self._emit(handle, "question.resolved", resolved)
        return {"ok": True}

    def reply_permission(self, request_id: str, choice: str) -> dict[str, Any]:
        handle, request = self._pending(request_id)
        if request.options and choice not in request.options:
            raise Refused(f"{choice!r} is not one of: {', '.join(request.options)}")
        if not request.answer(choice):
            # Already resolved — timed out, cancelled, or answered by another
            # client. The prompt this reply was aimed at is not waiting any
            # more, which is exactly what `unknown_request` means.
            handle._pending.pop(request_id, None)
            raise UnknownRequest(request_id)
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
        """Stop every session, and close what it was holding.

        The interrupt comes first so a running turn stops before the things it
        is using are taken away. Then the assembly, which flushes the learning
        store and releases tool, provider and MCP resources — leaving those to
        process teardown lost whatever the last turn had learned on every
        ordinary exit, which is the kind of thing nobody notices because
        nothing reports it.
        """
        for handle in self.list_handles():
            try:
                # Before the interrupt: a worker between turns would otherwise
                # be free to start delivering a background completion while
                # this teardown is halfway through taking its tools away.
                handle._closing = True
                manager = getattr(handle.assembly, "delegates", None)
                if manager is not None:
                    # Ask the children to settle now, so the join below waits
                    # on a turn that is ending rather than one that is waiting
                    # for a delegate nobody is going to stop.
                    manager.closing()
                    manager.stop_all()
                if handle.busy:
                    handle.assembly.agent.interrupt("shutting down")
                # Same reason as `cancel`: a worker parked in a prompt does not
                # see a flag, and the join below would otherwise sit out the
                # whole prompt timeout on the way out of the process.
                self._refuse_pending(handle)
            except Exception:
                pass
            # Let the worker notice the interrupt rather than closing the bus
            # out from under it.
            worker = handle._worker
            if worker is not None and worker.is_alive():
                worker.join(timeout=5.0)
            handle.assembly.close()
            try:
                handle.assembly.bus.close()
            except Exception:
                pass
        with self._lock:
            self._sessions.clear()

    # -- events ------------------------------------------------------------ #

    def _emit(self, handle: SessionHandle, name: str,
              params: dict[str, Any]) -> None:
        """Record one event, number it, and hand it on — in that order.

        The lock spans all three. It has to: the number and the send are two
        halves of one promise, and taking them separately lets a second thread
        be numbered 6 and reach the wire before 5. A client that is told
        "everything through 41" would then have applied 42 already.

        Re-entrant because answering on a client's behalf emits from inside
        this call: a question the client cannot draw is resolved here, and the
        resolution is an event of its own.
        """
        if self._declined(handle, name, params):
            return
        with handle.journal.lock:
            seq = handle.journal.record(name, params)
            if self.on_event is not None:
                self.on_event(handle.id, name, params, seq)

    def _declined(self, handle: SessionHandle, name: str,
                  params: dict[str, Any]) -> bool:
        """Answer for a client that said it cannot, instead of waiting on it.

        The handshake is a promise in both directions. A client that does not
        announce `questions` will never draw a form, so sending it one blocks
        the agent for the full timeout on something nobody will answer — which
        reads to a person as the agent having hung.

        This is application policy rather than framing, which is why it lives
        here and not in the transport. Keeping it there had a second cost: an
        event suppressed after being numbered leaves a hole in the sequence,
        and a client watching for holes would resynchronise over nothing.
        """
        needed = {"question.requested": "questions",
                  "permission.requested": "permissions"}.get(name)
        if needed is None or needed in self.client_capabilities:
            return False
        request_id = str(params.get("id", ""))
        if not request_id:
            return False
        try:
            if needed == "questions":
                self.answer_question(request_id, cancelled=True)
            else:
                # The request's own last option, not a hardcoded "deny".
                #
                # Every request this core raises puts its safe answer last, and
                # for a permission that is `deny` — but a mode proposal offers
                # mode names, with the current mode last so declining is one
                # press. Answering that with "deny" is not one of its options,
                # so the reply was refused, the exception swallowed, and the
                # tool left to wait out its full timeout for a client that had
                # already said it could not answer. The fallback is the same
                # answer a timeout gives, arrived at immediately.
                held = handle._pending.get(request_id)
                self.reply_permission(
                    request_id, held.fallback if held is not None else "deny")
        except Exception:  # pragma: no cover - defensive
            # Nothing to answer, or it was answered already. Suppressing the
            # event is still right; the alternative is a form nobody can fill.
            pass
        return True


def _encode_answer(answers: list[dict[str, Any]]) -> str:
    """What the `ask` tool actually reads back.

    Not a sentence. `Ask.run` passes whatever arrives straight to
    `questions.decode_answers`, which accepts only the JSON list that
    `encode_answers` produces — anything else is read as a cancelled form and
    the agent carries on with its own defaults.

    This wrote a comma-joined string, which meant every answer a client sent
    was silently discarded and the model was told the person had declined to
    answer. There was no error anywhere; the form simply had no effect.
    """
    from .. import questions as forms

    built = [
        forms.Answer(
            header=str(entry.get("header", "")),
            prompt=str(entry.get("prompt", "")),
            chosen=[str(choice) for choice in entry.get("chosen", []) or []],
            written=str(entry.get("written", "")),
        )
        for entry in answers
    ]
    return forms.encode_answers(built)


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
        turn_id = handle.turn_id or session_id
        # The message this event belongs to, named by the loop. A turn has
        # several, so taking it from the handle — as F1 did — labelled every
        # message of a turn with the same id and made the second look like a
        # repeat of the first.
        message_id = str(event.get("id", "") or "")

        if kind is Kind.ASSISTANT_START:
            service._emit(handle, "message.started", {
                "session_id": session_id, "turn_id": turn_id,
                "message_id": message_id, "role": "assistant"})
        elif kind is Kind.ASSISTANT_DELTA:
            service._emit(handle, "message.delta", {
                "session_id": session_id, "turn_id": turn_id,
                "message_id": message_id, "text": event.text})
        elif kind is Kind.REASONING_DELTA:
            # Same stream, named channel. A client that does not show
            # reasoning drops it on the name rather than guessing from prose.
            service._emit(handle, "message.delta", {
                "session_id": session_id, "turn_id": turn_id,
                "message_id": message_id, "text": event.text,
                "channel": "reasoning"})
        elif kind is Kind.ASSISTANT_END:
            service._emit(handle, "message.completed", {
                "session_id": session_id, "turn_id": turn_id,
                "message_id": message_id, "text": event.text,
                "status": "completed"})
        elif kind is Kind.TOOL_START:
            service._emit(handle, "tool.started", {
                "session_id": session_id, "turn_id": turn_id,
                "call_id": str(event.get("id", "") or event.get("name", "")),
                "name": str(event.get("name", "")),
                "summary": str(event.get("summary", ""))})
        elif kind is Kind.TOOL_OUTPUT:
            # Tagged where it was produced. The tool is handed a view of the
            # context that knows which call it is, so output from tools
            # running in parallel arrives already told apart rather than
            # attributed to whichever started most recently.
            service._emit(handle, "tool.output", {
                "session_id": session_id, "turn_id": turn_id,
                "call_id": str(event.get("id", "") or ""),
                "text": event.text})
        elif kind is Kind.TOOL_END:
            call_id = str(event.get("id", "") or event.get("name", ""))
            if event.get("ok") is False:
                # The reason is in `content` — a failed `ToolResult` carries
                # its message there. There is no separate `error` key to read.
                service._emit(handle, "tool.failed", {
                    "session_id": session_id, "turn_id": turn_id,
                    "call_id": call_id,
                    "name": str(event.get("name", "")),
                    "error": str(event.get("content", "") or "the tool failed")})
            else:
                completed: dict[str, Any] = {
                    "session_id": session_id, "turn_id": turn_id,
                    "call_id": call_id,
                    "name": str(event.get("name", "")),
                    "summary": str(event.get("display", "") or ""),
                }
                elapsed = event.get("elapsed")
                if isinstance(elapsed, (int, float)):
                    completed["elapsed_ms"] = int(elapsed * 1000)
                service._emit(handle, "tool.completed", completed)
            _announce_mode_if_moved(service, handle)
        elif kind is Kind.CANCELLED:
            # Two halves, because cancellation can land in two places. Mid
            # answer there is a message to end, and ending it is what stops
            # a client rendering a spinner for ever. Between messages — during a
            # tool, which is when people actually press stop — there is
            # nothing to end, and without the notice the turn would simply go
            # quiet and leave the person wondering whether the model hung.
            _close_open_message(service, handle, "cancelled")
            service._emit(handle, "notification.created", {
                "session_id": session_id, "level": "warning",
                "text": _stop_reason(event)})
        elif kind is Kind.TODO:
            # The model's own plan, in the tool's own vocabulary. The whole
            # list rides on every event because that is what `todo_write`
            # records: a client replaces what it holds rather than merging, so
            # a task the model removed stays removed. An entry with no text is
            # dropped, which is how the tool itself parses — the wire carries
            # the list the tool kept, not the raw one.
            tasks = [
                {"text": str(item.get("text", "")),
                 "state": _task_state(item.get("state"))}
                for item in (event.get("items") or [])
                if isinstance(item, dict) and str(item.get("text", ""))
            ]
            service._emit(handle, "tasks.updated", {
                "session_id": session_id, "tasks": tasks})
        elif kind is Kind.DELEGATE:
            record = _delegate_record(event.payload)
            if record is not None:
                service._emit(handle, "delegate.updated", {
                    "session_id": session_id, "delegate": record})
        elif kind is Kind.REQUEST:
            _relay_request(service, handle, event)
        elif kind is Kind.REQUEST_EXPIRED:
            _relay_expired(service, handle, event)
        elif kind is Kind.ERROR:
            # A provider that fails mid-answer raises before the loop can end
            # the message, so nothing else would ever complete it: the client
            # is left with a message that streams for the rest of the session.
            # The notification says what went wrong; this says the message is
            # over, and that it did not succeed.
            _close_open_message(service, handle, "failed", event.text)
            service._emit(handle, "notification.created", {
                "session_id": session_id, "level": "error", "text": event.text})
        elif kind is Kind.NOTICE:
            service._emit(handle, "notification.created", {
                "session_id": session_id, "level": "info", "text": event.text})

    return relay


def _stop_reason(event: Event) -> str:
    """Why the work stopped, in words a person reads.

    "You stopped it" and "a newer message took over" are different sentences,
    and the loop already distinguishes them.
    """
    reason = str(event.get("reason", "") or "")
    if reason == "interrupt":
        return "Stopped — a newer message took over."
    return "Stopped."


#: The task states the `todo_write` tool owns. A state the core has never
#: heard of is relayed as `pending` rather than passed through: a word outside
#: the schema's enum is a word a validating client trips on, and the tool
#: itself coerces exactly the same way.
_TASK_STATES = ("pending", "active", "done", "blocked")


def _task_state(value: Any) -> str:
    state = str(value or "pending").lower()
    return state if state in _TASK_STATES else "pending"


#: The lifecycle words the delegate manager announces, mapped onto the
#: protocol's state vocabulary. The manager says `started` where its own
#: record says `running`; everything else is already a protocol word.
_DELEGATE_STATES = {"started": "running", "running": "running",
                    "stopping": "stopping", "done": "done",
                    "failed": "failed", "stopped": "stopped", "lost": "lost"}


def _delegate_record(payload: dict[str, Any]) -> dict[str, Any] | None:
    """One bus payload as the protocol's delegate record, or None.

    An allow-list rather than a pass-through. The manager's own record is
    already careful, but the wire contract is this function: a field added to
    the internal record later does not ride along to every client by accident
    — including a field that one day holds something private. An unknown
    state word drops the announcement rather than inventing one; the journal
    keeps the last state it was told.
    """
    identifier = str(payload.get("id", ""))
    if not identifier:
        return None
    state = _DELEGATE_STATES.get(str(payload.get("state", "")), "")
    if not state:
        return None
    record: dict[str, Any] = {
        "id": identifier,
        "label": str(payload.get("label", "")),
        "state": state,
        "steps": int(payload.get("steps") or 0),
        "tool_calls": int(payload.get("tool_calls") or 0),
        "tokens": int(payload.get("tokens") or 0),
        "elapsed": float(payload.get("elapsed") or 0.0),
        "started_at": float(payload.get("started_at") or 0.0),
    }
    error = str(payload.get("error", ""))
    if error:
        record["error"] = error
    return record


def _announce_mode_if_moved(service: CoreService,
                            handle: SessionHandle) -> None:
    """Say so when the mode changed without anybody calling `set_mode`.

    `propose_mode` is a tool: the person accepts its card and the tool writes
    the session's mode itself, which never went through the verb that emits
    `mode.changed`. A client caches the mode from events, so it would keep
    drawing the old one for the rest of the turn — PLAN on the bar while the
    session runs under ACT and is allowed to write. That is not a cosmetic
    lag: the bar is how somebody tells what the agent may do next.

    Checked after each tool rather than wired to that one tool, so a future
    tool that changes the mode is announced too.
    """
    if handle._announced_mode == handle.mode:
        return
    handle._announced_mode = handle.mode
    service._emit(handle, "mode.changed",
                  {"session_id": handle.id, "mode": handle.mode})
    service._emit(handle, "session.updated", {"session": handle.describe()})


def _close_open_message(service: CoreService, handle: SessionHandle,
                        status: str, error: str = "") -> None:
    """End whichever message is still streaming, if one is.

    Asked of the journal rather than assumed, because both reasons for calling
    this can arrive when no message is open — a turn cancelled between steps,
    an error raised before the first token — and completing a message that
    already completed would tell a client its finished answer had been
    cancelled.
    """
    message = handle.journal.open_message()
    if message is None:
        return
    params: dict[str, Any] = {
        "session_id": handle.id,
        "turn_id": message.turn_id or handle.turn_id or handle.id,
        "message_id": message.message_id,
        "status": status,
    }
    if message.text:
        params["text"] = message.text
    if error:
        params["error"] = error
    service._emit(handle, "message.completed", params)


def _relay_expired(service: CoreService, handle: SessionHandle,
                   event: Event) -> None:
    """A prompt nobody answered in time, told to the client as the resolution it is.

    The worker has already acted on the fallback and moved on, so a card left
    on screen is a card offering a decision nothing will honour — the exact
    thing that reads as "the agent hung" while in fact it is running again.
    This is the event that lets a client stop offering it.

    It is also what makes the answer to a late reply honest: the request is
    dropped here, so a `permission.reply` arriving afterwards is refused as
    unknown rather than answered with a resolution the core ignored.
    """
    request = event.get("request")
    if request is None:
        return
    request_id = str(getattr(request, "id", "") or "")
    handle._pending.pop(request_id, None)
    resolved: dict[str, Any] = {"id": request_id, "session_id": handle.id}

    if getattr(request, "kind", "") == "questions":
        # A form nobody filled in is a cancelled form: the tool carries on with
        # its own defaults, which is what it already does on an explicit Esc.
        resolved["cancelled"] = True
        service._emit(handle, "question.resolved", resolved)
        return

    resolved["choice"] = str(event.get("choice") or request.fallback)
    service._emit(handle, "permission.resolved", resolved)


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

    service._emit(handle, "permission.requested",
                  _permission_shape(handle.id, request))


def _permission_shape(session_id: str, request: Request) -> dict[str, Any]:
    """A permission prompt, with the context an informed decision needs.

    The engine already knows which tool is asking and which risk tier it
    declared; not forwarding it left a client able to show only a sentence, so
    the person had to infer from prose whether they were approving a read, a
    write or a shell command. Both fields are sent as names rather than the
    engine's integers, because the numbering is a Python implementation detail
    and a client that guessed at it would guess silently.

    Nothing here is invented: an absent tool or an unrecognised tier is left
    out rather than filled in, because a made-up `dangerous` on a prompt that
    was really a write trains somebody to stop reading.
    """
    body: dict[str, Any] = {
        "id": request.id,
        "session_id": session_id,
        "title": request.prompt,
        "detail": request.detail,
        "options": list(request.options),
    }
    meta = request.meta or {}
    tool = str(meta.get("tool") or "")
    if tool:
        body["tool"] = tool
    risk = meta.get("risk")
    if not isinstance(risk, bool) and isinstance(risk, int):
        name = RISK_NAMES.get(risk, "")
        if name:
            body["risk"] = name
    return body


def _question_shape(session_id: str, request: Request) -> dict[str, Any]:
    """A form from the `ask` tool, in the protocol's shape.

    The questions are in `meta["questions"]` — `Ask` leaves `request.options`
    empty on purpose, because the answer is a JSON document rather than one of
    a fixed set and the interfaces that validate `options` by membership would
    reject every real answer.

    Reading `options` instead, as this did, produced an event carrying zero
    of them: a form a client could render and nobody could fill in.

    A form is several questions. `Ask` exists to ask four short things in one
    round trip rather than four, so flattening it to one prompt would undo the
    tool.
    """
    from .. import questions as forms

    meta = request.meta or {}
    questions = forms.decode(meta.get("questions") or [])

    return {
        "id": request.id,
        "session_id": session_id,
        "title": request.prompt,
        "questions": [
            {
                # The header is the stable name an answer is matched on.
                # Position would silently reattach every answer if a question
                # were reordered.
                "header": question.header,
                "prompt": question.prompt,
                "multiple": bool(question.multi),
                "options": [
                    {
                        "id": option.label,
                        "label": option.label,
                        **({"description": option.description}
                           if option.description else {}),
                        **({"free": True} if option.free else {}),
                    }
                    for option in question.options
                ],
            }
            for question in questions
        ],
    }
