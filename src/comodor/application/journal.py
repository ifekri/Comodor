"""What the core knows about one session, so a client can be rebuilt from it.

F1 gave a client every event as it happened and nothing to fall back on. That
is enough right up until the client's own state goes away — a remount, a
reconnect, a second window — and then `session.get` answers with four fields
of metadata and the conversation is simply gone. A protocol that streams but
cannot re-describe is one where the frontend's memory is the only copy.

So the core keeps its own projection. Not a second source of truth: *the*
source, of which every client's state is a copy. It is written from the same
relay that produces the events, so what a snapshot says and what the stream
said cannot disagree — there is one place doing both.

**The sequence number is the whole reason this is race-free.** A snapshot is
built while a turn is still streaming on another thread, and the two reach the
wire through the same lock in whichever order they arrive. Numbering every
event, under the same lock that updates the projection, lets a snapshot say
"this includes everything through 41" and a client discard 39 and 40 while
applying 42. Without it the client would have to guess, and the guess is wrong
exactly when the session is busiest.

Nothing here knows about JSON, a pipe, or a client. It is a record of what
happened, in the protocol's own vocabulary.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

__all__ = ["Journal", "JournalMessage", "JournalTool", "OUTPUT_CAP"]

#: How much of one tool's streamed output the core keeps for re-describing it.
#:
#: A command that prints for a minute is not a reason to hold a minute of text
#: per call forever. The cap is generous enough that ordinary output survives
#: whole, and when it does bite the snapshot says so — `output_truncated` — so
#: a client shows a shortened transcript as shortened rather than as all there
#: was. Live output is never capped; this is only what can still be recovered.
OUTPUT_CAP = 64_000

#: How far along a delegate a state word says it is. The manager guarantees its
#: announcements never move backwards; this is the same rule kept where the
#: snapshot is built, because a journal that folded a late `running` over a
#: `stopped` would re-describe a delegate as alive that the core had already
#: told everybody was finished — and the snapshot is what a reconnecting client
#: believes.
DELEGATE_PROGRESS = {"running": 0, "stopping": 1,
                     "done": 2, "failed": 2, "stopped": 2, "lost": 2}

#: States a delegate does not come back from.
DELEGATE_TERMINAL = ("done", "failed", "stopped", "lost")

#: The task states the `todo_write` tool owns. A state the core has never heard
#: of is folded as `pending` rather than passed through: the snapshot repeats
#: the tool's own coercion instead of shipping a word no client knows.
TASK_STATES = ("pending", "active", "done", "blocked")


@dataclass
class JournalMessage:
    """One assistant or user message, as the core has it."""

    message_id: str
    turn_id: str
    role: str
    text: str = ""
    reasoning: str = ""
    #: Empty while streaming. Otherwise completed | cancelled | failed.
    status: str = ""
    #: The session sequence at which this message entered the timeline. Shared
    #: with tools, so a rebuilt session interleaves the two the way the live
    #: stream did instead of drawing every message before every tool.
    started_seq: int = 0

    @property
    def open(self) -> bool:
        return not self.status

    @property
    def wire_status(self) -> str:
        """The status as the protocol spells it.

        Internally "open" is an empty status, because nothing has yet said how
        the message ended. On the wire an open message is `streaming`:
        reporting `completed` for one that has not completed tells a client to
        stop listening to an answer that is still arriving.
        """
        return self.status or "streaming"

    def shape(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message_id": self.message_id,
            "turn_id": self.turn_id,
            "role": self.role,
            "text": self.text,
            "status": self.wire_status,
            "started_seq": self.started_seq,
        }
        if self.reasoning:
            body["reasoning"] = self.reasoning
        return body


@dataclass
class JournalTool:
    """One tool invocation, and what it has produced so far."""

    call_id: str
    turn_id: str
    name: str
    summary: str = ""
    state: str = "running"
    output: str = ""
    output_truncated: bool = False
    error: str = ""
    elapsed_ms: int | None = None
    #: The session sequence of the `tool.started` that created this. Ordered
    #: against messages in one domain; see `JournalMessage.started_seq`.
    started_seq: int = 0

    def add_output(self, text: str) -> None:
        self.output += text
        if len(self.output) > OUTPUT_CAP:
            # The tail, because the end of a command's output is the part that
            # says how it went. Dropping the front is a loss either way, and
            # the flag is what stops it being a silent one.
            self.output = self.output[-OUTPUT_CAP:]
            self.output_truncated = True

    def shape(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "call_id": self.call_id,
            "turn_id": self.turn_id,
            "name": self.name,
            "state": self.state,
            "started_seq": self.started_seq,
        }
        if self.summary:
            body["summary"] = self.summary
        if self.output:
            body["output"] = self.output
        if self.output_truncated:
            body["output_truncated"] = True
        if self.error:
            body["error"] = self.error
        if self.elapsed_ms is not None:
            body["elapsed_ms"] = self.elapsed_ms
        return body


class Journal:
    """One session's visible history, and the counter that orders it.

    Every mutation happens under one lock, and the counter is read out in the
    same breath as the state it belongs to. `record` is called with an event
    about to be sent; `snapshot` is called from a request thread. Because both
    take the lock, a snapshot is always a state that actually existed, and the
    revision it reports is exactly the last event folded into it.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._revision = 0
        self._messages: list[JournalMessage] = []
        self._by_id: dict[str, JournalMessage] = {}
        self._tools: list[JournalTool] = []
        self._tool_by_id: dict[str, JournalTool] = {}
        #: The agent's task list, whole. `todo_write` replaces it on every
        #: update and so does this: a task the newest list does not carry is
        #: gone, which is the only way a removed or reordered plan survives a
        #: reconnect honestly.
        self._tasks: list[dict[str, Any]] = []
        #: Background delegates by id, insertion-ordered. Terminal records stay:
        #: a panel that forgot a finished delegate could not answer "what
        #: happened to those three background tasks?", and a `lost` one that
        #: vanished would look like a delegate that never existed.
        self._delegates: dict[str, dict[str, Any]] = {}
        #: Blocking interactions waiting on a person, oldest first, keyed by
        #: request id.
        #:
        #: A dict rather than one slot per kind, because two can be live at
        #: once: a batch of read-only tools runs in parallel and each may ask a
        #: question, and a delegate shares its parent's event bus, so a
        #: delegate's question can arrive while the parent is waiting on a
        #: permission. One slot would silently strand whichever came second,
        #: and a stranded prompt is a tool that looks hung.
        self._waiting: dict[str, tuple[str, dict[str, Any]]] = {}
        #: The latest usage report, whole. Replacement like the task list:
        #: context fill and cost are counters that only ever describe "now",
        #: so keeping anything but the newest would be a lie about the past.
        self._usage: dict[str, Any] = {}

    @property
    def lock(self) -> threading.RLock:
        """Held by the caller across recording *and* sending.

        Exposed rather than hidden because the ordering guarantee is between
        two things this class only owns one of: the number, and the write. A
        caller that took them separately could hand out 6 before 5.
        """
        return self._lock

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    # -- writing ----------------------------------------------------------- #

    def record(self, name: str, params: dict[str, Any]) -> int:
        """Fold one event in, and give it its number.

        The number is worked out *before* the fold, and handed to it. An item
        this event creates stores the sequence it arrived on, which is the next
        number this session will emit — not the one before it. Getting that
        backwards would date every item one event early and leave a message and
        the tool that follows it sharing a position, which is exactly the
        ambiguity `started_seq` exists to remove.

        The number is returned rather than stored on the event so nothing has
        to mutate the params a client is about to receive.
        """
        with self._lock:
            seq = self._revision + 1
            self._apply(name, params, seq)
            self._revision = seq
            return seq

    def _apply(self, name: str, params: dict[str, Any], seq: int) -> None:
        if name == "message.started":
            message = JournalMessage(
                message_id=str(params.get("message_id", "")),
                turn_id=str(params.get("turn_id", "")),
                role=str(params.get("role", "assistant")),
                started_seq=seq)
            # A repeated id would otherwise leave two entries a client cannot
            # tell apart. The core does not currently produce one; a bug that
            # made it would show up as a replaced message rather than a pair.
            if message.message_id in self._by_id:
                self._replace(message)
            else:
                self._messages.append(message)
                self._by_id[message.message_id] = message

        elif name == "message.delta":
            message = self._by_id.get(str(params.get("message_id", "")))
            if message is None:
                return
            if str(params.get("channel", "")) == "reasoning":
                message.reasoning += str(params.get("text", ""))
            else:
                message.text += str(params.get("text", ""))

        elif name == "message.completed":
            message = self._by_id.get(str(params.get("message_id", "")))
            if message is None:
                return
            text = str(params.get("text", ""))
            if text:
                message.text = text
            message.status = str(params.get("status", "completed"))

        elif name == "tool.started":
            tool = JournalTool(
                call_id=str(params.get("call_id", "")),
                turn_id=str(params.get("turn_id", "")),
                name=str(params.get("name", "")),
                summary=str(params.get("summary", "")),
                started_seq=seq)
            if tool.call_id in self._tool_by_id:
                held = self._tool_by_id[tool.call_id]
                held.state = "running"
                held.summary = tool.summary or held.summary
            else:
                self._tools.append(tool)
                self._tool_by_id[tool.call_id] = tool

        elif name == "tool.output":
            tool = self._tool_by_id.get(str(params.get("call_id", "")))
            if tool is not None:
                tool.add_output(str(params.get("text", "")))

        elif name == "tool.completed":
            tool = self._tool_by_id.get(str(params.get("call_id", "")))
            if tool is not None:
                tool.state = "completed"
                summary = str(params.get("summary", ""))
                if summary:
                    tool.summary = summary
                elapsed = params.get("elapsed_ms")
                if isinstance(elapsed, int):
                    tool.elapsed_ms = elapsed

        elif name == "tool.failed":
            tool = self._tool_by_id.get(str(params.get("call_id", "")))
            if tool is not None:
                tool.state = "failed"
                tool.error = str(params.get("error", ""))

        elif name == "tasks.updated":
            # Replacement, not addition — the tool's own semantics. The list is
            # rebuilt from the event rather than patched, so a task the model
            # removed stays removed and a reorder is the reorder it wrote.
            tasks = params.get("tasks")
            folded: list[dict[str, Any]] = []
            if isinstance(tasks, list):
                for entry in tasks:
                    if not isinstance(entry, dict):
                        continue
                    state = str(entry.get("state", "pending"))
                    folded.append({
                        "text": str(entry.get("text", "")),
                        "state": state if state in TASK_STATES else "pending",
                    })
            self._tasks = folded

        elif name == "delegate.updated":
            delegate = params.get("delegate")
            if isinstance(delegate, dict):
                self._fold_delegate(dict(delegate))

        elif name == "usage.updated":
            # Whole-report replacement: the numbers describe a moment, and a
            # snapshot that merged two moments would show a fill and a cost
            # that were never true together.
            self._usage = {field: params[field]
                           for field in ("context_used", "context_limit",
                                         "fill", "input_tokens",
                                         "output_tokens", "cost_usd")
                           if params.get(field) is not None}

        elif name in ("question.requested", "permission.requested"):
            kind = "question" if name.startswith("question") else "permission"
            request_id = str(params.get("id", ""))
            # Keyed by id, so a second live interaction is added rather than
            # written over the first.
            if request_id:
                self._waiting[request_id] = (kind, dict(params))

        elif name in ("question.resolved", "permission.resolved"):
            # Removing exactly the one that resolved. Clearing "the question"
            # or "the permission" would drop a second request that is still
            # waiting on somebody.
            self._waiting.pop(str(params.get("id", "")), None)

    def _replace(self, message: JournalMessage) -> None:
        held = self._by_id[message.message_id]
        at = self._messages.index(held)
        self._messages[at] = message
        self._by_id[message.message_id] = message

    def _fold_delegate(self, record: dict[str, Any]) -> None:
        """One delegate record, folded forward-only. Caller holds the lock.

        Replaced whole rather than merged field by field: the record is the
        manager's own description of the run, and half-merging two of them
        could pair a new state with an old error. Ignored entirely when it
        would move the delegate backwards — a late `running` behind a
        `stopped`, a `started` creeping in behind a terminal state. The
        manager already announces monotonically; this is the same rule kept
        where the reconnect truth is built, because a snapshot that
        re-described a finished delegate as alive would be the exact lie the
        lifecycle exists to prevent.
        """
        identifier = str(record.get("id", ""))
        if not identifier:
            return
        held = self._delegates.get(identifier)
        if held is not None:
            was = str(held.get("state", ""))
            now = str(record.get("state", ""))
            if was in DELEGATE_TERMINAL:
                return                  # nothing comes back from a terminal
            if DELEGATE_PROGRESS.get(now, 0) < DELEGATE_PROGRESS.get(was, -1):
                return                  # this record knows less than we do
        self._delegates[identifier] = record

    def seed_delegates(self, records: list[dict[str, Any]]) -> None:
        """Adopt the delegates that predate this journal's first event.

        The manager reads its crash record when the session is built — a run
        that was going when the process died is already `lost` — but none of
        that was announced as an event, so none of it arrives through the
        stream. Folded without spending a sequence number: the next event
        keeps the number it would have had, and a snapshot describes the
        machine as it actually is from the first moment a client can ask.
        """
        with self._lock:
            for record in records:
                if isinstance(record, dict):
                    self._fold_delegate(dict(record))

    def said(self, turn_id: str, text: str) -> None:
        """Record the person's own message, which no event announces.

        The core is told about it as a method call rather than an event, so
        without this a rebuilt client would recover every answer and none of
        the questions.

        It takes the sequence the session is about to use, rather than spending
        one of its own: spending a number without emitting an event would leave
        a hole a client reads as a gap and resynchronises over. No other item
        lands on that number, because the events that create items
        (`message.started`, `tool.started`) are all emitted after this, and each
        takes the next number in turn.
        """
        with self._lock:
            message = JournalMessage(message_id=f"user-{turn_id}",
                                     turn_id=turn_id, role="user",
                                     text=text, status="completed",
                                     started_seq=self._revision + 1)
            self._messages.append(message)
            self._by_id[message.message_id] = message

    def open_message(self) -> JournalMessage | None:
        """The message still streaming, if there is one."""
        with self._lock:
            for message in reversed(self._messages):
                if message.role == "assistant" and message.open:
                    return message
        return None

    def running_tools(self) -> list[JournalTool]:
        with self._lock:
            return [tool for tool in self._tools if tool.state == "running"]

    # -- reading ----------------------------------------------------------- #

    def snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        """The session as a client should draw it, and the revision it is at."""
        with self._lock:
            body: dict[str, Any] = {
                "session": session,
                "revision": self._revision,
                "messages": [message.shape() for message in self._messages],
                "tools": [tool.shape() for tool in self._tools],
                # Always present, empty or not: a client that has to guess
                # whether an absent field means "no tasks" or "a core too old
                # to know about tasks" guesses wrong in one of the two cases.
                # The handshake's capability list answers the age question;
                # this answers the state one.
                "tasks": [dict(task) for task in self._tasks],
                "delegates": [dict(record)
                              for record in self._delegates.values()],
            }
            if self._usage:
                # Present only when a report exists: an empty object would
                # tell a client the core knows usage it does not.
                body["usage"] = dict(self._usage)
            waiting = list(self._waiting.values())
            if waiting:
                body["interactions"] = [
                    {"kind": kind, kind: dict(request)}
                    for kind, request in waiting
                ]
                # The singular fields stay for a client that presents one
                # interaction at a time. Each is the oldest of its kind, which
                # is the one a person has been kept waiting on longest.
                for kind in ("question", "permission"):
                    oldest = next((request for other, request in waiting
                                   if other == kind), None)
                    if oldest is not None:
                        body[kind] = dict(oldest)
            return body
