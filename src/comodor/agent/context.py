"""Conversation state and the context budget.

A long agent session will always outgrow its context window — tool output is
verbose and there is a lot of it. When usage crosses the configured fraction of
the window, the oldest middle section is replaced by an LLM-written brief.

The subtle part is *where* to cut. Every assistant message that requests tools
must keep its matching tool results, or the next request is rejected outright by
the provider. So compaction only ever cuts at a boundary where no tool call is
outstanding, and the original request is always preserved — losing the goal is
the one failure a summary cannot recover from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..providers.base import Message, Role, ToolSpec, Usage
from .tokens import TokenCounter

Summariser = Callable[[list[Message]], str]


@dataclass
class Conversation:
    """The message history plus everything we track about its size."""

    messages: list[Message] = field(default_factory=list)
    counter: TokenCounter = field(default_factory=TokenCounter)
    usage: Usage = field(default_factory=Usage)
    compactions: int = 0

    # -- basics ----------------------------------------------------------- #

    def add(self, message: Message) -> Message:
        self.messages.append(message)
        return message

    def extend(self, messages: list[Message]) -> None:
        self.messages.extend(messages)

    def clear(self) -> None:
        self.messages.clear()
        self.usage = Usage()
        self.compactions = 0

    def render(self, system_prompt: str) -> list[Message]:
        """The full payload for one request."""
        return [Message.system(system_prompt), *self.messages]

    @property
    def last_user_text(self) -> str:
        for message in reversed(self.messages):
            if message.role is Role.USER:
                return message.content
        return ""

    # -- accounting ------------------------------------------------------- #

    def used_tokens(self, system_prompt: str = "", tools: list[ToolSpec] | None = None) -> int:
        payload = self.render(system_prompt) if system_prompt else self.messages
        return self.counter.count(payload, tools)

    def record_usage(self, usage: Usage) -> None:
        self.usage = self.usage.merge(usage)

    def fill(self, limit: int, system_prompt: str = "",
             tools: list[ToolSpec] | None = None) -> float:
        """How full the context window is, as a fraction."""
        if limit <= 0:
            return 0.0
        return min(1.0, self.used_tokens(system_prompt, tools) / limit)

    # -- compaction ------------------------------------------------------- #

    def needs_compaction(self, limit: int, threshold: float,
                         system_prompt: str = "",
                         tools: list[ToolSpec] | None = None) -> bool:
        return self.fill(limit, system_prompt, tools) >= threshold

    def safe_cut(self, keep_recent: int = 8) -> int:
        """Index up to which messages may be summarised away.

        A cut is only safe where the conversation is *settled*: a user turn
        with no assistant tool call still awaiting its result. Returns 0 when
        no safe point exists, which simply means compaction waits a turn.
        """
        if len(self.messages) <= keep_recent + 2:
            return 0

        latest_allowed = len(self.messages) - keep_recent
        pending: set[str] = set()
        last_safe = 0

        for index, message in enumerate(self.messages):
            if message.role is Role.ASSISTANT and message.tool_calls:
                pending.update(call.id for call in message.tool_calls)
            elif message.role is Role.TOOL:
                pending.discard(message.tool_call_id)

            # A user message with nothing outstanding is a clean seam.
            if (index > 0 and not pending and message.role is Role.USER
                    and index <= latest_allowed):
                last_safe = index

        return last_safe

    def compact(self, summarise: Summariser, keep_recent: int = 8) -> int:
        """Replace the middle of the history with a brief. Returns messages removed."""
        cut = self.safe_cut(keep_recent)
        if cut <= 1:
            return 0

        head = self.messages[0]            # the original request stays verbatim
        middle = self.messages[1:cut]
        tail = self.messages[cut:]
        if not middle:
            return 0

        try:
            brief = summarise(middle).strip()
        except Exception:
            # A failed summary must not lose messages; better a full context
            # and a hard error later than silently discarded work now.
            return 0
        if not brief:
            return 0

        marker = Message(
            role=Role.USER,
            content=("[Earlier in this session — compacted summary]\n\n" + brief),
            meta={"compacted": True, "replaced": len(middle)},
        )
        self.messages = [head, marker, *tail]
        self.compactions += 1
        return len(middle)

    def forget_old_pictures(self, keep: int = 2) -> int:
        """Drop all but the newest screenshots. Returns how many went.

        A picture costs the same every turn it stays in the history, and a
        screen from twenty clicks ago is not what is on the screen now. The
        message is left in place with a note where the image was, so the model
        can see that it looked and when, without paying to look again.

        `keep` is small on purpose. Two is enough to compare "before" with
        "after"; a third is a screen two actions old, which is history.
        """
        seen = 0
        dropped = 0
        for message in reversed(self.messages):
            if not message.images:
                continue
            seen += 1
            if seen <= keep:
                continue
            dropped += len(message.images)
            message.images = []
            note = "[the screenshot from this step is no longer in context]"
            if note not in message.content:
                message.content = (message.content + "\n" + note).strip()
        return dropped

    # -- introspection ---------------------------------------------------- #

    def summary_line(self) -> str:
        roles = dict.fromkeys(("user", "assistant", "tool"), 0)
        for message in self.messages:
            key = message.role.value
            if key in roles:
                roles[key] += 1
        return (f"{len(self.messages)} messages "
                f"({roles['user']} user, {roles['assistant']} assistant, "
                f"{roles['tool']} tool)")
