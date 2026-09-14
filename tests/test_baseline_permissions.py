"""The permission regression gate (T011; FR-019, FR-118, SC-022).

Run at the end of every phase of spec 002 that touches questions, ASK, modes,
tool advertisement, session interaction, orchestration or protocol — T028,
T060, T069, T098, T119, T129, T146 — and once more at the end (T167). It pins
the invariants the feature must not move:

    ASK    = no general tools
    PLAN   = read-only
    ACT    = permission-controlled
    unknown explicit mode = fail closed
    direct tool invocation cannot bypass policy
    a question never grants an action the mode forbids

The wire-level permission suite (`tests/test_protocol_permissions.py`) is
part of the gate too and is run alongside this file, not replaced by it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.events import Kind
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine, Risk, modes
from comodor.tools import ToolRegistry


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


def a_write(path="hello.py"):
    return ToolCall(id="w1", name="write_file",
                    arguments={"path": path, "content": "print('hi')\n"})


def a_shell():
    return ToolCall(id="s1", name="run_shell", arguments={"command": "echo hi"})


# --------------------------------------------------------------------------- #
# the policy table is the single source, and it is read-only
# --------------------------------------------------------------------------- #


def test_the_policy_table_is_frozen():
    policy = modes.policy_for("act")
    with pytest.raises((AttributeError, TypeError)):
        policy.may_mutate_files = False        # type: ignore[misc]


def test_an_unknown_explicit_mode_fails_closed():
    policy = modes.enforced("paln")
    assert not policy.may_use_any_tool
    assert not policy.may_read or not policy.may_use_read_tools
    assert "paln" in policy.refusal
    with pytest.raises(modes.UnknownMode):
        modes.policy_for("paln")


def test_absent_mode_is_act_and_a_typo_is_not():
    assert modes.policy_for(None).name == "act"
    assert modes.policy_for("").name == "act"
    assert modes.enforced("ACT ").name == "act"
    assert modes.enforced("act!").name == "act!"
    assert not modes.enforced("act!").may_use_any_tool


@pytest.mark.parametrize("mode, reads, mutates, shell", [
    ("act", True, True, True),
    ("plan", True, False, False),
    ("ask", False, False, False),
    ("chat", False, False, False),
])
def test_what_each_mode_permits(mode, reads, mutates, shell):
    policy = modes.policy_for(mode)
    assert policy.may_use_read_tools is reads
    assert policy.may_use_mutating_tools is mutates
    assert policy.may_execute_shell is shell
    assert policy.may_ask_questions is True or mode == "chat"


# --------------------------------------------------------------------------- #
# advertisement and enforcement agree, from the same table
# --------------------------------------------------------------------------- #


def test_ask_mode_advertises_no_general_tools():
    registry = ToolRegistry()
    names = {spec.name for spec in registry.specs("ask")}
    assert names == set()


def test_plan_mode_advertises_only_safe_tools():
    registry = ToolRegistry()
    for spec in registry.specs("plan"):
        assert registry.get(spec.name).risk is Risk.SAFE
    names = {spec.name for spec in registry.specs("plan")}
    assert "write_file" not in names and "run_shell" not in names
    assert "ask" in names, "planning is when the ambiguity bites"


def test_an_unknown_mode_advertises_nothing():
    assert ToolRegistry().specs("paln") == []


def test_direct_invocation_cannot_bypass_the_mode(config, tool_context):
    """`registry.invoke` checks the mode itself, whatever the model was shown."""
    registry = ToolRegistry()
    config.agent.mode = "plan"
    result = registry.invoke("write_file", tool_context,
                             {"path": "x.py", "content": "boom"})
    assert not result.ok
    assert "not available in plan mode" in result.content
    assert not (config.paths.project / "x.py").exists()


def test_an_unknown_mode_refuses_every_invocation(config, tool_context):
    registry = ToolRegistry()
    config.agent.mode = "paln"
    for name in ("read_file", "write_file", "ask"):
        result = registry.invoke(name, tool_context, {"path": "x"} if name != "ask"
                                 else {"questions": []})
        assert not result.ok, name


def test_the_engine_refuses_a_mutating_call_in_plan_mode_even_when_asked_directly(config, bus):
    config.agent.mode = "plan"
    engine = PermissionEngine(config, bus)
    decision = engine.check(tool="write_file", risk=Risk.WRITE, summary="write x")
    assert not decision
    assert "read-only" in decision.reason


def test_the_engine_refuses_everything_in_an_unknown_mode(config, bus):
    config.agent.mode = "act "  # a stray space is still act
    assert PermissionEngine(config, bus).check(tool="read_file", risk=Risk.SAFE,
                                               summary="r")
    config.agent.mode = "atc"
    engine = PermissionEngine(config, bus)
    assert not engine.check(tool="read_file", risk=Risk.SAFE, summary="r")
    assert not engine.check(tool="write_file", risk=Risk.WRITE, summary="w")


# --------------------------------------------------------------------------- #
# through the loop: what the model asks for is not what it gets
# --------------------------------------------------------------------------- #


def test_plan_mode_refuses_a_write_the_model_asks_for_anyway(config, bus):
    config.agent.mode = "plan"
    agent = make_agent(config, bus, [Script(text="Writing.", tool_calls=[a_write()]),
                                     Script(text="Done.")])
    agent.run("write it")
    assert not (config.paths.project / "hello.py").exists()


def test_act_mode_without_auto_approval_asks_and_a_silent_room_denies(config, bus):
    """No listener and no auto-approval: the write is refused, not assumed."""
    config.safety.auto_approve_writes = False
    engine = PermissionEngine(config, None)
    decision = engine.check(tool="write_file", risk=Risk.WRITE, summary="write x")
    assert not decision
    assert "no interactive approval" in decision.reason


def test_a_denied_prompt_denies(config, bus):
    config.safety.auto_approve_writes = False
    bus.subscribe(lambda event: event.payload["request"].answer("deny")
                  if event.kind is Kind.REQUEST else None)
    agent = make_agent(config, bus, [Script(text="Writing.", tool_calls=[a_write()]),
                                     Script(text="Done.")])
    agent.run("write it")
    assert not (config.paths.project / "hello.py").exists()


def test_a_question_grants_no_permission(config, bus):
    """Answering a form is information; it never approves a tool call."""
    config.agent.mode = "plan"
    engine = PermissionEngine(config, bus)
    before = engine.check(tool="write_file", risk=Risk.WRITE, summary="w")
    # A form goes past on the same bus...
    from comodor.events import Request
    bus.emit(Kind.REQUEST, request=Request(id="ask-1", prompt="q", options=[],
                                           kind="questions"))
    after = engine.check(tool="write_file", risk=Risk.WRITE, summary="w")
    assert not before and not after


def test_the_shell_deny_list_holds_before_anyone_is_asked(config, bus):
    """With auto-approval off the engine refuses a listed command itself; with
    it on, `run_shell` re-checks the list at run time (its own tests cover
    that half). Either way the pattern never runs."""
    config.safety.auto_approve_shell = False
    engine = PermissionEngine(config, bus)
    decision = engine.check(tool="run_shell", risk=Risk.DANGEROUS,
                            summary="run: rm -rf /", detail="$ rm -rf /")
    assert not decision
    assert "blocked pattern" in decision.reason


def test_the_wire_level_permission_suite_is_part_of_this_gate():
    """This file and `test_protocol_permissions.py` are one gate."""
    assert (Path(__file__).parent / "test_protocol_permissions.py").is_file()
