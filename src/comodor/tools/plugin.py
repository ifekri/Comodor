"""Bridging a plugin's registered function into the tool set.

The adapter is one class and no policy of its own: risk comes from what the
plugin declared, the schema from what it provided, and every call goes
through the ordinary permission gate. A plugin tool is indistinguishable
from a built-in to the model and to the approval dialog — which is the
point, and also why the risk declaration is checked at load time.
"""

from __future__ import annotations

from typing import Any

from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

_RISK_OF = {"SAFE": Risk.SAFE, "WRITE": Risk.WRITE,
            "DANGEROUS": Risk.DANGEROUS}


class PluginTool(Tool):
    """One tool a plugin registered."""

    def __init__(self, plugin_name: str, spec: dict[str, Any]) -> None:
        self.plugin = plugin_name
        self.name = spec["name"]
        self.description = f"{spec['description']} (plugin: {plugin_name})"
        self.parameters = spec["parameters"]
        self.handler = spec["handler"]
        self.risk = _RISK_OF.get(spec["risk"], Risk.DANGEROUS)

    def summary(self, args: dict[str, Any]) -> str:
        preview = ", ".join(f"{key}={str(value)[:40]}"
                            for key, value in list(args.items())[:3])
        return f"{self.name}({preview})" if preview else self.name

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        try:
            outcome = self.handler(**args)
        except TypeError as problem:
            return ToolResult.failure(f"invalid arguments for {self.name}: "
                                      f"{problem}")
        except Exception as problem:
            # The plugin is not ours; its exceptions are data, not crashes.
            return ToolResult.failure(
                f"{self.plugin}: {type(problem).__name__}: {problem}")

        if isinstance(outcome, ToolResult):
            return outcome
        if isinstance(outcome, str):
            return ToolResult.success(outcome)
        if isinstance(outcome, dict):
            return ToolResult.success(
                str(outcome.get("content") or outcome.get("text") or ""),
                display=str(outcome.get("display") or ""))
        return ToolResult.success(str(outcome))
