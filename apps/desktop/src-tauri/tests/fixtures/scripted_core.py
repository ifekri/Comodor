"""A real Comodor Core with scripted model responses, for the desktop's tests.

Test-only. It is never packaged and never used by the application itself.

It is the same `CoreService` and `Server` that `comodor core --stdio` runs,
built the way the protocol tests build one (`tests/test_protocol_permissions.py`):
`CoreService(config, assemble_with=...)` with a provider that replays scripts
instead of calling a model. Nothing reaches a network, and nothing is written
outside the temporary `COMODOR_HOME` and workspace the test chose.

    python scripted_core.py <scenario> core --stdio

The application appends `core --stdio` itself (contracts/core-supervision.md
§2); they are accepted and ignored here.

**Hold points.** Some scenarios stop at an explicit point until the test lets
them go. The point is a `multiprocessing.connection` listener — a named pipe on
Windows, a Unix socket elsewhere — at the address in `COMODOR_TEST_HOLD`. It is
opened at startup, so a test may connect before the hold is reached; the hold
itself is a blocking `accept()` and `recv_bytes()`. Released by a message, never
by elapsed time, and never polled.
"""

from __future__ import annotations

import os
import sys
import threading
from multiprocessing.connection import Listener
from pathlib import Path
from typing import Any

from comodor.agent import AgentLoop, Conversation
from comodor.application import Assembly, CoreService
from comodor.config import load
from comodor.events import EventBus
from comodor.providers import fake as fake_module
from comodor.providers import gateway as gateway_module
from comodor.providers.base import EventType, ToolCall
from comodor.providers.fake import FakeProvider, Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools.base import Risk, Tool, ToolContext, ToolResult
from comodor.transport.jsonl import Channel, own_stdout
from comodor.transport.server import Server

#: The strings every surface must show as inert text (quickstart.md §6).
ADVERSARIAL = (
    "<script>window.__pwned = true</script> <img src=x onerror=\"window.__pwned=1\"> "
    "[click](javascript:alert(1)) \x1b[2J\x1b[H\x1b]0;forged title\x07 [Connected] [Ready]"
)

#: Grounded in the prompt the test sends, so the `ask` tool keeps the options.
QUESTION_PROMPT = "Build the service. Which database: SQLite or PostgreSQL?"


class Hold:
    """One explicit release point, reachable from the test."""

    def __init__(self, address: str | None) -> None:
        self._listener: Listener | None = None
        if address:
            family = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"
            if family == "AF_UNIX" and os.path.exists(address):
                # Left by an earlier launch that was killed, as the restart
                # tests do; a stale socket file would refuse this bind.
                os.unlink(address)
            self._listener = Listener(address=address, family=family, authkey=None)

    def wait(self) -> None:
        if self._listener is None:
            raise RuntimeError("this scenario needs COMODOR_TEST_HOLD")
        with self._listener.accept() as connection:
            connection.recv_bytes()


HOLD = Hold(os.environ.get("COMODOR_TEST_HOLD"))
SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "echo"


class HoldStep(Tool):
    """A test-only step that blocks at the hold point (cancel-between-messages)."""

    name = "hold_step"
    description = "Test fixture: waits until the test releases it."
    risk = Risk.SAFE
    parameters: dict[str, Any] = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        HOLD.wait()
        return ToolResult.success("released")


class EchoText(Tool):
    """A test-only tool whose output is whatever text it was given."""

    name = "echo_text"
    description = "Test fixture: returns its text."
    risk = Risk.SAFE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
    }

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        return ToolResult.success(str(args.get("text", "")))


class ScriptedProvider(FakeProvider):
    """The fake provider, plus the two behaviours a scenario may need.

    `hold`: after the first visible chunk of the first answer, wait at the
    hold point — a turn that is provably mid-message. `crash`: end the whole
    process on the first model call, the way a Core that dies mid-turn does.
    """

    def stream(self, messages, *, tools=None, **kwargs):
        preflight = fake_module._is_preflight(messages)
        if SCENARIO == "crash-on-send" and not preflight:
            os._exit(70)
        held = getattr(self, "_held", False)
        for event in super().stream(messages, tools=tools, **kwargs):
            yield event
            if (not preflight and not held and event.type is EventType.TEXT
                    and SCENARIO in ("hold-mid-turn", "cancel-mid-message")):
                held = True
                self._held = True
                HOLD.wait()


