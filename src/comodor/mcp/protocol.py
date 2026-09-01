"""JSON-RPC 2.0 over a pipe, which is all the Model Context Protocol needs.

MCP is a small protocol wearing a large ecosystem. The wire format is
newline-delimited JSON-RPC over a subprocess's stdin and stdout: a handshake,
a request for the list of tools, and a call. That is the whole surface Comodor
uses, and it is about two hundred lines — considerably less than the official
SDK would add to a package whose only dependency is `rich`.

The care here is not in the protocol but in the failure modes. An MCP server is
somebody else's program, started by us, and it can hang, die on startup, write
rubbish to stdout, or answer a question we never asked. Every one of those has
to end in a readable message rather than a wedged agent, because the user did
not write that server and cannot debug it.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: The protocol version this client implements.
PROTOCOL_VERSION = "2024-11-05"
#: How long to wait for the handshake. A server that fetches its own
#: dependencies on first run (npx, uvx) is genuinely slow the first time.
STARTUP_TIMEOUT = 60.0
#: How long any later request may take before it is abandoned.
REQUEST_TIMEOUT = 120.0
#: Stderr is kept for the error message and then discarded, because some
#: servers log a line per call and it would otherwise grow without bound.
MAX_STDERR = 8_000


class MCPError(RuntimeError):
    """Anything that went wrong talking to a server."""


@dataclass
class ToolDescription:
    """One tool a server offers."""

    name: str
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceDescription:
    """One resource a server offers: a thing that can be read by URI."""

    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""


@dataclass
class PromptDescription:
    """One prompt template a server offers."""

    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)


class StdioConnection:
    """A running MCP server, spoken to over its stdin and stdout."""

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, cwd: str | None = None) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.cwd = cwd
        self.process: subprocess.Popen[str] | None = None
        self.server_info: dict[str, Any] = {}

        self._next_id = 1
        self._lock = threading.Lock()
        self._stderr: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        # Lines are read by a thread rather than inline. `readline()` blocks
        # with no deadline, so a timeout checked around it is not a timeout at
        # all: a server that never answers would hold the agent forever. A
        # queue makes the wait interruptible on every platform, which `select`
        # would not — Windows cannot select on a pipe.
        self._inbox: queue.Queue[str | None] = queue.Queue()
        self._reader_thread: threading.Thread | None = None

    # -- lifecycle --------------------------------------------------------- #

    def start(self, timeout: float = STARTUP_TIMEOUT) -> None:
        """Spawn the server and complete the handshake."""
        environment = os.environ.copy()
        environment.update(self.env)
        # Some servers buffer their output when stdout is a pipe, which would
        # deadlock the handshake: we wait for a line that is sitting in their
        # buffer. Python-based ones honour this; others set it themselves.
        environment.setdefault("PYTHONUNBUFFERED", "1")

        try:
            self.process = subprocess.Popen(
                _spawn_argv(self.command, self.args),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=environment, cwd=self.cwd,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                # Without this a Ctrl+C in the terminal reaches every server we
                # started, and they die before the agent can shut them down.
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError:
            raise MCPError(
                f"{self.command!r} is not installed or not on PATH") from None
        except OSError as error:
            raise MCPError(f"could not start {self.command!r}: {error}") from None

        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._reader_thread = threading.Thread(target=self._read_lines, daemon=True)
        self._reader_thread.start()

        try:
            result = self.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "comodor", "version": _version()},
            }, timeout=timeout)
        except MCPError:
            self.close()
            raise

        self.server_info = result.get("serverInfo") or {}
        # A notification, so there is no reply to wait for. Servers that follow
        # the spec will not answer questions until they have had it.
        self.notify("notifications/initialized")

    def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                pass

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    # -- the wire ---------------------------------------------------------- #

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
        """Send a request and wait for its reply."""
        with self._lock:
            identifier = self._next_id
            self._next_id += 1
            self._send({"jsonrpc": "2.0", "id": identifier, "method": method,
                        "params": params or {}})
            return self._await_reply(identifier, method, timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a notification. There is no reply, so nothing is waited for."""
        with self._lock:
            try:
                self._send({"jsonrpc": "2.0", "method": method,
                            "params": params or {}})
            except MCPError:
                pass                      # a notification is not worth failing on

    def _send(self, message: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.poll() is not None:
            raise MCPError(f"the server stopped{self._why()}")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError):
            raise MCPError(f"the server stopped{self._why()}") from None

    def _await_reply(self, identifier: int, method: str,
                     timeout: float) -> dict[str, Any]:
        """Read until the matching reply arrives, or time runs out.

        Anything that is not our reply is discarded: servers emit log lines,
        progress notifications and requests of their own, and a client that
        treated the first line it saw as the answer would misread all of them.
        """
        if self.process is None:
            raise MCPError("the server is not running")

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPError(f"{method} timed out after {timeout:.0f}s{self._why()}")

            try:
                line = self._inbox.get(timeout=remaining)
            except queue.Empty:
                raise MCPError(
                    f"{method} timed out after {timeout:.0f}s{self._why()}") from None

            if line is None:                  # the reader reached end of stream
                raise MCPError(f"the server stopped{self._why()}")

            line = line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except ValueError:
                # Not JSON: a startup banner, or a log line written to the
                # wrong stream. Common enough that it must not be fatal.
                continue

            if not isinstance(message, dict) or message.get("id") != identifier:
                continue

            if "error" in message:
                error = message["error"] or {}
                raise MCPError(
                    f"{method}: {error.get('message', 'unknown error')}"
                    f" (code {error.get('code', '?')})")

            result = message.get("result")
            return result if isinstance(result, dict) else {}

    # -- diagnostics ------------------------------------------------------- #

    def _read_lines(self) -> None:
        """Move stdout into the queue so waiting for it can have a deadline."""
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                self._inbox.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._inbox.put(None)         # unblocks anyone still waiting

    def _drain_stderr(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        try:
            for line in process.stderr:
                self._stderr.append(line.rstrip())
                # Keep the tail rather than the head: whatever killed it is at
                # the end, and the start is usually a banner.
                if len(self._stderr) > 40:
                    del self._stderr[0]
        except (OSError, ValueError):
            pass

    def _why(self) -> str:
        """The tail of stderr, which is nearly always the actual explanation."""
        text = "\n".join(self._stderr).strip()
        if not text:
            return ""
        if len(text) > MAX_STDERR:
            text = text[-MAX_STDERR:]
        return f". It said:\n{text}"


def _spawn_argv(command: str, args: list[str]) -> list[str]:
    """The argv that will actually start this command on this platform.

    Almost every MCP server is launched with `npx` or `uvx`, and on Windows
    those are `npx.cmd` and `uvx.exe` respectively. A batch file cannot be
    executed by CreateProcess at all, so `Popen(["npx", ...])` fails with
    "not installed" on a machine where npx works perfectly from a shell —
    which is every Windows machine with Node on it.

    Resolved through PATH first so the extension is known, then routed through
    cmd.exe when it turns out to be a script. Arguments stay a list, so they
    are quoted by subprocess rather than pasted into a command line.
    """
    resolved = shutil.which(command) or command

    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        return [comspec, "/c", resolved, *args]

    return [resolved, *args]


def _version() -> str:
    from .. import __version__

    return __version__
