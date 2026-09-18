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


def test_a_recovered_tool_failure_does_not_block_a_completion_claim(config, bus):
    """A transient failure the same operation recovered is not unresolved work.

    A failed edit followed by a successful retry is a normal way to finish; the
    turn must not be forced to describe completed work as incomplete because
    the first attempt is still being remembered.
    """
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    (config.paths.project / "a.py").write_text("x = 1\n", encoding="utf-8")
    scripts = [
        Script(text="Editing.", tool_calls=[ToolCall(
            id="e1", name="edit_file",
            arguments={"path": "a.py", "old_string": "nope", "new_string": "y"})]),
        Script(text="Retrying.", tool_calls=[ToolCall(
            id="e2", name="edit_file",
            arguments={"path": "a.py", "old_string": "x = 1", "new_string": "x = 2"})]),
        Script(text="The task is complete."),
    ]
    agent = _agent(config, bus, scripts)
    result = agent.run("update a.py")

    assert result.stopped == "done"
    assert len(agent.gateway.provider("fake").calls) == 3, (
        "a recovered failure must not trigger a correction turn")


def test_an_unrecovered_failure_still_blocks_a_completion_claim(config, bus):
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    (config.paths.project / "a.py").write_text("x = 1\n", encoding="utf-8")
    scripts = [
        Script(text="Editing.", tool_calls=[ToolCall(
            id="e1", name="edit_file",
            arguments={"path": "a.py", "old_string": "nope", "new_string": "y"})]),
        Script(text="The task is complete."),
        Script(text="Correction: the work is not complete — the edit never applied."),
    ]
    agent = _agent(config, bus, scripts)
    result = agent.run("update a.py")

    assert result.stopped == "done"
    assert len(agent.gateway.provider("fake").calls) == 3
    assert "not complete" in result.text.lower()


def test_a_carried_decision_ends_a_prose_only_turn(config, bus):
    """A decision a delegate left open is not lost when the model answers in prose.

    The turn was handed an unresolved mandatory decision; the model answers
    without calling a tool, so nothing else would ever report it and the client
    would be told the turn finished normally.
    """
    from comodor.providers.fake import Script

    agent = _agent(config, bus, [Script(text="Here is what I think about it.")])
    decision = {"kind": "clarification_required", "decision": "Which database?",
                "candidates": [], "evidence_consulted": [], "reason": "behaviour",
                "outcome": "cancelled"}

    result = agent.run("continue", decisions=[decision])

    assert result.stopped == "clarification_required"
    assert result.clarification is not None
    assert result.clarification["outcome"] == "cancelled"


def test_cancelling_the_turn_outranks_an_unanswered_form(config, bus):
    """`stopped = "cancelled"` is the turn; a resolved form does not override it."""
    from comodor import questions as forms
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    question = ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database should we use?", "header": "Database",
        "affects": ["persistence"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}]}]})

    def stop_the_turn(event):
        if event.kind is Kind.REQUEST:
            agent.interrupt("stop")
            event.payload["request"].answer(forms.CANCELLED)

    bus.subscribe(stop_the_turn)
    agent = _agent(config, bus, [Script(text="Asking.", tool_calls=[question])])
    result = agent.run("SQLite or PostgreSQL?")

    assert result.stopped == "cancelled"
    assert result.stopped != "clarification_required"


def test_an_unanswered_form_counts_as_a_raised_clarification(config, bus):
    """The mandatory questions that stop a turn are the ones the metric needs."""
    from comodor import questions as forms
    from comodor.events import Kind
    from comodor.providers.base import ToolCall
    from comodor.providers.fake import Script

    def dismiss(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer(forms.CANCELLED)

    bus.subscribe(dismiss)
    question = ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database should we use?", "header": "Database",
        "affects": ["persistence"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}]}]})
    agent = _agent(config, bus, [Script(text="Asking.", tool_calls=[question]),
                                 Script(text="never")])
    result = agent.run("SQLite or PostgreSQL?")

    assert result.stopped == "clarification_required"
    assert result.measurement.clarifications_raised == 1
    assert result.measurement.clarifications_answered == 0


