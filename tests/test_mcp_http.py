"""An MCP server that is a URL rather than a process.

The original transport assumed the server was something you launch. The
interesting ones increasingly are not: they are hosted, shared by a team, and
hold credentials nobody wants on a laptop.

Everything here runs against a real HTTP server on a real socket, because the
two things that break this transport are both things a mock would have been
written to do correctly: the session header the server issues and every later
request must carry, and the fact that a reply arrives as JSON from one server
and as an event stream from the next.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from comodor.mcp.http import HTTPConnection
from comodor.mcp.protocol import MCPError

SESSION = "session-abc-123"


class Handler(BaseHTTPRequestHandler):
    """A small MCP server. Its behaviour is set per test on the class."""

    stream = False                  # answer with an event stream, not JSON
    require_session = True
    status = 200
    seen: list = []
    headers_seen: list = []

    def log_message(self, *args):
        pass

    def do_DELETE(self):
        self.send_response(200)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"] or 0)))
        Handler.seen.append(body)
        Handler.headers_seen.append(dict(self.headers))

        if self.__class__.status != 200:
            self.send_response(self.__class__.status)
            self.end_headers()
            self.wfile.write(b"refused")
            return

        if body.get("id") is None:                 # a notification
            self.send_response(202)
            self.end_headers()
            return

        method = body.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {}}
        elif method == "tools/list":
            result = {"tools": [{"name": "ping", "description": "p",
                                 "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": "pong"}]}

        reply = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        payload = json.dumps(reply).encode()

        self.send_response(200)
        if method == "initialize":
            self.send_header("Mcp-Session-Id", SESSION)
        if self.__class__.stream:
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            # Noise first: progress, a log line, and a request of the server's
            # own. A client taking the first event as the answer misreads all.
            for noise in ({"jsonrpc": "2.0", "method": "notifications/progress"},
                          {"jsonrpc": "2.0", "id": 9999, "method": "ping"}):
                self.wfile.write(f"data: {json.dumps(noise)}\n\n".encode())
            self.wfile.write(b"data: " + payload + b"\n\n")
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)


@pytest.fixture
def server():
    Handler.seen = []
    Handler.headers_seen = []
    Handler.stream = False
    Handler.status = 200
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/mcp"
    httpd.shutdown()
    httpd.server_close()


# --------------------------------------------------------------------------- #
# the handshake
# --------------------------------------------------------------------------- #


def test_it_connects_and_lists_tools(server):
    connection = HTTPConnection(server)
    try:
        connection.start()
        tools = connection.request("tools/list")

        assert connection.alive
        assert tools["tools"][0]["name"] == "ping"
    finally:
        connection.close()


def test_the_session_the_server_issues_is_carried_on_every_later_request(server):
    """Omit it and a stateful server treats each call as a stranger's first —
    tools listed, then unavailable a second later."""
    connection = HTTPConnection(server)
    try:
        connection.start()
        assert connection.session_id == SESSION

        connection.request("tools/list")
        later = Handler.headers_seen[-1]

        assert later.get("Mcp-Session-Id") == SESSION
    finally:
        connection.close()


def test_both_content_types_are_offered(server):
    """A server that cannot find its preferred type refuses rather than
    downgrading, so the Accept header has to name both, every time."""
    connection = HTTPConnection(server)
    try:
        connection.start()
        accept = Handler.headers_seen[0].get("Accept", "")

        assert "application/json" in accept
        assert "text/event-stream" in accept
    finally:
        connection.close()


def test_the_initialized_notification_is_sent(server):
    connection = HTTPConnection(server)
    try:
        connection.start()
        methods = [message.get("method") for message in Handler.seen]

        assert "notifications/initialized" in methods
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# a reply arrives in one of two shapes
# --------------------------------------------------------------------------- #


def test_a_reply_sent_as_an_event_stream_is_read_too(server):
    Handler.stream = True
    connection = HTTPConnection(server)
    try:
        connection.start()
        result = connection.request("tools/call", {"name": "ping"})

        assert result["content"][0]["text"] == "pong"
    finally:
        connection.close()


def test_the_streams_other_traffic_is_not_mistaken_for_the_answer(server):
    """Progress notifications and the server's own requests share the stream."""
    Handler.stream = True
    connection = HTTPConnection(server)
    try:
        connection.start()
        result = connection.request("tools/list")

        assert "tools" in result           # not the progress event, not the ping
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# when it goes wrong
# --------------------------------------------------------------------------- #


