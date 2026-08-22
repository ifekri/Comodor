"""The agent, served to a browser.

Be clear about what this is before reading the code. Comodor edits files and
runs shell commands. A web interface to it is, in the most literal sense, a
remote code execution endpoint — the feature *is* running arbitrary commands on
this machine — and the difference between that being useful and being a
catastrophe is entirely in who can reach it.

So the defaults are the strict ones and they are not negotiable by accident:

* **It listens on the loopback address.** Nothing outside this machine can
  reach it unless the user says a different address on the command line, and
  saying so prints what they have just done.
* **Every request carries a token**, generated per run and never written to
  disk. It arrives once in the URL and is then held in a cookie marked
  `HttpOnly` and `SameSite=Strict`, so no other site can cause the browser to
  send it. Comparison is constant-time.
* **Writing requests need a header no cross-origin form can set.** `SameSite`
  should be enough on its own; this is the second lock, because the cost of
  the first one failing is somebody else's shell running as you.
* **There is no TLS.** Over a network the token and everything the agent reads
  travel in the clear, so binding to a public address says so in as many words
  and tells the user to put it behind a tunnel.

Everything else is deliberately plain: the standard library's HTTP server, one
page with no external anything, and long-polling rather than websockets —
because the event bus already gives us a stream and a websocket would be a
protocol implementation to maintain for no gain the user can see.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ..config import Config
from .session import Session

#: Loopback names, for deciding whether a warning is owed.
LOCAL = ("127.0.0.1", "::1", "localhost")
COOKIE = "comodor_token"
#: A header no cross-origin form or image can set, so its presence proves the
#: request came from our own page rather than from somebody else's.
GUARD = "X-Comodor"
MAX_BODY = 1_000_000


def in_a_container() -> bool:
    """Docker, Podman or a Kubernetes pod, as best as can be told from inside.

    Docker leaves a marker file; Podman sets an environment variable; both, and
    Kubernetes, show it in the process control groups. Any one of them is
    enough, and being wrong in either direction only changes the wording of a
    warning, never what is bound or who can reach it.
    """
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    if os.environ.get("container"):
        return True
    try:
        groups = Path("/proc/self/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(marker in groups for marker in ("docker", "kubepods", "containerd"))


def page() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


class Server:
    """One session, one port, one token."""

    def __init__(self, config: Config, host: str = "127.0.0.1", port: int = 8765,
                 token: str = "") -> None:
        self.config = config
        self.host = host
        self.port = port
        self.token = token or secrets.token_urlsafe(24)
        self.session = Session(config)
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def local(self) -> bool:
        return self.host in LOCAL

    @property
    def contained(self) -> bool:
        """Whether this is running inside a container.

        It changes what a wide bind means. A container has its own network
        namespace, so binding 127.0.0.1 inside one hides the port from the
        machine that started it — the interface becomes unreachable by the
        person who asked for it. Binding everything is therefore the correct
        thing to do, and who may reach it is decided one layer out, by how the
        port was published.
        """
        return in_a_container()

    @property
    def url(self) -> str:
        shown = "127.0.0.1" if self.host in ("", "0.0.0.0", "::") else self.host
        return f"http://{shown}:{self.port}/?token={self.token}"

    def bind(self) -> int:
        """Take the port. Separate from serving so a busy one is an error
        before a URL nobody can open has been printed."""
        self._httpd = ThreadingHTTPServer((self.host, self.port), _handler_for(self))
        self.port = self._httpd.server_address[1]      # when 0 was asked for
        return self.port

    def serve(self) -> None:
        if self._httpd is None:
            self.bind()
        try:
            self._httpd.serve_forever(poll_interval=0.3)
        finally:
            self.session.close()

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is not None:
            threading.Thread(target=httpd.shutdown, daemon=True).start()

    def authorised(self, presented: str) -> bool:
        return bool(presented) and hmac.compare_digest(presented, self.token)


def _handler_for(server: Server) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        server_version = "comodor"
        protocol_version = "HTTP/1.1"

        # -- plumbing ------------------------------------------------------ #

        def log_message(self, *args: Any) -> None:
            pass                       # the agent's own output is the log

        def _send(self, status: int, body: bytes = b"",
                  content_type: str = "application/json",
                  extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # Nothing here should ever be embedded, framed, or sniffed.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _token(self) -> str:
            cookies = self.headers.get("Cookie") or ""
            for part in cookies.split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
            return ""

        def _body(self) -> dict[str, Any]:
            """Read the body, whatever is going to be done with it.

            Always read, and read all of it. Bytes left in the socket are read
            by the *next* request on the connection as its request line, and a
            socket closed with unread data sends a reset instead of a close —
            which the client sees as a connection aborted rather than as the
            401 that was actually sent.
            """
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                return {}

            raw = b""
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
                # Past the cap it is drained and dropped, not left unread.
                if len(raw) < MAX_BODY:
                    raw += chunk
            if length > MAX_BODY:
                return {}
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}

        # -- reading ------------------------------------------------------- #

        def do_GET(self) -> None:
            if self.headers.get("Content-Length"):
                self._body()               # rare, but the same rule applies
            parts = urlparse(self.path)
            query = parse_qs(parts.query)
            route = parts.path

            if route == "/":
                # The token arrives once, in the URL, and is moved into a
                # cookie so it stops appearing in the address bar, in history,
                # and in the referrer of anything the page ever links to.
                supplied = (query.get("token") or [""])[0]
                if server.authorised(supplied):
                    self._send(303, b"", "text/plain", {
                        "Location": "/",
                        "Set-Cookie": (f"{COOKIE}={server.token}; Path=/; "
                                       f"HttpOnly; SameSite=Strict"),
                    })
                    return
                if not server.authorised(self._token()):
                    self._send(401, b"This needs the token Comodor printed when "
                                    b"it started.", "text/plain")
                    return
                body = page().encode("utf-8")
                self._send(200, body, "text/html; charset=utf-8")
                return

            if not server.authorised(self._token()):
                self._json(401, {"error": "unauthorised"})
                return

            if route == "/api/state":
                self._json(200, server.session.state())
                return

            if route == "/api/events":
                try:
                    cursor = int((query.get("cursor") or ["0"])[0])
                except ValueError:
                    cursor = 0
                events = server.session.wait_for(cursor)
                self._json(200, {"events": events,
                                 "cursor": events[-1]["seq"] if events else cursor,
                                 "busy": server.session.busy})
                return

            self._json(404, {"error": "no such thing"})

        # -- doing --------------------------------------------------------- #

        def do_POST(self) -> None:
            # Before any verdict: an unread body breaks the connection it
            # arrived on, and the caller sees a reset instead of the refusal.
            body = self._body()

            if not server.authorised(self._token()):
                self._json(401, {"error": "unauthorised"})
                return
            # Belt and braces over SameSite: a cross-origin form can post, but
            # it cannot set a header, and a fetch that tries triggers a
            # preflight this server answers for nobody.
            if self.headers.get(GUARD) != "1":
                self._json(403, {"error": "this request did not come from the page"})
                return

            route = urlparse(self.path).path

            if route == "/api/send":
                started = server.session.send(str(body.get("text") or ""))
                self._json(200 if started else 409,
                           {"started": started,
                            "error": "" if started else "a turn is already running"})
                return

            if route == "/api/answer":
                done, why = server.session.answer(str(body.get("id") or ""),
                                                  str(body.get("choice") or ""))
                self._json(200 if done else 409,
                           {"answered": done, "error": why})
                return

            if route == "/api/interrupt":
                server.session.interrupt()
                self._json(200, {"interrupted": True})
                return

            if route == "/api/mode":
                changed = server.session.set_mode(str(body.get("mode") or ""))
                self._json(200 if changed else 400, {"mode": config_mode(server)})
                return

            self._json(404, {"error": "no such thing"})

        def do_OPTIONS(self) -> None:
            # No CORS for anyone. A preflight that gets no permissions means a
            # cross-origin fetch cannot send the header the POST routes want.
            if self.headers.get("Content-Length"):
                self._body()
            self._send(405)

    return Handler


def config_mode(server: Server) -> str:
    return server.config.agent.mode
