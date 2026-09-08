"""A form, from the tool that asks it to the answer the model reads.

These exist because the first version of this adapter was wrong in both
directions and nothing failed: it built the event from a field the `ask` tool
deliberately leaves empty, so every form reached the client with no questions
in it, and it sent the answer back as a comma-joined sentence, which
`decode_answers` reads as a cancellation. A person filled in a form and the
model was told they had declined.

Neither end raised. That is why these tests go through the real tool rather
than through a `Request` built to fit.
"""

from __future__ import annotations

import json
import threading

import pytest

from comodor import questions as forms
from comodor.application import CoreService
from comodor.events import Kind
from comodor.tools.ask import Ask


@pytest.fixture
def service(config):
    made = CoreService(config)
    yield made
    made.close()


def a_form():
    return [
        {"header": "approach", "prompt": "Which approach?",
         "options": [{"label": "Refactor"}, {"label": "Replace"},
                     {"label": "Keep"}]},
        {"header": "when", "prompt": "When?", "multi": True,
         "options": [{"label": "Now"}, {"label": "After the release"}]},
    ]


def ask_in_the_background(service, session_id, questions):
    """Run the real `Ask` tool on a thread and return what it produced."""
    handle = service.session(session_id)
    result: dict = {}

    def work():
        from comodor.events import Cancellation
        from comodor.safety import CheckpointStore, Redactor
        from comodor.tools.base import ToolContext

        context = ToolContext(
            config=handle.assembly.config,
            permissions=handle.assembly.permissions,
            checkpoints=CheckpointStore(handle.assembly.config.paths.checkpoints),
            bus=handle.assembly.bus,
            redact=Redactor([]),
            cancel=Cancellation(),
            cwd=handle.assembly.config.paths.project,
        )
        result["tool"] = Ask().run(context, questions=questions)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    return worker, result


def test_a_form_reaches_the_client_with_its_questions_in_it(service):
    seen: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        seen.append(params) if name == "question.requested" else None)
    session = service.create_session()["id"]

    worker, result = ask_in_the_background(service, session, a_form())
    _wait_for(lambda: seen)

    event = seen[0]
    assert [q["header"] for q in event["questions"]] == ["approach", "when"]
    # The tool appends its own write-your-own row to every question, and strips
    # one the model tried to supply — two of them would mean one that does not
    # work. So there is always exactly one, and it always does.
    assert [o["id"] for o in event["questions"][0]["options"]] == [
        "Refactor", "Replace", "Keep", forms.WRITE_YOUR_OWN]
    assert event["questions"][0]["options"][-1]["free"] is True
    # The second question is multi-select, and a client that ignored that
    # would offer a radio button for a question with several answers.
    assert event["questions"][1]["multiple"] is True

    service.answer_question(event["id"], cancelled=True)
    worker.join(timeout=10)
    assert result


def test_the_answer_a_client_sends_is_the_answer_the_model_reads(service):
    seen: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        seen.append(params) if name == "question.requested" else None)
    session = service.create_session()["id"]

    worker, result = ask_in_the_background(service, session, a_form())
    _wait_for(lambda: seen)

    service.answer_question(seen[0]["id"], answers=[
        {"header": "approach", "chosen": ["Refactor"]},
        {"header": "when", "chosen": ["Now", "After the release"]},
    ])
    worker.join(timeout=10)

    # What the tool hands to the model. This is the assertion that would have
    # failed silently before: a cancelled form still produces a `ToolResult`,
    # so only the content shows the difference.
    tool = result["tool"]
    assert tool.ok
    assert "Refactor" in tool.content
    assert "Now" in tool.content
    assert tool.meta.get("answered") is True
    assert tool.meta.get("given") == 2


