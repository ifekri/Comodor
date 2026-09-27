"""Characterization: what each mode advertises to the model (T012).

Advertisement and enforcement both derive from `safety/modes.py`, so a tool
cannot be offered by one and refused by the other (FR-117, FR-118, FR-120).
Pinned before spec 002 registers a new protocol capability and adds fields to
the question form, neither of which may change what a mode offers.
"""

from __future__ import annotations

import json
from pathlib import Path

from comodor.safety import Risk, modes
from comodor.tools import ToolRegistry

SCHEMA = Path(__file__).resolve().parents[1] / "schemas/protocol/v2.json"


def test_write_tools_are_not_advertised_in_plan_mode():
    registry = ToolRegistry()
    offered = {spec.name for spec in registry.specs("plan")}
    for tool in registry.all():
        if tool.risk is not Risk.SAFE:
            assert tool.name not in offered, tool.name


def test_act_mode_advertises_every_registered_tool():
    registry = ToolRegistry()
    assert {spec.name for spec in registry.specs("act")} == \
        {tool.name for tool in registry.all()}


def test_ask_and_chat_advertise_nothing():
    registry = ToolRegistry()
    assert registry.specs("ask") == []
    assert registry.specs("chat") == []


def test_advertisement_follows_the_policy_table_not_a_second_list():
    registry = ToolRegistry()
    for mode in modes.ALL:
        policy = modes.policy_for(mode)
        offered = {spec.name for spec in registry.specs(mode)}
        if not policy.may_use_any_tool:
            assert offered == set()
        elif not policy.may_use_mutating_tools:
            assert offered == {t.name for t in registry.all() if t.risk is Risk.SAFE}
        else:
            assert offered == {t.name for t in registry.all()}


def test_every_advertised_tool_is_one_the_mode_will_run(config, tool_context):
    """What is offered is exactly what `invoke` lets through the mode gate."""
    registry = ToolRegistry()
    for mode in ("act", "plan"):
        config.agent.mode = mode
        offered = {spec.name for spec in registry.specs(mode)}
        for tool in registry.all():
            result = registry.invoke(tool.name, tool_context, {"__probe__": True})
            refused_by_mode = f"not available in {mode} mode" in result.content
            assert refused_by_mode is (tool.name not in offered), (mode, tool.name)


def test_the_protocol_capability_lists_are_what_they_are_today():
    """Additions later must be additive: nothing here may disappear."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    core = schema["x-capabilities"]["core"]
    client = schema["x-capabilities"]["client"]
    assert {"streaming", "questions", "permissions", "modes", "tool_events",
            "tasks", "delegates", "usage"} <= set(core)
    assert {"questions", "permissions"} <= set(client)


def test_the_question_capability_is_not_a_tool_permission():
    """`questions` in the handshake says a client can draw a form. It never
    changes which tools a mode advertises."""
    registry = ToolRegistry()
    assert {spec.name for spec in registry.specs("ask")} == set()
    assert "ask" in {spec.name for spec in registry.specs("plan")}
