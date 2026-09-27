"""Zero fabricated values on every non-answer outcome (T039; FR-019, SC-037–SC-040).

Cancelled, declined, expired and unattended: each asserts, independently,
that no value was invented, no option selected, no default applied and no
assumption substituted. Each guard is mutation-checked — the protection is
removed, the test sees the fabrication, and the protection is restored.
"""

from __future__ import annotations

import json

import pytest

from comodor import questions as forms
from comodor.agent.evidence import EvidenceState as S
from comodor.agent.evidence import Ledger, MaterialDecision
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools import ask as ask_tool
from comodor.tools.ask import Ask
from comodor.tools.base import ToolContext

QUESTION = {"question": "Which database should this use?", "header": "Database",
            "affects": ["architecture"],
            "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                        {"label": "PostgreSQL", "source": "request",
                         "evidence": "PostgreSQL"}]}


def _context(config, bus):
    return ToolContext(config=config, permissions=PermissionEngine(config, bus),
                       checkpoints=CheckpointStore(config.paths.checkpoints),
                       bus=bus, redact=Redactor([]), cancel=Cancellation(),
                       cwd=config.paths.project,
                       request_text="SQLite or PostgreSQL?")


def _run_ending(config, outcome, monkeypatch):
    """Run the tool so the form ends the given way; return (result, ledger)."""
    bus = EventBus()
    if outcome == "cancelled":
        bus.subscribe(lambda e: e.payload["request"].answer(forms.CANCELLED)
                      if e.kind is Kind.REQUEST else None)
    elif outcome == "declined":
        # Sent with the question left blank.
        bus.subscribe(lambda e: e.payload["request"].answer(json.dumps(
            [{"header": "Database", "prompt": "", "chosen": [], "written": ""}]))
            if e.kind is Kind.REQUEST else None)
    elif outcome == "expired":
        monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
        bus.subscribe(lambda e: None)
    elif outcome == "unattended":
        pass                                     # nobody subscribed at all
    context = _context(config, bus)
    result = Ask().run(context, questions=[QUESTION])
    return result, context.evidence


def _assert_nothing_fabricated(result, ledger, outcome):
    text = result.content
    assert "sensible default" not in text.lower()
    assert "decide them yourself" not in text.lower()
    assert result.meta["answered"] is False or result.meta.get("given") == 0
    assert result.meta["outcome"] == outcome
    # No option selected, no default applied, no assumption substituted.
    decision = ledger.decisions[0]
    assert decision.answer == ""
    assert decision.assumption == ""
    assert ledger.assumptions == []
    state = ledger.get(decision.entry_id).state
    assert state is (S.BLOCKED if outcome == "unattended" else S.UNRESOLVED)
    assert not ledger.may_rely_on(decision.what)
    assert result.meta["clarification"]["outcome"] == outcome


@pytest.mark.parametrize("ending, outcome", [
    ("cancelled", "cancelled"), ("declined", "cancelled"),
    ("expired", "expired"), ("unattended", "unattended"),
])
def test_no_value_is_fabricated(config, monkeypatch, ending, outcome):
    result, ledger = _run_ending(config, ending, monkeypatch)
    _assert_nothing_fabricated(result, ledger, outcome)


# --------------------------------------------------------------------------- #
# each guard, removed and restored
# --------------------------------------------------------------------------- #


def _mutated_unresolved(decisions, outcome, repeated=False):
    """The pre-feature behaviour: tell the model to choose defaults."""
    from comodor.tools.base import ToolResult

    return ToolResult.success(
        "The user closed the form without answering. Choose sensible defaults, "
        "carry on, and say plainly which decisions you made for them.",
        display="Questions dismissed.", answered=False, outcome=outcome)


@pytest.mark.parametrize("ending, outcome", [
    ("cancelled", "cancelled"), ("declined", "cancelled"),
    ("expired", "expired"), ("unattended", "unattended"),
])
def test_the_guard_for_each_outcome_fails_when_removed(config, monkeypatch, ending, outcome):
    real = ask_tool._unresolved
    monkeypatch.setattr(ask_tool, "_unresolved", _mutated_unresolved)
    if ending == "declined":
        # The declined path reports through `summarise`; mutate that instead.
        real_summarise = forms.summarise
        monkeypatch.setattr(forms, "summarise", lambda q, a: (
            "Left unanswered — decide them yourself and say which way you went"))
        result, _ = _run_ending(config, ending, monkeypatch)
        assert "decide them yourself" in result.content, "mutation shows the fabrication"
        monkeypatch.setattr(forms, "summarise", real_summarise)
    else:
        result, _ = _run_ending(config, ending, monkeypatch)
        assert "sensible defaults" in result.content, "mutation shows the fabrication"

    monkeypatch.setattr(ask_tool, "_unresolved", real)
    result, ledger = _run_ending(config, ending, monkeypatch)
    _assert_nothing_fabricated(result, ledger, outcome)


def test_the_ledger_guard_refuses_an_assumption_on_every_non_answer():
    for outcome in ("cancelled", "expired", "unattended"):
        ledger = Ledger()
        decision = ledger.open_decision("which database", affects=["architecture"])
        ledger.ended_without_answer(decision.id, outcome)
        with pytest.raises(MaterialDecision):
            ledger.assume(decision.id, "SQLite")
        assert ledger.assumptions == []


def test_declined_is_reported_as_cancelled_not_as_an_answer(config, monkeypatch):
    """FR-022: 'answered with nothing' is distinct from an answer, and the
    decision it belonged to stays open."""
    result, ledger = _run_ending(config, "declined", monkeypatch)
    assert result.meta["answered"] is True, "the form did come back"
    assert result.meta["given"] == 0
    assert "remain unresolved" in result.content
    assert ledger.withheld()
