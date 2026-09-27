"""The evidence ledger's closed state machine (T016, T017; FR-001, FR-002).

Every legal transition in data-model.md §2 passes; every other one is
refused; and a derivation may never rest on an `UNKNOWN` — the single rule
that mechanically stops a gap from being filled.
"""

from __future__ import annotations

import pytest

from comodor.agent.evidence import (
    STATES,
    TRANSITIONS,
    IllegalEvidence,
    IllegalTransition,
    Ledger,
    fingerprint_of,
)
from comodor.agent.evidence import (
    EvidenceState as S,
)

# --------------------------------------------------------------------------- #
# the set and the table are closed
# --------------------------------------------------------------------------- #


def test_the_state_set_is_exactly_the_nine_of_the_data_model():
    assert {state.value for state in S} == {
        "known", "verified", "derived", "unknown", "requires_clarification",
        "unresolved", "blocked", "validated", "failed"}
    assert STATES == tuple(S)


def test_the_transition_table_is_exactly_the_data_models():
    expected = {
        (S.UNKNOWN, "materiality"): S.REQUIRES_CLARIFICATION,
        (S.REQUIRES_CLARIFICATION, "answered"): S.KNOWN,
        (S.REQUIRES_CLARIFICATION, "cancelled"): S.UNRESOLVED,
        (S.REQUIRES_CLARIFICATION, "expired"): S.UNRESOLVED,
        (S.REQUIRES_CLARIFICATION, "unattended"): S.BLOCKED,
        (S.UNRESOLVED, "answered"): S.KNOWN,
        (S.KNOWN, "confirmed"): S.VALIDATED,
        (S.VERIFIED, "confirmed"): S.VALIDATED,
        (S.DERIVED, "confirmed"): S.VALIDATED,
        (S.KNOWN, "contradicted"): S.FAILED,
        (S.VERIFIED, "contradicted"): S.FAILED,
        (S.DERIVED, "contradicted"): S.FAILED,
        (S.VERIFIED, "source_changed"): S.UNKNOWN,
    }
    assert dict(TRANSITIONS) == expected


@pytest.mark.parametrize("state, trigger, target", [
    (S.UNKNOWN, "materiality", S.REQUIRES_CLARIFICATION),
    (S.REQUIRES_CLARIFICATION, "answered", S.KNOWN),
    (S.REQUIRES_CLARIFICATION, "cancelled", S.UNRESOLVED),
    (S.REQUIRES_CLARIFICATION, "expired", S.UNRESOLVED),
    (S.REQUIRES_CLARIFICATION, "unattended", S.BLOCKED),
    (S.UNRESOLVED, "answered", S.KNOWN),
    (S.KNOWN, "confirmed", S.VALIDATED),
    (S.VERIFIED, "confirmed", S.VALIDATED),
    (S.DERIVED, "confirmed", S.VALIDATED),
    (S.KNOWN, "contradicted", S.FAILED),
    (S.VERIFIED, "contradicted", S.FAILED),
    (S.DERIVED, "contradicted", S.FAILED),
    (S.VERIFIED, "source_changed", S.UNKNOWN),
])
def test_every_legal_transition_passes(state, trigger, target):
    ledger = Ledger()
    entry = ledger.seed(f"claim in {state.value}", state)
    ledger.transition(entry.id, trigger)
    assert ledger.get(entry.id).state is target


def _illegal_pairs():
    triggers = {trigger for _, trigger in TRANSITIONS}
    for state in S:
        for trigger in sorted(triggers):
            if (state, trigger) not in TRANSITIONS:
                yield state, trigger


@pytest.mark.parametrize("state, trigger", list(_illegal_pairs()))
def test_every_other_transition_is_refused_and_changes_nothing(state, trigger):
    ledger = Ledger()
    entry = ledger.seed("a claim", state)
    with pytest.raises(IllegalTransition):
        ledger.transition(entry.id, trigger)
    assert ledger.get(entry.id).state is state


def test_an_unknown_trigger_is_refused():
    ledger = Ledger()
    entry = ledger.seed("a claim", S.UNKNOWN)
    with pytest.raises(IllegalTransition):
        ledger.transition(entry.id, "guessed")


def test_terminal_states_within_the_turn():
    for terminal in (S.BLOCKED, S.VALIDATED, S.FAILED):
        assert not any(state is terminal for state, _ in TRANSITIONS), terminal


