"""Characterization: the token estimator and its calibration (T003).

The estimator is the number every context gauge, compaction decision and
benchmark token figure rests on. Provider `Usage` is the truth; the estimate
is what Comodor predicts before the reply arrives. This pins how far apart
the two are allowed to be (FR-055, SC-011), with the tolerance written down
rather than implied.
"""

from __future__ import annotations

from comodor.agent.tokens import (
    Calibration,
    TokenCounter,
    estimate_message,
    estimate_messages,
    estimate_text,
)
from comodor.providers.base import Message, ToolCall

#: How far the *uncalibrated* estimate may sit from a real count, as a ratio.
#:
#: Justified from the heuristic itself: it assumes 4 characters per token for
#: prose and 3 for code. Real tokenizers land between 3.3 and 4.5 for English
#: prose and 2.5 and 3.5 for code, so an honest estimate is within a factor of
#: two of the truth, and `Calibration.observe` itself refuses samples outside
#: 0.3–3.0 as outliers. Anything looser than 2× would let a broken estimator
#: pass; anything tighter would fail on the model's tokenizer rather than on
#: Comodor's code.
RAW_TOLERANCE = 2.0

#: After calibration against real counts the residual must be within this.
#: The correction is a single multiplicative factor learned with weight up to
#: 0.3 per sample, so two identical observations bring the factor to within
#: ~50% of the ratio and five to within ~10%. One-in-five is what the fifth
#: observation must reach.
CALIBRATED_TOLERANCE = 1.2


def _prose(n: int = 400) -> str:
    return " ".join(["the quick brown fox jumps over the lazy dog"] * n)


def _code(n: int = 100) -> str:
    return "\n".join(f"def f{i}(x):\n    return [x, {i}] if x else {{}}" for i in range(n))


def test_prose_and_code_are_estimated_at_different_densities():
    prose, code = _prose(), _code()
    assert estimate_text(prose) * 4 <= len(prose) * 1.05
    assert estimate_text(code) * 3 <= len(code) * 1.05
    assert estimate_text(code) / len(code) > estimate_text(prose) / len(prose)


def test_the_raw_estimate_is_within_the_stated_tolerance_of_a_real_count():
    """A real count for this exact prose from cl100k: 9 tokens per repeat."""
    text = _prose(400)
    real = 9 * 400
    estimate = estimate_text(text)
    assert real / RAW_TOLERANCE <= estimate <= real * RAW_TOLERANCE


def test_message_framing_and_tool_calls_are_counted():
    plain = Message.user("hello")
    assert estimate_message(plain) > estimate_text("hello")
    with_call = Message.assistant("x", [ToolCall(id="c", name="read_file",
                                                 arguments={"path": "a.py"})])
    assert estimate_message(with_call) > estimate_message(Message.assistant("x"))
    assert estimate_messages([plain, with_call]) == \
        estimate_message(plain) + estimate_message(with_call)


def test_a_briefing_costs_tokens_even_though_it_is_not_content():
    assert estimate_message(Message.user("a", briefing="b" * 4000)) > \
        estimate_message(Message.user("a"))


def test_calibration_learns_the_ratio_to_the_provider_count():
    calibration = Calibration()
    raw = 1000
    for _ in range(5):
        calibration.observe(raw, 1500)
    assert calibration.confident
    corrected = calibration.apply(raw)
    assert 1500 / CALIBRATED_TOLERANCE <= corrected <= 1500 * CALIBRATED_TOLERANCE


def test_calibration_ignores_a_cached_prefix_outlier():
    """A cached turn reports a fraction of the prompt; it must not poison the factor."""
    calibration = Calibration()
    calibration.observe(10_000, 100)
    assert calibration.samples == 0
    assert calibration.factor == 1.0


def test_the_counter_applies_calibration_to_the_whole_payload():
    counter = TokenCounter()
    messages = [Message.user(_prose(50))]
    raw = counter.count(messages)
    for _ in range(5):
        counter.observe_usage(messages, None, raw * 2)
    assert counter.count(messages) > raw * 1.5
