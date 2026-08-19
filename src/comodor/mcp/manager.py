"""Holding the connections, and turning what they offer into Comodor tools.

Two decisions shape this file.

**Servers start when they are first needed, not when Comodor does.** Several of
these fetch a package on first run; starting five of them up front would put
half a minute between pressing Enter and seeing anything. The tool list is
discovered lazily and cached, and a server that is never used is never spawned.

**A server that fails is a server that is dropped, once, with an explanation.**
It is somebody else's program. If it will not start, the agent should continue
without it rather than fail the user's task, and the reason should be visible
in `/mcp` rather than buried in a log.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from .protocol import MCPError, StdioConnection, ToolDescription

#: Tools arrive namespaced, because two servers can both offer `search` and the
#: model needs to be able to say which. The separator has to survive whatever
#: the provider allows in a function name, so it is not a dot or a slash.
SEPARATOR = "__"
#: A tool result can be enormous — a whole web page, a whole table. Truncated
#: with a note, because silently dropping the tail teaches the model wrong.
MAX_RESULT = 40_000


@dataclass
class ServerState:
    """One configured server, and how it is getting on."""

    name: str
    connection: StdioConnection | None = None
    tools: list[ToolDescription] = field(default_factory=list)
    error: str = ""
    started: bool = False

    @property
    def ok(self) -> bool:
        return self.started and not self.error


class MCPManager:
    """Every MCP server this session may use."""

    def __init__(self, servers: dict[str, Any] | None = None) -> None:
        #: name -> the config entry describing how to start it
        self.configured = dict(servers or {})
        self.states: dict[str, ServerState] = {}
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------- #

    def enabled_names(self) -> list[str]:
        return sorted(name for name, server in self.configured.items()
                      if getattr(server, "enabled", False))

    def start(self, name: str) -> ServerState:
        """Connect to one server, or return why it will not connect."""
        with self._lock:
            state = self.states.get(name)
            if state is not None and (state.ok or state.error):
                return state

            server = self.configured.get(name)
            state = ServerState(name=name)
            self.states[name] = state

            if server is None:
                state.error = "not configured"
                return state

            connection = StdioConnection(
                command=server.command, args=list(server.args),
                env=dict(server.env), cwd=server.cwd or None)
            try:
                connection.start()
                state.connection = connection
                state.tools = _list_tools(connection)
                state.started = True
            except MCPError as error:
                connection.close()
                state.error = str(error)
            except Exception as error:            # never take the session down
                connection.close()
                state.error = f"{type(error).__name__}: {error}"
            return state

    def start_all(self) -> dict[str, ServerState]:
        for name in self.enabled_names():
            self.start(name)
        return self.states

    def close(self) -> None:
        with self._lock:
            for state in self.states.values():
                if state.connection is not None:
                    state.connection.close()
            self.states.clear()

    # -- what the agent sees ----------------------------------------------- #

    def tools(self) -> list[Any]:
        """Every reachable MCP tool, wrapped so the agent can call it."""
        from ..tools.mcp import MCPTool

        wrapped: list[Any] = []
        for name in self.enabled_names():
            state = self.start(name)
            if not state.ok:
                continue
            for description in state.tools:
                wrapped.append(MCPTool(self, name, description))
        return wrapped

    def call(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        """Call one tool and return its output as text."""
        state = self.start(server)
        if not state.ok or state.connection is None:
            raise MCPError(state.error or f"{server} is not running")

        result = state.connection.request(
            "tools/call", {"name": tool, "arguments": arguments or {}})

        text = _flatten(result.get("content"))
        if result.get("isError"):
            raise MCPError(text or "the tool reported an error")
        if len(text) > MAX_RESULT:
            text = (text[:MAX_RESULT]
                    + f"\n\n[truncated: {len(text) - MAX_RESULT} more characters]")
        return text

    def report(self) -> list[tuple[str, str, str]]:
        """(name, status, detail) for `/mcp` and for doctor."""
        rows: list[tuple[str, str, str]] = []
        for name, server in sorted(self.configured.items()):
            if not getattr(server, "enabled", False):
                rows.append((name, "off", "not enabled"))
                continue
            state = self.states.get(name)
            if state is None:
                rows.append((name, "idle", "starts when first used"))
            elif state.ok:
                rows.append((name, "ready", f"{len(state.tools)} tool(s)"))
            else:
                rows.append((name, "failed", state.error))
        return rows


def _list_tools(connection: StdioConnection) -> list[ToolDescription]:
    """Ask a server what it offers, following pagination if it uses it."""
    found: list[ToolDescription] = []
    cursor: str | None = None

    for _ in range(20):                   # a bound, in case a server loops
        params = {"cursor": cursor} if cursor else {}
        result = connection.request("tools/list", params)
        for entry in result.get("tools") or []:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            found.append(ToolDescription(
                name=str(entry["name"]),
                description=str(entry.get("description") or ""),
                schema=entry.get("inputSchema") or {"type": "object", "properties": {}},
            ))
        cursor = result.get("nextCursor")
        if not cursor:
            break

    return found


def _flatten(content: Any) -> str:
    """MCP returns a list of typed blocks; the agent wants text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content

    parts: list[str] = []
    for block in content if isinstance(content, list) else [content]:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(str(block.get("text") or ""))
        elif kind == "resource":
            resource = block.get("resource") or {}
            parts.append(str(resource.get("text")
                             or resource.get("uri") or ""))
        elif kind == "image":
            # Named rather than inlined: base64 image data would flood the
            # context and the model cannot see it through this path anyway.
            parts.append(f"[image: {block.get('mimeType', 'unknown type')}]")
        else:
            parts.append(str(block.get("text") or ""))

    return "\n".join(part for part in parts if part).strip()
