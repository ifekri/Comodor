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
    """When it is asked for. It is not the default any more — see below."""
    config.agent.max_steps = 3
    runaway = Script(text="again", tool_calls=[
        ToolCall(id="c", name="list_dir", arguments={"path": "."})])
    agent = make_agent(config, bus, [runaway])
    result = agent.run("go forever")

    assert result.stopped == "max_steps"
    assert result.steps == 3


def test_there_is_no_step_limit_by_default():
    """Twenty-four steps is nothing on a real codebase. A refactor across a
    dozen files ran out of them mid-thought, and a step count has no
    relationship to harm — ten steps reading files cost almost nothing. The
    ceilings that do are time and money, and those stay on."""
    from comodor.config import AgentConfig

    assert AgentConfig().max_steps == 0
    assert AgentConfig().max_seconds > 0
    assert AgentConfig().max_cost_usd > 0


def test_zero_steps_means_no_limit(config, bus):
    config.agent.max_steps = 0
    config.agent.max_seconds = 0            # and zero here too
    scripts = [Script(text="again", tool_calls=[
        ToolCall(id=f"c{i}", name="list_dir", arguments={"path": "."})])
        for i in range(30)]
    scripts.append(Script(text="done"))

    result = make_agent(config, bus, scripts).run("keep going")

    assert result.stopped == "done"
    assert result.steps > 24, "it stopped somewhere it should not have"


def test_a_ceiling_says_how_to_go_past_it(config, bus):
    """Being stopped is only useful if the next move is obvious."""
    notes: list[str] = []
    bus.subscribe(lambda event: notes.append(event.payload.get("text", "")))
    config.agent.max_steps = 2
    runaway = Script(text="again", tool_calls=[
        ToolCall(id="c", name="list_dir", arguments={"path": "."})])

    make_agent(config, bus, [runaway]).run("go forever")

    said = " ".join(notes)
    assert "continue" in said
    assert "max_steps" in said


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


def test_a_turn_that_fails_halfway_still_reports_the_work_it_did(config, bus):
    """Found by the benchmark: a task whose files had been changed came back
    saying `steps: 0, tool_calls: 0`.

    The result used to be built on the way out of the loop, so an exception
    discarded it and left the empty one the caller started with. Everything
    downstream believed nothing had happened — the headless JSON, the turn
    summary, and the lesson the brain records about what a task like this
    costs — while the project on disk had been edited."""
    scripts = [
        Script(text="Reading.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Writing.", tool_calls=[
            ToolCall(id="c2", name="write_file",
                     arguments={"path": "made.py", "content": "x = 2\n"})]),
        Script(error="the provider fell over"),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("do the thing")

    assert result.stopped == "error"
    assert (config.paths.project / "made.py").exists(), \
        "the premise of this test is that work was done"
    assert result.steps == 3, f"reported {result.steps} steps"
    assert result.tool_calls == 2, f"reported {result.tool_calls} tool calls"


def test_a_cancelled_turn_reports_what_it_managed_first(config, bus):
    scripts = [
        Script(text="Working.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="Done."),
    ]
    agent = make_agent(config, bus, scripts)

    seen = []

    def stop_after_the_first_tool(event):
        seen.append(event.kind)
        if event.kind is Kind.TOOL_END:
            agent.interrupt()

    bus.subscribe(stop_after_the_first_tool)
    result = agent.run("look")

    assert result.stopped == "cancelled"
    assert result.tool_calls == 1, \
        "a cancelled turn that ran a tool must say it ran a tool"


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


# --------------------------------------------------------------------------- #
# a turn that ends saying nothing
#
# Found by the benchmark: two of eight failures were a completed task reported
# as an empty string. The model ran its tools, explained itself along the way,
# and closed with a blank message. In the interface that is invisible, because
# the explanation was streamed as it arrived — but `comodor run` prints only
# the final message, so a caller gets nothing for a turn that did the work.
# --------------------------------------------------------------------------- #


def test_a_blank_final_message_falls_back_to_what_was_said(config, bus):
    """No extra model call: this repeats what it actually said, and invents
    nothing."""
    scripts = [
        Script(text="Reading the file to see what changed.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text=""),
    ]
    result = make_agent(config, bus, scripts).run("look around")

    assert result.ok
    assert result.text == "Reading the file to see what changed."


def test_a_turn_that_said_nothing_at_all_is_asked_once(config, bus):
    scripts = [
        Script(text="", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text=""),
        Script(text="I listed the directory; it has three files."),
    ]
    agent = make_agent(config, bus, scripts)
    result = agent.run("look around")

    assert result.text == "I listed the directory; it has three files."


def test_it_is_asked_only_once(config, bus):
    """A model that answers an empty message with another one must not be
    asked forever."""
    scripts = [Script(text=""), Script(text=""), Script(text="")]
    agent = make_agent(config, bus, scripts)

    result = agent.run("say something")

    assert result.stopped == "done"
    assert result.text == ""
    assert result.steps <= 3, f"it kept asking: {result.steps} steps"


def test_the_nudge_does_not_invite_an_invented_result(config, bus):
    """A model pushed to report a result it does not have is a model invited
    to make one up."""
    from comodor.agent.loop import SAY_WHAT_HAPPENED

    assert "did nothing" in SAY_WHAT_HAPPENED
    assert "do not describe work you did not do" in SAY_WHAT_HAPPENED


def test_an_ordinary_answer_is_untouched(config, bus):
    result = make_agent(config, bus, [Script(text="All done.")]).run("hi")

    assert result.text == "All done."
    assert result.steps == 1
