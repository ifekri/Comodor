"""Execution pauses by state, never by timing (T043; FR-013, FR-018, SC-002).

While a mandatory question is outstanding, no mutating tool runs; after a
non-answer, none runs either. Independent read-only work is not blocked.
Everything here is driven by a controlled bus — the form is answered from
inside the subscriber, so there is no wait to time.
"""

from __future__ import annotations

import json

import pytest

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus, Kind
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools import ask as ask_tool

REQUEST = "SQLite or PostgreSQL? Then write db.py and list the directory."


def a_question():
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database?", "header": "Database", "affects": ["architecture"],
        "options": [{"label": "SQLite", "source": "request", "evidence": "SQLite"},
                    {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"}],
    }]})


def a_write():
    return ToolCall(id="w1", name="write_file",
                    arguments={"path": "db.py", "content": "x\n"})


def a_read():
    return ToolCall(id="r1", name="list_dir", arguments={"path": "."})


def dismiss_forms(event):
    """Dismiss every question form; leave permission prompts alone."""
    if event.kind is Kind.REQUEST and event.payload["request"].kind == "questions":
        event.payload["request"].answer(forms.CANCELLED)


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


def test_no_mutating_tool_runs_before_the_answer_and_it_runs_after(config, bus):
    order = []

    def watch(event):
        if event.kind is Kind.TOOL_START:
            order.append(event.get("name"))
        if event.kind is Kind.REQUEST:
            # Nothing mutating has run yet: the question came first (FR-013).
            assert "write_file" not in order
            event.payload["request"].answer(json.dumps(
                [{"header": "Database", "prompt": "", "chosen": ["SQLite"], "written": ""}]))

    bus.subscribe(watch)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[a_question()]),
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ])
    result = agent.run(REQUEST)
    assert result.ok
    assert order == ["ask", "write_file"]


def test_a_mutating_call_in_the_same_batch_as_a_dismissed_question_does_not_run(config, bus):
    """The model asks and writes in one round: the write is withheld because
    the decision it may depend on is open."""
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Asking and writing.", tool_calls=[a_question(), a_write()]),
        Script(text="never"),
    ])
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"
    assert not (config.paths.project / "db.py").exists()
    tool_messages = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    withheld = [m for m in tool_messages if m.name == "write_file"]
    assert withheld and "required decision is still open" in withheld[0].content


def test_independent_read_only_work_is_not_blocked(config, bus):
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Asking and looking.", tool_calls=[a_question(), a_read()]),
        Script(text="never"),
    ])
    agent.run(REQUEST)
    tool_messages = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    listing = [m for m in tool_messages if m.name == "list_dir"]
    assert listing and not listing[0].is_error


def test_after_a_non_answer_the_turn_ends_so_nothing_dependent_can_follow(config, bus):
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[a_question()]),
        Script(text="Writing anyway.", tool_calls=[a_write()]),
        Script(text="never"),
    ])
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"
    assert result.steps == 1
    assert not (config.paths.project / "db.py").exists()


def test_only_read_only_tools_are_exempt_while_a_decision_is_open(config, bus):
    """`SAFE` is not read-only.

    `memory`, `todo_write` and `delegate` are all SAFE yet persist state or
    start work, so they wait with everything else; only tools that just look
    may still run (FR-018).
    """
    agent = make_agent(config, bus, [Script(text="never")])
    context = agent._tool_context()
    decision = context.evidence.open_decision("Which database?",
                                              affects=["architecture"])
    context.evidence.asked(decision.id)

    def reason(name):
        return AgentLoop._withheld_by(agent, context,
                                      ToolCall(id="c", name=name, arguments={}))

    for name in ("memory", "todo_write", "delegate", "propose_mode", "write_file"):
        assert reason(name), f"{name} must wait for the decision"
    for name in ("read_file", "list_dir", "glob", "grep"):
        assert reason(name) == "", f"{name} is read-only and may still run"


def test_a_batch_with_ask_is_never_run_in_parallel(config, bus):
    """`ask` opens the decision; a SAFE call beside it must not be evaluated
    before the decision exists, or it persists state the answer may forbid."""
    agent = make_agent(config, bus, [Script(text="never")])
    agent._model_profile = lambda: type("P", (), {"parallel_tools": True})()
    agent.config.safety.auto_approve_safe = True

    def call(name):
        return ToolCall(id=name, name=name, arguments={})

    assert agent._can_parallelise([call("read_file"), call("list_dir")]) is True
    for name in ("ask", "delegate"):
        assert agent._can_parallelise([call(name), call("list_dir")]) is False, name


