"""A tool bridge: a script's way into the agent's own read-only tools.

Some answers need a lot of reading and one sentence. Reached one call at a
time, that reading is paid for twice — once in round trips, and once
permanently, because every tool result becomes part of the conversation and
is resent with every request afterwards. A script that reads thirty files,
keeps the three numbers it needed, and returns a sentence has read thirty
files at the cost of one.

The shape:

* **Out-of-process script, in-process dispatch.** The script itself runs in a
  subprocess, exactly as `run_python` always has — same isolation, same
  timeout, same DANGEROUS permission cost. The bridge is the parent half of a
  pipe protocol: the child writes one JSON request per line on stdout, the
  parent dispatches it through the normal tool registry — permission engine,
  mode filter, overflow bounding and all — and writes the reply back. There
  is no network, no daemon, no second place where permissions are checked.
* **SAFE tools only, by the registry's own definition.** The offer list is
  whatever the registry currently rates SAFE in the current mode — no second
  list to keep in step. Naming a write tool in a script is an error that says
  why, not a silence.
* **Metered, and it freezes when the meter ends.** Calls per run and seconds
  open are both capped. Past either, the bridge refuses with a plain message
  and the script can still finish.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from ..safety import Risk
from ..tools.base import ToolContext

#: Calls per script run. A pipeline that needs more is a pipeline that should
#: be ordinary tool calls the user can watch one by one.
BRIDGE_MAX_CALLS = 200
#: How long the bridge stays open for one run. The script's own subprocess
#: timeout governs its lifetime; this bounds the parent-side work its calls
#: can cause.
BRIDGE_MAX_SECONDS = 120.0


class Bridge:
    """The parent half of the protocol: dispatch, meter, stay honest.

    One per `run_python(tools=true)` call, so one script cannot spend another
    run's budget. `handle_line` is the whole surface: request line in, reply
    line out, never raises.
    """

    def __init__(self, registry: Any, ctx: ToolContext,
                 max_calls: int = BRIDGE_MAX_CALLS,
                 max_seconds: float = BRIDGE_MAX_SECONDS) -> None:
        self._registry = registry
        self._ctx = ctx
        self._max_calls = max_calls
        self._deadline = time.monotonic() + max_seconds
        self._lock = threading.Lock()
        self._calls = 0

    def handle_line(self, line: str) -> str:
        """One request line in, one reply line out. Never raises."""
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("not an object")
        except ValueError:
            return _reply(ok=False, content="not a JSON request object")

        number = request.get("id")
        try:
            with self._lock:
                self._calls += 1
                calls = self._calls
            if calls > self._max_calls:
                return _reply(id=number, ok=False, content=(
                    f"the bridge budget is spent ({self._max_calls} calls per "
                    "run). Finish with what you have."))
            if time.monotonic() > self._deadline:
                return _reply(id=number, ok=False, content=(
                    "the bridge has been open past its time limit and is "
                    "closed. Finish with what you have."))

            if request.get("op") == "list":
                return _reply(id=number, ok=True, content=self._offer())

            if request.get("op") != "call":
                return _reply(id=number, ok=False,
                              content="op must be \"call\" or \"list\"")

            name = str(request.get("tool") or "")
            arguments = request.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _reply(id=number, ok=False,
                              content="arguments must be an object")

            tool = self._registry.get(name)
            if tool is None:
                return _reply(id=number, ok=False, content=_unknown(name))
            if tool.risk is not Risk.SAFE:
                return _reply(id=number, ok=False, content=(
                    f"{name} is not available through the bridge: only "
                    "read-only tools are. A script has no path to write, "
                    "shell, or network tools — that is the design, not a "
                    "malfunction."))
            offered = {candidate.name for candidate in
                       self._registry.for_mode(self._ctx.config.agent.mode)}
            if name not in offered:
                return _reply(id=number, ok=False, content=(
                    f"{name} is read-only but is not offered in "
                    f"{self._ctx.config.agent.mode} mode."))

            result = tool.invoke(self._ctx, dict(arguments))
            self._announce(name, tool.summary(arguments), result)
            return _reply(id=number, ok=result.ok, content=result.content,
                          meta=_plain(result.meta))
        except Exception as error:                   # the parent must not die
            return _reply(id=number, ok=False,
                          content=f"bridge error: {type(error).__name__}: {error}")

    # -- the offer ------------------------------------------------------------ #

    def _offer(self) -> str:
        """The SAFE tools of the current mode, with their parameters."""
        offered = [tool for tool in self._registry.for_mode(self._ctx.config.agent.mode)
                   if tool.risk is Risk.SAFE]
        lines = ["Read-only tools, callable as comodor.tools.<name>(**arguments):"]
        for tool in offered:
            properties = (getattr(tool, "parameters", {}) or {}).get("properties") or {}
            params = ", ".join(str(key) for key in properties) or "no arguments"
            lines.append(f"- {tool.name}: {params}")
        return "\n".join(lines)

    @property
    def calls(self) -> int:
        return self._calls

    def _announce(self, name: str, summary: str, result: Any) -> None:
        """Show the call on the bus, prefixed, so the user sees the reading.

        A script quietly reading thirty files while the interface sits still
        looks frozen. These events give the same progress the normal tool
        calls give — and make it obvious the script, not the agent, is asking.
        """
        try:
            from ..events import Kind

            self._ctx.bus.emit(Kind.TOOL_START, id=f"bridge-{self._calls}",
                               name=f"bridge.{name}", summary=f"bridge: {summary}")
            self._ctx.bus.emit(Kind.TOOL_END, id=f"bridge-{self._calls}",
                               name=f"bridge.{name}", ok=result.ok,
                               content=result.content, display=result.rendered,
                               elapsed=result.elapsed)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# the child half, injected into the script's namespace
# --------------------------------------------------------------------------- #

#: Setup code run before the user's script, defining the `comodor` object.
#: The child *writes* requests on stdout and reads replies on stdin, one JSON
#: object per line, so the user's own prints must go to stderr while the
#: bridge is in use — which the setup tells the script outright.
CHILD_SETUP = '''\
import json as _json
import sys as _sys

class _BridgeClosed(Exception):
    pass

def _bridge_call(tool, arguments):
    _sys.stdout.write(_json.dumps({"op": "call", "tool": tool,
                                   "arguments": arguments}) + "\\n")
    _sys.stdout.flush()
    line = _sys.stdin.readline()
    if not line:
        raise _BridgeClosed("the bridge closed before answering")
    reply = _json.loads(line)
    if not reply.get("ok"):
        raise RuntimeError(reply.get("content") or "the bridge refused the call")
    return reply.get("content", "")

def _bridge_list():
    _sys.stdout.write(_json.dumps({"op": "list"}) + "\\n")
    _sys.stdout.flush()
    reply = _json.loads(_sys.stdin.readline())
    return reply.get("content", "")

class _Tools:
    def list_available(self):
        """The read-only tools and their parameters, as text."""
        return _bridge_list()

    def __getattr__(self, name):
        def _call(**arguments):
            return _bridge_call(name, arguments)
        return _call

    def __dir__(self):
        try:
            listing = _bridge_list()
        except Exception:
            return ["list_available"]
        return sorted({line.split(":")[0].lstrip("- ")
                       for line in listing.splitlines()
                       if line.startswith("- ")}) + ["list_available"]

class _Comodor:
    tools = _Tools()

comodor = _Comodor()

# The protocol owns stdout while the bridge is in use. Saying so beats a
# script whose prints silently vanish into the protocol stream.
print("[comodor.tools is live on stdout — send your own output to stderr]",
      file=_sys.stderr)
'''


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #

def _reply(**fields: Any) -> str:
    return json.dumps(fields)


def _unknown(name: str) -> str:
    return (f"unknown tool {name!r}. Call comodor.tools.list_available() "
            "first — only read-only tools are offered.")


def _plain(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in (meta or {}).items()
            if isinstance(value, (str, int, float, bool))}
