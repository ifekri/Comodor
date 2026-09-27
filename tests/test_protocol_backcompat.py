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


# --------------------------------------------------------------------------- #
# T177 / T178 — decision_ref is additive: nothing required changes, and a
# client that ignores it reads the same payload it always did
# --------------------------------------------------------------------------- #

#: The required fields at d911e3f. The additions must leave these exactly.
_REQUIRED_AT_D911E3F = {
    "ClarificationRequired": ["session_id", "turn_id", "kind", "decision",
                              "candidates", "evidence_consulted", "reason"],
    "ClarificationDecision": ["id", "decision"],
}


def test_decision_ref_is_optional_and_nothing_required_changed():
    schema = _schema()
    assert schema["x-protocol-version"] == 2
    defs = schema["$defs"]
    for shape, required in _REQUIRED_AT_D911E3F.items():
        assert defs[shape]["required"] == required
        assert defs[shape]["properties"]["decision_ref"]["type"] == "string"
        assert "decision_ref" not in defs[shape]["required"]
    assert defs["ClarificationOutcome"]["enum"] == ["cancelled", "expired", "unattended"]


def test_the_generated_shapes_carry_decision_ref_as_optional():
    from comodor.protocol import _generated

    assert _generated.SHAPES["ClarificationRequired"]["decision_ref"] == ("str", False)
    assert _generated.SHAPES["ClarificationDecision"]["decision_ref"] == ("str", False)
    assert _generated.SHAPES["ClarificationDecision"]["id"] == ("str", True)


def test_a_client_that_ignores_decision_ref_reads_an_unchanged_payload(config):
    """The relayed event validates as before, `decisions[].id` is present, and
    it carries the same value as `decision_ref` — one identity, one alias."""
    from comodor import protocol as P
    from comodor.agent.evidence import Ledger
    from comodor.application import _relay_clarification
    from comodor.events import Event, Kind
    from comodor.tools.ask import payload_for

    book = Ledger(mint=lambda: "dr-compat-1")
    decision = book.open_decision("Which database?", affects=["persistence"])
    payload = payload_for([decision], "unattended")

    service = CoreService(config)
    try:
        handle = service.session(service.create_session()["id"])
        sent = []
        service.on_event = lambda _s, name, params, _q: sent.append((name, params))
        _relay_clarification(service, handle, Event(kind=Kind.TURN_END, payload={
            "stopped": "clarification_required", "clarification": payload}))
        body = next(params for name, params in sent if name == "clarification.required")
    finally:
        service.close()

    P.validate("ClarificationRequired", body)
    for key in _REQUIRED_AT_D911E3F["ClarificationRequired"]:
        assert key in body
    (entry,) = body["decisions"]
    assert entry["id"] == entry["decision_ref"] == body["decision_ref"] == "dr-compat-1"
    assert entry["decision"] == "Which database?"
