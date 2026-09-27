"""Producers, materiality, discretion, uncertainty and reporting (T019–T025).

What writes to the ledger during a turn, how a decision is classified against
the closed FR-007 list, why a material decision can never be assumed, how
mode changes what may be claimed, and how low confidence, missing
information, conflict and partial access are surfaced instead of smoothed
over (FR-004, FR-007, FR-009, FR-010, FR-069, FR-070, FR-113, FR-115,
FR-122, FR-130, SC-004, SC-033).
"""

from __future__ import annotations

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.agent import evidence as ev
from comodor.agent.evidence import EvidenceState as S
from comodor.agent.evidence import Ledger, MaterialDecision, assess
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# T019 — the producers, from real tool results
# --------------------------------------------------------------------------- #


def test_a_read_a_search_and_a_command_each_produce_a_verified_entry(config, bus):
    (config.paths.project / "app.py").write_text("def main():\n    pass\n", encoding="utf-8")
    agent = make_agent(config, bus, [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": "app.py"}),
            ToolCall(id="g", name="grep", arguments={"pattern": "main", "path": "."}),
            ToolCall(id="s", name="run_shell", arguments={"command": "echo hi"}),
        ]),
        Script(text="Done."),
    ])
    result = agent.run("what is in app.py?")
    assert result.ok

    book = agent.tool_context.evidence
    verified = [entry for entry in book.entries if entry.state is S.VERIFIED]
    sources = {entry.source for entry in verified}
    assert "app.py" in sources
    assert any(source.startswith("grep") for source in sources)
    assert any(source.startswith("run_shell") for source in sources)
    for entry in verified:
        assert entry.fingerprint == "" or len(entry.fingerprint) == 16
        assert "def main" not in entry.fingerprint
    # The request itself is KNOWN, from the user.
    assert any(entry.state is S.KNOWN and entry.source == "user" for entry in book.entries)


def test_a_failed_tool_result_stays_unknown(config, bus):
    agent = make_agent(config, bus, [
        Script(text="Looking.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": "missing.py"})]),
        Script(text="Done."),
    ])
    agent.run("read missing.py")
    book = agent.tool_context.evidence
    entry = book.find("read_file missing.py")
    assert entry is not None and entry.state is S.UNKNOWN
    assert not book.may_rely_on("read_file missing.py")


def test_questions_and_plans_are_not_observations(config, bus):
    agent = make_agent(config, bus, [
        Script(text="Planning.", tool_calls=[
            ToolCall(id="t", name="todo_write",
                     arguments={"todos": [{"text": "x", "state": "pending"}]})]),
        Script(text="Done."),
    ])
    agent.run("plan it")
    book = agent.tool_context.evidence
    assert not any("todo_write" in entry.claim for entry in book.entries)


def test_the_ledger_is_new_every_turn_and_dies_with_it(config, bus):
    agent = make_agent(config, bus, [Script(text="ok")] * 2)
    agent.run("first")
    first = agent.tool_context.evidence
    first.unknown("something from turn one")
    agent.run("second")
    second = agent.tool_context.evidence
    assert second is not first
    assert second.find("something from turn one") is None


