"""Capability authority: one rule, and it fails closed (T139; FR-117, FR-118).

Advertisement and enforcement both read `safety.modes`. A forbidden tool is
never offered, an unknown mode offers nothing, and the question capability
does not imply any tool capability.
"""

from __future__ import annotations

import pytest

from comodor.safety import Risk, modes
from comodor.tools import ToolRegistry


def _names(mode):
    return {tool.name for tool in ToolRegistry().for_mode(mode)}


def test_plan_offers_only_safe_tools():
    assert _names("plan")
    assert all(tool.risk is Risk.SAFE for tool in ToolRegistry().for_mode("plan")), (
        "a write or dangerous tool must never be advertised in plan mode")


def test_act_offers_more_than_plan():
    assert _names("plan") < _names("act")


@pytest.mark.parametrize("mode", ["ask", "chat"])
def test_conversation_modes_offer_no_tools(mode):
    assert _names(mode) == set()


def test_an_unknown_mode_is_fail_closed():
    assert _names("paln") == set()
    policy = modes.enforced("paln")
    assert not policy.may_use_any_tool
    with pytest.raises(modes.UnknownMode):
        modes.policy_for("paln")


def test_the_question_capability_does_not_imply_a_tool_capability():
    ask = modes.policy_for("ask")
    assert ask.may_ask_questions is True
    assert ask.may_use_any_tool is False
    assert _names("ask") == set()


def test_advertisement_and_enforcement_cannot_disagree(tool_context):
    registry = ToolRegistry()
    tool_context.config.agent.mode = "plan"
    for tool in registry.for_mode("plan"):
        result = registry.invoke(tool.name, tool_context, {})
        assert "not available in" not in result.content, (
            f"{tool.name} was offered but refused by the mode rule")


def test_a_forbidden_tool_is_refused_with_the_mode_named(tool_context):
    registry = ToolRegistry()
    tool_context.config.agent.mode = "plan"
    result = registry.invoke("write_file", tool_context,
                             {"path": "a.py", "content": "x = 1\n"})
    assert not result.ok
    assert "plan" in result.content
