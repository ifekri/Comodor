"""Wire formats: SSE framing, message encoding, gateway routing, token counting."""

from __future__ import annotations

import pytest

from comodor.agent.context import Conversation
from comodor.agent.tokens import TokenCounter, estimate_text, humanise
from comodor.config import ProviderConfig
from comodor.net.sse import iter_sse
from comodor.providers.anthropic import AnthropicProvider
from comodor.providers.base import (
    AuthError,
    EventType,
    Message,
    ProviderError,
    Role,
    ToolCall,
    collapse,
    parse_arguments,
)
from comodor.providers.fake import FakeProvider, Script
from comodor.providers.gateway import Gateway
from comodor.providers.openai_compat import OpenAICompatProvider
from comodor.providers.registry import estimate_cost, lookup, supports_sampling

# --------------------------------------------------------------------------- #
# SSE
# --------------------------------------------------------------------------- #


class FakeResponse:
    """The slice of the HTTP response the SSE reader actually uses."""

    def __init__(self, body: str, chunk: int = 7) -> None:
        self.body = body
        self.chunk = chunk

    def iter_lines(self, chunk_size=8192, decode_unicode=True):
        # Deliberately yields the same lines a real chunked read would produce.
        for line in self.body.split("\n"):
            yield line


def test_sse_frames_are_dispatched_on_blank_lines():
    body = 'data: {"a": 1}\n\ndata: {"b": 2}\n\n'
    frames = list(iter_sse(FakeResponse(body)))
    assert [frame.json() for frame in frames] == [{"a": 1}, {"b": 2}]


def test_sse_stops_at_the_done_sentinel():
    body = 'data: {"a": 1}\n\ndata: [DONE]\n\ndata: {"never": true}\n\n'
    frames = list(iter_sse(FakeResponse(body)))
    assert len(frames) == 2
    assert frames[-1].is_done


def test_sse_joins_multi_line_data_and_reads_event_names():
    body = "event: ping\ndata: line one\ndata: line two\n\n"
    frame = next(iter(iter_sse(FakeResponse(body))))
    assert frame.event == "ping"
    assert frame.data == "line one\nline two"


def test_sse_ignores_comments_and_keepalives():
    body = ': keep-alive\n\ndata: {"a": 1}\n\n'
    frames = [frame for frame in iter_sse(FakeResponse(body)) if frame.data]
    assert [frame.json() for frame in frames] == [{"a": 1}]


def test_sse_survives_a_malformed_payload():
    body = "data: not json at all\n\n"
    frame = next(iter(iter_sse(FakeResponse(body))))
    assert frame.json() is None          # skipped, not raised


def test_sse_emits_a_final_frame_without_a_trailing_blank_line():
    frames = list(iter_sse(FakeResponse('data: {"a": 1}')))
    assert [frame.json() for frame in frames] == [{"a": 1}]


# --------------------------------------------------------------------------- #
# argument decoding
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("raw,expected", [
    ('{"path": "a.py"}', {"path": "a.py"}),
    ("", {}),
    ('{"path": "a.py",', {"path": "a.py"}),          # unterminated fragment
    ('{"a": 1},', {"a": 1}),                          # trailing comma
    ('"bare string"', {"value": "bare string"}),
])
def test_tool_arguments_are_decoded_defensively(raw, expected):
    assert parse_arguments(raw) == expected


def test_undecodable_arguments_are_handed_back_for_the_model_to_fix():
    assert parse_arguments("<<<garbage>>>") == {"__raw__": "<<<garbage>>>"}


# --------------------------------------------------------------------------- #
# OpenAI-compatible encoding
# --------------------------------------------------------------------------- #


def openai_provider() -> OpenAICompatProvider:
    return OpenAICompatProvider("test", "https://example.invalid/v1", api_key="k",
                                model="m")


