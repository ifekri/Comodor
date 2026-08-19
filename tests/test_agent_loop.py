"""The agent loop, driven by scripted responses — no network, no spend."""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
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


def test_plain_answer_ends_the_turn(config, bus):
    agent = make_agent(config, bus, [Script(text="Hello there.")])
    result = agent.run("hi")

    assert result.ok
    assert result.stopped == "done"
    assert result.text == "Hello there."
    assert result.steps == 1
    assert result.tool_calls == 0


def test_tool_call_round_trip_writes_a_file(config, bus):
    scripts = [
        Script(text="Writing it.", tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "hello.py", "content": "print('hi')\n"})]),
        Script(text="Done."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("create hello.py")

    assert result.ok
    assert result.steps == 2
    assert (config.paths.project / "hello.py").read_text() == "print('hi')\n"
    # The tool result must be threaded back to the model, keyed by call id.
    tool_messages = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "c1"


def test_parallel_safe_tools_run_together_and_stay_in_order(config, bus):
    calls = [
        ToolCall(id=f"c{i}", name="list_dir", arguments={"path": "."})
        for i in range(4)
    ]
    agent = make_agent(config, bus, [Script(text="Looking.", tool_calls=calls),
                                     Script(text="Done.")])
    agent.run("look around")

    results = [m for m in agent.conversation.messages if m.role is Role.TOOL]
    assert [m.tool_call_id for m in results] == ["c0", "c1", "c2", "c3"]


def test_loop_off_stops_after_one_round_of_tools(config, bus):
    config.agent.loop = False
    scripts = [
        Script(text="Checking.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="never reached"),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("look")

    assert result.steps == 1
    assert result.stopped == "done"


def test_step_limit_stops_a_runaway_loop(config, bus):
    config.agent.max_steps = 3
    runaway = Script(text="again", tool_calls=[
        ToolCall(id="c", name="list_dir", arguments={"path": "."})])
    agent = make_agent(config, bus, [runaway])
    result = agent.run("go forever")

    assert result.stopped == "max_steps"
    assert result.steps == 3


def test_plan_mode_hides_write_tools_from_the_model(config, bus):
    config.agent.mode = "plan"
    agent = make_agent(config, bus, [Script(text="Here is the plan.")])
    agent.run("how would you add a feature?")

    offered = {spec.name for spec in agent.tools.specs("plan")}
    assert "read_file" in offered
    assert "write_file" not in offered
    assert "run_shell" not in offered


def test_plan_mode_refuses_a_write_even_if_the_model_asks(config, bus):
    config.agent.mode = "plan"
    scripts = [
        Script(text="Editing.", tool_calls=[
            ToolCall(id="c1", name="write_file",
                     arguments={"path": "x.txt", "content": "nope"})]),
        Script(text="Blocked."),
    ]
    agent = make_agent(config, bus, scripts)
    agent.run("write a file")

    assert not (config.paths.project / "x.txt").exists()
    failure = [m for m in agent.conversation.messages if m.role is Role.TOOL][0]
    assert failure.is_error


def test_tool_failure_is_reported_to_the_model_not_raised(config, bus):
    scripts = [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="c1", name="read_file", arguments={"path": "missing.py"})]),
        Script(text="It does not exist."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("read missing.py")

    assert result.ok
    failure = [m for m in agent.conversation.messages if m.role is Role.TOOL][0]
    assert failure.is_error
    assert "does not exist" in failure.content


def test_provider_failure_surfaces_as_an_error_event(config, bus):
    seen = []
    bus.subscribe(lambda event: seen.append(event))
    agent = make_agent(config, bus, [Script(error="upstream exploded")])
    result = agent.run("hi")

    assert result.stopped == "error"
    assert any(event.kind is Kind.ERROR for event in seen)


def test_events_describe_the_whole_turn(config, bus):
    kinds = []
    bus.subscribe(lambda event: kinds.append(event.kind))
    scripts = [
        Script(text="Working.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Done."),
    ]
    make_agent(config, bus, scripts).run("look")

    assert kinds[0] is Kind.TURN_START
    assert kinds[-1] is Kind.TURN_END
    for expected in (Kind.ASSISTANT_START, Kind.ASSISTANT_DELTA, Kind.ASSISTANT_END,
                     Kind.TOOL_START, Kind.TOOL_END, Kind.USAGE):
        assert expected in kinds


def test_todo_tool_publishes_the_task_list(config, bus):
    published = []
    bus.subscribe(lambda event: published.append(event)
                  if event.kind is Kind.TODO else None)
    scripts = [
        Script(text="Planning.", tool_calls=[
            ToolCall(id="c1", name="todo_write", arguments={"items": [
                {"text": "read the code", "state": "done"},
                {"text": "make the change", "state": "active"},
            ]})]),
        Script(text="Done."),
    ]
    make_agent(config, bus, scripts).run("do a multi-step job")

    assert published
    assert published[0].get("items")[1]["state"] == "active"