def ask_call() -> ToolCall:
    return ToolCall(id="q1", name="ask", arguments={"questions": [{
        "question": "Which database should this use?",
        "header": "Database",
        "affects": ["architecture"],
        "options": [
            {"label": "SQLite", "source": "request", "evidence": "SQLite"},
            {"label": "PostgreSQL", "source": "request", "evidence": "PostgreSQL"},
        ],
    }]})


def scripts_for(scenario: str) -> list[Script] | None:
    if scenario in ("echo", "complete-turn", "crash-on-send"):
        return None
    if scenario == "stream-long":
        return [Script(text=" ".join(f"word{n}" for n in range(1500)))]
    if scenario in ("hold-mid-turn", "cancel-mid-message"):
        return [Script(text="The first words arrive, then the answer waits at the "
                            "hold point, and then the rest of it follows.")]
    if scenario in ("question", "clarification-stop"):
        return [Script(text="Asking.", tool_calls=[ask_call()]),
                Script(text="Done with the answer.")]
    if scenario == "permission":
        return [Script(text="Writing the file.", tool_calls=[ToolCall(
                    id="c1", name="write_file",
                    arguments={"path": "out.txt", "content": "hello"})]),
                Script(text="Done.")]
    if scenario == "adversarial":
        return [Script(text=ADVERSARIAL, tool_calls=[
                    ToolCall(id="t1", name="echo_text", arguments={"text": ADVERSARIAL}),
                    ToolCall(id="t2", name="read_file",
                             arguments={"path": "missing \x1b[2J [Ready].txt"})]),
                Script(text=ADVERSARIAL)]
    if scenario == "cancel-between-messages":
        return [Script(text="", tool_calls=[ToolCall(id="h1", name="hold_step",
                                                     arguments={})]),
                Script(text="After the step.")]
    if scenario == "fail-between-messages":
        return [Script(text="Looking.", tool_calls=[ToolCall(
                    id="e1", name="echo_text", arguments={"text": "ok"})]),
                Script(error="the provider failed", error_after=0)]
    if scenario == "fail-mid-message":
        return [Script(text="A partial answer that then fails part of the way.",
                       error="the provider failed", error_after=1)]
    raise SystemExit(f"scripted_core: unknown scenario {scenario!r}")


def record_launch() -> None:
    """What this process was started with, for the spawn tests (T010)."""
    target = os.environ.get("COMODOR_TEST_ARGV_FILE")
    if target:
        import json

        Path(target).write_text(json.dumps({
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
            "marker": os.environ.get("COMODOR_TEST_MARKER"),
            "path": os.environ.get("PATH"),
        }), encoding="utf-8")


def main() -> int:
    if sys.platform == "win32":
        sys.stdin.reconfigure(encoding="utf-8")
    record_launch()
    gateway_module.FakeProvider = ScriptedProvider
    config = load(cwd=os.getcwd())
    # The scripts are the whole turn, and several need the call after a tool
    # (the answer after a form, the failure between messages). With the loop
    # off the agent stops after the first tools and those calls never happen.
    config.agent.loop = True
    if SCENARIO == "permission":
        config.safety.auto_approve_writes = False
        config.safety.auto_approve_safe = True
    scripts = scripts_for(SCENARIO)

    def assemble(built_config, *, bus=None, plugins=None, delegates=False) -> Assembly:
        bus = bus or EventBus()
        permissions = PermissionEngine(built_config, bus)
        tools = ToolRegistry(config=built_config)
        tools.add(HoldStep())
        tools.add(EchoText())
        # The conversation is on the assembly as the real one has it, so the
        # Core persists each turn to the temporary home like the real Core.
        conversation = Conversation()
        agent = AgentLoop(built_config, Gateway(built_config, scripts=scripts),
                          tools, bus, permissions, conversation)
        return Assembly(config=built_config, bus=bus, gateway=None, memory=None,
                        permissions=permissions, skills=None, mcp=None,
                        tools=agent.tools, agent=agent, conversation=conversation)

    channel_out, restore = own_stdout()
    channel = Channel(reader=sys.stdin, writer=channel_out, log=sys.stderr)
    service = CoreService(config, assemble_with=assemble)
    server = Server(service, channel, name="comodor-core")
    print(f"scripted core: scenario {SCENARIO}, pid {os.getpid()}", file=sys.stderr)
    try:
        server.serve()
    finally:
        service.close()
        restore()
    return 0


if __name__ == "__main__":
    # A daemon thread waiting forever keeps nothing alive on its own; the
    # process ends when `serve` returns on stdin EOF, as a real Core does.
    threading.current_thread().name = "scripted-core"
    sys.exit(main())
