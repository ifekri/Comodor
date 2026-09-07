"""What each mode allows, checked where it is enforced.

The point of these is that mode is not a label. A client can draw whatever it
likes; what it cannot do is get a write past a core in Plan mode. So each test
goes at the layer that actually refuses — the tool registry and the permission
engine — rather than at the button.
"""

from __future__ import annotations

import pytest

from comodor.application import CoreService, Refused
from comodor.safety import Risk
from comodor.safety.modes import ALL, ORDER, cycle, known, policy_for
from comodor.safety.permissions import PermissionEngine
from comodor.tools import ToolRegistry

# --------------------------------------------------------------------------- #
# the table
# --------------------------------------------------------------------------- #

def test_act_is_the_only_mode_that_may_change_anything():
    changing = [name for name in ALL
                if policy_for(name).may_mutate_files
                or policy_for(name).may_execute_shell
                or policy_for(name).may_mutate_external_services]

    assert changing == ["act"]


def test_every_mode_may_ask_a_question():
    # A mode that could not ask would have to guess, and guessing is the thing
    # Plan mode exists to avoid.
    assert all(policy_for(name).may_ask_questions for name in ALL)


def test_chat_is_the_only_mode_with_no_tools_at_all():
    assert [name for name in ALL if not policy_for(name).may_use_any_tool] == ["chat"]


def test_plan_and_ask_can_read_and_cannot_write():
    for name in ("plan", "ask"):
        policy = policy_for(name)
        assert policy.may_read and policy.may_use_read_tools
        assert not policy.may_use_mutating_tools
        assert not policy.may_mutate_files
        assert not policy.may_execute_shell
        assert not policy.may_mutate_external_services


def test_an_unknown_mode_is_not_silently_accepted():
    assert known("act") and not known("turbo")


def test_the_cycle_is_the_three_a_person_sees():
    assert ORDER == ("act", "plan", "ask")
    assert [cycle("act"), cycle("plan"), cycle("ask")] == ["plan", "ask", "act"]
    assert [cycle("act", back=True), cycle("plan", back=True),
            cycle("ask", back=True)] == ["ask", "act", "plan"]


def test_chat_is_reachable_by_name_but_not_by_pressing_the_key():
    # It predates `ask` and reaching it by repeated presses would surprise
    # somebody who only knows the three.
    assert "chat" in ALL and "chat" not in ORDER
    assert cycle("chat") == "act"


# --------------------------------------------------------------------------- #
# what the model is offered
# --------------------------------------------------------------------------- #

def test_a_mutating_tool_is_never_advertised_in_plan_mode(config):
    registry = ToolRegistry(config=config)
    offered = {tool.name for tool in registry.for_mode("plan")}

    assert "read_file" in offered
    assert "write_file" not in offered
    assert "run_shell" not in offered


def test_ask_mode_is_offered_the_same_read_only_set_as_plan(config):
    registry = ToolRegistry(config=config)

    assert ({tool.name for tool in registry.for_mode("ask")}
            == {tool.name for tool in registry.for_mode("plan")})


def test_chat_mode_is_offered_nothing(config):
    assert ToolRegistry(config=config).for_mode("chat") == []


# --------------------------------------------------------------------------- #
# the bypass
# --------------------------------------------------------------------------- #

def test_a_write_tool_called_by_name_in_plan_mode_is_refused(
        config, tool_context):
    # The one that matters. Hiding a tool from the model is not a security
    # boundary — a model can name a tool it was never offered, and so can a
    # client driving the core. The registry refuses on invoke, not on display.
    config.agent.mode = "plan"
    registry = ToolRegistry(config=config)

    result = registry.invoke("write_file", tool_context,
                             {"path": "new.txt", "content": "x"})

    assert not result.ok
    assert "plan mode" in result.content.lower()
    assert not (config.paths.project / "new.txt").exists()


def test_the_permission_engine_refuses_a_dangerous_call_in_ask_mode(config, bus):
    config.agent.mode = "ask"
    engine = PermissionEngine(config, bus)

    decision = engine.check("run_shell", Risk.DANGEROUS, "run: ls")

    assert not decision.allowed
    assert "read-only" in decision.reason.lower()


def test_chat_mode_refuses_even_a_safe_call(config, bus):
    config.agent.mode = "chat"
    engine = PermissionEngine(config, bus)

    assert not engine.check("read_file", Risk.SAFE, "read: a.txt").allowed


def test_act_mode_lets_a_safe_call_through(config, bus):
    config.agent.mode = "act"
    engine = PermissionEngine(config, bus)

    assert engine.check("read_file", Risk.SAFE, "read: a.txt").allowed


def test_the_two_layers_cannot_disagree_about_a_mode(config, bus):
    """What the model is offered and what the engine permits are one rule.

    Before `safety.modes` these were two hand-written copies. The failure they
    invite is a tool that is advertised and then refused, or worse, one that
    is hidden and would have been permitted.
    """
    registry = ToolRegistry(config=config)
    for mode in ALL:
        config.agent.mode = mode
        engine = PermissionEngine(config, bus)
        offered = {tool.name: tool.risk for tool in registry.for_mode(mode)}
        for name, risk in offered.items():
            allowed, why = engine.mode_allows(risk)
            assert allowed, f"{mode}: {name} is offered but refused ({why})"


# --------------------------------------------------------------------------- #
# through the application service
# --------------------------------------------------------------------------- #

def test_setting_an_unknown_mode_is_refused_by_the_core(config):
    service = CoreService(config)
    try:
        session = service.create_session()
        with pytest.raises(Refused):
            service.set_mode(session["id"], "turbo")
    finally:
        service.close()


def test_a_session_keeps_its_own_mode(config):
    # Two sessions in one core must not share a mode, or setting one to Plan
    # would quietly disarm the other's Act.
    service = CoreService(config)
    try:
        first = service.create_session()
        second = service.create_session()
        service.set_mode(first["id"], "plan")

        assert service.get_session(first["id"])["mode"] == "plan"
        assert service.get_session(second["id"])["mode"] == "act"
    finally:
        service.close()


def test_the_mode_a_session_reports_is_the_one_its_tools_obey(config):
    service = CoreService(config)
    try:
        session = service.create_session(mode="plan")
        handle = service.session(session["id"])
        offered = {tool.name for tool in
                   handle.assembly.tools.for_mode(handle.mode)}

        assert session["mode"] == "plan"
        assert "write_file" not in offered
    finally:
        service.close()