def test_stale_knowledge_is_recorded_in_the_measurement(config, bus):
    class Memory:
        def check_staleness(self, paths=None, tables=None):
            return [{"text": "a learned item", "why": "its source changed"}]

    config.learning.enabled = True
    agent = _agent(config, bus, [])
    agent.memory = Memory()

    note = agent._learning_contradicted("a.py")

    assert "contradicted" in note.lower()
    assert agent._measurement.knowledge_stale == 1


def test_data_lines_are_not_requested_work():
    """A pasted log or an expected/actual table is not a work checklist."""
    from comodor.agent.verify import requested_elements

    assert requested_elements(
        "- fix the parser\n- Expected: 200\n- Actual: 500") == ["fix the parser"]
    assert requested_elements("- 42\n- 200") == []
    assert requested_elements("- add the regression test\n- Update the docs") == [
        "add the regression test", "Update the docs"]


def test_a_read_does_not_deliver_a_mutation_request():
    """Reading `foo.py` is not deleting it: an observation cannot satisfy a
    change/delete/create element (FR-036, FR-116)."""
    ledger = Ledger()
    ledger.verified("read_file foo.py", source="foo.py", material="x = 1")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved


def test_a_changed_path_delivers_a_write_request():
    assessment = verify.assess("- write foo.py", entries=[],
                               changed_paths=["foo.py"], answer="Wrote foo.py.")

    assert assessment.unresolved == []


def test_a_write_does_not_deliver_a_delete_request():
    """Editing `foo.py` is not deleting it: destructive requests need
    destructive or resulting-filesystem evidence (FR-036, FR-116)."""
    ledger = Ledger()
    ledger.verified("write_file foo.py", source="foo.py", material="x = 1")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=["foo.py"], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved


def test_a_destructive_command_delivers_a_delete_request():
    ledger = Ledger()
    ledger.verified("run_shell run: rm foo.py", source="run_shell:rm foo.py",
                    material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert assessment.unresolved == []


def test_a_read_only_shell_command_does_not_deliver_an_update():
    """`cat README.md` is not updating it (FR-036, FR-116)."""
    ledger = Ledger()
    ledger.verified("run_shell run: cat README.md",
                    source="run_shell:cat README.md", material="")

    assessment = verify.assess("- update README.md", entries=ledger.entries,
                               changed_paths=[], answer="Updated README.md.")

    assert "update README.md" in assessment.unresolved


def test_a_writing_shell_command_delivers_an_update():
    ledger = Ledger()
    ledger.verified("run_shell run: echo hi > README.md",
                    source="run_shell:echo", material="")

    assessment = verify.assess("- update README.md", entries=ledger.entries,
                               changed_paths=[], answer="Updated README.md.")

    assert assessment.unresolved == []


def test_a_changed_absolute_path_matches_the_requested_basename():
    """An absolute POSIX path is one keyword token, so the changed-path check
    must also look at the basename the request names (regression: CI Linux)."""
    assessment = verify.assess("- add notes.md", entries=[],
                               changed_paths=["/tmp/pytest-of-x/notes.md"],
                               answer="Added notes.md.")

    assert assessment.unresolved == []


def test_a_quoted_redirection_token_is_not_a_mutation():
    """`grep '> ' foo.py` searches for a string; the `>` is not redirection."""
    ledger = Ledger()
    ledger.verified("run_shell run: grep '> ' foo.py",
                    source="run_shell:grep", material="")

    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")

    assert "update foo.py" in assessment.unresolved


def test_a_python_write_delivers_an_update():
    """`run_python` writes are not shell commands; a `write_text` call is a
    change (FR-036)."""
    ledger = Ledger()
    ledger.verified('run_python from pathlib import Path\nPath("foo.py").write_text("new")',
                    source="run_python:code", material="")

    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")

    assert assessment.unresolved == []


def test_a_commented_out_python_write_is_not_a_mutation():
    """A commented-out `write_text` is not a write (FR-036)."""
    ledger = Ledger()
    ledger.verified('run_python # Path("foo.py").write_text("new")',
                    source="run_python:code", material="")

    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")

    assert "update foo.py" in assessment.unresolved
