"""Counting tokens without a tokenizer.

Shipping ``tiktoken`` would add a compiled dependency and still be wrong for
every non-OpenAI model, so Comodor estimates instead — and then *calibrates*.
Every provider reply carries a real ``usage.input_tokens``; comparing that to
what we predicted for the same messages yields a correction factor, so after a
couple of turns the ``Context: 1M`` gauge tracks reality closely for whatever
model is actually in use.

The base heuristic accounts for the fact that code tokenises worse than prose
and that CJK text tokenises worse still.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

from ..providers.base import Message, ToolSpec

# Rough characters-per-token for Latin prose. Code, with its punctuation and
# indentation, lands nearer 3.
_PROSE_CHARS_PER_TOKEN = 4.0
_CODE_CHARS_PER_TOKEN = 3.0
# CJK, Thai and similar scripts are close to one token per character.
_WIDE = re.compile(r"[ᄀ-ᇿ⺀-꓏ꥠ-꥿가-퟿"
                   r"豈-﫿︰-﹏＀-￯]")
_CODEY = re.compile(r"[{}()\[\];=<>+\-*/\\|&^%$#@~`_]")
# Per-message framing the API adds (role markers, separators).
_MESSAGE_OVERHEAD = 4
_TOOL_OVERHEAD = 12


def estimate_text(text: str) -> int:
    """Estimated token count for one string."""
    if not text:
        return 0
    wide = len(_WIDE.findall(text))
    rest = len(text) - wide
    if rest <= 0:
        return wide

    density = len(_CODEY.findall(text)) / max(1, rest)
    chars_per_token = (_CODE_CHARS_PER_TOKEN if density > 0.06
                       else _PROSE_CHARS_PER_TOKEN)
    return int(wide + rest / chars_per_token) + 1


def estimate_message(message: Message) -> int:
    total = _MESSAGE_OVERHEAD + estimate_text(message.content)
    total += estimate_text(message.briefing)
    for call in message.tool_calls:
        total += _TOOL_OVERHEAD + estimate_text(call.name) + estimate_text(call.arguments_json())
    # An image costs far more than its base64 length suggests; this is the
    # commonly used ~1.1k tokens for a typical screenshot.
    total += 1100 * len(message.images)
    return total


def estimate_messages(messages: list[Message]) -> int:
    return sum(estimate_message(message) for message in messages)


def estimate_tools(tools: list[ToolSpec]) -> int:
    total = 0
    for tool in tools:
        total += _TOOL_OVERHEAD + estimate_text(tool.name) + estimate_text(tool.description)
        total += estimate_text(str(tool.parameters))
    return total


@dataclass
class Calibration:
    """Learns the ratio between our estimate and the provider's real count."""

    factor: float = 1.0
    samples: int = 0
    _lock: threading.Lock = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def observe(self, estimated: int, actual: int) -> None:
        """Fold one real measurement into the correction factor."""
        if estimated <= 0 or actual <= 0:
            return
        ratio = actual / estimated
        # Ignore wild outliers: a cached-prefix turn reports far fewer input
        # tokens than were sent and would otherwise poison the estimate.
        if not 0.3 <= ratio <= 3.0:
            return
        with self._lock:
            self.samples += 1
            weight = min(0.3, 1.0 / self.samples)
            self.factor = (1 - weight) * self.factor + weight * ratio

    def apply(self, estimated: int) -> int:
        with self._lock:
            return int(estimated * self.factor)

    @property
    def confident(self) -> bool:
        return self.samples >= 2


class TokenCounter:
    """Estimation plus calibration, for one session."""

    def __init__(self) -> None:
        self.calibration = Calibration()

    def count(self, messages: list[Message], tools: list[ToolSpec] | None = None) -> int:
        raw = estimate_messages(messages) + estimate_tools(tools or [])
        return self.calibration.apply(raw)

    def observe_usage(self, messages: list[Message], tools: list[ToolSpec] | None,
                      actual_input_tokens: int) -> None:
        raw = estimate_messages(messages) + estimate_tools(tools or [])
        self.calibration.observe(raw, actual_input_tokens)


# --------------------------------------------------------------------------- #
# measurement: what one task cost, beside how it went
# --------------------------------------------------------------------------- #


@dataclass
class TurnRecord:
    """One model call's cost, from the provider's own accounting (FR-055).

    The three input figures are kept apart because they are billed apart.
    `estimated` is set only when the provider reported nothing and the
    estimator filled in the prompt size — never silently.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    context_size: int = 0
    estimated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                "cached_tokens": self.cached_tokens, "context_size": self.context_size,
                "estimated": self.estimated}


@dataclass
class TaskMeasurement:
    """One task's paired record: cost and outcome together (FR-072, FR-073).

    Counts, sizes and one-word states only. No prompt body, no file content,
    no credential ever enters this record (FR-074) — `as_dict` is the whole
    of what leaves it, and the redaction test mutates exactly that.
    """

    turns: list[TurnRecord] = field(default_factory=list)
    tool_calls: int = 0
    retries: int = 0
    clarifications_raised: int = 0
    clarifications_answered: int = 0
    corrections: int = 0
    knowledge_hits: int = 0
    knowledge_stale: int = 0
    outcome: str = ""
    validation_outcome: str = ""

    def record_turn(self, usage: Any, context_estimate: int = 0) -> TurnRecord:
        """Provider `Usage` is the truth; the estimate fills in only its absence."""
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        record = TurnRecord(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cached_tokens=int(getattr(usage, "cached_tokens", 0) or 0),
            context_size=prompt if prompt else int(context_estimate or 0),
            estimated=not prompt,
        )
        self.turns.append(record)
        return record

    @property
    def model_turns(self) -> int:
        return len(self.turns)

    @property
    def input_tokens(self) -> int:
        return sum(turn.input_tokens for turn in self.turns)

    @property
    def output_tokens(self) -> int:
        return sum(turn.output_tokens for turn in self.turns)

    @property
    def cached_tokens(self) -> int:
        return sum(turn.cached_tokens for turn in self.turns)

    @property
    def context_size(self) -> int:
        """The last request's size — what the model read most recently."""
        return self.turns[-1].context_size if self.turns else 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "context_size": self.context_size,
            "model_turns": self.model_turns,
            "tool_calls": self.tool_calls,
            "retries": self.retries,
            "clarifications_raised": self.clarifications_raised,
            "clarifications_answered": self.clarifications_answered,
            "corrections": self.corrections,
            "knowledge_hits": self.knowledge_hits,
            "knowledge_stale": self.knowledge_stale,
            "outcome": self.outcome,
            "validation_outcome": self.validation_outcome,
            "estimated_turns": sum(1 for turn in self.turns if turn.estimated),
        }


def humanise(count: int) -> str:
    """Compact display: 1.2M, 340K, 812."""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M".replace(".0M", "M")
    if count >= 1_000:
        return f"{count / 1_000:.0f}K"
    return str(count)
