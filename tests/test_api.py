"""The OpenAI-compatible endpoint.

The tests here are the spec's acceptance list, translated: no token means
401 and that answer comes in constant time; a two-megabyte body means 413;
a turn the step cap stopped says so rather than hanging. Around them sit
the shape tests — the request mapping that must forgive the ecosystem's
variants, and the response that must be exact because a client parses it
with a schema, not with judgement.

The server is exercised over a real socket on the loopback where the
environment allows it, and against the handler's pieces directly where it
does not.
"""

from __future__ import annotations

import json

import pytest

from comodor.api import schema


@pytest.fixture
def config(tmp_path):
    from comodor.config import load

    return load(str(tmp_path))


# --------------------------------------------------------------------------- #
# mapping requests: the forgiving half
# --------------------------------------------------------------------------- #

def test_the_last_user_message_is_the_task():
    text, prior = schema.messages_from({"messages": [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "what changed?"},
        {"role": "assistant", "content": "the tests"},
        {"role": "user", "content": "summarise it"},
    ]})
    assert text == "summarise it"
    assert [(p["role"], p["text"]) for p in prior] == [
        ("system", "be brief"), ("user", "what changed?"),
        ("assistant", "the tests")]


def test_an_array_content_yields_its_text_and_names_its_images():
    text, _ = schema.messages_from({"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "what is this?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}},
        ]}]})
    assert "what is this?" in text
    assert "image" in text.lower()


def test_client_tool_traffic_is_refused_not_ignored():
    with pytest.raises(schema.BadRequest):
        schema.messages_from({"messages": [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "done"},
            {"role": "user", "content": "continue"},
        ]})


def test_a_request_without_a_user_message_is_a_bad_request():
    with pytest.raises(schema.BadRequest):
        schema.messages_from({"messages": [{"role": "system", "content": "hi"}]})
    with pytest.raises(schema.BadRequest):
        schema.messages_from({"messages": []})


# --------------------------------------------------------------------------- #
# the response shapes: the exact half
# --------------------------------------------------------------------------- #

def test_the_final_response_carries_the_answer_where_clients_read_it():
    out = schema.final(1000.0, "comodor", "chatcmpl-x", "It is done.",
                       {"prompt_tokens": 3, "completion_tokens": 5,
                        "total_tokens": 8}, "stop")
    choice = out["choices"][0]
    assert choice["message"]["content"] == "It is done."
    assert choice["finish_reason"] == "stop"
    assert out["object"] == "chat.completion"
    assert out["usage"]["total_tokens"] == 8


def test_the_stream_ends_with_done():
    chunks = [schema.chunk(1000.0, "comodor", "id", delta={"content": "hi"}),
              schema.chunk(1000.0, "comodor", "id", finish="stop")]
    assert all(c["object"] == "chat.completion.chunk" for c in chunks)
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_a_truncated_turn_is_length_not_stop():
    from comodor.api.server import _finish_reason

    assert _finish_reason({"stopped": "max_steps"}) == "length"
    assert _finish_reason({"stopped": "budget"}) == "length"
    assert _finish_reason({"stopped": "done"}) == "stop"


def test_a_long_answer_is_cut_on_structure_not_mid_word():
    from comodor.api.server import _pieces

    text = "word " * 200
    pieces = _pieces(text)
    assert "".join(pieces) == text
    assert all(len(p) <= 250 for p in pieces)
    # Nothing ends inside a word when a space was within reach.
    for piece in pieces[:-1]:
        assert piece.endswith((" ", "\n"))


def test_an_empty_answer_streams_without_pieces():
    from comodor.api.server import _pieces

    assert _pieces("") == []


# --------------------------------------------------------------------------- #
# the live server, where a socket may be bound
# --------------------------------------------------------------------------- #

@pytest.fixture
def server(config):
    from comodor.api.server import Server

    made = Server(config, host="127.0.0.1", port=0)
    try:
        made.bind()
    except PermissionError:
        pytest.skip("cannot bind a socket in this environment")
    yield made
    made.stop()
    made.map.close_all()


