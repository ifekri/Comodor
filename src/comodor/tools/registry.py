"""The set of tools the agent may use.

Mode filtering happens here as well as in the permission engine, and that
duplication is deliberate: in Plan mode the write tools are not merely blocked,
they are never *advertised* to the model. A model that cannot see a tool does
not plan around it, so a plan produced in Plan mode reads like a plan rather
than like a thwarted attempt to edit files.
"""

from __future__ import annotations

from typing import Iterable

from ..providers.base import ToolSpec
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult
from .fs import EditFile, ListDir, ReadFile, WriteFile
from .search import Glob, Grep
from .shell import RunPython, RunShell
from .todo import TodoWrite
from .web import WebFetch, WebSearch

DEFAULT_TOOLS: tuple[type[Tool], ...] = (
    ReadFile, WriteFile, EditFile, ListDir,
    Glob, Grep,
    RunShell, RunPython,
    WebFetch, WebSearch,
    TodoWrite,
)


class ToolRegistry:
    """Holds tool instances and answers "what can I use right now?"."""

    def __init__(self, tools: Iterable[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools if tools is not None else (cls() for cls in DEFAULT_TOOLS):
            self.add(tool)

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

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
        if mode == "plan":
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

        return tool.invoke(ctx, args)
