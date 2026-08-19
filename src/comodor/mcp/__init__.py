"""Model Context Protocol: using tools that live in somebody else's program.

Comodor's own tools are built in and audited. MCP is the opposite arrangement —
a separate process, written by someone else, offering capabilities Comodor
never has to implement: a browser, a database, an issue tracker. The protocol
is small enough to speak directly, which is why there is no SDK dependency
here.

Everything is off until the user turns it on, and what each server can reach is
stated before they do.
"""

from .catalogue import CATALOGUE, ServerSpec, get, needing_setup, offered
from .manager import MCPManager, ServerState
from .protocol import MCPError, StdioConnection, ToolDescription

__all__ = ["CATALOGUE", "ServerSpec", "MCPManager", "ServerState", "MCPError",
           "StdioConnection", "ToolDescription", "get", "offered",
           "needing_setup", "probe_server"]


def probe_server(server) -> tuple[bool, str]:
    """Can this server start and answer? Used by `comodor doctor`.

    Starts it, asks for its tool list, and shuts it down again. That is slower
    than checking whether the command exists, and it is the only check worth
    making: `npx` existing says nothing about whether the package behind it
    resolves.
    """
    connection = StdioConnection(
        command=server.command, args=list(server.args),
        env=dict(server.env), cwd=server.cwd or None)
    try:
        connection.start(timeout=30.0)
        result = connection.request("tools/list", {}, timeout=20.0)
        count = len(result.get("tools") or [])
        return True, f"{count} tool(s)"
    except MCPError as error:
        return False, str(error).splitlines()[0]
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"
    finally:
        connection.close()
