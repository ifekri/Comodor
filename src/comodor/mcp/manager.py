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

from .http import HTTPConnection
from .protocol import (
    MCPError,
    PromptDescription,
    ResourceDescription,
    StdioConnection,
    ToolDescription,
)


def _connection_for(server: Any) -> Any:
    """A process to launch, or a URL to reach. Nothing below here can tell."""
    url = getattr(server, "url", "")
    if url:
        return HTTPConnection(url=url, headers=dict(getattr(server, "headers", {})),
                              token=getattr(server, "token", ""))
    return StdioConnection(
        command=server.command, args=list(server.args),
        env=dict(server.env), cwd=server.cwd or None)

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
    connection: Any = None      # stdio or http; same interface
    tools: list[ToolDescription] = field(default_factory=list)
    resources: list[ResourceDescription] = field(default_factory=list)
    prompts: list[PromptDescription] = field(default_factory=list)
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

            connection = _connection_for(server)
            try:
                connection.start()
                state.connection = connection
                state.tools = _list_tools(connection)
                # Resources and prompts are asked for, not assumed: a server
                # that never declared the capability answers with a protocol
                # error, and that is not a failure of the connection.
                state.resources = _list_resources(connection)
                state.prompts = _list_prompts(connection)
                state.started = True
            except MCPError as error:
                connection.close()
                state.error = str(error)
            except Exception as error:            # never take the session down
                connection.close()
                state.error = f"{type(error).__name__}: {error}"
            return state

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

    def has_resources(self) -> bool:
        """Whether any started server has declared resources.

        Deliberately does not start servers to find out: the tool wrapped
        around this only becomes useful once a server is up, and probing
        every one on construction would put half a minute back into a
        first turn. A server started later is picked up on reload.
        """
        for name in self.enabled_names():
            state = self.states.get(name)
            if state is not None and state.ok and state.resources:
                return True
        return False

    def read_resource(self, server: str, uri: str) -> str:
        """Read one resource. Text comes back as text; anything else is named."""
        state = self.start(server)
        if not state.ok or state.connection is None:
            raise MCPError(state.error or f"{server} is not running")

        result = state.connection.request(
            "resources/read", {"uri": uri})
        parts: list[str] = []
        for block in result.get("contents") or []:
            if not isinstance(block, dict):
                continue
            if "text" in block:
                parts.append(str(block["text"]))
            elif "blob" in block:
                parts.append(f"[binary resource: {block.get('mimeType', 'unknown type')}"
                             f" — {len(str(block['blob']))} base64 characters]")
        text = "\n".join(part for part in parts if part).strip()
        if len(text) > MAX_RESULT:
            text = (text[:MAX_RESULT]
                    + f"\n\n[truncated: {len(text) - MAX_RESULT} more characters]")
        return text

    def get_prompt(self, server: str, name: str,
                   arguments: dict[str, str] | None = None) -> str:
        """Fetch one prompt template, filled, as a plain user message."""
        state = self.start(server)
        if not state.ok or state.connection is None:
            raise MCPError(state.error or f"{server} is not running")

        result = state.connection.request(
            "prompts/get", {"name": name, "arguments": arguments or {}})
        lines: list[str] = []
        for message in result.get("messages") or []:
            if not isinstance(message, dict):
                continue
            content = message.get("content") or {}
            text = content.get("text") if isinstance(content, dict) else ""
            if text:
                lines.append(str(text))
        if not lines:
            raise MCPError(f"the prompt {name!r} came back empty")
        return "\n\n".join(lines)

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
                detail = f"{len(state.tools)} tool(s)"
                if state.resources:
                    detail += f", {len(state.resources)} resource(s)"
                if state.prompts:
                    detail += f", {len(state.prompts)} prompt(s)"
                rows.append((name, "ready", detail))
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


def _list_resources(connection: StdioConnection) -> list[ResourceDescription]:
    """Ask a server what it lets you read. Servers without resources stay quiet.

    A server that never declared the capability is expected to refuse these
    with a method-not-found error; that is "none", not a failure, so it is
    swallowed here rather than landing on the state as a broken connection.
    """
    try:
        result = connection.request("resources/list", {})
    except MCPError as error:
        if _method_not_supported(error):
            return []
        raise
    found: list[ResourceDescription] = []
    for entry in result.get("resources") or []:
        if not isinstance(entry, dict) or not entry.get("uri"):
            continue
        found.append(ResourceDescription(
            uri=str(entry["uri"]),
            name=str(entry.get("name") or ""),
            description=str(entry.get("description") or ""),
            mime_type=str(entry.get("mimeType") or ""),
        ))
    return found


def _list_prompts(connection: StdioConnection) -> list[PromptDescription]:
    """Same question for prompts. Absent capability means none, as above."""
    try:
        result = connection.request("prompts/list", {})
    except MCPError as error:
        if _method_not_supported(error):
            return []
        raise
    found: list[PromptDescription] = []
    for entry in result.get("prompts") or []:
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        arguments = entry.get("arguments")
        found.append(PromptDescription(
            name=str(entry["name"]),
            description=str(entry.get("description") or ""),
            arguments=arguments if isinstance(arguments, list) else [],
        ))
    return found


def _method_not_supported(error: MCPError) -> bool:
    """Whether a refusal means "I do not do that", rather than "I broke".

    The codes differ across servers in the wild; the words are the part that
    is reliable, so they are what is matched.
    """
    text = str(error).lower()
    return "-32601" in text or "method not found" in text


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
