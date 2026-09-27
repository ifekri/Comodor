"""Validation is proportional to what the turn touched (T127; FR-042, FR-043).

A turn that changed nothing runs no project check. A turn that changed
something runs it once. It is never run for a read-only answer, and never
repeated in a loop.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.events import Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def _agent(config, bus, scripts):
    return AgentLoop(config, Gateway(config, scripts=scripts), ToolRegistry(),
                     bus, PermissionEngine(config, bus), Conversation())


def _watch(bus):
    seen: list[str] = []
    bus.subscribe(lambda event: seen.append(event.text)
                  if event.kind is Kind.NOTICE and "Running" in event.text else None)
    return seen


def test_a_turn_that_changed_nothing_runs_no_check(config, bus):
    config.agent.verify_command = "echo check"
    checks = _watch(bus)
    scripts = [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="read_file", arguments={"path": "a.py"})]),
        Script(text="The file defines a helper."),
    ]
    agent = _agent(config, bus, scripts)
    agent.run("what does a.py do?")
    assert checks == []


def test_a_turn_that_changed_a_file_runs_the_check_once(config, bus):
    config.safety.auto_approve_writes = True
    config.agent.verify_command = "echo check"
    checks = _watch(bus)
    scripts = [
        Script(text="Writing.", tool_calls=[ToolCall(
            id="w1", name="write_file",
            arguments={"path": "a.py", "content": "x = 2\n"})]),
        Script(text="Done."),
    ]
    agent = _agent(config, bus, scripts)
    agent.run("change a.py")
    assert len(checks) == 1, "one check, not a loop"


def test_a_question_turn_is_not_verified(config, bus):
    """An answer to a question is not a change, so nothing is run for it."""
    config.agent.verify_command = "echo check"
    checks = _watch(bus)
    scripts = [
        Script(text="Reading.", tool_calls=[ToolCall(
            id="r1", name="list_dir", arguments={"path": "."})]),
        Script(text="The repository has three folders."),
    ]
    agent = _agent(config, bus, scripts)
    agent.run("what is in the repository?")
    assert checks == []