def test_the_guard_is_the_withheld_check(config, bus, monkeypatch):
    """Mutation check (T040): remove the check and the write runs."""
    bus.subscribe(dismiss_forms)
    real = AgentLoop._withheld_by
    monkeypatch.setattr(AgentLoop, "_withheld_by", lambda self, context, call: "")
    agent = make_agent(config, bus, [
        Script(text="Asking and writing.", tool_calls=[a_question(), a_write()]),
        Script(text="never"),
    ])
    agent.run(REQUEST)
    assert (config.paths.project / "db.py").exists(), "the mutation lets the write through"

    (config.paths.project / "db.py").unlink()
    monkeypatch.setattr(AgentLoop, "_withheld_by", real)
    fresh_bus = EventBus()
    fresh_bus.subscribe(dismiss_forms)
    agent = make_agent(config, fresh_bus, [
        Script(text="Asking and writing.", tool_calls=[a_question(), a_write()]),
        Script(text="never"),
    ])
    agent.run(REQUEST)
    assert not (config.paths.project / "db.py").exists()


def test_a_mutation_before_a_material_question_is_preserved_and_reported(config, bus):
    """A write in an earlier step is kept when a material question turns up
    later, and the stop discloses it rather than claiming nothing was done."""
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="never"),
    ])

    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert (config.paths.project / "db.py").exists(), "the earlier write is preserved"
    assert result.clarification["prior_changes"] == ["db.py"]
    assert "Nothing depending on it was done" not in result.text
    assert "preserved" in result.text


def test_a_clarification_with_no_prior_change_reports_none(config, bus):
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Asking.", tool_calls=[a_question()]),
        Script(text="never"),
    ])

    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert "prior_changes" not in result.clarification
    assert "Nothing depending on it was done" in result.text


def test_a_shell_mutation_is_reported_as_a_prior_change(config, bus, monkeypatch):
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    call = ToolCall(id="s1", name="run_shell", arguments={"command": "rm db.py"})
    monkeypatch.setattr(agent, "_run_one",
                        lambda c, ctx: ToolResult.success("done", exit_code=0))

    agent._execute([call])

    assert agent._prior_changes() == ["run_shell"]


def test_a_writing_delegate_is_reported_as_a_prior_change(config, bus, monkeypatch):
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x"})
    monkeypatch.setattr(agent, "_run_one",
                        lambda c, ctx: ToolResult.success("applied", applied=True,
                                                          files=["a.py"]))

    agent._execute([call])

    assert agent._prior_changes() == ["a.py"]


@pytest.mark.parametrize("ending", ["cancelled", "expired", "unattended"])
def test_a_prior_mutation_is_preserved_across_every_ending(
        config, bus, monkeypatch, ending):
    if ending == "cancelled":
        bus.subscribe(dismiss_forms)
    elif ending == "expired":
        bus.subscribe(lambda event: None)
        monkeypatch.setattr(ask_tool, "WAIT_FOR", 0.0)
    # unattended: nobody is subscribed at all.

    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="One thing first.", tool_calls=[a_question()]),
        Script(text="never"),
    ])

    result = agent.run(REQUEST)

    assert result.stopped == "clarification_required"
    assert result.clarification["outcome"] == ending
    assert (config.paths.project / "db.py").exists()
    assert result.clarification["prior_changes"] == ["db.py"]


def test_a_long_shell_command_is_recorded_in_full_for_the_gate(config, bus, monkeypatch):
    """The display summary truncates at 120 characters; the evidence identity
    keeps the whole command, so a write past the cut is still proof."""
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    command = "echo " + "x" * 200 + " > foo.py"
    call = ToolCall(id="s1", name="run_shell", arguments={"command": command})
    monkeypatch.setattr(agent, "_run_one",
                        lambda c, ctx: ToolResult.success("done", exit_code=0))

    agent._execute([call])

    claims = [entry.claim for entry in agent._tool_context().evidence.entries]
    assert any("> foo.py" in claim for claim in claims)


