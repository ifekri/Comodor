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


def _shell_ledger(command: str) -> Ledger:
    """A verified `run_shell` entry in the loop's own claim format."""
    ledger = Ledger()
    ledger.verified(f"run_shell {command}", source=f"run_shell:{command}",
                    material="")
    return ledger


@pytest.mark.parametrize("command", [
    "grep rm foo.py",
    "grep -n unlink foo.py",
    "cat rm foo.py",
    "sed -n /unlink/p foo.py",
])
def test_a_read_only_shell_command_is_not_delete_evidence(command):
    """An operation word in argument position is not an operation: `grep rm
    foo.py` reads. False destructive evidence would let a false completion
    claim pass (review fix; FR-036, FR-116, FR-125)."""
    assert not verify.shell_deletes(command)
    assert not verify.command_mutates(command)

    assessment = verify.assess("- delete foo.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Deleted foo.py.")

    assert assessment.unresolved == ["delete foo.py"]
    assert assessment.contradicted
    assert assessment.verdict == "block"


@pytest.mark.parametrize("command", ["grep cp foo.py", "printf touch foo.py"])
def test_a_read_only_shell_command_is_not_a_mutation(command):
    """`grep cp foo.py` names a write word and writes nothing (review fix)."""
    assert not verify.shell_writes(command)
    assert not verify.command_mutates(command)

    assessment = verify.assess("- update foo.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Updated foo.py.")

    assert assessment.unresolved == ["update foo.py"]
    assert assessment.verdict == "block"


@pytest.mark.parametrize("command", ["grep mv foo.py", "printf rename foo.py"])
def test_a_read_only_shell_command_is_not_move_evidence(command):
    """A read-only command that names a move word moves nothing (review fix)."""
    assert not verify.shell_moves(command)

    assessment = verify.assess("- move foo.py to bar.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Moved foo.py to bar.py.")

    assert assessment.unresolved == ["move foo.py to bar.py"]
    assert assessment.verdict == "block"


@pytest.mark.parametrize("command", [
    "rm foo.py", "git rm foo.py", "rmdir build", "unlink foo.py",
])
def test_a_delete_command_is_delete_evidence(command):
    assert verify.shell_deletes(command)
    assert verify.command_mutates(command)


@pytest.mark.parametrize("command", ["mv old.py new.py", "git mv old.py new.py"])
def test_a_move_command_is_move_evidence(command):
    assert verify.shell_moves(command)
    assert verify.command_mutates(command)


@pytest.mark.parametrize("command", [
    "cp source.py target.py", "touch foo.py", "sed -i s/a/b/ foo.py",
    "tee out.txt", "truncate -s 0 foo.py", "xcopy a b /E", "robocopy a b",
])
def test_a_write_command_is_mutation_evidence(command):
    assert verify.shell_writes(command)
    assert verify.command_mutates(command)


@pytest.mark.parametrize("command", [
    "echo hi > foo.txt", "echo hi>foo.txt", "echo hi >> foo.txt",
    "echo hi>>foo.txt", "echo hi 1>foo.txt", "echo err 2>errors.log",
    "echo err 2>>errors.log",
])
def test_an_output_redirection_is_a_mutation(command):
    assert verify.shell_writes(command)
    assert verify.command_mutates(command)


@pytest.mark.parametrize("command", [
    "echo hi 2>&1", "echo hi 1>&2", "echo hi >&2", "grep '> ' foo.py",
    "cat foo.py # > backup", "cat <file", "cat <<EOF",
])
def test_a_descriptor_duplication_or_input_is_not_a_mutation(command):
    assert not verify.shell_writes(command)
    assert not verify.command_mutates(command)


def test_shell_evidence_claim_prefixes_are_stripped():
    """`run_shell run:` must not take part in command classification."""
    assert verify._shell_command("run_shell rm foo.py") == "rm foo.py"
    assert verify._shell_command("run_shell run: rm foo.py") == "rm foo.py"
    assert verify.shell_deletes(verify._shell_command("run_shell run: rm foo.py"))
    assert not verify.shell_deletes(
        verify._shell_command("run_shell run: grep rm foo.py"))


