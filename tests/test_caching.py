"""Paying once for what the model reads many times.

An agent resends its whole conversation on every request, so the same tool
result is billed at every step after the one that produced it. Providers sell
those resends at a tenth of the price on one condition: the request must begin
with bytes they have already seen. These tests are about that condition, which
is easy to state and easy to break — one query-shaped word near the front and
the entire prefix misses, at full price.
"""

from __future__ import annotations

import json

import pytest

from comodor.providers import caching
from comodor.providers.anthropic import AnthropicProvider
from comodor.providers.base import Message, ToolSpec

BIG = 20_000            # characters — comfortably over the cacheable floor


def body_for(messages, *, tools=True, system=""):
    provider = AnthropicProvider(api_key="x")
    encoded_system, encoded = provider._encode(messages)
    body = {"model": "claude-sonnet-4-5", "messages": encoded}
    if encoded_system:
        body["system"] = encoded_system
    if tools:
        body["tools"] = [ToolSpec("read", "Read a file. " * 200,
                                  {"type": "object"}).to_anthropic()]
    provider._cache(body)
    return body


def marks_in(body) -> int:
    found = 0
    for block in body.get("system") or []:
        found += "cache_control" in block
    for message in body["messages"]:
        for block in message["content"]:
            found += "cache_control" in block
    return found


# --------------------------------------------------------------------------- #
# where the marks go
# --------------------------------------------------------------------------- #


def test_nothing_is_marked_when_there_is_nothing_worth_caching():
    """A cache write costs a 25% premium. On a short first exchange there is
    nothing to read back, so the premium would buy nothing at all."""
    marks = caching.plan(head_tokens=50, sizes=[20, 30])

    assert not marks
    assert marks.count == 0


def test_the_head_is_marked_once_it_is_large_enough():
    marks = caching.plan(head_tokens=caching.MIN_CACHEABLE, sizes=[])

    assert marks.head
    assert marks.messages == ()


def test_the_marks_sit_at_the_end_of_the_conversation():
    """Everything before the last message is what the previous request already
    sent, so the last mark is exactly the boundary between paid and cached."""
    sizes = [caching.MIN_CACHEABLE] * 6
    marks = caching.plan(head_tokens=0, sizes=sizes)

    assert marks.messages == (4, 5)
    assert max(marks.messages) == len(sizes) - 1


def test_never_more_marks_than_the_api_accepts():
    marks = caching.plan(head_tokens=caching.MIN_CACHEABLE,
                         sizes=[caching.MIN_CACHEABLE] * 40, rolling=99)

    assert marks.count <= caching.MAX_BREAKPOINTS


def test_a_second_mark_needs_real_conversation_behind_it():
    """Two marks a few hundred tokens apart spend a breakpoint on nothing."""
    sizes = [caching.MIN_CACHEABLE * 4] + [4] * 5
    marks = caching.plan(head_tokens=0, sizes=sizes)

    assert len(marks.messages) == 1


def test_a_mark_is_never_placed_where_the_provider_would_ignore_it():
    """Below the floor the API caches nothing and says nothing; the breakpoint
    is simply lost, and so is the write premium paid for it."""
    marks = caching.plan(head_tokens=10, sizes=[10, 10, 10])

    assert marks.messages == ()


def test_marks_only_land_on_permitted_boundaries():
    sizes = [caching.MIN_CACHEABLE] * 6
    marks = caching.plan(head_tokens=0, sizes=sizes, boundaries=[1, 3])

    assert set(marks.messages) <= {1, 3}


# --------------------------------------------------------------------------- #
# the request that goes on the wire
# --------------------------------------------------------------------------- #


def test_a_long_conversation_is_marked_for_caching():
    messages = [Message.user("x" * BIG), Message.assistant("y" * BIG),
                Message.user("z" * BIG)]
    body = body_for(messages)

    assert marks_in(body) >= 2


def test_the_head_mark_covers_the_tool_schemas_too():
    """Anthropic orders a request tools, system, messages, and a breakpoint
    covers everything before it — so one mark on the system block caches the
    schemas as well and leaves a breakpoint spare for the conversation."""
    body = body_for([Message.system("You are Comodor. " * 900),
                     Message.user("x" * BIG)])

    assert isinstance(body["system"], list)
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_no_marks_means_the_body_is_untouched():
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]}
    before = json.dumps(body)
    caching.apply(body, caching.Marks())

    assert json.dumps(body) == before


def test_marking_changes_nothing_the_model_reads():
    """The saving must be invisible in the answer: same text, same order, same
    tools — one extra key that only the billing system looks at."""
    messages = [Message.user("x" * BIG), Message.assistant("y" * BIG)]
    marked = body_for(messages)

    def stripped(payload):
        return [[{key: value for key, value in block.items() if key != "cache_control"}
                 for block in message["content"]] for message in payload["messages"]]

    plain = AnthropicProvider(api_key="x")._encode(messages)[1]

    assert stripped(marked) == [message["content"] for message in plain]


