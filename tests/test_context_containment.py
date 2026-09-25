"""Containment can force a recovery read — the mechanism, not a history.

A tool result larger than the budget keeps its head and tail and drops the
middle. If the model needs the middle, it must ask again, and the benchmark's
end-to-end total pays for that extra turn *on top of* the containment.

This proves the architectural possibility with a deterministic provider that
decides from what it can actually see. It does **not** prove that any
historical benchmark run behaved this way: the committed T015/T096 artifacts
carry no truncation or overflow record, so historical causation is not
established here.
"""

from __future__ import annotations

from comodor.agent import AgentLoop, Conversation
from comodor.events import EventBus
from comodor.providers.base import EventType, Role, StreamEvent, ToolCall, Usage
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry

NEEDLE = "NEEDLE-IN-THE-MIDDLE"


def _a_file_with_a_middle_marker(workspace):
    lines = [f"line {n}" for n in range(1, 400)]
    lines[200] = NEEDLE                     # line 201, in the middle
    (workspace / "big.txt").write_text("\n".join(lines), encoding="utf-8")


def _a_model_that_needs_the_middle():
    """Read the file; then ask again while the marker is not visible; then answer.

    Returns the stream and the list it appends each provider call to.
    """
    calls: list[list] = []

    def stream(messages, **kwargs):
        calls.append(messages)
        seen = [m for m in messages if m.role is Role.TOOL]
        if not seen:
            yield StreamEvent(type=EventType.TOOL_CALL, tool_call=ToolCall(
                id="first", name="read_file", arguments={"path": "big.txt"}))
        elif NEEDLE not in "\n".join(m.content for m in seen):
            yield StreamEvent(type=EventType.TOOL_CALL, tool_call=ToolCall(
                id="recovery", name="read_file",
                arguments={"path": "big.txt", "offset": 201, "limit": 1}))
        else:
            yield StreamEvent(type=EventType.TEXT, text="found it")
        yield StreamEvent(type=EventType.USAGE,
                          usage=Usage(input_tokens=1, output_tokens=1))
        yield StreamEvent(type=EventType.DONE, finish_reason="end_turn")

    return stream, calls


def _an_agent(config, stream):
    bus = EventBus()
    agent = AgentLoop(config, Gateway(config, scripts=[]), ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation())
    agent.gateway.provider("fake").stream = stream
    return agent


def _reads(agent):
    return [c for m in agent.conversation.messages if m.role is Role.ASSISTANT
            for c in m.tool_calls if c.name == "read_file"]


def test_a_contained_read_forces_a_recovery_read(config, workspace):
    _a_file_with_a_middle_marker(workspace)
    config.agent.max_tool_chars = 800       # small enough to contain the read
    stream, calls = _a_model_that_needs_the_middle()
    agent = _an_agent(config, stream)

    agent.run("read big.txt and report the marked line")

    reads = _reads(agent)
    assert len(reads) >= 2, "the contained middle forced a second read"
    assert any(c.id == "recovery" for c in reads)
    # Every provider call is counted, so the extra turn shows in the total.
    assert len(calls) == 3
    assert agent.conversation.usage.total == 2 * len(calls)


def test_an_uncontained_read_needs_no_recovery_read(config, workspace):
    _a_file_with_a_middle_marker(workspace)
    config.agent.max_tool_chars = 100_000    # the whole read fits
    stream, calls = _a_model_that_needs_the_middle()
    agent = _an_agent(config, stream)

    agent.run("read big.txt and report the marked line")

    reads = _reads(agent)
    assert len(reads) == 1, "the visible middle needed no recovery read"
    assert not any(c.id == "recovery" for c in reads)
    assert len(calls) == 2
    assert agent.conversation.usage.total == 2 * len(calls)
