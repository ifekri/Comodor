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
#: Addresses a request can arrive *from* and still be on this machine.
LOOPBACK = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
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


#: The page's own files, by the exact name it asks for.
#:
#: A table, not a directory listing. Deriving a path from the URL is how a
#: static handler ends up serving `../../.ssh/id_rsa`, and the whole security
#: model of this server is about what a request can reach.
ASSETS: dict[str, tuple[str, str]] = {
    "/ui.css": ("ui.css", "text/css; charset=utf-8"),
    "/ui.js": ("ui.js", "text/javascript; charset=utf-8"),
    "/vazirmatn.woff2": ("vazirmatn.woff2", "font/woff2"),
}


def page() -> str:
    return (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


def asset(name: str) -> bytes:
    return (Path(__file__).parent / name).read_bytes()


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

        def _from_this_machine(self) -> bool:
            """Whether this request never crossed a network.

            Asked of the request, not of the bind: a server listening on every
            address still answers loopback, and a rule about the bind would
            have refused that. What it decides is whether an API key may be
            typed into the page - there is no TLS here, and a key is a
            credential with a bill attached.

            A container is allowed as well. Its loopback is not the operator's
            machine, but the operator chose how to publish the port and was
            told at startup what that choice means.
            """
            try:
                where = self.client_address[0]
            except (AttributeError, IndexError):
                return False
            return where in LOOPBACK or server.contained

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

            if route in ASSETS:
                name, kind = ASSETS[route]
                try:
                    body = asset(name)
                except OSError:
                    self._json(404, {"error": "no such thing"})
                    return
                # Revalidated rather than cached: the file is on this machine,
                # the request costs nothing, and a stale stylesheet after an
                # upgrade is a broken interface nobody can explain.
                self._send(200, body, kind)
                return

            if route == "/api/state":
                self._json(200, server.session.state())
                return

            if route == "/api/chats":
                wanted = (query.get("q") or [""])[0]
                self._json(200, {"chats": server.session.chats(wanted)})
                return

            if route == "/api/admin":
                self._json(200, server.session.admin())
                return

            if route == "/api/rules":
                self._json(200, server.session.rules())
                return

            if route == "/api/facts":
                self._json(200, server.session.facts())
                return

            if route == "/api/models":
                wanted = (query.get("provider") or [""])[0]
                self._json(200, server.session.models_for(
                    wanted or server.config.provider,
                    refresh=(query.get("refresh") or [""])[0] == "1"))
                return

            if route == "/api/folder":
                self._json(200, server.session.folder())
                return

            if route == "/api/signin":
                self._json(200, server.session.sign_in_state())
                return

            if route == "/api/channels":
                self._json(200, server.session.channels())
                return

            if route == "/api/skills":
                self._json(200, server.session.skill_shelf())
                return

            if route == "/api/local":
                self._json(200, server.session.local_shelf())
                return

            if route == "/api/setup":
                offer = server.session.offer()
                offer["may_enter_a_key"] = self._from_this_machine()
                offer["port"] = server.port
                self._json(200, offer)
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

            if route == "/api/screen":
                data, number = server.session.screen()
                if not data:
                    self._json(404, {"error": "nothing has been looked at yet"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                # The number is in the URL the page asks for, so the frame can
                # be cached hard: a given number is always the same picture.
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.send_header("X-Frame-Number", str(number))
                self.end_headers()
                self.wfile.write(data)
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

            if route == "/api/delegates":
                self._json(200, {"delegates": server.session.delegates.listing()})
                return

            if route == "/api/delegates/stop":
                identifier = str(body.get("id") or "")
                stopped = (server.session.delegates.stop(identifier)
                           if identifier
                           else bool(server.session.delegates.stop_all()))
                self._json(200 if stopped else 409,
                           {"stopped": stopped,
                            "error": "" if stopped else "nothing was running"})
                return

            if route == "/api/mode":
                changed = server.session.set_mode(str(body.get("mode") or ""))
                self._json(200 if changed else 400, {"mode": config_mode(server)})
                return

            if route == "/api/quit":
                # The page offers this because a browser tab is a strange
                # place to be told to go and press Ctrl-C somewhere else.
                # `stop` already hands the shutdown to its own thread, which
                # it must: `serve_forever` cannot be stopped from inside one
                # of the requests it is serving.
                self._json(200, {"stopping": True})
                try:
                    self.wfile.flush()
                except OSError:
                    pass
                server.stop()
                return

            if route == "/api/setup":
                if not self._from_this_machine():
                    self._json(403, {
                        "ok": False,
                        "error": "There is no TLS here, so a key typed into "
                                 "this page would cross the network in the "
                                 "clear. Set it up on the machine Comodor is "
                                 "running on, or reach this page through an "
                                 "SSH tunnel."})
                    return
                done, why = server.session.set_up(
                    str(body.get("provider") or ""),
                    api_key=str(body.get("api_key") or ""),
                    model=str(body.get("model") or ""),
                    base_url=str(body.get("base_url") or ""))
                self._json(200 if done else 400,
                           {"ok": done, "error": why,
                            "state": server.session.state()})
                return

            if route == "/api/signin":
                # The key that comes back is a credential like any other, so
                # this is behind the same rule as typing one in.
                if not self._from_this_machine():
                    self._json(403, {
                        "ok": False,
                        "error": "Signing in stores a key on the machine "
                                 "Comodor is running on, and there is no TLS "
                                 "here. Do it there, or through an SSH "
                                 "tunnel."})
                    return
                step = str(body.get("step") or "start")
                if step == "start":
                    self._json(200, server.session.sign_in_start(
                        str(body.get("provider") or ""),
                        browser=bool(body.get("browser", True))))
                    return
                done, why = server.session.sign_in_finish(
                    str(body.get("code") or ""))
                self._json(200 if done else 400,
                           {"ok": done, "error": why,
                            "state": server.session.state()})
                return

            if route == "/api/folder":
                # The same rule as a key: this decides which files the agent
                # may touch, and pointing it somewhere new from across a
                # network is not a thing to allow without TLS.
                if not self._from_this_machine():
                    self._json(403, {"ok": False,
                                     "error": "The working folder can only be "
                                              "changed from the machine "
                                              "Comodor is running on."})
                    return
                done, why, where = server.session.change_folder(
                    str(body.get("path") or ""))
                self._json(200 if done else 400,
                           {"ok": done, "error": why, "folder": where,
                            "state": server.session.state()})
                return

            if route == "/api/channels":
                # The same rule as an API key and the working folder: a bot
                # token is a credential that hands remote control of this
                # machine to whoever holds it, and pairing adds somebody to
                # the list of people who may drive it. Neither is a thing a
                # page loaded from somewhere else gets to do.
                if not self._from_this_machine():
                    self._json(403, {"ok": False, "error":
                                     "Phone channels can only be set up from "
                                     "the machine Comodor is running on."})
                    return
                fields = {key: value for key, value in body.items()
                          if key not in ("action", "channel")}
                done, why = server.session.channel(
                    str(body.get("action") or ""),
                    str(body.get("channel") or ""), **fields)
                self._json(200 if done else 400,
                           {"ok": done, "error": "" if done else why,
                            "message": why if done else "",
                            "channels": server.session.channels()})
                return

            if route == "/api/skills":
                done, why = server.session.skill(str(body.get("action") or ""),
                                                 str(body.get("name") or ""))
                self._json(200 if done else 400, {"ok": done, "error": why})
                return

            if route == "/api/local":
                # Downloading a model is a several-gigabyte write to this
                # machine and switching provider changes where every prompt
                # goes. Neither is something a page loaded from somewhere else
                # gets to do, and neither is something to do over a shared
                # link without the person being at the keyboard.
                if not self._from_this_machine():
                    self._json(403, {"ok": False, "error":
                                     "models can only be managed from this machine"})
                    return
                action = str(body.get("action") or "")
                model_id = str(body.get("model") or "")
                doer = {
                    "get": server.session.local_get,
                    "cancel": server.session.local_cancel,
                    "remove": server.session.local_remove,
                    "use": server.session.local_use,
                }.get(action)
                if doer is None:
                    self._json(400, {"ok": False,
                                     "error": f"unknown action {action!r}"})
                    return
                done, why = doer(model_id)
                self._json(200 if done else 400, {"ok": done, "error": why})
                return

            if route == "/api/rules":
                action = str(body.get("action") or "")
                if action == "export":
                    done, why, where = server.session.export_rules()
                    self._json(200 if done else 500,
                               {"ok": done, "error": why, "path": where})
                    return
                done, why, extra = server.session.rule(
                    action, id=body.get("id"),
                    statement=body.get("statement"))
                self._json(200 if done else 400,
                           {"ok": done, "error": why, "rule": extra})
                return

            if route == "/api/facts":
                done, why = server.session.fact(
                    str(body.get("action") or ""), id=body.get("id"),
                    text=body.get("text"), kind=body.get("kind"))
                self._json(200 if done else 400, {"ok": done, "error": why})
                return

            if route == "/api/setting":
                done, why = server.session.setting(str(body.get("key") or ""),
                                                   body.get("value"))
                self._json(200 if done else 400, {"saved": done, "error": why})
                return

            if route == "/api/chat":
                action = str(body.get("action") or "")
                chat_id = str(body.get("id") or "")

                if action == "new":
                    done, why = server.session.new_chat()
                elif action == "open":
                    done, why, turns = server.session.open_chat(chat_id)
                    if done:
                        # The cursor moves with the chat. Without it the page
                        # would draw the transcript and then replay the events
                        # of the conversation it just left on top of it.
                        self._json(200, {"opened": True, "turns": turns,
                                         "cursor": server.session.cursor,
                                         "chat": server.session.state()["chat"]})
                        return
                elif action == "delete":
                    done, why = server.session.delete_chat(chat_id)
                else:
                    done, why = False, "no such action"

                self._json(200 if done else 409,
                           {"ok": done, "error": why,
                            "cursor": server.session.cursor,
                            "chat": server.session.state()["chat"]})
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
