"""Reading what MCP servers offer to be read.

Tools go through the same gate as everything else; resources are the gentler
half of MCP — logs, tables, documents a server holds — and reading one changes
nothing, so the tool is SAFE. It is only advertised when some server actually
declares resources, on the same rule the rest of the registry follows: a tool
that can only ever answer "nothing" is a wasted schema on every turn.
"""

from __future__ import annotations

from typing import Any

from ..mcp.protocol import MCPError
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult


class MCPReadResource(Tool):
    """List or read the resources one MCP server offers."""

    name = "mcp_read_resource"
    description = (
        "Read data an MCP server offers as resources — logs, tables, "
        "documents, database listings. Called without a URI it lists what "
        "is available; called with one it returns the content."
    )
    risk = Risk.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "server": {"type": "string",
                       "description": "which MCP server to ask; omitted "
                                      "means list every server's resources"},
            "uri": {"type": "string",
                    "description": "the resource URI to read, as the list "
                                   "shows it; omitted means list only"},
        },
    }

    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def summary(self, args: dict[str, Any]) -> str:
        if args.get("uri"):
            return f"read {args['uri']}"
        return "list MCP resources"

    def run(self, ctx: ToolContext, server: str = "", uri: str = "",
            **_: Any) -> ToolResult:
        names = [server] if server else self.manager.enabled_names()
        if not names:
            return ToolResult.failure("no MCP servers are enabled")

        if not uri and len(names) > 1:
            # Listing several servers: one compact inventory, so the model
            # can pick without reading each in turn.
            lines: list[str] = []
            for name in names:
                state = self.manager.start(name)
                if not state.ok:
                    continue
                for resource in state.resources:
                    label = resource.name or resource.uri
                    note = f" — {resource.description}" if resource.description else ""
                    lines.append(f"{name}: {resource.uri} ({label}{note})")
            if not lines:
                return ToolResult.success(
                    "none of the enabled servers offer resources")
            return ToolResult.success("\n".join(lines),
                                      display=f"{len(lines)} resource(s)")

        who = names[0]
        if not uri:
            state = self.manager.start(who)
            if not state.ok:
                return ToolResult.failure(state.error or f"{who} is not running")
            if not state.resources:
                return ToolResult.success(f"{who} offers no resources")
            lines = []
            for resource in state.resources:
                label = resource.name or resource.uri
                note = f" — {resource.description}" if resource.description else ""
                lines.append(f"{resource.uri} ({label}{note})")
            return ToolResult.success("\n".join(lines),
                                      display=f"{who}: {len(lines)} resource(s)")

        try:
            text = self.manager.read_resource(who, uri)
        except MCPError as error:
            return ToolResult.failure(f"{who}: {error}")
        except Exception as error:
            return ToolResult.failure(
                f"{who}: {type(error).__name__}: {error}")
        return ToolResult.success(
            text or "(the resource is empty)",
            display=f"{who}: {uri} · {len(text)} chars",
            server=who, uri=uri)
