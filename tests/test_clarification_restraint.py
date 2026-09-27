"""Not over-asking (T034, T035; FR-008, FR-011, FR-012, SC-006).

"Never guess" must not become "ask about everything". Zero forms are raised
when the question is settled by the repository, by configuration, by
trustworthy learned knowledge, by safe implementation discretion, or by an
established obvious default — measured in a mode permitted to inspect. And
a form is never a request for permission or for a plan to be confirmed back.
"""

from __future__ import annotations

import pytest

from comodor import questions as forms
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools import ask as ask_tool
from comodor.tools.ask import Ask
from comodor.tools.base import ToolContext


@pytest.fixture
def context(config):
    config.agent.mode = "act"                 # a mode permitted to inspect
    bus = EventBus()
    made = ToolContext(config=config, permissions=PermissionEngine(config, bus),
                       checkpoints=CheckpointStore(config.paths.checkpoints),
                       bus=bus, redact=Redactor([]), cancel=Cancellation(),
                       cwd=config.paths.project,
                       request_text="Add a retry to the pricing client.")
    return made


@pytest.fixture
def forms_raised(context):
    seen = []
    context.bus.subscribe(lambda event: (seen.append(event.payload["request"]),
                                         event.payload["request"].answer(forms.CANCELLED))
                          if event.kind is Kind.REQUEST else None)
    return seen


def a_question(prompt="which database", **extra):
    body = {"question": prompt, "header": "Database",
            "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}]}
    body.update(extra)
    return body


# --------------------------------------------------------------------------- #
# T034 — the five settled cases raise nothing
# --------------------------------------------------------------------------- #


def test_settled_by_repository_evidence_raises_no_form(context, forms_raised):
    context.evidence.verified("which database", source="app/db.py",
                              material="engine = create_engine('sqlite:///x')")
    result = Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert forms_raised == []
    assert result.ok and result.meta["asked"] == 0
    assert "already settled" in result.content


def test_settled_by_project_configuration_raises_no_form(context, forms_raised):
    context.evidence.verified("which database", source="config/settings.toml",
                              material="[database]\nkind = 'postgres'")
    Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert forms_raised == []


def test_settled_by_trustworthy_learned_knowledge_raises_no_form(context, forms_raised):
    context.evidence.knowledge("which database", ref="fact:7")
    Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert forms_raised == []


def test_safe_implementation_discretion_raises_no_form(context, forms_raised):
    """A decision the model marks as touching nothing material is its own."""
    decision = context.evidence.open_decision("name of the retry helper", affects=[])
    assert not decision.material
    context.evidence.assume(decision.id, "retry_once")
    assert forms_raised == []
    assert context.evidence.assumptions[0].chosen == "retry_once"


def test_an_established_obvious_default_is_taken_and_said(context, forms_raised):
    """The user already stated it: the ledger holds it KNOWN, so no form."""
    context.evidence.known("which database")
    Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert forms_raised == []


def test_an_unsettled_material_decision_does_raise_a_form(context, forms_raised):
    """The other direction, so the five cases above are not vacuous."""
    Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert len(forms_raised) == 1


def test_the_restraint_is_the_settled_check(context, forms_raised, monkeypatch):
    """Mutation check: with `settled` disabled, a settled decision is asked."""
    from comodor.agent.evidence import Ledger

    context.evidence.verified("which database", source="app/db.py", material="sqlite")
    real = Ledger.settled
    monkeypatch.setattr(Ledger, "settled", lambda self, what: None)
    Ask().run(context, questions=[a_question(affects=["architecture"])])
    assert len(forms_raised) == 1, "the mutation asks about a settled decision"

    monkeypatch.setattr(Ledger, "settled", real)
    forms_raised.clear()
    Ask().run(context, questions=[a_question("which database", affects=["architecture"])])
    assert forms_raised == []


# --------------------------------------------------------------------------- #
# T035 — never a permission prompt, never a plan confirmation
# --------------------------------------------------------------------------- #


PERMISSION_SHAPED = [
    "Should I proceed?",
    "May I go ahead and make the change?",
    "Do you want me to continue?",
    "Is it OK to run the tests now?",
    "Can I proceed with the plan?",
]

CONFIRMATION_SHAPED = [
    "Does this plan look right to you?",
    "Please confirm the plan: 1) add retry 2) add test.",
    "Is my understanding correct that you want a retry?",
    "Shall I do it the way I described above?",
]


@pytest.mark.parametrize("prompt", PERMISSION_SHAPED + CONFIRMATION_SHAPED)
def test_a_permission_or_confirmation_question_is_refused_not_asked(context, forms_raised, prompt):
    result = Ask().run(context, questions=[{
        "question": prompt, "header": "Go ahead",
        "options": [{"label": "Yes"}, {"label": "No"}]}])
    assert forms_raised == []
    assert not result.ok
    assert "not for permission" in result.content or "not for confirm" in result.content


def test_a_real_decision_with_a_yes_no_shape_is_still_asked(context, forms_raised):
    Ask().run(context, questions=[{
        "question": "Should failed requests be retried with backoff or immediately?",
        "header": "Retry", "affects": ["behaviour"],
        "options": [{"label": "With backoff", "source": "request", "evidence": "retry"},
                    {"label": "Immediately", "source": "request", "evidence": "retry"}]}])
    assert len(forms_raised) == 1


def test_the_refusal_is_the_shape_check(context, forms_raised, monkeypatch):
    """Mutation check: without the check, a permission prompt becomes a form."""
    real = ask_tool.not_a_decision
    monkeypatch.setattr(ask_tool, "not_a_decision", lambda prompt: "")
    Ask().run(context, questions=[{
        "question": "Should I proceed?", "header": "Go",
        "options": [{"label": "Yes"}, {"label": "No"}]}])
    assert len(forms_raised) == 1, "the mutation lets a permission prompt through"

    monkeypatch.setattr(ask_tool, "not_a_decision", real)
    forms_raised.clear()
    result = Ask().run(context, questions=[{
        "question": "Should I proceed?", "header": "Go",
        "options": [{"label": "Yes"}, {"label": "No"}]}])
    assert forms_raised == [] and not result.ok
