"""The wire contract, and the handshake that gates it.

These are the tests a second implementation of the client would be written
against. They drive the server through in-memory streams rather than a
subprocess, so they are fast and deterministic; `test_core_stdio.py` proves
the same thing survives a real pipe.
"""

from __future__ import annotations

import io
import json

import pytest

from comodor import protocol as P
from comodor.application import CoreService, Refused
from comodor.transport.jsonl import Channel
from comodor.transport.server import Server


class Driver:
    """Feeds lines to a server and collects what comes back."""

    def __init__(self, service: CoreService, lines: list[dict]) -> None:
        text = "\n".join(json.dumps(line) for line in lines)
        self.out = io.StringIO()
        self.log = io.StringIO()
        self.channel = Channel(reader=io.StringIO(text + "\n"),
                               writer=self.out, log=self.log)
        self.server = Server(service, self.channel)

    def run(self) -> list[dict]:
        self.server.serve()
        return [json.loads(row) for row in self.out.getvalue().splitlines()]


def hello(id: str = "h", version: int = P.PROTOCOL_VERSION,
          capabilities: list[str] | None = None) -> dict:
    return {"version": P.PROTOCOL_VERSION, "type": "request", "id": id,
            "method": "client.hello",
            "params": {"protocol_version": version,
                       "client": {"name": "test-client", "version": "0.1"},
                       "capabilities": capabilities
                       if capabilities is not None else ["questions"]}}


def call(id: str, method: str, params: dict | None = None) -> dict:
    return {"version": P.PROTOCOL_VERSION, "type": "request", "id": id,
            "method": method, "params": params or {}}


@pytest.fixture
def service(config):
    made = CoreService(config)
    yield made
    made.close()


# --------------------------------------------------------------------------- #
# the handshake
# --------------------------------------------------------------------------- #

def test_the_handshake_answers_with_a_version_and_what_the_core_can_do(service):
    answers = Driver(service, [hello()]).run()

    assert len(answers) == 1
    result = answers[0]["result"]
    assert result["protocol_version"] == P.PROTOCOL_VERSION
    assert result["core"]["name"] == "comodor-core"
    # A client must be able to tell streaming from no streaming before it
    # decides how to render, not after the first delta fails to arrive.
    assert "streaming" in result["capabilities"]
    assert "questions" in result["capabilities"]


def test_nothing_else_is_accepted_before_the_handshake(service):
    answers = Driver(service, [call("1", "session.list")]).run()

    assert answers[0]["type"] == "error"
    assert answers[0]["error"]["code"] == P.NOT_INITIALIZED


def test_a_version_this_core_does_not_speak_is_refused_at_the_first_message(service):
    answers = Driver(service, [hello(version=99), call("1", "session.list")]).run()

    assert answers[0]["error"]["code"] == P.UNSUPPORTED_VERSION
    # And it stays refused: a client that ignores the refusal does not get to
    # proceed, which is the whole point of failing at the handshake rather
    # than at whatever message first goes wrong.
    assert answers[1]["error"]["code"] == P.NOT_INITIALIZED


def test_the_refusal_says_which_versions_would_work(service):
    answers = Driver(service, [hello(version=99)]).run()

    assert answers[0]["error"]["data"]["supported"] == [P.PROTOCOL_VERSION]


def test_saying_hello_twice_is_an_error(service):
    answers = Driver(service, [hello("a"), hello("b")]).run()

    assert answers[0]["type"] == "response"
    assert answers[1]["error"]["code"] == P.ALREADY_INITIALIZED


def test_a_capability_this_core_has_never_heard_of_is_ignored_not_refused(service):
    # Forward compatibility: a newer client announcing something unknown must
    # still connect, or every core release breaks every older client.
    answers = Driver(service, [hello(capabilities=["questions", "telepathy"])]).run()

    assert answers[0]["type"] == "response"


def test_a_handshake_with_no_client_name_is_invalid(service):
    broken = {"version": P.PROTOCOL_VERSION, "type": "request", "id": "1",
              "method": "client.hello",
              "params": {"protocol_version": P.PROTOCOL_VERSION}}
    answers = Driver(service, [broken]).run()

    assert answers[0]["error"]["code"] == P.INVALID_PARAMS


