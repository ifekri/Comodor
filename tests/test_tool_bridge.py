"""The tool bridge: a script's way into read-only tools, and nothing more."""

from __future__ import annotations

from comodor.agent.tool_bridge import Bridge
from comodor.events import EventBus
from comodor.safety import Risk
from comodor.tools.base import Tool, ToolContext, ToolResult
from comodor.tools.registry import ToolRegistry


class FakePermissions:
    def check(self, **kwargs):
        return type("D", (), {"__bool__": lambda self: True,
                              "reason": "", "remembered": False})()

    def denied_command(self, command):
        return None


class ReadThing(Tool):
    name = "read_thing"
    description = "reads a thing"
    risk = Risk.SAFE
    parameters = {"type": "object", "properties": {
        "path": {"type": "string"}}}

    def run(self, ctx, path: str = "", **_) -> ToolResult:
        return ToolResult.success(content=f"contents of {path}")


class WriteThing(Tool):
    name = "write_thing"
    description = "writes a thing"
    risk = Risk.WRITE
    parameters = {"type": "object", "properties": {}}

    def run(self, ctx, **_) -> ToolResult:
        return ToolResult.success(content="wrote")


def bridge_with(tools, mode="act", max_calls=200, max_seconds=30.0):
    registry = ToolRegistry(tools=[ReadThing(), WriteThing()])
    config = type("C", (), {"agent": type("A", (), {"mode": mode})()})()
    ctx = ToolContext(
        config=config,
        permissions=FakePermissions(),
        checkpoints=type("K", (), {"journal": None})(),
        bus=EventBus(),
        redact=lambda text: text,
        cancel=type("X", (), {"cancelled": False,
                              "raise_if_cancelled": lambda self: None})(),
        cwd=_cwd(),
    )
    return Bridge(registry, ctx, max_calls=max_calls, max_seconds=max_seconds)


def _cwd():
    import pathlib
    return pathlib.Path.cwd()


def reply(raw: str) -> dict:
    import json
    return json.loads(raw)


# -- the happy path ---------------------------------------------------------- #

def test_a_call_goes_through_the_normal_gate():
    bridge = bridge_with([ReadThing()])
    result = reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "read_thing", "arguments": {"path": "a.txt"}}'))
    assert result["ok"] is True
    assert result["content"] == "contents of a.txt"
    assert bridge.calls == 1


def test_the_offer_names_only_safe_tools():
    bridge = bridge_with([ReadThing(), WriteThing()])
    result = reply(bridge.handle_line('{"id": 1, "op": "list"}'))
    assert "read_thing" in result["content"]
    assert "write_thing" not in result["content"]


# -- the refusals that make the design real ----------------------------------- #

def test_a_write_tool_is_refused_with_the_reason():
    bridge = bridge_with([WriteThing()])
    result = reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "write_thing", "arguments": {}}'))
    assert result["ok"] is False
    assert "read-only" in result["content"]


def test_an_unknown_tool_says_what_exists():
    bridge = bridge_with([ReadThing()])
    result = reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "run_shell", "arguments": {}}'))
    assert result["ok"] is False
    assert "unknown tool" in result["content"]
    assert "list_available" in result["content"]


def test_plan_mode_hides_the_write_tools_by_name():
    bridge = bridge_with([ReadThing()], mode="plan")
    result = reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "write_thing", "arguments": {}}'))
    assert result["ok"] is False
    assert "read-only" in result["content"]


def test_the_call_cap_freezes_the_bridge():
    bridge = bridge_with([ReadThing()], max_calls=2)
    assert reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "read_thing", "arguments": {}}'))["ok"]
    assert reply(bridge.handle_line(
        '{"id": 2, "op": "call", "tool": "read_thing", "arguments": {}}'))["ok"]
    spent = reply(bridge.handle_line(
        '{"id": 3, "op": "call", "tool": "read_thing", "arguments": {}}'))
    assert spent["ok"] is False
    assert "budget is spent" in spent["content"]


def test_the_time_cap_freezes_the_bridge():
    bridge = bridge_with([ReadThing()], max_seconds=0.0)
    result = reply(bridge.handle_line(
        '{"id": 1, "op": "call", "tool": "read_thing", "arguments": {}}'))
    assert result["ok"] is False
    assert "time limit" in result["content"]


def test_garbage_gets_a_reply_not_a_crash():
    bridge = bridge_with([ReadThing()])
    assert reply(bridge.handle_line("not json at all"))["ok"] is False
    assert reply(bridge.handle_line('["a list"]'))["ok"] is False
    assert reply(bridge.handle_line('{"id": 1, "op": "explode"}'))["ok"] is False


# -- end to end through the real subprocess ------------------------------------ #

def test_the_full_pipe_end_to_end(tool_context, tmp_path):
    """A real script, a real subprocess, real tool calls through the bridge."""
    registry = ToolRegistry()
    registry._tools["run_python"].use_registry(registry)
    (tool_context.cwd / "sample.txt").write_text("alpha\nbeta\ngamma\n")

    code = """
import sys
available = comodor.tools.list_available()
print("read_file" in available, file=sys.stderr)

try:
    comodor.tools.run_shell(command="echo pwned")
except RuntimeError as error:
    print("refused:", error, file=sys.stderr)

head = comodor.tools.read_file(path="sample.txt")
print("lines:", len(head.splitlines()), file=sys.stderr)
"""
    from comodor.tools.base import ToolResult  # noqa: F401
    result = registry.invoke("run_python", tool_context,
                             {"code": code, "tools": True, "timeout": 60.0})
    assert result.ok, result.content
    assert "True" in result.content
    assert "refused:" in result.content
    assert "read-only" in result.content
    assert "lines:" in result.content
    assert result.meta.get("bridge_calls", 0) >= 2


def test_the_script_that_prints_to_stdout_still_gets_its_own_stderr_through(
        tool_context):
    registry = ToolRegistry()
    registry._tools["run_python"].use_registry(registry)
    code = "print('to stderr')\n"
    result = registry.invoke("run_python", tool_context,
                             {"code": code, "tools": True, "timeout": 30.0})
    assert result.ok
    assert "to stderr" in result.content


def test_a_script_without_tools_is_untouched(tool_context):
    registry = ToolRegistry()
    registry._tools["run_python"].use_registry(registry)
    result = registry.invoke("run_python", tool_context,
                             {"code": "print(6 * 7)"})
    assert result.ok
    assert "42" in result.content


def test_unwired_run_python_refuses_tools_true(tool_context):
    from comodor.tools.shell import RunPython

    tool = RunPython()
    result = tool.run(tool_context, code="pass", tools=True)
    assert not result.ok
    assert "needs a tool registry" in result.content
