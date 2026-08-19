"""Presenting an MCP server's tool as one of Comodor's own.

The adapter is thin on purpose. What it must not do is let a foreign tool
bypass the rules that apply to Comodor's own: an MCP server can write files,
run queries and reach the network, so its calls go through the same permission
gate as `run_shell` does.

Risk is judged from the tool's own description, which is imperfect and is
supposed to be. Erring towards asking costs the user a keypress; erring the
other way runs somebody else's code against their machine without telling them.
"""

from __future__ import annotations

import re
from typing import Any

from ..mcp.manager import SEPARATOR
from ..mcp.protocol import MCPError, ToolDescription
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult

#: Words in a tool's name or description that mean it changes something. A
#: server is free to describe a destructive tool as "update the record", so the
#: list is broad and the failure mode is an unnecessary prompt.
WRITES = re.compile(
    r"\b(write|create|update|delete|remove|insert|drop|edit|modify|set|put|"
    r"post|patch|push|commit|merge|rename|move|upload|send|publish|execute|"
    r"run|install|deploy|kill|restart)\b", re.IGNORECASE)
#: Things that leave the machine. Comodor's safety model puts network calls in
#: the same tier as shell commands: they always ask.
NETWORK = re.compile(
    r"\b(fetch|http|url|web|browse|navigate|search|download|api|request)\b",
    re.IGNORECASE)


class MCPTool(Tool):
    """One tool from one MCP server."""

    def __init__(self, manager: Any, server: str,
                 description: ToolDescription) -> None:
        self.manager = manager
        self.server = server
        self.remote_name = description.name

        self.name = f"{server}{SEPARATOR}{description.name}"
        self.description = _describe(server, description)
        self.parameters = _schema(description.schema)
        self.risk = _risk(description)

    def summary(self, args: dict[str, Any]) -> str:
        detail = ", ".join(f"{key}={_short(value)}"
                           for key, value in list(args.items())[:3])
        return f"{self.server}: {self.remote_name}({detail})"

    def run(self, ctx: ToolContext, **arguments: Any) -> ToolResult:
        try:
            text = self.manager.call(self.server, self.remote_name, arguments)
        except MCPError as error:
            # Reported as a tool failure rather than raised: the agent should
            # get the chance to try something else, the way it would with any
            # other tool that did not work.
            return ToolResult.failure(f"{self.server}: {error}")
        except Exception as error:
            return ToolResult.failure(
                f"{self.server}: {type(error).__name__}: {error}")

        if not text:
            return ToolResult.success(
                "(the tool returned nothing)",
                display=f"{self.remote_name}: empty result")

        return ToolResult.success(
            text,
            display=f"{self.remote_name}: {len(text)} chars",
            server=self.server, tool=self.remote_name)


def _describe(server: str, description: ToolDescription) -> str:
    """The description the model sees, with its origin attached.

    Saying where a tool comes from matters once there are several servers: the
    model picks between `github__search` and `brave-search__search` on this
    text alone.
    """
    text = (description.description or "").strip()
    if not text:
        text = f"The {description.name} tool."
    return f"{text}\n\n(Provided by the {server} MCP server.)"


def _schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Normalise a server's JSON Schema into what the provider layer expects.

    Servers are inconsistent about this — some omit `type`, some omit
    `properties` entirely — and a malformed schema makes the whole tool list
    unusable rather than just that one tool.
    """
    if not isinstance(schema, dict) or not schema:
        return {"type": "object", "properties": {}}

    normalised = dict(schema)
    normalised.setdefault("type", "object")
    if not isinstance(normalised.get("properties"), dict):
        normalised["properties"] = {}
    if "required" in normalised and not isinstance(normalised["required"], list):
        del normalised["required"]
    return normalised


def _risk(description: ToolDescription) -> Risk:
    """Guess how much this tool can do, and round up when unsure."""
    haystack = f"{description.name} {description.description}"
    if NETWORK.search(haystack):
        return Risk.DANGEROUS
    if WRITES.search(haystack):
        return Risk.WRITE
    return Risk.SAFE


def _short(value: Any, limit: int = 40) -> str:
    text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