@pytest.mark.parametrize("command", [
    "cat <<'EOF'\nrm foo.py\nEOF",
    "cat <<EOF\nrm foo.py\nEOF",
    'cat <<"EOF"\nrm foo.py\nEOF',
    "cat <<-EOF\n\trm foo.py\n\tEOF",
    "cat <<-'EOF'\n\trm foo.py\n\tEOF",
    "cat <<EOF\nmv a.py b.py\nEOF",
    "cat <<EOF\ncp source.py target.py\nEOF",
    "cat <<EOF\ntouch foo.py\nEOF",
])
def test_a_heredoc_body_is_not_a_shell_operation(command):
    """A heredoc body is stdin data, not commands: `cat <<'EOF'` followed by
    `rm foo.py` deletes nothing. Every heredoc form must leave the body
    unread (review fix; FR-036, FR-116, FR-125)."""
    assert not verify.shell_writes(command)
    assert not verify.shell_deletes(command)
    assert not verify.shell_moves(command)
    assert not verify.command_mutates(command)


def test_a_heredoc_delete_body_does_not_deliver_a_delete_request():
    command = "cat <<'EOF'\nrm foo.py\nEOF"
    assessment = verify.assess("- delete foo.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Deleted foo.py.")
    assert assessment.unresolved == ["delete foo.py"]
    assert assessment.contradicted
    assert assessment.verdict == "block"


def test_a_heredoc_move_body_does_not_deliver_a_move_request():
    command = "cat <<EOF\nmv a.py b.py\nEOF"
    assessment = verify.assess("- move a.py to b.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Moved a.py to b.py.")
    assert assessment.unresolved == ["move a.py to b.py"]
    assert assessment.verdict == "block"


def test_a_heredoc_write_word_body_does_not_deliver_an_update_request():
    command = "cat <<EOF\ntouch foo.py\nEOF"
    assessment = verify.assess("- update foo.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Updated foo.py.")
    assert assessment.unresolved == ["update foo.py"]
    assert assessment.verdict == "block"


def test_a_real_header_redirection_survives_its_heredoc():
    """`cat > deploy.sh <<EOF` writes deploy.sh through the header redirect;
    the body must not add a delete or move (review fix; FR-036)."""
    command = "cat > deploy.sh <<EOF\nrm build\nEOF"
    assert verify.shell_writes(command)
    assert not verify.shell_deletes(command)
    assert not verify.shell_moves(command)

    updated = verify.assess("- update deploy.sh",
                            entries=_shell_ledger(command).entries,
                            changed_paths=[],
                            answer="The task is complete. Updated deploy.sh.")
    assert updated.unresolved == []

    for request, answer in (("- update build", "Updated build."),
                            ("- delete build", "Deleted build.")):
        blocked = verify.assess(request, entries=_shell_ledger(command).entries,
                                changed_paths=[],
                                answer=f"The task is complete. {answer}")
        assert blocked.unresolved == [request.removeprefix("- ")], request
        assert blocked.verdict == "block", request


def test_a_body_path_cannot_piggyback_on_an_unrelated_real_write():
    """`cat > deploy.sh <<EOF` writes deploy.sh; `foo.py` in the body is data,
    not evidence that foo.py changed (review fix; FR-036, FR-116)."""
    command = "cat > deploy.sh <<EOF\nfoo.py\nEOF"
    assert verify.shell_writes(command)

    assessment = verify.assess("- update foo.py",
                               entries=_shell_ledger(command).entries,
                               changed_paths=[],
                               answer="The task is complete. Updated foo.py.")
    assert assessment.unresolved == ["update foo.py"]
    assert assessment.verdict == "block"


