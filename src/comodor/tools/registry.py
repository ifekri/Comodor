"""The set of tools the agent may use.

Mode filtering happens here as well as in the permission engine, and that
duplication is deliberate: in Plan mode the write tools are not merely blocked,
they are never *advertised* to the model. A model that cannot see a tool does
not plan around it, so a plan produced in Plan mode reads like a plan rather
than like a thwarted attempt to edit files.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..providers.base import ToolSpec
from ..safety import Risk
from . import overflow
from .ask import Ask
from .base import Tool, ToolContext, ToolResult
from .browser import Browser
from .cronjob import CronJob
from .delegate import Delegate
from .fs import EditFile, ListDir, ReadFile, WriteFile
from .history import SearchHistory
from .propose_mode import ProposeMode
from .search import Glob, Grep
from .shell import RunPython, RunShell
from .skill_manage import SkillManage
from .skills import ReadSkillFile
from .todo import TodoWrite
from .web import WebFetch, WebSearch

DEFAULT_TOOLS: tuple[type[Tool], ...] = (
    ReadFile, WriteFile, EditFile, ListDir,
    Glob, Grep,
    RunShell, RunPython,
    WebFetch, WebSearch,
    TodoWrite,
    Ask, ProposeMode,
)


def _browser_tool() -> Tool:
    """The real browser where there is one, the text browser where there is not.

    Both would be offered as something called "browser", and choosing between
    two of those is a turn the model should not have to spend. The real one
    needs Chrome, Chromium, Edge or Brave installed; the text one needs nothing
    and still answers most questions about a page.
    """
    try:
        from ..browser.launch import find

        find()
    except Exception:
        return Browser()
    from .browse import Browse

    return Browse()


class ToolRegistry:
    """Holds tool instances and answers "what can I use right now?"."""

    def __init__(self, tools: Iterable[Tool] | None = None,
                 skills: Any = None, history: Any = None,
                 session_id: str = "", mcp: Any = None,
                 spawn: Any = None, config: Any = None,
                 cron_store: Any = None, skill_ledger: Any = None) -> None:
        self._tools: dict[str, Tool] = {}
        if tools is not None:
            for tool in tools:
                self.add(tool)
        else:
            for cls in DEFAULT_TOOLS:
                self.add(cls())
            self.add(_browser_tool())
        # Only offered when a skill actually bundles files. A tool the model can
        # see but can never use successfully is worse than one that is absent:
        # it invites a wasted call on every turn.
        if skills is not None and any(skill.bundled for skill in skills.all()):
            self.add(ReadSkillFile(skills))
        # Likewise: with no transcripts yet there is nothing to find, and a
        # search tool that can only ever answer "nothing" trains the model to
        # keep asking.
        if history is not None and history.stats()["turns"]:
            self.add(SearchHistory(history, current_session=session_id))
        # Only where there is something to spawn *with*. A delegate needs a
        # gateway, and a registry built without one — inside a delegate, for
        # instance — must not advertise a tool that cannot run.
        if spawn is not None:
            self.add(Delegate(spawn))
        # The scheduler's own runs build their registry through cron/runner,
        # which simply does not pass a cron store — and that absence is the
        # recursion guard: a scheduled run cannot schedule another.
        if cron_store is not None:
            self.add(CronJob(cron_store))
        # The skills tool, where skills are enabled at all. It reaches the
        # managed skills directories only, and every change it makes is
        # recorded in the ledger so the person can put it back.
        if skills is not None and config is not None \
                and getattr(config, "skills", None) and config.skills.enabled:
            from ..skills.ledger import Ledger

            self.add(SkillManage(ledger=skill_ledger or Ledger(
                config.paths.skills)))
        # The desktop, when this machine can be driven and the user has said
        # so. Both conditions matter: a tool that answers "not on this
        # platform" every time is the wasted call this rule exists to prevent,
        # and a tool that can take the mouse is not something a default enables.
        if config is not None and getattr(config, "computer", None) \
                and config.computer.enabled:
            self._add_computer(config)

        # Whatever the enabled MCP servers offer, alongside the built-in tools
        # and subject to exactly the same permission gate.
        if mcp is not None:
            for tool in mcp.tools():
                self.add(tool)

    def _add_computer(self, config: Any) -> None:
        """The computer tool, if this platform has a backend for it."""
        from ..desktop import available

        if not available():
            return
        from ..desktop.guard import NEVER, Guard
        from .computer import Computer

        extra = tuple(str(entry).lower() for entry in
                      getattr(config.computer, "never", ()) or ())
        self.add(Computer(guard=Guard(deny=NEVER + extra),
                          overlay=bool(getattr(config.computer, "overlay", True))))

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def close(self) -> None:
        """Let go of anything a tool is holding open.

        The browser keeps a connection pool and a cookie jar for the length of
        a session, which is the point of it; leaving them to the garbage
        collector means a socket that outlives the program's own shutdown
        message. A tool with nothing to release simply has no `close`.
        """
        for tool in self._tools.values():
            closer = getattr(tool, "close", None)
            if closer is None:
                continue
            try:
                closer()
            except Exception:
                pass

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    # -- mode-aware views -------------------------------------------------- #

    def for_mode(self, mode: str) -> list[Tool]:
        mode = (mode or "act").lower()
        if mode == "chat":
            return []
        if mode in ("plan", "ask"):
            return [tool for tool in self._tools.values() if tool.risk is Risk.SAFE]
        return list(self._tools.values())

    def specs(self, mode: str = "act") -> list[ToolSpec]:
        return [tool.spec() for tool in self.for_mode(mode)]

    # -- dispatch ---------------------------------------------------------- #

    def invoke(self, name: str, ctx: ToolContext, args: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "none"
            return ToolResult.failure(
                f"unknown tool {name!r}. Available tools: {available}")

        allowed = {candidate.name for candidate in self.for_mode(ctx.config.agent.mode)}
        if name not in allowed:
            return ToolResult.failure(
                f"{name} is not available in {ctx.config.agent.mode} mode")

        # Arguments that were not JSON at all. `parse_arguments` puts what it
        # could not decode under `__raw__` rather than crashing, and that then
        # reached the tool as an unexpected keyword — so the model was told
        # "invalid arguments for read_file: unexpected keyword __raw__", which
        # names neither the problem nor the fix. Weaker models emit this
        # regularly and, told that, emit it again. Showing the schema turns a
        # loop into a correction.
        if "__raw__" in args:
            return ToolResult.failure(_teach(tool, str(args["__raw__"])))

        # Bounded here rather than in each tool, so a tool added tomorrow —
        # or one that arrived over MCP and was never written here at all — is
        # covered by the same rule as the ones that exist today.
        return overflow.contain(tool.invoke(ctx, args), ctx, name)


def _teach(tool: Any, raw: str) -> str:
    """Say what the tool wanted, next to what arrived.

    Deliberately shaped like an example rather than a schema dump. A model that
    has just failed to produce JSON is not helped by being handed more of it to
    read; it is helped by seeing the object it should have written.
    """
    schema = getattr(tool, "parameters", None) or {}
    properties = schema.get("properties") or {}
    required = [name for name in schema.get("required") or [] if name in properties]

    parts = []
    for name in required or list(properties)[:4]:
        kind = str((properties.get(name) or {}).get("type", "string"))
        parts.append(f'"{name}": {_example(kind)}')
    shape = "{" + ", ".join(parts) + "}"

    optional = [name for name in properties if name not in required]
    tail = (f" Optional: {', '.join(sorted(optional)[:6])}." if optional else "")

    return (f"the arguments for {tool.name} were not valid JSON, so nothing "
            f"could be read from them.\n\n"
            f"Send an object like: {shape}{tail}\n\n"
            f"What arrived was: {raw[:300]}")


def _example(kind: str) -> str:
    # ASCII, and valid JSON as it stands. An ellipsis inside the example would
    # make the one thing being shown — a well-formed object — not one.
    return {"integer": "1", "number": "1", "boolean": "true",
            "array": "[]", "object": "{}"}.get(kind, '"..."')
