"""Assumptions are stated, and never carry a material decision (T126; FR-003,
SC-004).

The only path to an assumption is a decision that failed the materiality
test. Every proceed-on-assumption case is recorded as an assumption; no
material decision can reach that path.
"""

from __future__ import annotations

import pytest

from comodor.agent.evidence import Ledger, MaterialDecision


def test_an_immaterial_decision_may_be_assumed_and_is_recorded():
    ledger = Ledger()
    decision = ledger.open_decision("Which log format should the tool use?", affects=())
    assert not decision.material

    assumption = ledger.assume(decision.id, "plain text")
    assert assumption.chosen == "plain text"
    assert ledger.assumptions == [assumption]
    assert decision.state == "answered"


@pytest.mark.parametrize("affects", [("persistence",), ("data_loss",), ("security",)])
def test_a_material_decision_can_never_be_assumed(affects):
    ledger = Ledger()
    decision = ledger.open_decision("Which database should we use?", affects=affects)
    assert decision.material

    with pytest.raises(MaterialDecision):
        ledger.assume(decision.id, "SQLite")
    assert ledger.assumptions == []


def test_every_assumption_is_in_the_record():
    """No proceed-on-assumption case exists that the ledger does not name."""
    ledger = Ledger()
    for index in range(3):
        decision = ledger.open_decision(f"immaterial choice {index}", affects=())
        ledger.assume(decision.id, f"option {index}")
    named = {assumption.chosen for assumption in ledger.assumptions}
    assert named == {"option 0", "option 1", "option 2"}
