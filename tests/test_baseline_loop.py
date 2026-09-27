"""Characterization: the completion guards in `AgentLoop._iterate` (T010).

The project's own check runs once, only when the turn changed a file, is
bounded by `verify.py`, and a check that cannot be run never turns a good turn
into a failure. Spec 002 widens the completion gate around these guards
(FR-038 to FR-043) and must leave every one of them standing.
"""

from __future__ import annotations

import pytest

from comodor.agent import AgentLoop, Conversation, verify
from comodor.events import Kind
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


def a_write():
    return ToolCall(id="w1", name="write_file",
                    arguments={"path": "hello.py", "content": "print('hi')\n"})


@pytest.fixture
def notices(bus):
    seen: list[str] = []
    bus.subscribe(lambda event: seen.append(event.text)
                  if event.kind is Kind.NOTICE else None)
    return seen


def test_no_check_runs_when_the_turn_changed_nothing(config, bus, monkeypatch, notices):
    config.agent.verify_command = "pytest -q"
    ran: list[str] = []
    def fake_run(*a, **k):
        ran.append("ran")
        return verify.Outcome(ran=True, passed=True, output="")

    monkeypatch.setattr(verify, "run", fake_run)
    agent = make_agent(config, bus, [
        Script(text="Looking.", tool_calls=[ToolCall(id="r", name="list_dir",
                                                     arguments={"path": "."})]),
        Script(text="Nothing to change."),
    ])
    result = agent.run("look")
    assert result.stopped == "done"
    assert ran == []


def test_the_check_runs_once_when_a_file_changed_and_passes_quietly(
        config, bus, monkeypatch, notices):
    config.agent.verify_command = "pytest -q"
    ran: list[str] = []

    def fake_run(command, cwd, patience=None):
        ran.append(command)
        return verify.Outcome(ran=True, passed=True, output="")

    monkeypatch.setattr(verify, "run", fake_run)
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ])
    result = agent.run("write it")
    assert result.stopped == "done" and result.text == "Done."
    assert ran == ["pytest -q"]
    assert any("passed" in note for note in notices)


def test_a_failing_check_is_handed_back_exactly_once(config, bus, monkeypatch, notices):
    config.agent.verify_command = "pytest -q"
    ran: list[str] = []

    def fake_run(command, cwd, patience=None):
        ran.append(command)
        return verify.Outcome(ran=True, passed=False, output="1 failed")

    monkeypatch.setattr(verify, "run", fake_run)
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
        Script(text="Fixed now."),
    ])
    result = agent.run("write it")

    assert result.stopped == "done" and result.text == "Fixed now."
    assert ran == ["pytest -q"], "one chance, not one per message"
    corrections = [m for m in agent.conversation.messages
                   if m.role is Role.USER and "pytest -q" in m.content]
    assert len(corrections) == 1


def test_a_check_that_cannot_run_is_said_once_and_the_turn_still_completes(
        config, bus, monkeypatch, notices):
    config.agent.verify_command = "pytest -q"
    monkeypatch.setattr(verify, "run", lambda *a, **k: verify.Outcome(
        ran=False, passed=True, output="", unusable="no such command"))
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ])
    result = agent.run("write it")
    assert result.ok and result.stopped == "done" and result.text == "Done."
    assert sum("could not be run" in note for note in notices) == 1


def test_a_check_that_raises_never_kills_the_turn(config, bus, monkeypatch, notices):
    config.agent.verify_command = "pytest -q"

    def boom(*a, **k):
        raise RuntimeError("exploded")

    monkeypatch.setattr(verify, "run", boom)
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done."),
    ])
    result = agent.run("write it")
    assert result.ok and result.text == "Done."


def test_the_check_is_bounded_by_a_patience_the_runner_enforces(tmp_path):
    """`verify.run` kills the process; the loop never waits forever."""
    import sys

    outcome = verify.run(f'"{sys.executable}" -c "import time; time.sleep(30)"',
                         cwd=tmp_path, patience=0.5)
    assert outcome.ran and not outcome.passed
    assert "no result within" in outcome.output


def test_an_unverified_pass_claim_is_noticed_but_not_blocked(config, bus, notices):
    """`claims.unverified` annotates; nothing here withholds the answer."""
    agent = make_agent(config, bus, [
        Script(text="Writing.", tool_calls=[a_write()]),
        Script(text="Done. All tests pass."),
    ])
    result = agent.run("write it and make the tests pass")
    assert result.ok and result.text == "Done. All tests pass."
    assert any("has not been checked" in note for note in notices)
