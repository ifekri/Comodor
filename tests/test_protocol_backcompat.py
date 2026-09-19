"""Old clients are unaffected (T136; FR-079, FR-080, SC-023).

The clarification additions are optional and additive. A client that does not
negotiate the `clarification_required` capability is sent nothing new — its
turn ends exactly as it did before — and no existing message changes meaning.
"""

from __future__ import annotations

import json
from pathlib import Path

from comodor.application import CLIENT_CAPABILITIES, CoreService

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "protocol" / "v2.json"


def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def test_the_capability_is_advertised_on_both_sides():
    schema = _schema()
    capabilities = schema["x-capabilities"]
    assert "clarification_required" in capabilities["core"]
    assert "clarification_required" in capabilities["client"]
    assert "clarification_required" in CLIENT_CAPABILITIES


def test_the_new_fields_are_optional():
    defs = _schema()["$defs"]
    question_required = set(defs["QuestionField"].get("required") or [])
    assert {"reason", "evidence_consulted", "decision_ref"} & question_required == set()

    clarification_required = set(defs["ClarificationRequired"].get("required") or [])
    assert "outcome" not in clarification_required
    assert "outcome" in defs["ClarificationRequired"]["properties"]


def test_the_outcome_enum_is_the_three_lifecycle_events():
    assert _schema()["$defs"]["ClarificationOutcome"]["enum"] == [
        "cancelled", "expired", "unattended"]


class _Client:
    def __init__(self, capabilities):
        self.client_capabilities = capabilities


def test_a_client_without_the_capability_never_receives_the_event():
    """`_declined` returns True — nothing is sent — and the turn keeps its
    existing meaning."""
    old = _Client(("questions", "permissions"))
    assert CoreService._declined(old, object(), "clarification.required", {}) is True


def test_a_client_with_the_capability_receives_the_event():
    new = _Client(("questions", "permissions", "clarification_required"))
    assert CoreService._declined(new, object(), "clarification.required", {}) is False


def test_the_turn_outcome_vocabulary_is_unchanged():
    """`clarification_required` is a stopped value, not a new finish reason on
    an existing message; `stopped: "cancelled"` keeps its turn meaning."""
    from comodor.agent.loop import TurnResult

    result = TurnResult()
    assert result.stopped == "done"
    assert result.clarification is None