# --------------------------------------------------------------------------- #
# envelopes
# --------------------------------------------------------------------------- #

def test_every_answer_carries_the_id_it_was_asked_with(service):
    answers = Driver(service, [hello("first"),
                               call("second", "workspace.get"),
                               call("third", "model.get")]).run()

    assert [answer["id"] for answer in answers] == ["first", "second", "third"]


def test_a_line_that_is_not_json_is_answered_without_an_id(service):
    driver = Driver(service, [hello()])
    driver.channel.reader = io.StringIO('{"unclosed"\n')
    answers = driver.run()

    assert answers[0]["error"]["code"] == P.PARSE_ERROR
    # `null` rather than a made-up id: the line could not be read far enough
    # to have one, and inventing one would correlate the error to nothing.
    assert answers[0]["id"] is None


def test_a_blank_line_is_not_an_error(service):
    driver = Driver(service, [hello()])
    driver.channel.reader = io.StringIO("\n\n" + json.dumps(hello()) + "\n\n")
    answers = driver.run()

    assert len(answers) == 1
    assert answers[0]["type"] == "response"


def test_an_unknown_method_is_named_in_the_refusal(service):
    answers = Driver(service, [hello(), call("1", "session.teleport")]).run()

    assert answers[1]["error"]["code"] == P.UNKNOWN_METHOD
    assert "session.teleport" in answers[1]["error"]["message"]


def test_a_method_with_the_wrong_parameters_says_which_field(service):
    answers = Driver(service, [hello(), call("1", "session.send",
                                             {"session_id": "x"})]).run()

    assert answers[1]["error"]["code"] == P.INVALID_PARAMS
    assert "text" in answers[1]["error"]["message"]


def test_a_core_refuses_to_be_sent_a_response(service):
    # A core answers requests. Something sending it a response has the two
    # ends confused, and dropping it silently would hide that.
    stray = {"version": P.PROTOCOL_VERSION, "type": "response", "id": "1",
             "result": {}}
    answers = Driver(service, [hello(), stray]).run()

    assert answers[1]["error"]["code"] == P.INVALID_ENVELOPE


def test_an_unknown_session_is_its_own_error_code(service):
    answers = Driver(service, [hello(),
                               call("1", "session.get", {"session_id": "nope"})]).run()

    assert answers[1]["error"]["code"] == P.UNKNOWN_SESSION


# --------------------------------------------------------------------------- #
# sessions
# --------------------------------------------------------------------------- #

def test_a_session_is_created_read_back_and_listed_the_same_way(service):
    # One connection, because a closed pipe ends the sessions it opened — see
    # the test below. Reading a session back has to describe it identically or
    # a client cannot tell a resync from a change.
    answers = Driver(service, [
        hello(),
        call("1", "session.create"),
        call("2", "session.list"),
    ]).run()
    created = _by_id(answers, "1")["result"]["session"]
    listed = _by_id(answers, "2")["result"]["sessions"]

    assert listed == [created]


def test_reading_a_session_back_describes_it_identically(service):
    answers = Driver(service, [hello(), call("1", "session.create")]).run()
    created = _by_id(answers, "1")["result"]["session"]

    # A fresh connection to the same service is a fresh core: `serve` closing
    # is what ends the sessions, so this reads it back within the connection.
    again = Driver(CoreService(service._config), [
        hello(), call("1", "session.create"),
        call("2", "session.get", {"session_id": ""}),
    ])
    made = again.run()
    session = _by_id(made, "1")["result"]["session"]
    assert set(session) == set(created)


def test_closing_the_pipe_ends_the_sessions_that_connection_opened(service):
    Driver(service, [hello(), call("1", "session.create")]).run()

    # Not a leak of one process into the next: a stdio core belongs to the
    # client that spawned it, and the client going away is the end of it.
    assert service.list_sessions() == []


