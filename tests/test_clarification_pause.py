"""Execution pauses by state, never by timing (T043; FR-013, FR-018, SC-002).

While a mandatory question is outstanding, no mutating tool runs; after a
non-answer, none runs either. Independent read-only work is not blocked.
Everything here is driven by a controlled bus — the form is answered from
inside the subscriber, so there is no wait to time.
"""

from __future__ import annotations

import json

from comodor import questions as forms
from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus, Kind
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

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
