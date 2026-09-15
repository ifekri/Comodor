"""The form across reconnect, in the transcript, and in exports (T050, T051;
FR-023, FR-030, SC-009), plus model switching mid-form (T053; FR-028) and
availability across modes (T059; FR-010, FR-032).
"""

from __future__ import annotations

import json
import threading

import pytest

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.application import CoreService
from comodor.events import EventBus, Kind
from comodor.providers.base import Message, Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.session.store import SessionMeta, SessionStore, new_session_id
from comodor.tools import ToolRegistry

REQUEST = "Which database, SQLite or PostgreSQL? Then write db.py."
SECRET = "sk-live-0123456789abcdef"


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite",
                     "description": "one file"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def scripts():
    return [Script(text="Asking.", tool_calls=[a_question()]),
            Script(text="Done: SQLite.")]


def _until(condition, tries=500):
    ready = threading.Event()
    for _ in range(tries):
        if condition():
            return
        ready.wait(0.01)
    raise AssertionError("condition never held")


@pytest.fixture
def service(config):
    made = CoreService(config)
    yield made
    made.close()


def _start_turn(service, session):
    handle = service.session(session)
    handle.assembly.agent.gateway = Gateway(handle.assembly.config, scripts=scripts())
    worker = threading.Thread(target=lambda: service.send(session, REQUEST), daemon=True)
    worker.start()
    _until(lambda: service.snapshot(session).get("question"))
    return handle, worker


# --------------------------------------------------------------------------- #
# T050 — reconnect restores the form with its new fields
# --------------------------------------------------------------------------- #


def test_a_reconnecting_client_gets_the_form_with_reason_and_evidence(service):
    session = service.create_session()["id"]
    handle, worker = _start_turn(service, session)

    snapshot = service.snapshot(session)
    form = snapshot["question"]
    question = form["questions"][0]
    assert question["reason"] == "architecture"
    assert question["decision_ref"].startswith("d")
    assert [o["id"] for o in question["options"]] == ["SQLite", "PostgreSQL",
                                                       forms.WRITE_YOUR_OWN]
    assert question["options"][0]["description"] == "one file"
    json.dumps(snapshot)                       # wire-shaped all the way down

    # And the restored form is answerable.
    service.answer_question(form["id"], answers=[{"header": "Database",
                                                  "chosen": ["SQLite"]}])
    _until(lambda: not service.session(session).busy)
    assert "question" not in service.snapshot(session)


def test_a_cancelled_form_is_gone_from_the_snapshot_and_the_turn_says_why(service):
    session = service.create_session()["id"]
    seen = []
    service.on_event = lambda _s, name, params, _q: seen.append((name, params))
    handle, worker = _start_turn(service, session)
    form = service.snapshot(session)["question"]
    service.answer_question(form["id"], cancelled=True)
    _until(lambda: not service.session(session).busy)

    assert "question" not in service.snapshot(session)
    required = [params for name, params in seen if name == "clarification.required"]
    assert required and required[0]["outcome"] == "cancelled"


# --------------------------------------------------------------------------- #
# T051 — the transcript and the exports
# --------------------------------------------------------------------------- #