def test_a_longer_hour_is_requested_only_when_asked_for():
    body = body_for([Message.system("s" * BIG), Message.user("x" * BIG)])
    assert "ttl" not in body["system"][-1]["cache_control"]

    other = {"system": "s" * BIG}
    caching.apply(other, caching.Marks(head=True), ttl="1h")
    assert other["system"][-1]["cache_control"]["ttl"] == "1h"


# --------------------------------------------------------------------------- #
# the condition the whole thing rests on
# --------------------------------------------------------------------------- #


def test_the_head_of_the_request_is_identical_from_turn_to_turn():
    """The bug this feature exists to fix. Recalled lessons used to be appended
    to the system prompt, and recall runs against each new request — so the
    first paragraph differed every turn and nothing behind it could match."""
    first = [Message.system("You are Comodor."),
             Message.user("add a test", briefing="Lesson: prefer pytest fixtures")]
    second = first + [
        Message.assistant("done"),
        Message.user("now the parser", briefing="Lesson: the parser lives in src/"),
    ]

    provider = AnthropicProvider(api_key="x")
    head_one, encoded_one = provider._encode(first)
    head_two, encoded_two = provider._encode(second)

    assert head_one == head_two
    assert encoded_two[:len(encoded_one)] == encoded_one


def test_the_briefing_reaches_the_model():
    """Cheaper is worthless if the lessons stopped arriving."""
    body = body_for([Message.user("add a test", briefing="Prefer pytest fixtures")])
    texts = [block.get("text") for block in body["messages"][0]["content"]]

    assert "Prefer pytest fixtures" in texts
    assert "add a test" in texts


def test_the_briefing_leads_so_the_users_words_come_last():
    body = body_for([Message.user("the question", briefing="the context")])
    texts = [block["text"] for block in body["messages"][0]["content"]
             if block["type"] == "text"]

    assert texts == ["the context", "the question"]


def test_the_briefing_is_not_the_users_words():
    """It is never shown in the transcript, so it must not be mixed into the
    field the transcript renders."""
    message = Message.user("add a test", briefing="Lesson: prefer fixtures")

    assert message.content == "add a test"


def test_a_turn_without_recall_sends_no_extra_block():
    body = body_for([Message.user("hello")])

    assert len(body["messages"][0]["content"]) == 1


def test_the_openai_dialect_carries_the_briefing_too():
    from comodor.providers.openai_compat import OpenAICompatProvider

    provider = OpenAICompatProvider("test", "https://example.invalid", api_key="x")
    encoded = provider._encode_messages(
        [Message.user("the question", briefing="the context")])

    assert encoded[0]["content"] == "the context\n\nthe question"


def test_a_resumed_session_sends_what_it_sent_before(tmp_path):
    """Reload must reproduce the bytes exactly, or the first request after a
    resume misses on the entire history."""
    from comodor.session.store import SessionStore

    store = SessionStore(tmp_path)
    original = Message.user("add a test", briefing="Lesson: prefer fixtures")
    store.append("s1", original)
    restored = store.load("s1")

    assert restored[0].briefing == original.briefing
    assert restored[0].content == original.content


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #


def test_savings_are_measured_not_assumed():
    """Reported from what the provider says it served, never from the plan."""
    assert caching.savings(0, 1000) == 0.0
    assert caching.savings(0, 0) == 0.0
    assert caching.savings(9_000, 1_000) == pytest.approx(0.81)


def test_the_weight_of_an_empty_payload_is_zero():
    assert caching.weigh(None) == 0
    assert caching.weigh("") == 0


# --------------------------------------------------------------------------- #
# the bill
# --------------------------------------------------------------------------- #


def test_the_three_input_figures_do_not_overlap():
    """Anthropic reports them separately and `input_tokens` excludes both the
    others. Adding them is what the prompt actually was."""
    from comodor.providers.base import Usage

    usage = Usage(input_tokens=500, cached_tokens=40_000, written_tokens=1_500)

    assert usage.prompt_tokens == 42_000
    assert usage.cache_hit_rate == pytest.approx(40_000 / 42_000)


def test_a_cached_prefix_is_billed_at_a_tenth():
    from comodor.providers import registry

    plain = registry.estimate_cost("claude-sonnet-5", 100_000, 0)
    cached = registry.estimate_cost("claude-sonnet-5", 0, 0, 100_000, 0)

    assert cached == pytest.approx(plain * registry.CACHE_READ)


def test_writing_a_prefix_costs_a_premium_paid_once():
    from comodor.providers import registry

    plain = registry.estimate_cost("claude-sonnet-5", 100_000, 0)
    written = registry.estimate_cost("claude-sonnet-5", 0, 0, 0, 100_000)

    assert written == pytest.approx(plain * registry.CACHE_WRITE)
    assert written > plain


