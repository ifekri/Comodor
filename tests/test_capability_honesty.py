"""A capability is never claimed or attempted when it is not available
(T138; FR-120, SC-034).

In plan mode and conversation-only mode, no tool outside what the mode
advertises may be attempted, and when one is refused the mode is named as the
reason.
"""

from __future__ import annotations

import pytest

from comodor.tools import ToolRegistry


def test_a_plan_mode_write_is_refused_with_the_mode_named(tool_context):
    registry = ToolRegistry()
    tool_context.config.agent.mode = "plan"
    result = registry.invoke("write_file", tool_context,
                             {"path": "a.py", "content": "x = 1\n"})
    assert not result.ok
    assert "plan" in result.content
    assert "not available" in result.content


def test_a_conversation_only_turn_may_not_reach_for_a_tool(tool_context):
    registry = ToolRegistry()
    tool_context.config.agent.mode = "ask"
    result = registry.invoke("read_file", tool_context, {"path": "a.py"})
    assert not result.ok
    assert "ask" in result.content


@pytest.mark.parametrize("mode", ["plan", "ask", "chat"])
def test_no_advertised_tool_is_one_the_mode_would_refuse(tool_context, mode):
    registry = ToolRegistry()
    tool_context.config.agent.mode = mode
    for spec in registry.specs(mode):
        result = registry.invoke(spec.name, tool_context, {})
        assert "not available in" not in result.content, (
            f"{spec.name} was advertised in {mode} but refused by the same rule")