def _run_agent(config, bus, reply):
    bus.subscribe(lambda e: e.payload["request"].answer(reply)
                  if e.kind is Kind.REQUEST else None)
    agent = AgentLoop(config, Gateway(config, scripts=scripts()), ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    agent.run(REQUEST)
    return agent


def _exported(config, agent, tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session_id = new_session_id()
    for message in agent.conversation.messages:
        store.append(session_id, message)
    store.save_meta(SessionMeta(id=session_id, title="t"))
    markdown = store.export_markdown(session_id, tmp_path / "out.md",
                                     secrets=[SECRET]).read_text(encoding="utf-8")
    exported = json.loads(store.export_json(session_id, tmp_path / "out.json",
                                            secrets=[SECRET]).read_text(encoding="utf-8"))
    return store, session_id, markdown, exported


def test_an_answered_form_appears_in_history_and_exports_as_what_it_was(config, bus, tmp_path):
    agent = _run_agent(config, bus, json.dumps(
        [{"header": "Database", "prompt": "", "chosen": ["SQLite"],
          "written": f"and the key is {SECRET}"}]))
    store, session_id, markdown, exported = _exported(config, agent, tmp_path)

    tool = next(m for m in agent.conversation.messages if m.role is Role.TOOL)
    form = tool.meta["question"]
    assert form["state"] == "answered"

    # 1. question text  2. grounded options  3. the custom row
    assert "Which database?" in markdown
    assert "- SQLite" in markdown and "- PostgreSQL" in markdown
    assert f"- {forms.WRITE_YOUR_OWN} *(write your own)*" in markdown
    # 4. the user's answer  6. final state
    assert "**Answer:** SQLite, and the key is" in markdown
    assert "*Outcome: answered*" in markdown
    # secrets redacted in both exports
    assert SECRET not in markdown
    assert SECRET not in json.dumps(exported)
    # the record round-trips through the store
    back = store.load(session_id)
    restored = next(m for m in back if m.role is Role.TOOL)
    assert restored.meta["question"]["outcome"] == "answered"
    assert restored.meta["question"]["questions"][0]["options"][-1]["free"] is True


def test_a_cancelled_form_reads_as_cancelled_not_as_answered(config, bus, tmp_path):
    agent = _run_agent(config, bus, forms.CANCELLED)
    _, _, markdown, exported = _exported(config, agent, tmp_path)
    # 5. cancellation/decline
    assert "*Outcome: cancelled — left unresolved*" in markdown
    assert "**Answer:** none" in markdown
    record = next(m for m in exported["messages"] if m.get("question"))
    assert record["question"]["state"] == "unresolved"
    assert record["question"]["answers"] == []


def test_a_record_without_the_question_key_still_reads(tmp_path):
    """Pre-change transcripts have no such key; they load unchanged."""
    store = SessionStore(tmp_path / "sessions")
    session_id = new_session_id()
    store.append(session_id, Message.tool(call_id="c", name="ask", content="old"))
    back = store.load(session_id)
    assert back[0].meta == {}
    store.export_markdown(session_id, tmp_path / "old.md")


# --------------------------------------------------------------------------- #
# T053 — the form survives a model switch
# --------------------------------------------------------------------------- #


def test_the_form_survives_a_model_switch_and_the_answer_applies_to_the_work(service, config):
    config.providers["fake"].model = "fake-1"
    session = service.create_session()["id"]
    handle, worker = _start_turn(service, session)
    form = service.snapshot(session)["question"]

    service.set_model("fake-fast")
    assert service.snapshot(session)["question"]["id"] == form["id"], "still outstanding"

    service.answer_question(form["id"], answers=[{"header": "Database",
                                                  "chosen": ["SQLite"]}])
    _until(lambda: not service.session(session).busy)
    decision = handle.assembly.agent.tool_context.evidence.decisions[0]
    assert decision.state == "answered" and decision.answer == "SQLite"
    assert handle.assembly.config.model == "fake-fast"


# --------------------------------------------------------------------------- #
# T059 — every mode may ask; a conversation-only mode claims no inspection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode", ["act", "plan", "ask"])
def test_every_mode_that_permits_questions_can_raise_a_form(config, mode):
    from comodor.events import Cancellation
    from comodor.safety import CheckpointStore, Redactor
    from comodor.tools.ask import Ask
    from comodor.tools.base import ToolContext

    config.agent.mode = mode
    bus = EventBus()
    seen = []
    bus.subscribe(lambda e: (seen.append(e.payload["request"]),
                             e.payload["request"].answer(forms.CANCELLED))
                  if e.kind is Kind.REQUEST else None)
    context = ToolContext(config=config, permissions=PermissionEngine(config, bus),
                          checkpoints=CheckpointStore(config.paths.checkpoints), bus=bus,
                          redact=Redactor([]), cancel=Cancellation(),
                          cwd=config.paths.project, request_text="SQLite or PostgreSQL?")
    (config.paths.project / "settings.py").write_text("x", encoding="utf-8")
    context.note_read(config.paths.project / "settings.py", material="x")
    Ask().run(context, questions=a_question().arguments["questions"])
    assert len(seen) == 1
    question = seen[0].meta["questions"][0]
    if mode == "ask":
        assert question.get("evidence_consulted", []) == [], \
            "a conversation-only mode claims no inspection (FR-010)"
    else:
        assert "settings.py" in question["evidence_consulted"]