def test_a_cancelled_form_is_reported_as_cancelled_not_as_an_answer(service):
    seen: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        seen.append(params) if name == "question.requested" else None)
    session = service.create_session()["id"]

    worker, result = ask_in_the_background(service, session, a_form())
    _wait_for(lambda: seen)

    service.answer_question(seen[0]["id"], cancelled=True)
    worker.join(timeout=10)

    assert result["tool"].meta.get("answered") is False


def test_a_typed_answer_survives_the_round_trip(service):
    # No hand-written escape hatch: the tool strips one the model supplies —
    # two of them would mean one that does not work — and appends its own.
    # Supplying "something else" here left a single real option, which is
    # below the minimum, so the form was rejected before it was ever asked.
    written = [
        {"header": "approach", "prompt": "Which approach?",
         "options": [{"label": "Refactor"}, {"label": "Replace"}]},
    ]
    seen: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        seen.append(params) if name == "question.requested" else None)
    session = service.create_session()["id"]

    worker, result = ask_in_the_background(service, session, written)
    _wait_for(lambda: seen)

    # The free row is marked, so a client knows to draw a text field.
    free = [o for o in seen[0]["questions"][0]["options"] if o.get("free")]
    assert len(free) == 1

    service.answer_question(seen[0]["id"], answers=[
        {"header": "approach", "chosen": [], "written": "rewrite it in Rust"},
    ])
    worker.join(timeout=10)

    assert "rewrite it in Rust" in result["tool"].content


def test_the_encoding_is_the_one_decode_answers_accepts():
    # The narrow version of the bug, without a thread: anything other than the
    # JSON `encode_answers` produces is read as a cancellation.
    from comodor.application import _encode_answer

    encoded = _encode_answer([
        {"header": "approach", "chosen": ["Refactor"], "written": ""},
    ])
    decoded = forms.decode_answers(encoded)

    assert decoded is not None, "a real answer must not read as a cancellation"
    assert decoded[0].chosen == ["Refactor"]
    # It really is the documented shape, not something that happens to parse.
    assert json.loads(encoded)[0]["header"] == "approach"


def _wait_for(condition, timeout: float = 10.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("the form never arrived")


def test_a_question_for_a_client_that_cannot_draw_one_is_declined_at_once(config):
    """A client that did not announce `questions` must not block the agent.

    Sending it a form it will never render leaves the tool waiting for its
    full timeout on an answer nobody will give, which reads to a person as the
    agent having hung.
    """
    import io

    from comodor import protocol as P
    from comodor.transport.jsonl import Channel
    from comodor.transport.server import Server

    service = CoreService(config)
    try:
        out = io.StringIO()
        hello = P.request("1", "client.hello", {
            "protocol_version": P.PROTOCOL_VERSION,
            "client": {"name": "plain", "version": "0"},
            "capabilities": []})          # announces neither
        channel = Channel(reader=io.StringIO(json.dumps(hello) + "\n"),
                          writer=out, log=io.StringIO())
        server = Server(service, channel)
        server.serve()

        assert server.client_capabilities == ()

        session = service.create_session()["id"]
        worker, result = ask_in_the_background(service, session, a_form())
        worker.join(timeout=10)

        assert not worker.is_alive(), "the tool waited for an answer nobody could give"
        assert result["tool"].meta.get("answered") is False
    finally:
        service.close()


def test_the_relay_still_carries_a_permission_prompt(config):
    """The other kind of request, which is not a form and must still arrive."""
    from comodor.events import Request

    service = CoreService(config)
    seen: list[tuple[str, dict]] = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    try:
        session = service.create_session()["id"]
        handle = service.session(session)
        handle.assembly.bus.emit(Kind.REQUEST, request=Request(
            id="perm-1", prompt="run: rm -rf build", options=["allow", "deny"],
            detail="$ rm -rf build", kind="permission"))

        names = [name for name, _ in seen]
        assert "permission.requested" in names
        body = dict(seen[names.index("permission.requested")][1])
        assert body["options"] == ["allow", "deny"]
        assert body["detail"] == "$ rm -rf build"
    finally:
        service.close()
