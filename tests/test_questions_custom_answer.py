"""Custom-answer entry and carry-back (T030; FR-017, SC-005).

What a person types into the write-your-own row reaches the tool result bound
to that question's header — through the Python decode path here, and through
the TypeScript reducer in `packages/questions/test/questions.test.ts`.
"""

from __future__ import annotations

import json

import pytest

from comodor import questions as forms
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools.ask import Ask
from comodor.tools.base import ToolContext


@pytest.fixture
def context(config):
    bus = EventBus()
    made = ToolContext(config=config, permissions=PermissionEngine(config, bus),
                       checkpoints=CheckpointStore(config.paths.checkpoints),
                       bus=bus, redact=Redactor([]), cancel=Cancellation(),
                       cwd=config.paths.project,
                       request_text="SQLite or PostgreSQL? Python or Go?")
    return made


def two_questions():
    return [
        {"question": "Which database?", "header": "Database",
         "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}]},
        {"question": "Which language?", "header": "Language",
         "options": [{"label": "Python"}, {"label": "Go"}]},
    ]


def _answer_with(context, reply):
    def answer(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(reply)
    context.bus.subscribe(answer)


def test_written_text_is_carried_back_to_its_own_question(context):
    _answer_with(context, json.dumps([
        {"header": "Database", "prompt": "", "chosen": [], "written": "DuckDB, in-process"},
        {"header": "Language", "prompt": "", "chosen": ["Go"], "written": ""},
    ]))
    result = Ask().run(context, questions=two_questions())
    assert "Which database?\n  -> DuckDB, in-process" in result.content
    assert "Which language?\n  -> Go" in result.content


def test_written_text_binds_by_header_whatever_the_order(context):
    _answer_with(context, json.dumps([
        {"header": "Language", "prompt": "", "chosen": [], "written": "Rust"},
        {"header": "Database", "prompt": "", "chosen": [], "written": "DuckDB"},
    ]))
    result = Ask().run(context, questions=two_questions())
    assert "Which database?\n  -> DuckDB" in result.content
    assert "Which language?\n  -> Rust" in result.content


def test_a_choice_and_written_text_together_are_both_carried(context):
    _answer_with(context, json.dumps([
        {"header": "Database", "prompt": "", "chosen": ["SQLite"],
         "written": "but with WAL mode"},
    ]))
    result = Ask().run(context, questions=two_questions()[:1])
    assert "SQLite, but with WAL mode" in result.content


def test_written_text_is_never_coerced_into_an_option(context):
    _answer_with(context, json.dumps([
        {"header": "Database", "prompt": "", "chosen": [], "written": "sqlite"},
    ]))
    result = Ask().run(context, questions=two_questions()[:1])
    assert "-> sqlite" in result.content
    assert "-> SQLite" not in result.content


def test_the_written_answer_resolves_the_decision_in_the_ledger(context):
    _answer_with(context, json.dumps([
        {"header": "Database", "prompt": "", "chosen": [], "written": "DuckDB"},
    ]))
    Ask().run(context, questions=two_questions()[:1])
    from comodor.agent.evidence import EvidenceState

    decision = context.evidence.decisions[0]
    assert decision.state == "answered" and decision.answer == "DuckDB"
    assert context.evidence.get(decision.entry_id).state is EvidenceState.KNOWN
    assert context.evidence.withheld() == []


def test_whitespace_only_writing_is_not_an_answer():
    answer = forms.Answer(header="Database", prompt="", written="   ")
    assert not answer.given
    assert forms.encode_answers([answer]) == json.dumps(
        [{"header": "Database", "prompt": "", "chosen": [], "written": "   "}],
        ensure_ascii=False)
    assert forms.decode_answers(forms.encode_answers([answer]))[0].given is False


def test_unicode_and_rtl_text_survive_the_round_trip():
    written = "پایگاه‌داده SQLite با حالت WAL — ✓"
    encoded = forms.encode_answers([forms.Answer(header="Database", prompt="",
                                                 written=written)])
    assert forms.decode_answers(encoded)[0].written == written
