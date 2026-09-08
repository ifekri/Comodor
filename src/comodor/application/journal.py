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

    @property
    def open(self) -> bool:
        return not self.status

    def shape(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message_id": self.message_id,
            "turn_id": self.turn_id,
            "role": self.role,
            "text": self.text,
            "status": self.status or "completed",
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
        self._question: dict[str, Any] | None = None
        self._permission: dict[str, Any] | None = None

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

        The number is the event's own; a client that has applied it is at that
        revision. Returned rather than stored on the event so nothing has to
        mutate the params a client is about to receive.
        """
        with self._lock:
            self._apply(name, params)
            self._revision += 1
            return self._revision

    def _apply(self, name: str, params: dict[str, Any]) -> None:
        if name == "message.started":
            message = JournalMessage(
                message_id=str(params.get("message_id", "")),
                turn_id=str(params.get("turn_id", "")),
                role=str(params.get("role", "assistant")))
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
                summary=str(params.get("summary", "")))
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

        elif name == "question.requested":
            self._question = dict(params)
        elif name == "question.resolved":
            self._question = None
        elif name == "permission.requested":
            self._permission = dict(params)
        elif name == "permission.resolved":
            self._permission = None

    def _replace(self, message: JournalMessage) -> None:
        held = self._by_id[message.message_id]
        at = self._messages.index(held)
        self._messages[at] = message
        self._by_id[message.message_id] = message

    def said(self, turn_id: str, text: str) -> None:
        """Record the person's own message, which no event announces.

        The core is told about it as a method call rather than an event, so
        without this a rebuilt client would recover every answer and none of
        the questions.
        """
        with self._lock:
            message = JournalMessage(message_id=f"user-{turn_id}",
                                     turn_id=turn_id, role="user",
                                     text=text, status="completed")
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
            }
            if self._question is not None:
                body["question"] = dict(self._question)
            if self._permission is not None:
                body["permission"] = dict(self._permission)
            return body