def test_a_real_header_operation_survives_its_heredoc():
    """`rm actual.txt <<EOF` deletes actual.txt; the body must not become a
    move of `fake.txt` (review fix; FR-036)."""
    command = "rm actual.txt <<EOF\nmv fake.txt other.txt\nEOF"
    assert verify.shell_deletes(command)
    assert not verify.shell_moves(command)

    deleted = verify.assess("- delete actual.txt",
                            entries=_shell_ledger(command).entries,
                            changed_paths=[],
                            answer="The task is complete. Deleted actual.txt.")
    assert deleted.unresolved == []

    moved = verify.assess("- move fake.txt to other.txt",
                          entries=_shell_ledger(command).entries,
                          changed_paths=[],
                          answer="The task is complete. Moved fake.txt to other.txt.")
    assert moved.verdict == "block"


def test_multiple_heredocs_on_one_line_are_each_removed():
    command = "cat <<A <<B\nrm x.py\nA\nmv y.py z.py\nB"
    assert not verify.shell_writes(command)
    assert not verify.shell_deletes(command)
    assert not verify.shell_moves(command)


def test_a_commented_heredoc_declaration_does_not_swallow_the_next_command():
    """`# cat <<EOF` is a comment, so the line after it is a real command and
    `rm foo.py` still deletes."""
    assert verify.shell_deletes("# cat <<EOF\nrm foo.py\nEOF")


@pytest.mark.parametrize("command", [
    "cat >(grep foo.py)", "echo hi >(cat)", "cat >(grep x) foo.py",
])
def test_process_substitution_is_not_output_redirection(command):
    """`>(cmd)` is process substitution, not a file output redirection
    (review fix)."""
    assert not verify.shell_writes(command)


@pytest.mark.parametrize("command", [
    "echo hi > foo.txt", "echo hi >> foo.txt", "echo hi >|foo.txt",
    "echo hi 1>foo.txt", "echo err 2>errors.log", "echo err 2>>errors.log",
])
def test_a_plain_output_redirection_is_still_a_mutation(command):
    assert verify.shell_writes(command)


