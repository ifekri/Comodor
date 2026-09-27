"""Characterization: a pending question survives a snapshot and a reconnect (T007).

The core keeps an outstanding form in the session journal; a client that
reconnects rebuilds the card from `session.snapshot`. Spec 002 extends the
form with optional fields (FR-023) and must keep this round trip intact,
along with the on-disk session record the current version writes (FR-081,
SC-024). Pinned here, against the unmodified implementation.
"""

from __future__ import annotations

import json
import threading

import pytest

from comodor import questions as forms
from comodor.application import CoreService
from comodor.providers.base import Message, ToolCall
from comodor.session.store import SessionMeta, SessionStore, new_session_id
from comodor.tools.ask import Ask


@pytest.fixture
def service(config):
    made = CoreService(config)
    yield made
    made.close()


def a_form():
    return [{"header": "Database", "prompt": "Which database?",
             "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}]}]


def _ask_in_background(service, session_id, questions):
    handle = service.session(session_id)
    out: dict = {}

    def work():
        from comodor.events import Cancellation
        from comodor.safety import CheckpointStore, Redactor
        from comodor.tools.base import ToolContext

        context = ToolContext(
            config=handle.assembly.config, permissions=handle.assembly.permissions,
            checkpoints=CheckpointStore(handle.assembly.config.paths.checkpoints),
            bus=handle.assembly.bus, redact=Redactor([]), cancel=Cancellation(),
            cwd=handle.assembly.config.paths.project,
            # The request names the candidates, so they are grounded (FR-016).
            request_text="SQLite or PostgreSQL?")
        out["result"] = Ask().run(context, questions=questions)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    return worker, out


def _until(condition, tries=200):
    ready = threading.Event()
    for _ in range(tries):
        if condition():
            return
        ready.wait(0.01)
    raise AssertionError("condition never held")


def test_an_outstanding_form_is_in_the_snapshot_with_its_free_row(service):
    seen: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        seen.append(params) if name == "question.requested" else None)
    session = service.create_session()["id"]
    worker, out = _ask_in_background(service, session, a_form())
    _until(lambda: seen)

    snapshot = service.snapshot(session)
    assert snapshot["question"]["id"] == seen[0]["id"]
    question = snapshot["question"]["questions"][0]
    assert question["header"] == "Database"
    assert [option["id"] for option in question["options"]] == \
        ["SQLite", "PostgreSQL", forms.WRITE_YOUR_OWN]
    assert question["options"][-1]["free"] is True
    assert snapshot["interactions"][0]["kind"] == "question"

    # The snapshot is JSON all the way down — a reconnecting client reads it
    # over the wire, not from Python objects.
    json.dumps(snapshot)

    service.answer_question(seen[0]["id"], cancelled=True)
    worker.join(5.0)


def test_a_reconnecting_client_answers_the_form_it_found_in_the_snapshot(service):
    session = service.create_session()["id"]
    worker, out = _ask_in_background(service, session, a_form())
    _until(lambda: service.snapshot(session).get("question"))

    found = service.snapshot(session)["question"]
    service.answer_question(found["id"], answers=[
        {"header": "Database", "chosen": ["PostgreSQL"]}])
    worker.join(5.0)

    assert "PostgreSQL" in out["result"].content
    assert "question" not in service.snapshot(session)
    assert "interactions" not in service.snapshot(session)


def test_a_cancelled_form_leaves_the_snapshot_and_is_reported_cancelled(service):
    resolved: list[dict] = []
    service.on_event = lambda _s, name, params, _q: (
        resolved.append(params) if name == "question.resolved" else None)
    session = service.create_session()["id"]
    worker, out = _ask_in_background(service, session, a_form())
    _until(lambda: service.snapshot(session).get("question"))

    request_id = service.snapshot(session)["question"]["id"]
    service.answer_question(request_id, cancelled=True)
    worker.join(5.0)

    assert resolved[-1] == {"id": request_id, "session_id": session, "cancelled": True}
    assert "question" not in service.snapshot(session)
    assert out["result"].meta["answered"] is False


def test_a_second_answer_to_the_same_form_is_refused(service):
    from comodor.application import UnknownRequest

    session = service.create_session()["id"]
    worker, _ = _ask_in_background(service, session, a_form())
    _until(lambda: service.snapshot(session).get("question"))
    request_id = service.snapshot(session)["question"]["id"]

    service.answer_question(request_id, cancelled=True)
    with pytest.raises(UnknownRequest):
        service.answer_question(request_id, answers=[{"header": "Database",
                                                       "chosen": ["SQLite"]}])
    worker.join(5.0)


# --------------------------------------------------------------------------- #
# the on-disk record the current version writes
# --------------------------------------------------------------------------- #


def test_a_session_written_by_the_current_version_reads_back_intact(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session_id = new_session_id()
    call = ToolCall(id="c1", name="ask", arguments={"questions": a_form()})
    messages = [
        Message.user("build it", briefing="playbook"),
        Message.assistant("One question first.", [call]),
        Message.tool(call_id="c1", name="ask", content="The user answered:\n\n"
                     "Which database?\n  -> SQLite"),
        Message.assistant("Done."),
    ]
    for message in messages:
        store.append(session_id, message)
    store.save_meta(SessionMeta(id=session_id, title="build it", provider="fake",
                                model="fake-1", cwd=str(tmp_path)))

    back = store.load(session_id)
    assert [m.role for m in back] == [m.role for m in messages]
    assert [m.content for m in back] == [m.content for m in messages]
    assert back[1].tool_calls[0].id == "c1"
    assert back[1].tool_calls[0].arguments["questions"][0]["header"] == "Database"
    assert back[2].tool_call_id == "c1" and back[2].name == "ask"
    meta = store.load_meta(session_id)
    assert meta is not None and meta.title == "build it"


def test_the_record_is_line_delimited_json_one_message_per_line(tmp_path):
    """The format a pre-change reader relies on: JSONL, appended, never rewritten."""
    store = SessionStore(tmp_path / "sessions")
    session_id = new_session_id()
    store.append(session_id, Message.user("one"))
    store.append(session_id, Message.assistant("two"))
    lines = store.path_for(session_id).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["role"] for line in lines] == ["user", "assistant"]