def test_a_session_is_announced_after_the_answer_that_created_it(service):
    answers = Driver(service, [hello(), call("1", "session.create")]).run()

    kinds = [(a["type"], a.get("event") or a.get("id")) for a in answers]
    assert kinds == [("response", "h"), ("response", "1"),
                     ("event", "session.created")]
    assert answers[2]["params"]["session"]["mode"] == "act"


def _by_id(answers: list[dict], id: str) -> dict:
    for answer in answers:
        if answer.get("id") == id:
            return answer
    raise AssertionError(f"nothing answered {id!r}: {answers}")


def test_a_workspace_that_does_not_exist_is_refused(service):
    answers = Driver(service, [hello(), call("1", "session.create",
                                             {"workspace": "/no/such/place"})]).run()

    assert answers[1]["error"]["code"] == P.NOT_ALLOWED


def test_shutdown_is_answered_before_the_pipe_closes(service):
    answers = Driver(service, [hello(), call("1", "shutdown"),
                               call("2", "session.list")]).run()

    assert answers[1]["result"] == {"ok": True}
    # Nothing after it: the core stopped reading rather than answering one
    # more message on its way out.
    assert len(answers) == 2


# --------------------------------------------------------------------------- #
# what a client is never told
# --------------------------------------------------------------------------- #

def test_the_model_is_named_without_its_key(service, config):
    config.providers["fake"].api_key = "sk-do-not-leak-this"
    answers = Driver(service, [hello(), call("1", "model.get")]).run()
    result = answers[1]["result"]

    assert result["provider"] == "fake"
    assert result["configured"] is True
    assert "sk-do-not-leak-this" not in json.dumps(answers)


def test_an_unconfigured_provider_is_reported_as_such(service, config):
    config.providers["fake"].api_key = ""
    answers = Driver(service, [hello(), call("1", "model.get")]).run()

    assert answers[1]["result"]["configured"] is False


def test_choosing_a_provider_that_is_not_configured_is_refused(service):
    answers = Driver(service, [hello(), call("1", "model.set",
                                            {"model": "x", "provider": "ghost"})]).run()

    assert answers[1]["error"]["code"] == P.NOT_ALLOWED


# --------------------------------------------------------------------------- #
# the module itself
# --------------------------------------------------------------------------- #

def test_an_event_name_the_schema_does_not_have_is_refused_at_the_source():
    # Otherwise a typo is invisible: the client never receives the event and
    # the core looks like it stopped.
    with pytest.raises(ValueError):
        P.event("message.startd", {})


def test_validate_rejects_a_boolean_where_a_number_belongs():
    # `bool` is an `int` in Python, so a naive isinstance check stores `True`
    # as a count and nothing complains until the arithmetic looks wrong.
    with pytest.raises(P.ProtocolError):
        P.validate("ToolCompleted", {"session_id": "s", "call_id": "c",
                                     "elapsed_ms": True})


def test_every_method_in_the_schema_has_a_handler(service):
    # A method the schema advertises and the server cannot dispatch is a
    # promise the core does not keep.
    server = Server(service, Channel(io.StringIO(), io.StringIO(), io.StringIO()))
    handled = set(server._handlers()) | {"client.hello"}

    assert handled == set(P.METHODS)


def test_every_event_the_schema_names_has_a_shape():
    for name in P.EVENTS:
        assert P.event_shape(name) in P._generated.SHAPES


# --------------------------------------------------------------------------- #
# what a turn may not overtake
# --------------------------------------------------------------------------- #

