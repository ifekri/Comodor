"""Every failure state reports the real limitation, invents nothing (T128;
FR-068, FR-069, FR-070, FR-113, FR-115, FR-116).

Tool failure, conflicting evidence, partial access, insufficient
information, low confidence and failed validation each say what is actually
the case. None is re-characterised as success and none substitutes a
synthesised result.
"""

from __future__ import annotations

from comodor.agent import verify
from comodor.agent.evidence import Ledger


def test_a_tool_failure_is_named_with_its_reason():
    assessment = verify.assess("fix it", entries=[],
                               failures=[("run_shell", "exit code 2")],
                               answer="I have fixed it.")
    named = next(what for what in assessment.unresolved if "run_shell" in what)
    assert "exit code 2" in assessment.unresolved_reasons[named]


def test_conflicting_evidence_is_surfaced_not_resolved():
    ledger = Ledger()
    ledger.verified("the config sets DEBUG", source="a.py", material="DEBUG = True")
    conflict = ledger.observe_conflict("debug mode", ["a.py", "b.py"])
    assert ledger.conflicts == [conflict]
    assert conflict.sources == ["a.py", "b.py"]


def test_partial_access_names_what_was_not_inspected():
    ledger = Ledger()
    ledger.could_not_inspect("vendor/")
    report = ledger.report_partial_access()
    assert "vendor/" in report
    assert "Nothing is claimed" in report


def test_insufficient_information_names_what_is_missing():
    ledger = Ledger()
    insufficiency = ledger.insufficient(["the production database name", "the API key"])
    assert insufficiency.missing == ["the production database name", "the API key"]
    # The missing things stay UNKNOWN; nothing is filled in.
    for missing in insufficiency.missing:
        assert ledger.find(missing) is not None


def test_low_confidence_on_a_material_conclusion_escalates_to_a_question():
    ledger = Ledger()
    escalation = ledger.escalate("use PostgreSQL", confidence=0.2,
                                 affects=("persistence",))
    assert escalation is not None
    assert escalation.kind == "clarification"
    assert ledger.decisions[-1].material


def test_low_confidence_on_an_immaterial_point_is_a_hedge_not_a_silent_claim():
    ledger = Ledger()
    escalation = ledger.escalate("use tabs", confidence=0.2, affects=())
    assert escalation.kind == "hedge"
    assert escalation.would_settle


def test_a_failed_validation_is_reported_with_its_output():
    outcome = verify.Outcome(ran=True, passed=False, output="2 failed, 1 passed")
    assert not outcome.passed
    correction = verify.as_correction("pytest -q", outcome)
    assert "2 failed, 1 passed" in correction
    assert "fails" in correction
