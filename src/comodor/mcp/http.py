"""Talking to an MCP server that is a URL rather than a process.

The original transport assumed the server was something you launch: a command,
a pipe, a process you own. Most of the interesting ones are no longer that.
They are hosted, they are shared by a team, they hold credentials nobody wants
on a laptop, and reaching them means an HTTP request rather than a `Popen`.

This is the Streamable HTTP transport, and it is the same JSON-RPC in a
different envelope. Everything is a POST to one endpoint. What comes back is
either a JSON object — the reply, and that is the end of it — or an event
stream, because the server wants to send progress before the answer. A client
that assumed one shape would work against half the servers in existence, so
this reads both and takes the reply out of whichever arrived.

Two details are not obvious and both cause silent failure:

* **The session is a header.** The server issues `Mcp-Session-Id` when it
  answers `initialize`, and every later request has to carry it. Omit it and a
  stateful server treats each call as a stranger's first — tools listed, then
  unavailable a second later.
* **Both content types must be offered.** The `Accept` header has to name JSON
  *and* the event stream, on every request. Servers pick, and one that cannot
  find its preferred type refuses rather than downgrading.

Same interface as the stdio connection — ``start``, ``request``, ``notify``,
``close``, ``alive`` — so the manager, the tool wrapper and the permission gate
below it never learn that a server is remote.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from ..net import http
from ..net.sse import iter_sse
from .protocol import MCPError, PROTOCOL_VERSION

#: Long enough for a cold serverless server to wake up.
STARTUP_TIMEOUT = 60.0
REQUEST_TIMEOUT = 120.0
#: Both, always. A server that cannot find its preferred content type refuses
#: the request rather than falling back to the other one.
ACCEPT = "application/json, text/event-stream"


class HTTPConnection:
    """An MCP server reached over Streamable HTTP."""

    def __init__(self, url: str, headers: dict[str, str] | None = None,
                 token: str = "", timeout: float = REQUEST_TIMEOUT) -> None:
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session_id = ""
        self.started = False
        #: What the server said it was, from the handshake. The same field the
        #: stdio connection exposes, because everything above reads one shape.
        self.server_info: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._next_id = 1
        self._failure = ""

        sending = {"Content-Type": "application/json", "Accept": ACCEPT}
        if token:
            sending["Authorization"] = f"Bearer {token}"
        sending.update(headers or {})
        self._session = http.Session(
            headers=sending,
            timeout=http.Timeout(connect=15.0, read=timeout),
            # A POST carries a JSON-RPC id; replaying one would run a tool twice.
            retry=http.Retry(total=2, allowed_methods=frozenset({"GET"})),
        )

    # -- lifecycle --------------------------------------------------------- #

    def start(self, timeout: float = STARTUP_TIMEOUT) -> None:
        """Handshake, and keep whatever session the server hands back."""
        reply = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "comodor", "version": "1"},
        }, timeout=timeout)
        if not isinstance(reply, dict):
            raise MCPError("the server did not answer initialize")
        info = reply.get("serverInfo")
        self.server_info = info if isinstance(info, dict) else {}
        self.notify("notifications/initialized")
        self.started = True

    def close(self) -> None:
        """Tell the server the session is over, then stop caring."""
        if self.session_id:
            try:
                self._session.request(
                    "DELETE", self.url,
                    headers={"Mcp-Session-Id": self.session_id}, timeout=(5.0, 10.0))
            except Exception:
                pass                       # ending a session is best-effort
        self.started = False
        try:
            self._session.close()
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return self.started and not self._failure

    # -- the wire ---------------------------------------------------------- #

    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float = REQUEST_TIMEOUT) -> dict[str, Any]:
        with self._lock:
            identifier = self._next_id
            self._next_id += 1
        body = {"jsonrpc": "2.0", "id": identifier, "method": method,
                "params": params or {}}
        payload = self._post(body, timeout, method)
        return _result_of(payload, method)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """No id, so no reply. A server may answer 202 and nothing else."""
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params or {}},
                       self.timeout, method, expect_reply=False)
        except MCPError:
            pass                           # a notification is not worth failing on

    # -- one exchange ------------------------------------------------------ #

    def _post(self, body: dict[str, Any], timeout: float, method: str,
              expect_reply: bool = True) -> Any:
        headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
        try:
            response = self._session.post(
                self.url, json=body, headers=headers, stream=True,
                timeout=(15.0, timeout))
        except http.RequestError as error:
            self._failure = str(error)
            raise MCPError(f"{method}: {error}") from error

        with response:
            issued = response.headers.get("Mcp-Session-Id") or \
                response.headers.get("mcp-session-id")
            if issued:
                self.session_id = str(issued)

            if not response.ok:
                self._failure = f"HTTP {response.status_code}"
                raise MCPError(_why(response, method))

            if not expect_reply:
                return None
            kind = (response.headers.get("Content-Type") or "").lower()
            if "text/event-stream" in kind:
                return self._from_stream(response, body["id"], method, timeout)
            try:
                return response.json()
            except Exception as error:
                raise MCPError(f"{method}: the reply was not JSON") from error

    def _from_stream(self, response: Any, identifier: int, method: str,
                     timeout: float) -> Any:
        """Take our reply out of the stream and ignore everything else.

        A server sends progress notifications, log lines and requests of its
        own down the same stream; a client treating the first event as the
        answer would misread every one of them.
        """
        for event in iter_sse(response):
            payload = event.json()
            if not isinstance(payload, dict):
                continue
            if payload.get("id") == identifier:
                return payload
        raise MCPError(f"{method}: the stream ended without a reply")


def _result_of(payload: Any, method: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MCPError(f"{method}: the reply was not an object")
    error = payload.get("error")
    if isinstance(error, dict):
        raise MCPError(f"{method}: {error.get('message') or error}")
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _why(response: Any, method: str) -> str:
    status = response.status_code
    if status in (401, 403):
        return (f"{method}: the server refused the request ({status}) — it "
                f"wants credentials this server entry does not carry")
    if status == 404:
        return f"{method}: nothing at that URL ({status})"
    detail = ""
    try:
        body = response.text[:200]
        detail = f" — {body}" if body else ""
    except Exception:
        pass
    return f"{method}: HTTP {status}{detail}"