def _post(url: str, token: str, body: dict, *, headers: dict[str, str] | None = None,
          raw: bytes | None = None) -> tuple[int, dict | str]:
    import urllib.error
    import urllib.request

    sent = raw if raw is not None else json.dumps(body).encode("utf-8")
    head = {"Content-Type": "application/json", **(headers or {})}
    if token:
        head["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=sent, headers=head, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as problem:
        text = problem.read().decode("utf-8")
        try:
            return problem.code, json.loads(text)
        except ValueError:
            return problem.code, text


def _setup(config):
    """A provider the session can find, without ever calling it."""
    from comodor.config import ProviderConfig

    config.providers["fake"] = ProviderConfig(
        name="fake", kind="fake", base_url="offline", api_key="demo",
        model="comodor-demo", label="Demo (offline)", configured=True)
    config.provider = "fake"
    config.model = "comodor-demo"


def test_no_token_is_401(server):
    status, body = _post(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                         "", {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 401
    assert "error" in body


def test_a_wrong_token_is_401(server):
    status, body = _post(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                         "not-it", {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 401


def test_a_two_megabyte_body_is_413(server):
    status, body = _post(
        f"http://127.0.0.1:{server.port}/v1/chat/completions",
        server.token, {}, raw=b'{"messages":"' + b"x" * (2_000_000 + 64) + b'"}')
    assert status == 413


def test_an_invalid_json_body_is_400_not_a_crash(server):
    status, body = _post(
        f"http://127.0.0.1:{server.port}/v1/chat/completions",
        server.token, {}, raw=b"{not json")
    assert status == 400


def test_models_needs_the_token_too(server):
    import urllib.error
    import urllib.request

    base = f"http://127.0.0.1:{server.port}"
    try:
        urllib.request.urlopen(f"{base}/v1/models", timeout=5)
        raised = False
    except urllib.error.HTTPError as problem:
        raised = problem.code == 401
    assert raised, "a model list without auth is a footprint"


def test_models_lists_the_one_model(server):
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/v1/models",
        headers={"Authorization": f"Bearer {server.token}"})
    with urllib.request.urlopen(request, timeout=5) as answer:
        body = json.loads(answer.read().decode("utf-8"))
    assert body["data"][0]["id"] == schema.MODEL_ID


def test_one_request_is_one_answered_turn(server, monkeypatch):
    """A chat request runs the loop and returns its final answer."""
    _setup(server.config)

    class FakeResult:
        text = "The tests pass."
        steps = 2
        stopped = "done"
        ok = True

        class usage:
            prompt_tokens = 10
            output_tokens = 4
            total = 14

    class FakeTalk:
        id = "api-test"

        def run(self, text, prior=None, mode="", patience=600.0):
            assert text == "why do the tests fail?"
            return {"text": FakeResult.text, "steps": 2, "stopped": "done",
                    "result": FakeResult()}

    monkeypatch.setattr(server.map, "for_session", lambda presented: FakeTalk())
    status, body = _post(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                         server.token,
                         {"messages": [{"role": "user",
                                        "content": "why do the tests fail?"}]})
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "The tests pass."
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["comodor"]["session"] == "api-test"


def test_a_mode_request_is_passed_through(server, monkeypatch):
    _setup(server.config)
    seen = {}

    class FakeTalk:
        id = "api-test"

        def run(self, text, prior=None, mode="", patience=600.0):
            seen["mode"] = mode
            return {"text": "ok", "steps": 1, "stopped": "done",
                    "result": None}

    monkeypatch.setattr(server.map, "for_session", lambda presented: FakeTalk())
    status, body = _post(
        f"http://127.0.0.1:{server.port}/v1/chat/completions", server.token,
        {"messages": [{"role": "user", "content": "plan it"}],
         "comodor": {"mode": "plan"}})
    assert status == 200
    assert seen["mode"] == "plan"


def test_a_truncated_turn_says_length_and_names_the_cut(server, monkeypatch):
    _setup(server.config)

    class FakeTalk:
        id = "api-test"

        def run(self, text, prior=None, mode="", patience=600.0):
            return {"text": "partly done", "steps": 8, "stopped": "max_steps",
                    "result": None}

    monkeypatch.setattr(server.map, "for_session", lambda presented: FakeTalk())
    status, body = _post(f"http://127.0.0.1:{server.port}/v1/chat/completions",
                         server.token,
                         {"messages": [{"role": "user", "content": "go"}]})
    assert status == 200
    assert body["choices"][0]["finish_reason"] == "length"
    assert body["comodor"]["stopped"] == "max_steps"
    assert body["comodor"]["truncated"] is True


def test_streaming_speaks_sse_and_ends_with_done(server, monkeypatch):
    import urllib.request

    _setup(server.config)

    class FakeTalk:
        id = "api-test"

        def run(self, text, prior=None, mode="", patience=600.0):
            return {"text": "one two three", "steps": 1, "stopped": "done",
                    "result": None}

    monkeypatch.setattr(server.map, "for_session", lambda presented: FakeTalk())
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/v1/chat/completions",
        data=json.dumps({"messages": [{"role": "user", "content": "go"}],
                         "stream": True}).encode("utf-8"),
        headers={"Authorization": f"Bearer {server.token}",
                 "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as answer:
        wire = answer.read().decode("utf-8")

    frames = [line[6:] for line in wire.split("\n\n") if line.startswith("data: ")]
    assert frames[-1] == "[DONE]"
    parsed = [json.loads(frame) for frame in frames[:-1]]
    assert parsed[0]["choices"][0]["delta"].get("role") == "assistant"
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in parsed)
    assert text == "one two three"
    assert parsed[-1]["choices"][0]["finish_reason"] == "stop"


def test_the_session_header_continues_one_session(server, monkeypatch):
    _setup(server.config)
    asked: list[str] = []

    class FakeTalk:
        id = ""

        def run(self, text, prior=None, mode="", patience=600.0):
            return {"text": "ok", "steps": 1, "stopped": "done", "result": None}

    def watch(presented: str):
        asked.append(presented)
        talk = FakeTalk()
        talk.id = presented or "api-new"
        return talk

    monkeypatch.setattr(server.map, "for_session", watch)
    body = {"messages": [{"role": "user", "content": "hi"}]}
    _post(f"http://127.0.0.1:{server.port}/v1/chat/completions",
          server.token, body, headers={"X-Comodor-Session": "sess-7"})
    assert asked == ["sess-7"], "the presented id names the session"


def test_the_configured_step_cap_applies_when_the_user_set_none(config):
    from comodor.api.server import Server

    Server(config, host="127.0.0.1", port=0)
    assert config.agent.max_steps == config.api.max_turns, \
        "an unlimited loop behind a chat client would outlive its timeout"


def test_a_user_step_cap_is_not_overridden(config):
    from comodor.api.server import Server

    config.agent.max_steps = 40
    Server(config, host="127.0.0.1", port=0)
    assert config.agent.max_steps == 40
