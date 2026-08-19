"""A scripted provider: deterministic streams with no network and no spend.

It backs three things — the test suite, ``comodor --demo`` (a full UI walkthrough
without any API key), and reproduction cases for stream-handling bugs. Because
it emits the same :class:`StreamEvent` values as a real provider, everything
downstream of it is exercised for real.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from .base import (
    EventType,
    Message,
    ProviderError,
    Role,
    StreamEvent,
    ToolCall,
    ToolSpec,
    Usage,
)


@dataclass
class Script:
    """One scripted turn."""

    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str = ""                       # fail, to exercise recovery paths
    # How many text chunks to emit before failing. Zero fails before any output
    # (the case where failover is safe); one or more fails mid-stream (the case
    # where it is not, because the user has already seen part of an answer).
    error_after: int = 0
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=120, output_tokens=40))
    delay: float = 0.0                    # seconds between chunks, for UI demos


class FakeProvider:
    """Replays :class:`Script` objects, one per call, then repeats the last."""

    name = "fake"
    label = "Fake"

    def __init__(self, scripts: list[Script] | None = None, model: str = "fake-1",
                 chunk: int = 24) -> None:
        self.scripts = list(scripts or [])
        self.model = model
        self.chunk = chunk
        self.calls: list[list[Message]] = []
        self._index = 0

    def stream(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
               model: str = "", temperature: float = 0.3, max_tokens: int = 4096,
               **kwargs: Any) -> Iterator[StreamEvent]:
        self.calls.append(list(messages))
        script = self._next_script(messages)

        for piece in _chunks(script.reasoning, self.chunk):
            yield StreamEvent(type=EventType.REASONING, text=piece)
            if script.delay:
                time.sleep(script.delay)

        emitted = 0
        for piece in _chunks(script.text, self.chunk):
            if script.error and emitted >= script.error_after:
                raise ProviderError(script.error, provider=self.name)
            yield StreamEvent(type=EventType.TEXT, text=piece)
            emitted += 1
            if script.delay:
                time.sleep(script.delay)

        if script.error:
            raise ProviderError(script.error, provider=self.name)

        for call in script.tool_calls:
            yield StreamEvent(type=EventType.TOOL_CALL, tool_call=call)

        yield StreamEvent(type=EventType.USAGE, usage=script.usage)
        yield StreamEvent(type=EventType.DONE,
                          finish_reason="tool_use" if script.tool_calls else "end_turn")

    def _next_script(self, messages: list[Message]) -> Script:
        if self._index < len(self.scripts):
            script = self.scripts[self._index]
            self._index += 1
            return script
        if self.scripts:
            return self.scripts[-1]
        return Script(text=_echo(messages))

    def list_models(self) -> list[str]:
        return ["fake-1", "fake-fast"]

    def close(self) -> None:
        pass


def _chunks(text: str, size: int) -> Iterator[str]:
    for start in range(0, len(text), size):
        yield text[start:start + size]


def _echo(messages: list[Message]) -> str:
    """The default reply when no script is supplied."""
    last = next((m for m in reversed(messages) if m.role is Role.USER), None)
    question = (last.content if last else "").strip()
    return (f"(offline provider) I received {len(messages)} messages. "
            f"Your last message was: {question[:200] or '(empty)'}")


def demo_scripts() -> list[Script]:
    """A short tour used by ``comodor --demo``: a tool call, then an answer."""
    return [
        Script(
            reasoning="Checking what the project looks like before answering.",
            text="Let me look at the project layout first.\n\n",
            tool_calls=[ToolCall(id="call_demo1", name="list_dir", arguments={"path": "."})],
            delay=0.02,
        ),
        Script(
            text=(
                "Here is what I found.\n\n"
                "The project is a Python package with a `src/` layout. A few notes:\n\n"
                "- **Entry point** lives in `cli.py`\n"
                "- **Tests** sit under `tests/`\n\n"
                "```python\ndef hello() -> str:\n    return \"Comodor is running offline\"\n```\n\n"
                "Ask me anything else — this demo runs with no API key and no network."
            ),
            delay=0.01,
        ),
    ]