def test_credentials_are_sent_when_there_are_any(server):
    connection = HTTPConnection(server, token="secret-token")
    try:
        connection.start()
        assert Handler.headers_seen[0].get("Authorization") == "Bearer secret-token"
    finally:
        connection.close()


def test_extra_headers_are_sent(server):
    connection = HTTPConnection(server, headers={"X-Team": "platform"})
    try:
        connection.start()
        assert Handler.headers_seen[0].get("X-Team") == "platform"
    finally:
        connection.close()


def test_a_refusal_says_it_is_about_credentials(server):
    Handler.status = 401
    connection = HTTPConnection(server)
    try:
        with pytest.raises(MCPError) as raised:
            connection.start()
        assert "credentials" in str(raised.value)
    finally:
        connection.close()


def test_a_server_that_is_not_there_fails_rather_than_hangs():
    connection = HTTPConnection("http://127.0.0.1:1/mcp")
    try:
        with pytest.raises(MCPError):
            connection.start()
        assert not connection.alive
    finally:
        connection.close()


def test_a_notification_never_raises(server):
    Handler.status = 500
    connection = HTTPConnection(server)
    try:
        connection.notify("notifications/cancelled")     # must not raise
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# it reaches the rest of the program unchanged
# --------------------------------------------------------------------------- #


def test_the_manager_picks_the_transport_from_the_entry(server):
    from comodor.config import MCPServerConfig
    from comodor.mcp.manager import _connection_for
    from comodor.mcp.protocol import StdioConnection

    remote = _connection_for(MCPServerConfig(name="r", url=server))
    local = _connection_for(MCPServerConfig(name="l", command="echo"))

    assert isinstance(remote, HTTPConnection)
    assert isinstance(local, StdioConnection)


def test_a_url_server_survives_being_written_and_read(tmp_path):
    """A config that loses the URL leaves a server entry that cannot connect."""
    import json as json_module

    from comodor import config as config_module

    document = {"mcp": {"enabled": True, "servers": {
        "hosted": {"url": "https://example.invalid/mcp", "enabled": True,
                   "headers": {"X-Team": "platform"}}}}}
    (tmp_path / ".comodor").mkdir(parents=True)
    (tmp_path / ".comodor" / "config.json").write_text(
        json_module.dumps(document), encoding="utf-8")

    loaded = config_module.load(cwd=tmp_path, use_environment=False)
    entry = loaded.mcp.servers["hosted"]

    assert entry.url == "https://example.invalid/mcp"
    assert entry.headers == {"X-Team": "platform"}
    assert entry.to_json()["url"] == "https://example.invalid/mcp"


# --------------------------------------------------------------------------- #
# adding one from the command line
# --------------------------------------------------------------------------- #


def test_a_remote_server_is_probed_before_it_is_enabled(server, tmp_path,
                                                        monkeypatch, capsys):
    """An entry that cannot connect is worse than no entry: it fails once per
    session, in a place nobody is looking."""
    import argparse

    from comodor.config import Config
    from comodor.mcp import commands
    from comodor.paths import Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    (tmp_path / "home").mkdir(parents=True)
    args = argparse.Namespace(name="hosted", url=server, token="", header=[])

    assert commands._remote(config, args) == 0

    entry = config.mcp.servers["hosted"]
    assert entry.url == server
    assert entry.enabled is True
    assert "ping" in capsys.readouterr().out


def test_a_remote_server_that_does_not_answer_is_left_off(tmp_path, capsys):
    import argparse

    from comodor.config import Config
    from comodor.mcp import commands
    from comodor.paths import Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    (tmp_path / "home").mkdir(parents=True)
    args = argparse.Namespace(name="dead", url="http://127.0.0.1:1/mcp",
                              token="", header=[])

    assert commands._remote(config, args) == 1
    assert config.mcp.servers["dead"].enabled is False


def test_a_plain_http_endpoint_off_the_machine_is_refused(tmp_path, capsys):
    """The token and everything the tools return would cross in the clear."""
    import argparse

    from comodor.config import Config
    from comodor.mcp import commands
    from comodor.paths import Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    args = argparse.Namespace(name="risky", url="http://example.com/mcp",
                              token="secret", header=[])

    assert commands._remote(config, args) == 1
    assert "clear" in capsys.readouterr().err
    assert "risky" not in config.mcp.servers


def test_a_local_plain_http_endpoint_is_fine(server, tmp_path):
    import argparse

    from comodor.config import Config
    from comodor.mcp import commands
    from comodor.paths import Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    (tmp_path / "home").mkdir(parents=True)
    args = argparse.Namespace(name="local", url=server, token="", header=[])

    assert commands._remote(config, args) == 0