def test_a_python_remove_delivers_a_delete_request():
    """`run_python` is read as code, so `os.remove` is delete evidence
    (review fix; FR-036, FR-116)."""
    ledger = Ledger()
    ledger.verified("run_python os.remove('foo.py')", source="run_python:code",
                    material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert assessment.unresolved == []


def test_a_python_path_unlink_delivers_a_delete_request():
    ledger = Ledger()
    ledger.verified('run_python Path("foo.py").unlink()', source="run_python:code",
                    material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert assessment.unresolved == []


def test_a_python_path_rmdir_delivers_a_delete_request():
    ledger = Ledger()
    ledger.verified('run_python Path("build/cache").rmdir()',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete build/cache", entries=ledger.entries,
                               changed_paths=[], answer="Deleted build/cache.")

    assert assessment.unresolved == []


def test_a_python_rmtree_delivers_a_delete_request():
    ledger = Ledger()
    ledger.verified('run_python shutil.rmtree("build/cache")',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete build/cache", entries=ledger.entries,
                               changed_paths=[], answer="Deleted build/cache.")

    assert assessment.unresolved == []


def test_an_ordinary_python_write_does_not_deliver_a_delete_request():
    """A write is not a delete, even read as code (review fix)."""
    ledger = Ledger()
    ledger.verified('run_python Path("foo.py").write_text("x")',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved


def test_a_python_delete_inside_a_string_does_not_deliver_a_delete_request():
    """`print('os.remove("foo.py")')` prints; nothing is deleted. The AST
    reading introduced in e46df9a is what makes this true."""
    ledger = Ledger()
    ledger.verified('run_python print(\'os.remove("foo.py")\')',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved
    assert not verify.python_deletes('print(\'os.remove("foo.py")\')')
    assert not verify.python_deletes('# os.remove("foo.py")')
    assert not verify.python_deletes('x = "Path(\\"foo.py\\").unlink()"')


@pytest.mark.parametrize("code", [
    'import os\nos.remove("foo.py")',
    'import os\nos.unlink("foo.py")',
    'import os\nos.rmdir("build/cache")',
    'from pathlib import Path\nPath("foo.py").unlink()',
    'from pathlib import Path\nPath("build/cache").rmdir()',
    'import shutil\nshutil.rmtree("build/cache")',
])
def test_python_deletes_recognises_executable_deletes(code):
    assert verify.python_deletes(code)


def test_python_rmdir_is_also_a_mutation():
    """`Path.rmdir()` deletes, so it is a write too — mutation tracking and
    delete evidence agree (review fix)."""
    assert verify.command_mutates('Path("build/cache").rmdir()', "run_python")


@pytest.mark.parametrize("code", [
    'from os import remove\nremove("foo.py")',
    'from os import remove as rmfile\nrmfile("foo.py")',
    'from os import unlink\nunlink("foo.py")',
    'from os import rmdir\nrmdir("build/cache")',
    'import os as o\no.remove("foo.py")',
    'import os as o\no.rmdir("build/cache")',
    'from shutil import rmtree\nrmtree("build/cache")',
    'from shutil import rmtree as remove_tree\nremove_tree("build/cache")',
    'import shutil as sh\nsh.rmtree("build/cache")',
    'from pathlib import Path as P\nP("foo.py").unlink()',
    'import pathlib as pl\npl.Path("build/cache").rmdir()',
    'import pathlib\npathlib.Path("foo.py").unlink()',
])
def test_python_deletes_resolves_aliases_and_from_imports(code):
    """An aliased or from-imported call is the function it names, not a
    different operation (review fix; FR-036, FR-116)."""
    assert verify.python_deletes(code)


def test_a_simple_path_binding_is_followed_to_a_delete():
    """`p = Path("foo"); p.unlink()` is a delete: the bounded binding analysis
    follows a name assigned exactly once to a path (review fix)."""
    code = 'from pathlib import Path\np = Path("foo.py")\np.unlink()'
    assert verify.python_deletes(code)
    assert verify.command_mutates(code, "run_python")


@pytest.mark.parametrize("code", [
    'from os import remove as rmfile\nrmfile("foo.py")',
    'import os as o\no.remove("foo.py")',
    'from shutil import rmtree as remove_tree\nremove_tree("build/cache")',
    'import shutil as sh\nsh.rmtree("build/cache")',
    'from pathlib import Path as P\nP("foo.py").unlink()',
    'import pathlib as pl\npl.Path("build/cache").rmdir()',
])
def test_an_aliased_python_mutation_is_tracked(code):
    """Mutation tracking resolves the same aliases the delete check does: a
    recognised delete must also count as a write (review fix; FR-036)."""
    assert verify.command_mutates(code, "run_python")


def test_an_ordinary_path_write_is_a_mutation_but_not_a_delete():
    """`Path.write_text` is a write and not a delete (review fix)."""
    assert verify.python_writes('Path("foo.py").write_text("x")')
    assert not verify.python_deletes('Path("foo.py").write_text("x")')


@pytest.mark.parametrize("code", [
    'from multiprocessing.shared_memory import SharedMemory\n'
    'SharedMemory(name="foo.py").unlink()',
    'class Cache:\n'
    '    def unlink(self, value):\n'
    '        pass\n'
    'Cache().unlink("foo.py")',
    'print(\'os.remove("foo.py")\')',
    'x = \'Path("foo.py").unlink()\'',
    '# os.remove("foo.py")',
])
def test_a_non_filesystem_unlink_is_not_a_delete(code):
    """A method is a filesystem delete only when its receiver is a path: an
    arbitrary `.unlink()` deletes no file (review fix; FR-116)."""
    assert not verify.python_deletes(code)


def test_an_aliased_python_delete_delivers_a_delete_request():
    """`run_python` read from the syntax tree: a from-imported delete is
    delivery for the delete request (review fix; FR-036)."""
    ledger = Ledger()
    ledger.verified('run_python from os import remove\nremove("foo.py")',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert assessment.unresolved == []


def test_a_non_filesystem_unlink_does_not_deliver_a_delete_request():
    """`SharedMemory(...).unlink()` names the path and deletes no file, so a
    `delete foo.py` request stays unresolved (review fix; FR-116)."""
    ledger = Ledger()
    ledger.verified('run_python from multiprocessing.shared_memory import SharedMemory\n'
                    'SharedMemory(name="foo.py").unlink()',
                    source="run_python:code", material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved


@pytest.mark.parametrize("code", [
    # A module alias rebound to a non-filesystem object.
    'import os as o\n'
    'class Dummy:\n'
    '    def remove(self, path):\n'
    '        pass\n'
    'o = Dummy()\n'
    'o.remove("foo.py")',
    # A from-imported function rebound by a `def` of the same name.
    'from os import remove\n'
    'def remove(path):\n'
    '    pass\n'
    'remove("foo.py")',
    # ... and by an assignment or a lambda.
    'import os as o\n'
    'o = object()\n'
    'o.remove("foo.py")',
    'from os import remove\n'
    'remove = lambda path: None\n'
    'remove("foo.py")',
    # A parameter shadows the module name inside the function.
    'import os\n'
    'def execute(os):\n'
    '    os.remove("foo.py")\n'
    'execute(object())',
    # An import in a sibling function does not reach this one.
    'def first():\n'
    '    import os as o\n'
    'def second(o):\n'
    '    o.remove("foo.py")',
    'def first():\n'
    '    import os as o\n'
    'def second():\n'
    '    o.remove("foo.py")',
    # A comprehension target shadows the alias in its own scope.
    'import os as o\n'
    '[o.remove("x") for o in items]',
])
def test_shadowed_or_rebound_imports_are_not_filesystem_deletes(code):
    """A binding is filesystem evidence only in the scope that holds it: a
    parameter, `def`, assignment, comprehension target or sibling scope that
    rebinds the name is not the import it shadows (review fix; FR-036,
    FR-116)."""
    assert not verify.python_deletes(code)
    assert not verify.command_mutates(code, "run_python")


@pytest.mark.parametrize("code", [
    # A path binding in one function does not reach a sibling function.
    'def first():\n'
    '    p = Path("foo.py")\n'
    'def second():\n'
    '    p.unlink()',
    # A parameter shadows a module-level path binding.
    'from pathlib import Path\n'
    'p = Path("foo.py")\n'
    'def f(p):\n'
    '    p.unlink()',
])
def test_a_scope_leaked_or_shadowed_path_is_not_a_delete(code):
    """A pathlib delete needs a receiver established as a path in *its* scope
    (review fix; FR-116)."""
    assert not verify.python_deletes(code)


def test_a_function_local_import_alias_is_a_delete():
    """The scope correction keeps the legitimate form: an import inside the
    function that uses it is still the module function (review fix)."""
    code = ('def f():\n'
            '    import os as o\n'
            '    o.remove("foo.py")')
    assert verify.python_deletes(code)
    assert verify.command_mutates(code, "run_python")


def test_a_function_local_path_binding_is_a_delete():
    """`p = Path(...)` inside the function that calls `p.unlink()` (review
    fix)."""
    code = ('from pathlib import Path\n'
            'def f():\n'
            '    p = Path("foo.py")\n'
            '    p.unlink()')
    assert verify.python_deletes(code)
    assert verify.command_mutates(code, "run_python")


@pytest.mark.parametrize("code", [
    'import os as o\n'
    'class Dummy:\n'
    '    def remove(self, path):\n'
    '        pass\n'
    'o = Dummy()\n'
    'o.remove("foo.py")',
    'from os import remove\n'
    'def remove(path):\n'
    '    pass\n'
    'remove("foo.py")',
    'import os\n'
    'def execute(os):\n'
    '    os.remove("foo.py")\n'
    'execute(object())',
    'def first():\n'
    '    import os as o\n'
    'def second(o):\n'
    '    o.remove("foo.py")',
])
def test_a_shadowed_delete_does_not_deliver_a_delete_request(code):
    """The completion gate must not accept a shadowed call as delete evidence
    (review fix; FR-036, FR-116, FR-125)."""
    ledger = Ledger()
    ledger.verified(f"run_python {code}", source="run_python:code", material="")

    assessment = verify.assess("- delete foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Deleted foo.py.")

    assert "delete foo.py" in assessment.unresolved


def test_a_function_local_import_delete_delivers_a_delete_request():
    """A legitimate function-local import alias still satisfies the gate
    (review fix; FR-036)."""
    ledger = Ledger()
    ledger.verified('run_python def f():\n    import os as o\n    o.remove("foo.py")',
                    source="run_python:code", material="")

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


def test_a_python_open_write_delivers_an_update():
    """`open("foo.py", "w").write(...)` keeps its mode literal, so the Python
    detector still sees the write (FR-036)."""
    ledger = Ledger()
    ledger.verified('run_python open("foo.py", "w").write("new")',
                    source="run_python:code", material="")

    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")

    assert assessment.unresolved == []


def test_a_commented_redirection_is_not_a_mutation():
    """`cat foo.py # > backup` reads: the `>` is inside a shell comment
    (review 4045469341)."""
    ledger = Ledger()
    ledger.verified("run_shell run: cat foo.py # > backup",
                    source="run_shell:cat", material="")

    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")

    assert "update foo.py" in assessment.unresolved


def test_a_hash_inside_a_word_or_quotes_is_not_a_comment():
    """`$#`, `a#b` and a quoted `#` do not start a comment, so the redirection
    after them is real."""
    assert verify.command_mutates("echo $# > out.txt")
    assert verify.command_mutates("cat a#b > c")
    assert verify.command_mutates("echo '#' > out.txt")
    assert not verify.command_mutates("cat foo.py # > backup")
    assert not verify.command_mutates("ls; # rm foo.py")
    assert not verify.command_mutates("grep '> ' foo.py")


def test_mutation_keeping_comments_accepts_a_commented_write(monkeypatch):
    """With comment stripping removed, the commented `>` is read as
    redirection and the read-only command delivers an update."""
    import re

    monkeypatch.setattr(verify, "_unquoted",
                        lambda command: re.sub(r"'[^']*'|\"[^\"]*\"", " ", command or ""))
    ledger = Ledger()
    ledger.verified("run_shell run: cat foo.py # > backup",
                    source="run_shell:cat", material="")
    mutated = verify.assess("- update foo.py", entries=ledger.entries,
                            changed_paths=[], answer="Updated foo.py.")
    assert mutated.unresolved == [], "the mutation: a comment delivers"

    monkeypatch.undo()
    restored = verify.assess("- update foo.py", entries=ledger.entries,
                             changed_paths=[], answer="Updated foo.py.")
    assert "update foo.py" in restored.unresolved


@pytest.mark.parametrize("mode", ["wb", "w+", "wt", "ab", "a+", "xb", "r+", "rb+"])
def test_every_writable_python_open_mode_is_a_mutation(mode):
    """`open(..., "wb")`, `"w+"` and `"r+"` write as surely as `"w"` does
    (review 4045639927)."""
    assert verify.command_mutates(f'open("foo.bin", "{mode}").write(b"x")', "run_python")
    assert verify.command_mutates(f'open("foo.bin", mode="{mode}")', "run_python")


@pytest.mark.parametrize("mode", ["r", "rb", "rt"])
def test_a_read_only_python_open_is_not_a_mutation(mode):
    assert not verify.command_mutates(f'open("foo.bin", "{mode}").read()', "run_python")


def test_a_binary_python_write_delivers_an_update():
    ledger = Ledger()
    ledger.verified('run_python open("foo.bin", "wb").write(b"new")',
                    source="run_python:code", material="")

    assessment = verify.assess("- update foo.bin", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.bin.")

    assert assessment.unresolved == []


def test_a_copy_request_is_not_delivered_by_reading_the_destination():
    """`- Copy config.example to config.ini` is a mutation; a read of
    config.ini names the path and changes nothing (review 4045800935)."""
    ledger = Ledger()
    ledger.verified("read_file config.ini", source="read_file:config.ini", material="")

    assessment = verify.assess("- Copy config.example to config.ini",
                               entries=ledger.entries, changed_paths=[],
                               answer="Copied config.example to config.ini.")

    assert assessment.unresolved == ["Copy config.example to config.ini"]


def test_a_copy_request_is_delivered_by_a_copy_command_or_a_changed_path():
    ledger = Ledger()
    ledger.verified("run_shell run: cp config.example config.ini",
                    source="run_shell:cp", material="")
    by_command = verify.assess("- Copy config.example to config.ini",
                               entries=ledger.entries, changed_paths=[],
                               answer="Copied config.example to config.ini.")
    assert by_command.unresolved == []

    by_path = verify.assess("- Copy config.example to config.ini", entries=[],
                            changed_paths=["config.ini"],
                            answer="Copied config.example to config.ini.")
    assert by_path.unresolved == []


@pytest.mark.parametrize("command", ["cp a b", "copy a b", "xcopy a b /E", "robocopy a b"])
def test_copy_commands_are_mutations(command):
    assert verify.command_mutates(command)


def test_the_learning_staleness_check_reads_commands_as_the_gate_does():
    from comodor.learning import memory as memory_module

    assert memory_module.shell_writes is verify.shell_writes
    assert memory_module.python_writes is verify.python_writes


def test_a_write_inside_a_python_string_is_not_a_mutation():
    """`print('Path("foo.py").write_text("new")')` prints; nothing is written
    (review 4045928907)."""
    code = 'print(\'Path("foo.py").write_text("new")\')'
    assert not verify.command_mutates(code, "run_python")
    assert not verify.command_mutates('x = "os.remove(\'foo.py\')"', "run_python")
    assert not verify.command_mutates('"""open("foo.py", "w")"""', "run_python")

    ledger = Ledger()
    ledger.verified(f"run_python {code}", source="run_python:code", material="")
    assessment = verify.assess("- update foo.py", entries=ledger.entries,
                               changed_paths=[], answer="Updated foo.py.")
    assert "update foo.py" in assessment.unresolved


@pytest.mark.parametrize("code", [
    'from pathlib import Path\nPath("foo.py").write_text("new")',
    'import os\nos.remove("foo.py")',
    'import shutil\nshutil.copy("a", "foo.py")',
    'with open("foo.py", "w") as handle:\n    handle.write("x")',
    'open("foo.py", mode="a+").write("x")',
    'target.unlink()',
])
def test_an_executable_python_write_is_a_mutation(code):
    assert verify.command_mutates(code, "run_python")


def test_a_non_literal_open_mode_is_not_evidence_of_a_write():
    assert not verify.command_mutates('open("foo.py", mode).read()', "run_python")


def test_unparseable_python_falls_back_to_the_text_reading():
    assert verify.command_mutates('Path("foo.py").write_text("x"', "run_python")
    assert not verify.command_mutates('print("hello"', "run_python")


def test_mutation_reading_python_as_text_accepts_a_printed_write(monkeypatch):
    import re

    monkeypatch.setattr(verify, "python_writes", lambda code: bool(
        verify._PYTHON_MUTATION.search(verify._python_code(code))))
    code = 'print(\'Path("foo.py").write_text("new")\')'
    ledger = Ledger()
    ledger.verified(f"run_python {code}", source="run_python:code", material="")
    mutated = verify.assess("- update foo.py", entries=ledger.entries,
                            changed_paths=[], answer="Updated foo.py.")
    assert mutated.unresolved == [], "the mutation: a printed write delivers"
    assert re.search(r"write_text", code)

    monkeypatch.undo()
    restored = verify.assess("- update foo.py", entries=ledger.entries,
                             changed_paths=[], answer="Updated foo.py.")
    assert "update foo.py" in restored.unresolved