def test_openai_encodes_tool_calls_and_results():
    provider = openai_provider()
    encoded = provider._encode_messages([
        Message.system("be helpful"),
        Message.user("hi"),
        Message.assistant("calling", [ToolCall(id="c1", name="read_file",
                                               arguments={"path": "a.py"})]),
        Message.tool("c1", "read_file", "contents"),
    ])

    assert encoded[0]["role"] == "system"
    assert encoded[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert encoded[2]["content"] == "calling"        # never null alongside tool calls
    assert encoded[3] == {"role": "tool", "tool_call_id": "c1", "content": "contents"}


def test_openai_encodes_images_as_content_blocks():
    provider = openai_provider()
    encoded = provider._encode_messages([Message.user("what is this?", images=["QUJD"])])
    blocks = encoded[0]["content"]
    assert blocks[0]["type"] == "text"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_streamed_tool_call_fragments_are_reassembled():
    """Arguments arrive split across chunks and addressed by index, not id."""
    provider = openai_provider()
    chunks = [
        '{"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1",'
        '"function":{"name":"edit_file","arguments":"{\\"path\\":"}}]}}]}',
        '{"choices":[{"delta":{"tool_calls":[{"index":0,'
        '"function":{"arguments":"\\"a.py\\"}"}}]}}]}',
        '{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
    ]
    body = "".join(f"data: {chunk}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    events = list(provider._parse_stream(FakeResponse(body), "m"))
    calls = [event.tool_call for event in events if event.type is EventType.TOOL_CALL]

    assert len(calls) == 1
    assert calls[0].name == "edit_file"
    assert calls[0].arguments == {"path": "a.py"}


def test_streamed_text_and_reasoning_are_separated():
    provider = openai_provider()
    body = (
        'data: {"choices":[{"delta":{"reasoning":"thinking hard"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"the answer"}}]}\n\n'
        'data: {"usage":{"prompt_tokens":10,"completion_tokens":4}}\n\n'
        "data: [DONE]\n\n"
    )
    events = list(provider._parse_stream(FakeResponse(body), "m"))
    completion = collapse(iter(events))

    assert completion.text == "the answer"
    assert completion.reasoning == "thinking hard"
    assert completion.usage.input_tokens == 10


def test_a_mid_stream_error_frame_raises():
    provider = openai_provider()
    body = 'data: {"error":{"message":"context length exceeded"}}\n\n'
    with pytest.raises(ProviderError, match="context length"):
        list(provider._parse_stream(FakeResponse(body), "m"))


# --------------------------------------------------------------------------- #
# Anthropic encoding
# --------------------------------------------------------------------------- #


def anthropic_provider() -> AnthropicProvider:
    return AnthropicProvider(api_key="k", model="claude-sonnet-4-5")


def test_anthropic_lifts_the_system_prompt_out_of_the_messages():
    system, messages = anthropic_provider()._encode([
        Message.system("first rule"),
        Message.system("second rule"),
        Message.user("hi"),
    ])
    assert system == "first rule\n\nsecond rule"
    assert [message["role"] for message in messages] == ["user"]


def test_anthropic_puts_parallel_tool_results_in_one_user_message():
    """Splitting them teaches the model to stop calling tools in parallel."""
    _, messages = anthropic_provider()._encode([
        Message.user("go"),
        Message.assistant("working", [
            ToolCall(id="c1", name="read_file", arguments={"path": "a"}),
            ToolCall(id="c2", name="read_file", arguments={"path": "b"}),
        ]),
        Message.tool("c1", "read_file", "one"),
        Message.tool("c2", "read_file", "two"),
    ])

    assert len(messages) == 3
    results = messages[2]["content"]
    assert [block["type"] for block in results] == ["tool_result", "tool_result"]
    assert [block["tool_use_id"] for block in results] == ["c1", "c2"]


def test_anthropic_marks_failed_tool_results():
    _, messages = anthropic_provider()._encode([
        Message.user("go"),
        Message.tool("c1", "read_file", "boom", is_error=True),
    ])
    assert messages[-1]["content"][0]["is_error"] is True


def test_anthropic_stream_events_are_translated():
    provider = anthropic_provider()
    body = (
        'event: message_start\ndata: {"type":"message_start","message":'
        '{"usage":{"input_tokens":25}}}\n\n'
        'data: {"type":"content_block_start","index":0,'
        '"content_block":{"type":"text"}}\n\n'
        'data: {"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"hello"}}\n\n'
        'data: {"type":"content_block_start","index":1,"content_block":'
        '{"type":"tool_use","id":"tu_1","name":"read_file"}}\n\n'
        'data: {"type":"content_block_delta","index":1,'
        '"delta":{"type":"input_json_delta","partial_json":"{\\"path\\":\\"a.py\\"}"}}\n\n'
        'data: {"type":"content_block_stop","index":1}\n\n'
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
        '"usage":{"output_tokens":12}}\n\n'
        'data: {"type":"message_stop"}\n\n'
    )
    completion = collapse(provider._parse_stream(FakeResponse(body), "claude-sonnet-4-5"))

    assert completion.text == "hello"
    assert completion.tool_calls[0].name == "read_file"
    assert completion.tool_calls[0].arguments == {"path": "a.py"}
    assert completion.usage.input_tokens == 25
    assert completion.usage.output_tokens == 12
    assert completion.finish_reason == "tool_use"


def test_sampling_is_omitted_for_models_that_reject_it():
    # Claude 4.6+ removed temperature; sending it is a 400.
    assert not supports_sampling("claude-opus-5")
    assert not supports_sampling("anthropic/claude-fable-5")
    assert supports_sampling("claude-sonnet-4-5")
    assert supports_sampling("gpt-4o")


# --------------------------------------------------------------------------- #
# pricing
# --------------------------------------------------------------------------- #


def test_known_models_price_correctly():
    assert estimate_cost("claude-opus-5", 1_000_000, 1_000_000) == pytest.approx(30.0)
    assert lookup("claude-haiku-4-5").context == 200_000


def test_an_unknown_price_reports_nothing_rather_than_zero():
    """A wrong cost readout is worse than no cost readout."""
    assert estimate_cost("some-new-model", 1000, 1000) is None


def test_provider_prefixes_resolve_to_the_base_model():
    assert lookup("anthropic/claude-opus-5").context == 1_000_000


# --------------------------------------------------------------------------- #
# gateway
# --------------------------------------------------------------------------- #


def make_config_with(config, names: list[str]):
    for name in names:
        config.providers[name] = ProviderConfig(
            name=name, kind="fake", base_url="offline", api_key="k",
            model=f"{name}-model")
    return config


def test_gateway_disabled_pins_the_chosen_provider(config):
    make_config_with(config, ["alpha", "beta"])
    config.provider = "alpha"
    gateway = Gateway(config)

    assert gateway.candidates() == ["alpha"]
    assert gateway.describe() == "Disable"


def test_gateway_enabled_builds_a_failover_chain(config):
    make_config_with(config, ["alpha", "beta"])
    config.provider = "alpha"
    config.gateway.enabled = True
    gateway = Gateway(config)

    chain = gateway.candidates()
    assert chain[0] == "alpha"
    assert "beta" in chain


def test_gateway_fails_over_before_the_first_token(config):
    config.gateway.enabled = True
    config.providers["broken"] = ProviderConfig(name="broken", kind="fake",
                                                base_url="offline", api_key="k",
                                                model="broken-1")
    config.provider = "broken"
    config.gateway.chain = ["broken", "fake"]

    gateway = Gateway(config)
    gateway._instances["broken"] = FakeProvider([Script(error="upstream down")])
    gateway._instances["fake"] = FakeProvider([Script(text="rescued")])

    completion = collapse(gateway.stream([Message.user("hi")]))
    assert completion.text == "rescued"
    assert gateway.last_route.provider == "fake"
    assert gateway.last_route.failed_over_from == ["broken"]


def test_gateway_never_replays_a_stream_that_already_produced_output(config):
    """Retrying elsewhere would duplicate half an answer and bill it twice."""
    config.gateway.enabled = True
    config.providers["broken"] = ProviderConfig(name="broken", kind="fake",
                                                base_url="offline", api_key="k",
                                                model="broken-1")
    config.provider = "broken"
    config.gateway.chain = ["broken", "fake"]

    gateway = Gateway(config)
    gateway._instances["broken"] = FakeProvider(
        [Script(text="a partial answer that then breaks",
                 error="died mid-stream", error_after=1)])
    gateway._instances["fake"] = FakeProvider([Script(text="should not be reached")])

    with pytest.raises(ProviderError):
        list(gateway.stream([Message.user("hi")]))


def test_an_auth_failure_is_not_retried_anywhere(config):

    class Unauthorised:
        name = "bad"
        model = "x"

        def stream(self, *args, **kwargs):
            raise AuthError("invalid key", provider="bad")
            yield

        def list_models(self):
            return []

    config.gateway.enabled = True
    config.providers["bad"] = ProviderConfig(name="bad", kind="fake",
                                             base_url="offline", api_key="k", model="x")
    config.provider = "bad"
    config.gateway.chain = ["bad", "fake"]

    gateway = Gateway(config)
    gateway._instances["bad"] = Unauthorised()
    gateway._instances["fake"] = FakeProvider([Script(text="never reached")])

    with pytest.raises(AuthError):
        list(gateway.stream([Message.user("hi")]))


def test_health_tracking_trips_a_failing_provider(config):
    gateway = Gateway(config)
    health = gateway.health("fake")
    for _ in range(3):
        health.record_failure("boom", cooldown=60.0, threshold=3)

    assert not health.available
    health.record_success(0.4)
    assert health.available


# --------------------------------------------------------------------------- #
# token accounting
# --------------------------------------------------------------------------- #


def test_estimates_scale_with_content():
    assert estimate_text("") == 0
    assert estimate_text("hello world") < estimate_text("hello world " * 10)
    # Code tokenises worse than prose, so the same length costs more.
    prose = "the quick brown fox jumps over the lazy dog again and again"
    code = "x=[{'a':1},{'b':2}];y=(x[0]['a']+x[1]['b'])*3;print(y);#comment"
    assert estimate_text(code) > estimate_text(prose)


def test_cjk_is_counted_near_one_token_per_character():
    text = "これは日本語のテキストです"
    assert estimate_text(text) >= len(text)


def test_calibration_learns_from_real_usage():
    counter = TokenCounter()
    messages = [Message.user("hello there, this is a message of some length")]
    before = counter.count(messages)

    for _ in range(5):
        counter.observe_usage(messages, None, actual_input_tokens=before * 2)

    assert counter.count(messages) > before
    assert counter.calibration.confident


def test_calibration_ignores_outliers_from_cached_prefixes():
    counter = TokenCounter()
    messages = [Message.user("a message")]
    baseline = counter.count(messages)

    counter.observe_usage(messages, None, actual_input_tokens=1)     # cache hit
    assert counter.count(messages) == baseline


@pytest.mark.parametrize("count,expected", [
    (0, "0"), (999, "999"), (1500, "2K"), (143_000, "143K"), (1_000_000, "1M"),
    (1_200_000, "1.2M"),
])
def test_humanised_counts(count, expected):
    assert humanise(count) == expected


# --------------------------------------------------------------------------- #
# compaction
# --------------------------------------------------------------------------- #


def test_compaction_never_splits_a_tool_call_from_its_result():
    conversation = Conversation()
    conversation.extend([
        Message.user("first request"),
        Message.assistant("working", [ToolCall(id="c1", name="read_file")]),
        Message.tool("c1", "read_file", "data"),
        Message.assistant("done"),
        Message.user("second request"),
        Message.assistant("working", [ToolCall(id="c2", name="read_file")]),
        Message.tool("c2", "read_file", "data"),
        Message.assistant("done"),
        Message.user("third request"),
        Message.assistant("done"),
    ])

    cut = conversation.safe_cut(keep_recent=2)
    assert cut > 0
    assert conversation.messages[cut].role is Role.USER

    pending = set()
    for message in conversation.messages[:cut]:
        if message.role is Role.ASSISTANT:
            pending.update(call.id for call in message.tool_calls)
        elif message.role is Role.TOOL:
            pending.discard(message.tool_call_id)
    assert not pending, "a summarised section left a tool call without its result"


def test_compaction_keeps_the_original_request_verbatim():
    conversation = Conversation()
    conversation.extend([Message.user("the original goal")]
                        + [Message.user(f"turn {i}") for i in range(12)])

    removed = conversation.compact(lambda messages: "a summary of the middle",
                                   keep_recent=3)

    assert removed > 0
    assert conversation.messages[0].content == "the original goal"
    assert "a summary of the middle" in conversation.messages[1].content
    assert conversation.compactions == 1


def test_a_failed_summary_leaves_the_conversation_intact():
    conversation = Conversation()
    conversation.extend([Message.user(f"turn {i}") for i in range(12)])
    before = list(conversation.messages)

    def broken(messages):
        raise RuntimeError("the summariser is down")

    assert conversation.compact(broken) == 0
    assert conversation.messages == before


# --------------------------------------------------------------------------- #
# saying who is calling
# --------------------------------------------------------------------------- #


def test_openrouter_is_told_which_application_is_calling():
    """OpenRouter attributes a request to an app by these two headers and shows
    it on its model pages and leaderboards. The icon beside the name is the
    favicon of the referer, which is why that is the site and not the repo."""
    from comodor import catalogue

    headers = catalogue.get("openrouter").headers

    assert headers["HTTP-Referer"] == catalogue.SITE
    assert headers["X-Title"] == catalogue.APP_NAME
    assert catalogue.SITE.startswith("https://")


def test_the_attribution_survives_into_the_provider_entry(config):
    """Three places it could be lost between the catalogue and the socket, and
    none of them raises if it is."""
    from comodor import catalogue
    from comodor.config import provider_from_spec

    entry = provider_from_spec(catalogue.get("openrouter"))

    assert entry.headers["X-Title"] == "Comodor"


def test_the_user_agent_says_comodor():
    """This client is API-compatible with `requests` and was naming itself as
    `requests` because of it — a statement about a library nobody is using,
    made to every provider on every request."""
    from comodor.net.http import DEFAULT_USER_AGENT

    assert DEFAULT_USER_AGENT.startswith("Comodor/")
    assert "comodor.ai" in DEFAULT_USER_AGENT
    assert "requests/" not in DEFAULT_USER_AGENT
