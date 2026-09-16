"""The completion gate: request versus delivery (T120–T125; FR-036, FR-037,
FR-116, FR-124 to FR-127).

Annotate by default; block only an explicit completion claim the gathered
evidence contradicts; never withhold an honest partial answer; and never
claim completion while a required decision is open.
"""

from __future__ import annotations

import pytest

from comodor.agent import verify
from comodor.agent.claims import claims_completion
from comodor.agent.evidence import Ledger


def _pending(ledger, what="Which database should we use?"):
    decision = ledger.open_decision(what, affects=("persistence",))
    ledger.ended_without_answer(decision.id, "cancelled")
    return decision


# --------------------------------------------------------------------------- #
# the verdict rules
# --------------------------------------------------------------------------- #


def test_a_plain_request_needs_no_intervention():
    ledger = Ledger()
    ledger.known("the request, as the user stated it", material="fix the parser")
    assessment = verify.assess("fix the parser", entries=ledger.entries, answer="Fixed the parser.")
    assert assessment.verdict == "no_intervention"
    assert assessment.unresolved == []


def test_an_undelivered_element_is_annotated_not_blocked():
    ledger = Ledger()
    ledger.verified("the parser is fixed", source="parser.py", material="def parse():")
    assessment = verify.assess(
        "- fix the parser\n- add a regression test",
        entries=ledger.entries, changed_paths=["parser.py"],
        answer="I fixed the parser.")
    assert "add a regression test" in assessment.unresolved
    assert assessment.verdict == "annotate"
    assert "add a regression test" in assessment.annotation()


def test_a_contradicted_completion_claim_blocks():
    ledger = Ledger()
    assessment = verify.assess(
        "- fix the parser\n- add a regression test",
        entries=ledger.entries, changed_paths=["parser.py"],
        answer="The task is complete.")
    assert assessment.claims_completion
    assert assessment.contradicted
    assert assessment.verdict == "block"
    assert "incomplete" in verify.as_incomplete(assessment).lower()


def test_an_honest_partial_answer_is_never_blocked():
    assessment = verify.assess(
        "- fix the parser\n- add a regression test",
        entries=[], changed_paths=["parser.py"],
        answer="I fixed the parser, but I have not added the regression test yet.")
    assert not assessment.claims_completion
    assert assessment.verdict == "annotate"


# --------------------------------------------------------------------------- #
# the requests the gate acts on
# --------------------------------------------------------------------------- #


def test_prose_is_not_parsed_into_a_checklist():
    assert verify.requested_elements("fix the parser and add a test") == []
    assert verify.requested_elements("- fix the parser\n- add a test") == [
        "fix the parser", "add a test"]


def test_a_failed_tool_call_is_unresolved_work():
    assessment = verify.assess(
        "fix it", entries=[], failures=[("edit_file", "old_string not found")],
        answer="The task is complete.")
    assert any("edit_file" in what for what in assessment.unresolved)
    assert assessment.verdict == "block"
    assert "not found" in assessment.unresolved_reasons[
        next(w for w in assessment.unresolved if "edit_file" in w)]


def test_a_pending_decision_is_named_with_what_blocks_it():
    ledger = Ledger()
    decision = _pending(ledger)
    assessment = verify.assess("fix it", entries=ledger.entries,
                               pending=[decision], answer="All done.")
    assert assessment.pending_clarification == decision.id
    assert any("database" in what for what in assessment.unresolved)
    assert assessment.verdict == "block"
    assert "open decision" in " ".join(assessment.unresolved_reasons.values())


# --------------------------------------------------------------------------- #
# the completion-claim detector's bar
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("answer", [
    "The task is complete.", "Everything is done.", "I have finished the work.",
    "All done — the parser works.",
])
def test_a_plain_completion_claim_is_recognised(answer):
    assert claims_completion(answer)


@pytest.mark.parametrize("answer", [
    "This is not complete yet.", "If the tests pass, the task is complete.",
    "Make sure the task is complete before you stop.",
    "I cannot say the task is complete.",
    "The task is still incomplete.",
])
def test_a_hedge_negation_or_instruction_is_not_a_claim(answer):
    assert not claims_completion(answer)


def test_the_gate_never_verifies_work_it_did_not_do():
    """A failure is reported with its evidence; it is not re-characterised as
    success (FR-116)."""
    ledger = Ledger()
    ledger.unknown("the required edit")
    assessment = verify.assess(
        "- apply the edit", entries=ledger.entries, failures=[("edit_file", "no match")],
        answer="The task is complete.")
    assert assessment.verdict == "block"


# --------------------------------------------------------------------------- #
# wired into the loop
# --------------------------------------------------------------------------- #


def _agent(config, bus, scripts):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    config.safety.auto_approve_writes = True
    return AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                     bus, PermissionEngine(config, bus), Conversation())


def test_the_loop_corrects_a_contradicted_completion_claim_once(config, bus):
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    scripts = [
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file", arguments={"path": "parser.py", "content": "x = 1\n"})]),
        Script(text="The task is complete."),
        Script(text="Correction: the work is not complete — the regression test is missing."),
    ]
    agent = _agent(config, bus, scripts)
    result = agent.run("- fix the parser\n- add a regression test")

    assert result.stopped == "done"
    assert len(agent.gateway.provider("fake").calls) == 3, "exactly one correction turn"
    assert "not complete" in result.text.lower()


def test_the_loop_annotates_without_blocking_an_honest_answer(config, bus):
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    notices: list[str] = []
    bus.subscribe(lambda event: notices.append(event.text)
                  if event.kind is Kind.NOTICE else None)
    scripts = [
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file", arguments={"path": "parser.py", "content": "x = 1\n"})]),
        Script(text="I fixed the parser; the regression test is still to come."),
    ]
    agent = _agent(config, bus, scripts)
    result = agent.run("- fix the parser\n- add a regression test")

    assert result.stopped == "done"
    assert len(agent.gateway.provider("fake").calls) == 2, "an honest answer is not blocked"
    assert any("Not everything" in text for text in notices), notices


def test_an_open_decision_ends_the_turn_not_a_false_success(config, bus):
    from comodor import questions as forms
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    def dismiss(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(forms.CANCELLED)

    bus.subscribe(dismiss)
    question = ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database should we use?",
        "header": "Database", "affects": ["persistence"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}]}]})
    scripts = [Script(text="Asking.", tool_calls=[question]), Script(text="never")]
    agent = _agent(config, bus, scripts)
    result = agent.run("SQLite or PostgreSQL?")

    assert result.stopped == "clarification_required"
    assert result.stopped != "done"
