"""The provider-neutral message format and streaming contract.

Every backend — OpenAI-compatible, Anthropic, or the offline fake — converts to
and from the types defined here. The agent loop therefore never learns a wire
format, and adding a provider means writing one adapter, not touching the loop.

Streaming is expressed as a flat sequence of :class:`StreamEvent` values rather
than provider-shaped deltas: text, reasoning, tool-call fragments and usage all
arrive on the same channel, in arrival order.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Protocol, runtime_checkable

# --------------------------------------------------------------------------- #
# messages
# --------------------------------------------------------------------------- #


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return f"call_{uuid.uuid4().hex[:12]}"

    def arguments_json(self) -> str:
        return json.dumps(self.arguments, ensure_ascii=False)


@dataclass
class Message:
    """One turn in the conversation, in Comodor's own shape."""

    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""               # set on TOOL messages
    name: str = ""                       # tool name, for readability
    is_error: bool = False
    images: list[str] = field(default_factory=list)   # base64 data, for vision
    meta: dict[str, Any] = field(default_factory=dict)
    briefing: str = ""                   # see below

    """``briefing`` is material the agent gathered *for this turn* — the lessons
    recall matched against these words, the skills that fit them. It rides on
    the message rather than the system prompt for one reason, which is money:
    the system prompt is the first thing in every request, and a provider will
    only serve a request from cache when it begins with bytes it has already
    seen. Put something query-shaped at the front and nothing behind it can ever
    match; put it here, after everything the last request cached, and the whole
    conversation stays cheap. It is sent to the model, never shown in the
    transcript, and it is not the user's words — which is why it is a separate
    field and not a prefix on ``content``."""

    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str, images: list[str] | None = None,
             briefing: str = "") -> "Message":
        return cls(role=Role.USER, content=content, images=images or [],
                   briefing=briefing)

    @classmethod
    def assistant(cls, content: str = "", tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool(cls, call_id: str, name: str, content: str, is_error: bool = False) -> "Message":
        return cls(role=Role.TOOL, content=content, tool_call_id=call_id,
                   name=name, is_error=is_error)


@dataclass
class ToolSpec:
    """A tool as advertised to the model."""

    name: str
    description: str
    parameters: dict[str, Any]           # JSON Schema for the arguments object

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #


class EventType(str, Enum):
    TEXT = "text"                        # visible answer tokens
    REASONING = "reasoning"              # thinking tokens, when exposed
    TOOL_CALL = "tool_call"              # a fully assembled call
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


@dataclass
class Usage:
    """What one request consumed.

    The three input figures do not overlap, and keeping them apart is the whole
    point: they are billed at different rates. ``input_tokens`` is what was sent
    and paid for in full; ``cached_tokens`` is what the provider recognised from
    an earlier request and served at a fraction of the price; ``written_tokens``
    is what it stored for next time, at a small premium.

    Note what this means for anything reading ``input_tokens`` on its own — it
    is *not* the size of the prompt once caching is working, and on a long
    session it is a small fraction of it. Use :attr:`prompt_tokens` for how much
    the model read, and ``input_tokens`` only for what it cost.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    written_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def prompt_tokens(self) -> int:
        """Everything the model read, however it was billed."""
        return self.input_tokens + self.cached_tokens + self.written_tokens

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.output_tokens

    @property
    def cache_hit_rate(self) -> float:
        """The share of the prompt that did not have to be sent again."""
        prompt = self.prompt_tokens
        return self.cached_tokens / prompt if prompt else 0.0

    def merge(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            written_tokens=self.written_tokens + other.written_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


@dataclass
class StreamEvent:
    type: EventType
    text: str = ""
    tool_call: ToolCall | None = None
    usage: Usage | None = None
    finish_reason: str = ""
    error: str = ""


@dataclass
class Completion:
    """The collapsed result of a stream — what the agent loop acts on."""

    text: str = ""
    reasoning: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    finish_reason: str = ""
    model: str = ""
    provider: str = ""

# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #


class ProviderError(RuntimeError):
    """A call failed. ``retryable`` tells the gateway whether to fail over."""

    def __init__(self, message: str, *, status: int | None = None,
                 provider: str = "", retryable: bool = True) -> None:
        super().__init__(message)
        self.status = status
        self.provider = provider
        self.retryable = retryable


class AuthError(ProviderError):
    def __init__(self, message: str, *, provider: str = "", status: int | None = 401) -> None:
        super().__init__(message, status=status, provider=provider, retryable=False)


class RateLimited(ProviderError):
    def __init__(self, message: str, *, provider: str = "", retry_after: float = 0.0) -> None:
        super().__init__(message, status=429, provider=provider, retryable=True)
        self.retry_after = retry_after


# --------------------------------------------------------------------------- #
# the contract
# --------------------------------------------------------------------------- #


@runtime_checkable
class Provider(Protocol):
    """What every backend must offer."""

    name: str
    model: str

    def stream(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
               model: str = "", temperature: float = 0.3, max_tokens: int = 4096,
               **kwargs: Any) -> Iterator[StreamEvent]:
        ...

    def list_models(self) -> list[str]:
        ...


def collapse(events: Iterator[StreamEvent], *, model: str = "",
             provider: str = "") -> Completion:
    """Fold a stream into a :class:`Completion`.

    Used by non-streaming callers (reflection, titling, headless mode) so there
    is exactly one code path through every provider.
    """
    completion = Completion(model=model, provider=provider)
    text: list[str] = []
    reasoning: list[str] = []
    for event in events:
        if event.type is EventType.TEXT:
            text.append(event.text)
        elif event.type is EventType.REASONING:
            reasoning.append(event.text)
        elif event.type is EventType.TOOL_CALL and event.tool_call is not None:
            completion.tool_calls.append(event.tool_call)
        elif event.type is EventType.USAGE and event.usage is not None:
            completion.usage = completion.usage.merge(event.usage)
        elif event.type is EventType.ERROR:
            raise ProviderError(event.error or "stream failed", provider=provider)
        elif event.type is EventType.DONE:
            completion.finish_reason = event.finish_reason or completion.finish_reason
    completion.text = "".join(text)
    completion.reasoning = "".join(reasoning)
    return completion


def parse_arguments(raw: str) -> dict[str, Any]:
    """Decode tool arguments defensively.

    Models sometimes emit an empty string, trailing commas, or a bare value for
    a single-parameter tool. A malformed argument blob should surface to the
    model as a tool error it can correct, not as a crash.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        repaired = text.rstrip(",")
        for opener, closer in (("{", "}"), ("[", "]")):
            if repaired.startswith(opener) and not repaired.endswith(closer):
                repaired += closer
        try:
            value = json.loads(repaired)
        except ValueError:
            return {"__raw__": text}
    return value if isinstance(value, dict) else {"value": value}
