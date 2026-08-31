"""The mode system: ask mode, and proposals to change mode.

The proposal is the interesting half. It has to reach the user through the
same request channel as a permission prompt — every interface already knows
how to render one of those — and its answer has to change the mode the loop
reads on the very next step, mid-turn, without anybody re-sending anything.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus, Kind
from comodor.providers.base import Role, ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools.propose_mode import ProposeMode, _options_for


def make_agent(config, bus, scripts):
    gateway = Gateway(config, scripts=scripts)
    return AgentLoop(config, gateway, ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation())


# --------------------------------------------------------------------------- #
# ask mode
# --------------------------------------------------------------------------- #


def test_ask_mode_offers_only_safe_tools():
    registry = ToolRegistry()
    offered = {tool.name for tool in registry.for_mode("ask")}
    assert "read_file" in offered
    assert "ask" in offered
    assert "write_file" not in offered
    assert "run_shell" not in offered


def test_ask_mode_refuses_a_write_even_if_the_model_asks(config, bus):
    config.agent.mode = "ask"
    scripts = [
        Script(text="Writing.", tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "x.txt", "content": "nope"})]),
        Script(text="Blocked."),
    ]
    agent = make_agent(config, bus, scripts)
    agent.run("write a file")

    assert not (config.paths.project / "x.txt").exists()
    failure = [m for m in agent.conversation.messages if m.role is Role.TOOL][0]
    assert failure.is_error


def test_ask_mode_has_its_own_guidance(config):
    from comodor.agent.prompts import build_system_prompt

    config.agent.mode = "ask"
    prompt = build_system_prompt(config)
    assert "Mode: ASK" in prompt
    assert "Mode: PLAN" not in prompt


def test_every_mode_has_guidance(config):
    from comodor.agent import prompts

    for mode in ("act", "plan", "ask", "chat"):
        config.agent.mode = mode
        assert f"Mode: {mode.upper()}" in prompts.build_system_prompt(config)


# --------------------------------------------------------------------------- #
# the proposal tool
# --------------------------------------------------------------------------- #


def _subscribe_answers(bus: EventBus, answers: list[str]) -> list[dict]:
    """Record every request the bus sees and answer it in order."""
    seen: list[dict] = []

    def watch(event) -> None:
        if event.kind is not Kind.REQUEST:
            return
        request = event.payload.get("request")
        if request is None or request.answered:
            return
        seen.append({"kind": request.kind, "options": list(request.options)})
        if answers:
            request.answer(answers.pop(0))

    bus.subscribe(watch)
    return seen


def test_a_proposal_that_is_accepted_changes_the_mode_mid_turn(config, bus):
    config.agent.mode = "plan"
    seen = _subscribe_answers(bus, ["act"])
    scripts = [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="c1", name="propose_mode",
                     arguments={"target_mode": "act",
                                "reason": "The plan is complete."})]),
        Script(text="Getting on with it."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("do it")

    assert result.ok
    assert config.agent.mode == "act"
    assert seen[0]["kind"] == "mode"
    assert seen[0]["options"][0] == "act"


def test_a_declined_proposal_keeps_the_mode(config, bus):
    config.agent.mode = "plan"
    _subscribe_answers(bus, ["plan"])
    scripts = [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="c1", name="propose_mode",
                     arguments={"target_mode": "act",
                                "reason": "The plan is complete."})]),
        Script(text="Carrying on in plan mode."),
    ]
    agent = make_agent(config, bus, scripts)

    result = agent.run("do it")
    assert result.ok
    assert config.agent.mode == "plan"


def test_a_proposal_of_the_current_mode_changes_nothing(config, bus):
    config.agent.mode = "act"
    _subscribe_answers(bus, [])
    scripts = [
        Script(text="Done."),
        Script(text="Never reached."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("hi")

    assert result.ok
    assert config.agent.mode == "act"


def test_the_current_mode_is_always_the_last_option(config, bus):
    config.agent.mode = "plan"
    seen = _subscribe_answers(bus, ["ask"])
    scripts = [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="c1", name="propose_mode",
                     arguments={"target_mode": "act", "reason": "r"})]),
        Script(text="Done."),
    ]
    agent = make_agent(config, bus, scripts)
    agent.run("go")

    # Silence has to mean "no change", and the interface falls back to the
    # last option — so the current mode must be the one there.
    assert seen[0]["options"][-1] == "plan"


def test_a_proposal_without_a_target_asks_which_mode(config, bus):
    config.agent.mode = "plan"
    seen = _subscribe_answers(bus, ["ask"])
    scripts = [
        Script(text="Asking.", tool_calls=[
            ToolCall(id="c1", name="propose_mode",
                     arguments={"reason": "This needs file access."})]),
        Script(text="Done."),
    ]
    agent = make_agent(config, bus, scripts)
    agent.run("hi")

    assert config.agent.mode == "ask"
    assert seen[0]["options"][0] == "act"


def test_a_proposal_needs_a_reason(config, tool_context):
    result = ProposeMode().invoke(tool_context, {"target_mode": "act"})
    assert not result.ok


def test_an_unknown_mode_is_refused(config, tool_context):
    result = ProposeMode().invoke(tool_context,
                                  {"target_mode": "turbo", "reason": "r"})
    assert not result.ok
    assert "turbo" in result.content


# --------------------------------------------------------------------------- #
# the option ordering rule
# --------------------------------------------------------------------------- #


def test_options_for_every_pairing_ends_with_the_current_mode():
    for current in ("act", "plan", "ask"):
        for target in ("act", "plan", "ask"):
            options = _options_for(current, "" if target == current else target)
            assert options[-1] == current
            assert len(options) == len(set(options))