def test_counting_only_the_billed_input_would_understate_a_session():
    """The failure this arithmetic exists to prevent: `input_tokens` alone looks
    tiny once caching works, and the spend guard is built on it."""
    from comodor.providers import registry

    honest = registry.estimate_cost("claude-sonnet-5", 2_000, 500, 98_000, 0)
    naive = registry.estimate_cost("claude-sonnet-5", 2_000, 500)

    assert honest > naive


def test_an_unpriced_model_still_reports_nothing():
    """A wrong cost is worse than no cost; caching must not change that."""
    from comodor.providers import registry

    assert registry.estimate_cost("some-unknown-model", 10, 10, 10, 10) is None


def test_usage_merges_the_cache_figures_too():
    from comodor.providers.base import Usage

    total = Usage(cached_tokens=10, written_tokens=3).merge(
        Usage(cached_tokens=5, written_tokens=2))

    assert (total.cached_tokens, total.written_tokens) == (15, 5)


def test_caching_is_on_by_default_and_can_be_turned_off():
    from comodor.config import AgentConfig

    assert AgentConfig().prompt_cache is True
    assert AgentConfig().prompt_cache_ttl == "5m"


# --------------------------------------------------------------------------- #
# when the endpoint will not have it
# --------------------------------------------------------------------------- #


def test_an_endpoint_that_rejects_the_marks_loses_the_discount_not_the_answer():
    """Proxies and self-hosted gateways speak this protocol too, and one that
    does not know `cache_control` rejects the whole request."""
    body = body_for([Message.system("s" * BIG), Message.user("x" * BIG)])
    assert marks_in(body) >= 1

    assert caching.strip(body) is True
    assert marks_in(body) == 0
    assert isinstance(body["system"], str), "the system block should be plain again"


def test_stripping_a_request_that_was_never_marked_changes_nothing():
    body = {"system": "hello", "messages": []}
    assert caching.strip(body) is False
    assert body["system"] == "hello"


def test_only_a_complaint_about_the_marks_triggers_the_retry():
    assert caching.refused("invalid request: cache_control not supported")
    assert caching.refused("Unknown field: cache control")
    assert not caching.refused("model not found")
    assert not caching.refused("")


def test_the_longer_hour_asks_for_the_header_it_needs():
    """Requesting an hour without the opt-in header is a 400, not a downgrade."""
    provider = AnthropicProvider(api_key="x")
    body = {"system": "s" * BIG,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "x" * BIG}]}]}
    provider._cache(body, ttl="1h")

    assert provider._session.headers["anthropic-beta"] == caching.LONG_TTL_BETA


def test_the_default_five_minutes_asks_for_no_header():
    provider = AnthropicProvider(api_key="x")
    body = {"system": "s" * BIG,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "x" * BIG}]}]}
    provider._cache(body)

    assert "anthropic-beta" not in provider._session.headers


# --------------------------------------------------------------------------- #
# the floor, which is not the same for every model
# --------------------------------------------------------------------------- #


def test_the_real_head_of_a_real_request_is_cacheable():
    """The bug this test exists for: Comodor's own system prompt and tool
    schemas measure just over two thousand tokens. Rounding the floor up to the
    strictest model's 2048 does not cost a little caching at the margin — it
    declines to cache the one block that is identical for the whole session."""
    from comodor import config as config_module
    from comodor.agent.prompts import build_system_prompt
    from comodor.tools.registry import ToolRegistry

    specs = ToolRegistry().specs("act")
    provider = AnthropicProvider(api_key="x", model="claude-sonnet-5")
    body = {
        "system": build_system_prompt(config_module.load()),
        "tools": [spec.to_anthropic() for spec in specs],
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
    }
    provider._cache(body, model="claude-sonnet-5")

    assert isinstance(body["system"], list), \
        "the session-long prefix was left uncached"
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}


def test_the_small_models_want_twice_as_much_before_they_will_hold_it():
    assert caching.floor_for("claude-haiku-4-5") == caching.MIN_CACHEABLE_SMALL
    assert caching.floor_for("claude-sonnet-5") == caching.MIN_CACHEABLE
    assert caching.floor_for("claude-opus-5") == caching.MIN_CACHEABLE
    assert caching.floor_for("") == caching.MIN_CACHEABLE


def test_the_policy_never_counts_more_tokens_than_are_really_there():
    """`weigh` is deliberately generous with characters per token so that it
    errs towards fewer marks — a mark below the floor is silently ignored and
    the write premium is paid for nothing."""
    from comodor.agent.tokens import estimate_text

    text = "def function(value):\n    return value * 2\n" * 200

    assert caching.weigh(text) <= estimate_text(text)