def test_wiring_the_ledger_changed_no_observable_behaviour(config, bus):
    """The Phase 2 checkpoint: nothing the user sees moved."""
    (config.paths.project / "app.py").write_text("x = 1\n", encoding="utf-8")
    scripts = [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="r", name="read_file", arguments={"path": "app.py"})]),
        Script(text="It sets x to 1."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("what does app.py do?")
    assert result.ok and result.text == "It sets x to 1."
    assert result.steps == 2 and result.tool_calls == 1
    tool_messages = [m for m in agent.conversation.messages if m.role.value == "tool"]
    assert "x = 1" in tool_messages[0].content


# --------------------------------------------------------------------------- #
# T020 — the materiality test is a table
# --------------------------------------------------------------------------- #


def test_the_eleven_classes_of_fr_007_exactly():
    assert ev.MATERIALITY == (
        "behaviour", "architecture", "data_loss", "security", "compatibility",
        "api_contract", "interface_behaviour", "destructive_operation",
        "release_action", "external_side_effect", "persisted_state")


@pytest.mark.parametrize("affects, expected", [
    (["behaviour"], "behaviour"),
    (["architecture"], "architecture"),
    (["data loss"], "data_loss"),
    (["security"], "security"),
    (["compatibility"], "compatibility"),
    (["api"], "api_contract"),
    (["protocol contract"], "api_contract"),
    (["ui"], "interface_behaviour"),
    (["destructive"], "destructive_operation"),
    (["release"], "release_action"),
    (["side effect"], "external_side_effect"),
    (["persistence"], "persisted_state"),
    (["naming", "security"], "security"),
    ([], ""),
    (["", "  "], ""),
    (None, "behaviour"),
    (["something the table has never heard of"], "behaviour"),
])
def test_classification_is_deterministic_and_fails_to_material(affects, expected):
    assert assess(affects) == expected
    assert assess(affects) == assess(affects)


def test_an_immaterial_decision_never_becomes_requires_clarification():
    ledger = Ledger()
    decision = ledger.open_decision("tabs or spaces in the new file", affects=[])
    assert not decision.material
    assert ledger.get(decision.entry_id).state is S.UNKNOWN
    assert decision not in ledger.withheld()


def test_a_material_decision_promotes_its_entry_and_withholds_dependent_work():
    ledger = Ledger()
    decision = ledger.open_decision("delete the old records or keep them",
                                    affects=["data loss"],
                                    evidence_consulted=["e1"])
    assert decision.materiality == "data_loss"
    assert ledger.get(decision.entry_id).state is S.REQUIRES_CLARIFICATION
    assert ledger.withheld() == [decision]


def test_a_decision_settled_by_evidence_is_not_a_decision(config):
    """FR-008: settled by the repository, no question is raised."""
    ledger = Ledger()
    ledger.verified("which database", source="config.py", material="DATABASE = 'sqlite'")
    decision = ledger.open_decision("which database", affects=["architecture"])
    assert decision.state == "answered" and not decision.material
    assert ledger.withheld() == []


# --------------------------------------------------------------------------- #
# T021 — discretion is confined to non-material decisions
# --------------------------------------------------------------------------- #


def test_a_non_material_decision_may_be_assumed_and_the_assumption_is_recorded():
    ledger = Ledger()
    decision = ledger.open_decision("variable name for the counter", affects=[])
    assumption = ledger.assume(decision.id, "count")
    assert assumption.chosen == "count"
    assert ledger.assumptions == [assumption]
    assert ledger.decision(decision.id).assumption == "count"


@pytest.mark.parametrize("state_before", ["open", "asked", "unresolved", "blocked"])
def test_a_material_decision_can_never_reach_the_assumption_path(state_before):
    ledger = Ledger()
    decision = ledger.open_decision("which database", affects=["architecture"])
    if state_before == "asked":
        ledger.asked(decision.id)
    elif state_before == "unresolved":
        ledger.ended_without_answer(decision.id, "cancelled")
    elif state_before == "blocked":
        ledger.ended_without_answer(decision.id, "unattended")
    with pytest.raises(MaterialDecision):
        ledger.assume(decision.id, "PostgreSQL")
    assert ledger.assumptions == []
    assert ledger.decision(decision.id).assumption == ""


def test_competing_readings_are_material(config):
    """FR-130: `affects=None` — the caller could not say — is material."""
    ledger = Ledger()
    decision = ledger.open_decision("which of two files was meant")
    assert decision.material
    with pytest.raises(MaterialDecision):
        ledger.assume(decision.id, "the first")


def test_the_guard_is_the_materiality_check_itself(monkeypatch):
    """Mutation check: with the check removed, a material decision is assumed."""
    ledger = Ledger()
    decision = ledger.open_decision("which database", affects=["architecture"])

    real = Ledger.assume

    def mutated(self, decision_id, chosen):
        found = self._decisions[decision_id]
        found.assumption = chosen
        found.state = "answered"
        return ev.Assumption(decision_id=found.id, what=found.what, chosen=chosen)

    monkeypatch.setattr(Ledger, "assume", mutated)
    Ledger.assume(ledger, decision.id, "PostgreSQL")     # the mutation lets it through
    assert ledger.decision(decision.id).assumption == "PostgreSQL"

    monkeypatch.setattr(Ledger, "assume", real)
    fresh = Ledger()
    again = fresh.open_decision("which database", affects=["architecture"])
    with pytest.raises(MaterialDecision):
        fresh.assume(again.id, "PostgreSQL")


# --------------------------------------------------------------------------- #
# T022 — mode-aware evidence-first duty
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("mode, inspects", [("act", True), ("plan", True),
                                            ("ask", False), ("chat", False),
                                            ("paln", False)])
def test_whether_a_mode_may_inspect_comes_from_the_policy_table(mode, inspects):
    assert ev.may_inspect(mode) is inspects
    assert Ledger(mode=mode).may_inspect is inspects


def test_in_a_mode_that_cannot_inspect_no_inspection_is_claimed():
    ledger = Ledger(mode="ask")
    decision = ledger.open_decision("which database", affects=["architecture"],
                                    evidence_consulted=["config.py"])
    assert decision.evidence_consulted == []
    assert decision.inspected is False
    assert decision.material, "asking is still possible (FR-032)"


def test_in_a_mode_that_can_inspect_the_evidence_consulted_is_kept():
    ledger = Ledger(mode="plan")
    decision = ledger.open_decision("which database", affects=["architecture"],
                                    evidence_consulted=["config.py", "README.md"])
    assert decision.evidence_consulted == ["config.py", "README.md"]
    assert decision.inspected is True


def test_the_mode_table_is_read_never_written():
    from comodor.safety import modes

    before = {name: modes.policy_for(name) for name in modes.ALL}
    Ledger(mode="ask").open_decision("x", affects=["security"])
    Ledger(mode="paln")
    assert {name: modes.policy_for(name) for name in modes.ALL} == before


# --------------------------------------------------------------------------- #
# T023 — low confidence escalates; hedging is not escalation
# --------------------------------------------------------------------------- #


def test_confidence_above_the_threshold_changes_nothing():
    ledger = Ledger()
    assert ledger.escalate("the API returns JSON", confidence=0.9,
                           affects=["api"]) is None
    assert ledger.decisions == []


def test_low_confidence_alone_never_licenses_certainty():
    ledger = Ledger()
    outcome = ledger.escalate("the API returns JSON", confidence=0.2,
                              affects=[], would_settle="calling it once")
    assert outcome is not None and outcome.kind == "hedge"
    assert "Not verified" in outcome.report()
    assert ledger.may_rely_on("the API returns JSON") is False


def test_low_confidence_on_a_material_conclusion_raises_a_clarification():
    ledger = Ledger()
    outcome = ledger.escalate("dropping the column loses no live data",
                              confidence=0.3, affects=["data loss"],
                              would_settle="a row count on production")
    assert outcome is not None and outcome.kind == "clarification"
    assert outcome.decision is not None and outcome.decision.material
    assert ledger.withheld() == [outcome.decision]
    assert "needs a decision" in outcome.report()


def test_low_confidence_on_a_non_material_point_is_reported_not_asked():
    ledger = Ledger()
    outcome = ledger.escalate("the helper is unused", confidence=0.3, affects=[])
    assert outcome is not None and outcome.kind == "hedge"
    assert ledger.withheld() == []


def test_hedging_language_cannot_substitute_for_escalation(monkeypatch):
    """Mutation check: an escalation that hedged a material point would be
    the conclusion delivered anyway, which FR-115 forbids."""
    ledger = Ledger()
    outcome = ledger.escalate("dropping the column loses no live data",
                              confidence=0.3, affects=["data loss"])
    assert outcome.kind == "clarification"

    real = Ledger.escalate

    def mutated(self, claim, *, confidence, affects=None, would_settle="", threshold=0.5):
        if confidence >= threshold:
            return None
        return ev.Escalation(kind="hedge", claim=claim, would_settle=would_settle)

    monkeypatch.setattr(Ledger, "escalate", mutated)
    hedged = Ledger().escalate("dropping the column loses no live data",
                               confidence=0.3, affects=["data loss"])
    assert hedged.kind == "hedge", "the mutation hedges a material point"
    monkeypatch.setattr(Ledger, "escalate", real)
    restored = Ledger().escalate("dropping the column loses no live data",
                                 confidence=0.3, affects=["data loss"])
    assert restored.kind == "clarification"


# --------------------------------------------------------------------------- #
# T024 — insufficient information is an outcome, not a result
# --------------------------------------------------------------------------- #


def test_insufficient_information_names_what_is_missing():
    ledger = Ledger()
    outcome = ledger.insufficient(["the production row count", "the retention policy"])
    report = outcome.report()
    assert "the production row count" in report
    assert "the retention policy" in report
    assert outcome.ok is False


def test_insufficient_information_is_not_fabricated_success():
    outcome = Ledger().insufficient(["the rate limit"])
    assert outcome.ok is False
    assert "No result was produced" in outcome.report()


def test_insufficient_information_is_not_a_generic_failure():
    outcome = Ledger().insufficient(["the rate limit"])
    assert "Insufficient information" in outcome.report()
    assert "the rate limit" in outcome.report()
    assert "Error" not in outcome.report()


def test_insufficient_information_is_not_a_default_assumption():
    ledger = Ledger()
    ledger.insufficient(["the rate limit"])
    assert ledger.state_of("the rate limit") is S.UNKNOWN
    assert ledger.assumptions == []
    with pytest.raises(ev.IllegalEvidence):
        ledger.insufficient([])


# --------------------------------------------------------------------------- #
# T025 — conflict and partial access are surfaced
# --------------------------------------------------------------------------- #


def test_conflicting_evidence_is_reported_with_both_sources_retained():
    ledger = Ledger()
    a = ledger.verified("the port", source="config.py", material="PORT = 8080")
    b = ledger.verified("the port", source="docker-compose.yml", material="8081:8081")
    conflict = ledger.observe_conflict("the port", sources=["config.py", "docker-compose.yml"])
    assert ledger.get(a.id).state is S.VERIFIED and ledger.get(b.id).state is S.VERIFIED
    assert "config.py disagrees with docker-compose.yml" in conflict.report()
    assert "Not resolved silently" in conflict.report()
    assert ledger.conflicts == [conflict]


def test_uninspected_areas_are_named_in_the_answer():
    ledger = Ledger()
    ledger.could_not_inspect("vendor/ (permission denied)")
    ledger.could_not_inspect("build/ (too large to scan)")
    ledger.could_not_inspect("vendor/ (permission denied)")
    report = ledger.report_partial_access()
    assert "vendor/ (permission denied)" in report
    assert "build/ (too large to scan)" in report
    assert report.count("vendor/") == 1
    assert "Nothing is claimed" in report
    assert Ledger().report_partial_access() == ""


# --------------------------------------------------------------------------- #
# T172 — the semantic decision_ref: minted once, never derived, never d#
# --------------------------------------------------------------------------- #


def _material(book: Ledger, what: str = "Which database?", **kwargs):
    return book.open_decision(what, affects=["persistence"], **kwargs)


def test_two_turns_mint_distinct_refs_for_the_same_question():
    # Two ledgers are two turns. The ledger-local id restarts (`d1` twice);
    # the semantic ref must not, or an answer could close the wrong turn's
    # decision.
    first, second = _material(Ledger()), _material(Ledger())
    assert first.id == second.id
    assert first.ref and second.ref
    assert first.ref != second.ref
    assert ev.well_formed_ref(first.ref) and ev.well_formed_ref(second.ref)


def test_a_ref_is_never_the_ledger_local_id_nor_derived_from_the_wording():
    decision = _material(Ledger(), "Which database should the service use?")
    assert decision.ref != decision.id
    assert not decision.ref.startswith("d1")
    assert "database" not in decision.ref.lower()
    # The same words in another turn give another ref: nothing about the
    # wording, the position or a counter goes into it.
    refs = {_material(Ledger(), "Which database should the service use?").ref
            for _ in range(20)}
    assert len(refs) == 20


@pytest.mark.parametrize("ending", ["cancelled", "expired", "unattended"])
def test_one_decision_keeps_its_ref_whichever_way_the_question_ended(ending):
    book = Ledger()
    decision = _material(book)
    minted = decision.ref
    book.asked(decision.id)
    book.ended_without_answer(decision.id, ending)
    assert book.decision(decision.id).ref == minted


def test_an_injected_minter_makes_refs_deterministic():
    counter = iter(["ref-a", "ref-b", "ref-c"])
    book = Ledger(mint=lambda: next(counter))
    assert _material(book, "Which database?").ref == "ref-a"
    assert _material(book, "Which queue?").ref == "ref-b"


def test_a_ref_is_minted_once_per_decision_not_per_mention():
    minted: list[str] = []

    def mint() -> str:
        minted.append(f"ref-{len(minted) + 1}")
        return minted[-1]

    book = Ledger(mint=mint)
    first = _material(book, "Which database?")
    again = _material(book, "which  DATABASE?")
    assert again.ref == first.ref == "ref-1"
    assert minted == ["ref-1"]


def test_a_decision_raised_again_keeps_the_ref_it_already_has():
    # Carried from a delegate, or put again in a later turn: the decision
    # accepts its original ref instead of minting a new one.
    book = Ledger(mint=lambda: "ref-new")
    carried = _material(book, "Which database?", ref="ref-original")
    assert carried.ref == "ref-original"

    later = Ledger(mint=lambda: "ref-new")
    later.outstanding("Which database?", "ref-original")
    assert _material(later, "Which database?").ref == "ref-original"
    assert _material(later, "Which queue?").ref == "ref-new"


def test_only_a_decision_that_needs_asking_gets_a_ref(config):
    book = Ledger(mint=lambda: "ref-x")
    immaterial = book.open_decision("Tabs or spaces?", affects=[])
    assert immaterial.ref == ""
    book.knowledge("Which database?", "lesson:1", answer="postgres")
    settled = book.open_decision("Which database?", affects=["persistence"])
    assert settled.state == "answered" and settled.ref == ""


def test_the_minter_is_the_module_function_unless_one_is_injected(monkeypatch):
    monkeypatch.setattr(ev, "mint_ref", lambda: "ref-patched")
    assert _material(Ledger()).ref == "ref-patched"


@pytest.mark.parametrize("value, ok", [
    ("dr-0123456789abcdef0123", True), ("ref-1", True), ("", False),
    ("has space", False), ("x" * 65, False), (None, False), (7, False),
    ("-leading", False), ("ok:1.2_3-4", True),
])
def test_what_counts_as_a_well_formed_ref(value, ok):
    assert ev.well_formed_ref(value) is ok
