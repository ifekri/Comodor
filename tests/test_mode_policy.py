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


def test_plan_is_the_only_mode_that_may_look_without_changing():
    """The line between Plan and Ask is which one may go and fetch.

    Ask answers from the conversation; Plan inspects and produces a plan it
    may not carry out. Giving Ask the read tools makes them one mode with two
    labels, which is the thing a mode exists to prevent.
    """
    inspecting = [name for name in ALL
                  if policy_for(name).may_use_read_tools
                  and not policy_for(name).may_use_mutating_tools]

    assert inspecting == ["plan"]


def test_ask_gets_no_tools_at_all():
    policy = policy_for("ask")

    assert policy.may_use_any_tool is False
    assert policy.may_use_read_tools is False
    assert policy.may_use_mutating_tools is False
    assert policy.may_execute_shell is False
    assert policy.may_mutate_files is False
    assert policy.may_mutate_external_services is False
    # It is still a conversation, and a conversation may ask.
    assert policy.may_ask_questions is True
    assert policy.may_read is True


def test_ask_and_chat_are_the_two_modes_with_no_tools():
    assert [name for name in ALL
            if not policy_for(name).may_use_any_tool] == ["ask", "chat"]


def test_plan_can_read_and_cannot_write():
    policy = policy_for("plan")
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


def test_ask_mode_is_offered_nothing(config):
    # Not the read-only set. Ask is conversation.
    assert ToolRegistry(config=config).for_mode("ask") == []


def test_plan_is_offered_the_read_only_tools(config):
    offered = {tool.name for tool in ToolRegistry(config=config).for_mode("plan")}

    assert "read_file" in offered
    assert "list_dir" in offered
    assert "write_file" not in offered


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


def test_the_permission_engine_refuses_a_dangerous_call_in_plan_mode(config, bus):
    config.agent.mode = "plan"
    engine = PermissionEngine(config, bus)

    decision = engine.check("run_shell", Risk.DANGEROUS, "run: ls")

    assert not decision.allowed
    assert "read-only" in decision.reason.lower()


def test_ask_mode_refuses_a_read_as_well_as_a_write(config, bus):
    config.agent.mode = "ask"
    engine = PermissionEngine(config, bus)

    assert not engine.check("read_file", Risk.SAFE, "read: a.txt").allowed
    assert not engine.check("run_shell", Risk.DANGEROUS, "run: ls").allowed


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


# --------------------------------------------------------------------------- #
# ASK, at the layer that enforces it
# --------------------------------------------------------------------------- #

def test_a_read_tool_called_by_name_in_ask_mode_is_refused(config, tool_context):
    # Hiding it is not the boundary. A model can name a tool it was never
    # offered, and so can a client driving the core.
    config.agent.mode = "ask"
    registry = ToolRegistry(config=config)
    (config.paths.project / "a.txt").write_text("hello", encoding="utf-8")

    result = registry.invoke("read_file", tool_context, {"path": "a.txt"})

    assert not result.ok
    assert "ask mode" in result.content.lower()


def test_a_mutating_tool_called_by_name_in_ask_mode_is_refused(config, tool_context):
    config.agent.mode = "ask"
    registry = ToolRegistry(config=config)

    result = registry.invoke("write_file", tool_context,
                             {"path": "new.txt", "content": "x"})

    assert not result.ok
    assert not (config.paths.project / "new.txt").exists()


def test_a_read_tool_still_works_in_plan_mode(config, tool_context):
    # The other half: making Ask strict must not make Plan useless.
    config.agent.mode = "plan"
    registry = ToolRegistry(config=config)
    (config.paths.project / "a.txt").write_text("hello", encoding="utf-8")

    result = registry.invoke("read_file", tool_context, {"path": "a.txt"})

    assert result.ok
    assert "hello" in result.content


def test_act_remains_permission_controlled_rather_than_unrestricted(config, bus):
    # Act is not "anything goes": the risk tiers and the approval policy still
    # apply, and turning auto-approval off makes a shell call ask.
    config.agent.mode = "act"
    config.safety.auto_approve_shell = False
    config.safety.auto_approve_writes = False
    engine = PermissionEngine(config, bus)

    allowed, why = engine.mode_allows(Risk.DANGEROUS)
    assert allowed, why
    # The mode permits it; the policy is what decides, and with nobody to ask
    # it does not simply proceed.
    assert not engine.auto_approved(Risk.DANGEROUS)
    assert not engine.auto_approved(Risk.WRITE)


# --------------------------------------------------------------------------- #
# an unrecognised mode
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["paln", "acts", "unknown", "foo", "ACTT", "1"])
def test_an_explicit_unknown_mode_raises_where_it_enters(bad):
    from comodor.safety.modes import UnknownMode
    from comodor.safety.modes import policy_for as strict

    with pytest.raises(UnknownMode):
        strict(bad)


@pytest.mark.parametrize("bad", ["paln", "acts", "unknown", "foo"])
def test_an_unrecognised_mode_never_gains_act_privileges(bad):
    """The failure this exists for: a typo becoming full write and shell.

    `policy_for` used to fall back to Act, so `"paln"` in a config file was a
    session with every tool. It denies everything now, and names itself.
    """
    from comodor.safety.modes import enforced

    policy = enforced(bad)

    assert policy.may_use_any_tool is False
    assert policy.may_use_mutating_tools is False
    assert policy.may_execute_shell is False
    assert policy.may_mutate_files is False
    assert policy.may_mutate_external_services is False
    assert bad in policy.refusal


def test_the_absent_mode_is_the_documented_default():
    from comodor.safety.modes import DEFAULT
    from comodor.safety.modes import policy_for as strict

    assert strict(None).name == DEFAULT
    assert strict("").name == DEFAULT


def test_whitespace_around_a_real_mode_is_not_a_different_mode():
    assert policy_for(" PLAN ").name == "plan"


def test_an_unrecognised_mode_offers_no_tools_and_refuses_every_call(
        config, bus, tool_context):
    config.agent.mode = "paln"
    registry = ToolRegistry(config=config)

    assert registry.for_mode("paln") == []
    assert not PermissionEngine(config, bus).check(
        "read_file", Risk.SAFE, "read: a.txt").allowed

    result = registry.invoke("write_file", tool_context,
                             {"path": "new.txt", "content": "x"})
    assert not result.ok
    assert not (config.paths.project / "new.txt").exists()


def test_a_config_file_with_an_unknown_mode_says_so_and_grants_nothing(tmp_path):
    """Config ingestion, not just `session.set_mode`.

    The value is left exactly as written rather than corrected to a default,
    because the default is Act and correcting a typo *into* write and shell
    access is the one outcome this must never have.
    """
    import json
    import os

    from comodor.config import load

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(
        json.dumps({"agent": {"mode": "paln"}}), encoding="utf-8")

    was = os.environ.get("COMODOR_HOME")
    os.environ["COMODOR_HOME"] = str(home)
    try:
        config = load(cwd=tmp_path)
    finally:
        if was is None:
            os.environ.pop("COMODOR_HOME", None)
        else:
            os.environ["COMODOR_HOME"] = was

    assert config.agent.mode == "paln", "the wrong value must not be laundered"
    assert any("paln" in note for note in config.complaints), config.complaints
    assert ToolRegistry(config=config).for_mode(config.agent.mode) == []


def test_the_application_service_refuses_an_unknown_mode_at_creation(config):
    # The other entry point: not every caller goes through `set_mode`.
    service = CoreService(config)
    try:
        with pytest.raises(Refused):
            service.create_session(mode="paln")
    finally:
        service.close()