# --------------------------------------------------------------------------- #
# what may be written, and by whom
# --------------------------------------------------------------------------- #


def test_a_user_statement_is_known_and_a_tool_observation_is_verified():
    ledger = Ledger()
    stated = ledger.known("the service must stay on port 8080")
    seen = ledger.verified("config.py sets PORT", source="config.py",
                           material="PORT = 8080\n")
    assert stated.state is S.KNOWN and stated.source == "user"
    assert seen.state is S.VERIFIED and seen.source == "config.py"
    assert seen.fingerprint == fingerprint_of("PORT = 8080\n")
    assert "PORT = 8080" not in seen.fingerprint


def test_verified_requires_a_source_and_known_requires_the_user():
    ledger = Ledger()
    with pytest.raises(IllegalEvidence):
        ledger.verified("something", source="", material="x")
    with pytest.raises(IllegalEvidence):
        ledger.seed("stated", S.KNOWN, source="the model")


def test_established_knowledge_is_known_with_a_knowledge_source():
    ledger = Ledger()
    fact = ledger.knowledge("the project targets PostgreSQL 15", ref="fact:12")
    assert fact.state is S.KNOWN
    assert fact.source == "knowledge:fact:12"
    assert fact.category == "knowledge"


def test_a_derivation_rests_only_on_known_verified_or_derived():
    ledger = Ledger()
    a = ledger.known("A")
    b = ledger.verified("B", source="b.py", material="b")
    c = ledger.derive("C follows from A and B", derived_from=[a.id, b.id])
    d = ledger.derive("D follows from C", derived_from=[c.id])
    assert c.state is S.DERIVED and d.state is S.DERIVED
    assert d.derived_from == [c.id]


def test_a_derivation_resting_on_an_unknown_is_refused():
    """The one rule that mechanically prevents gap-filling (FR-002)."""
    ledger = Ledger()
    gap = ledger.unknown("which database")
    fact = ledger.known("A")
    with pytest.raises(IllegalEvidence):
        ledger.derive("conclusion", derived_from=[fact.id, gap.id])
    assert ledger.get(gap.id).state is S.UNKNOWN
    assert not [entry for entry in ledger.entries if entry.claim == "conclusion"]


@pytest.mark.parametrize("state", [S.REQUIRES_CLARIFICATION, S.UNRESOLVED, S.BLOCKED,
                                   S.FAILED])
def test_a_derivation_never_rests_on_an_unsettled_or_failed_entry(state):
    ledger = Ledger()
    shaky = ledger.seed("shaky", state)
    with pytest.raises(IllegalEvidence):
        ledger.derive("conclusion", derived_from=[shaky.id])


def test_a_derivation_needs_at_least_one_premise():
    with pytest.raises(IllegalEvidence):
        Ledger().derive("from nothing", derived_from=[])


def test_the_default_for_anything_absent_is_unknown():
    ledger = Ledger()
    assert ledger.state_of("never mentioned") is S.UNKNOWN
    assert ledger.may_rely_on("never mentioned") is False


@pytest.mark.parametrize("state, usable", [
    (S.KNOWN, True), (S.VERIFIED, True), (S.DERIVED, True), (S.VALIDATED, True),
    (S.UNKNOWN, False), (S.REQUIRES_CLARIFICATION, False), (S.UNRESOLVED, False),
    (S.BLOCKED, False), (S.FAILED, False),
])
def test_which_states_a_decision_may_rest_on(state, usable):
    ledger = Ledger()
    entry = ledger.seed("claim", state)
    assert ledger.may_rely_on(entry.claim) is usable


def test_a_fingerprint_is_never_the_material_and_never_looks_like_a_secret():
    ledger = Ledger()
    entry = ledger.verified("env read", source=".env",
                            material="XIAOMI_API_KEY=sk-live-abcdef0123456789\n")
    assert "sk-live" not in entry.fingerprint
    assert len(entry.fingerprint) == 16
    with pytest.raises(IllegalEvidence):
        ledger.seed("raw", S.VERIFIED, source="x", fingerprint="sk-live-abcdef0123456789")


def test_a_source_change_sends_verified_back_to_unknown_not_to_a_guess():
    ledger = Ledger()
    seen = ledger.verified("app.py defines main", source="app.py", material="def main")
    ledger.source_changed(seen.id)
    assert ledger.get(seen.id).state is S.UNKNOWN
    assert ledger.may_rely_on("app.py defines main") is False