def test_an_in_place_delegates_prior_changes_are_carried(config, bus, monkeypatch):
    """A writing delegate that could not isolate itself works in the parent
    workspace; when it stops for a decision, the changes it reports having
    made are the parent's prior work too (review 4045639914)."""
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x", "write": True})
    monkeypatch.setattr(agent, "_run_one", lambda c, ctx: ToolResult.success(
        "Stopped: a decision is needed.", isolated=False,
        clarification={"kind": "clarification_required", "decision": "Which database?",
                       "candidates": [], "evidence_consulted": [],
                       "reason": "architecture", "outcome": "unattended",
                       "prior_changes": ["models.py", "run_shell"]}))

    agent._execute([call])

    assert agent._prior_changes() == ["models.py", "run_shell"]
    payload = agent._clarification_outcome()
    assert payload["prior_changes"] == ["models.py", "run_shell"]
    assert "preserved" in agent._needs_a_decision(payload)


def test_a_new_turn_forgets_a_carried_delegates_changes(config, bus, monkeypatch):
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x", "write": True})
    monkeypatch.setattr(agent, "_run_one", lambda c, ctx: ToolResult.success(
        "Stopped.", clarification={"kind": "clarification_required",
                                   "decision": "Which database?", "candidates": [],
                                   "evidence_consulted": [], "reason": "architecture",
                                   "outcome": "unattended", "prior_changes": ["models.py"]}))
    agent._execute([call])
    assert agent._prior_changes() == ["models.py"]

    monkeypatch.undo()
    agent.run("say hi")
    assert agent._prior_changes() == []


def test_mutation_dropping_carried_changes_claims_nothing_was_done(
        config, bus, monkeypatch):
    from comodor.providers.base import ToolCall
    from comodor.tools.base import ToolResult

    agent = make_agent(config, bus, [Script(text="never")])
    call = ToolCall(id="d1", name="delegate", arguments={"task": "x", "write": True})
    monkeypatch.setattr(agent, "_run_one", lambda c, ctx: ToolResult.success(
        "Stopped.", clarification={"kind": "clarification_required",
                                   "decision": "Which database?", "candidates": [],
                                   "evidence_consulted": [], "reason": "architecture",
                                   "outcome": "unattended", "prior_changes": ["models.py"]}))
    agent._execute([call])
    agent._carried_changes.clear()                # the mutation: not carried
    assert "prior_changes" not in agent._clarification_outcome()
    assert "Nothing depending on it was done" in agent._needs_a_decision(
        agent._clarification_outcome())

    agent._execute([call])                        # carried again
    assert agent._clarification_outcome()["prior_changes"] == ["models.py"]


# --------------------------------------------------------------------------- #
# T190 — D7 / SC-002: measured per attempt, never as "no write before asking"
# --------------------------------------------------------------------------- #


def a_notes_write():
    return ToolCall(id="n1", name="write_file",
                    arguments={"path": "NOTES.md", "content": "Plan: pick a database.\n"})


def test_d7_a_demonstrably_independent_write_is_permitted_and_is_no_failure(config, bus):
    """(a) Work that does not depend on the decision may run before it is
    known. It is kept, disclosed, and the stop is a clarification — not an
    error and not a failed attempt; only the dependent artifact is absent."""
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Notes first.", tool_calls=[a_notes_write()]),
        Script(text="One question.", tool_calls=[a_question()]),
        Script(text="never"),
    ])
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required" and result.error == ""
    assert (config.paths.project / "NOTES.md").exists()
    assert not (config.paths.project / "db.py").exists()
    assert result.clarification["prior_changes"] == ["NOTES.md"]


def test_d7_a_write_whose_dependence_is_uncertain_is_withheld(config, bus):
    """(b) While the decision is open, a mutation nobody has shown to be
    independent counts as dependent — even one whose name says nothing about
    the decision — and is withheld."""
    bus.subscribe(dismiss_forms)
    agent = make_agent(config, bus, [
        Script(text="Asking and writing notes.", tool_calls=[a_question(), a_notes_write()]),
        Script(text="never"),
    ])
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"
    assert not (config.paths.project / "NOTES.md").exists()


def test_d7_independent_work_is_not_required_and_nothing_starts_to_stay_active(config):
    """(d) With nobody there, the run stops at the decision. It is not made to
    find independent work to do first, and nothing runs after the stop: no
    further model call, no further tool."""
    bus = EventBus()                       # nobody subscribed: unattended
    gateway = Gateway(config, scripts=[
        Script(text="One question.", tool_calls=[a_question()]),
        Script(text="Meanwhile, some tidying.", tool_calls=[a_read(), a_notes_write()]),
        Script(text="never")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    result = agent.run(REQUEST)
    assert result.stopped == "clarification_required"
    assert [m.name for m in agent.conversation.messages if m.role is Role.TOOL] == ["ask"]
    assert len(gateway.provider("fake").calls) == 1
    assert "prior_changes" not in result.clarification