def test_a_turn_cannot_stream_before_its_own_acceptance(config):
    """The acceptance names the message id every delta will carry.

    The turn runs on its own thread, and the transport only holds events
    raised on the thread answering a request — so without a barrier a fast
    provider could emit `message.started` before `session.send` returned. A
    client correlating on `message_id` would see a stream begin for a turn it
    had not been told about; one that subscribes after the response would drop
    the opening of every fast answer.
    """
    import time

    from comodor.providers.fake import FakeProvider, Script

    class Slow(Server):
        """Widens the window between dispatching and writing the answer.

        The race is real and narrow: `send` returns, and the answer is written
        a few instructions later. In an ordinary run the worker thread has not
        been scheduled yet, so a test without this passes whether the barrier
        is there or not — which is worse than no test, because it reports the
        guarantee as held.
        """

        def _answer(self, message):
            answer = super()._answer(message)
            if message.method == "session.send":
                time.sleep(0.25)
            return answer

    service = CoreService(config)
    try:
        # Made directly, because `serve` returning closes the sessions that
        # connection opened — so creating it through a first Driver would
        # leave nothing to send to.
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.gateway._instances["fake"] = FakeProvider(
            [Script(text="an answer that arrives immediately")])

        out = io.StringIO()
        lines = "\n".join(json.dumps(line) for line in [
            hello(),
            call("2", "session.send", {"session_id": session, "text": "go"}),
        ])
        channel = Channel(reader=io.StringIO(lines + "\n"), writer=out,
                          log=io.StringIO())
        server = Slow(service, channel)
        server.serve()

        transcript = [json.loads(row) for row in out.getvalue().splitlines()]
        order = [entry.get("event") or f"answer:{entry.get('id')}"
                 for entry in transcript]

        accepted = order.index("answer:2")
        streamed = [index for index, name in enumerate(order)
                    if str(name).startswith("message.")]
        assert streamed, "nothing streamed, so the ordering was not exercised"
        assert min(streamed) > accepted, (
            f"a message event preceded its acceptance: {order}")
    finally:
        service.close()


def test_closing_the_core_closes_what_each_session_was_holding(config):
    """Not just the bus.

    The learning engine flushes on close, so leaving assemblies to process
    teardown lost whatever the last turn had learned on every ordinary exit —
    silently, because nothing reports it.
    """
    closed: list[str] = []

    class Watched:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def close(self):
            closed.append("assembly")
            self._real.close()

    from comodor.application import assemble as real_assemble

    service = CoreService(config,
                          assemble_with=lambda cfg, **kw: Watched(
                              real_assemble(cfg, **kw)))
    service.create_session()
    service.close()

    assert closed == ["assembly"]


def test_a_local_provider_with_no_key_is_reported_as_configured(config):
    """A model on this machine has no key by design.

    Reading credential presence alone told a client to send somebody to set up
    a provider that was already working.
    """
    from comodor.config import ProviderConfig

    config.providers["ollama"] = ProviderConfig(
        name="ollama", kind="openai", base_url="http://localhost:11434/v1",
        api_key="", model="qwen3:8b", label="Ollama")
    config.provider = "ollama"
    config.model = "qwen3:8b"

    service = CoreService(config)
    try:
        assert service.model()["configured"] is True
    finally:
        service.close()


def test_a_session_that_is_already_working_refuses_a_second_turn(config):
    """One turn per session, refused rather than queued.

    Two turns interleaving their events would be indistinguishable to a client
    correlating on a message id.

    In-process and gated, because the obvious version of this test is a race:
    over a real pipe with a scripted provider the first turn can finish before
    the second request arrives, and then there is nothing to refuse. That is
    how it was written first, and macOS found it — passing on three platforms
    and failing on the fourth is the worst possible result, because it reads
    as an infrastructure problem rather than as a test that proves nothing.
    """
    import threading

    from comodor.providers.base import EventType, StreamEvent, Usage

    held = threading.Event()
    started = threading.Event()

    class Blocking:
        """Answers only once the test says so."""

        name = "fake"
        label = "Blocking"
        model = "fake-1"

        def stream(self, messages, **kwargs):
            started.set()
            held.wait(timeout=10)
            yield StreamEvent(type=EventType.TEXT, text="done")
            yield StreamEvent(type=EventType.USAGE, usage=Usage())

        def close(self):
            pass

    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.gateway._instances["fake"] = Blocking()

        service.send(session, "one")
        service.release()
        assert started.wait(timeout=10), "the first turn never began"

        with pytest.raises(Refused):
            service.send(session, "two")

        assert service.get_session(session)["busy"] is True
    finally:
        held.set()
        service.close()
