"""The OpenAI-compatible endpoint itself.

One process, one port, the agent's whole loop behind two routes. The
security model is the web server's verbatim, minus the browser parts that
do not apply — no cookies (a program presents ``Authorization: Bearer``),
no cross-origin guard (there is no page, and CORS is answered by nobody),
no static assets.

What replaces them is the rule that decides whether this server is a
convenience or an open door: **who holds the token may run shell commands
on this machine**, because that is what a turn is. So the token is required
on every route, generated per run, compared in constant time, never logged;
the default bind is loopback; a non-loopback bind is allowed but says in as
many words what was just done; and a body past the cap is refused before it
is parsed, because a parser is where oversized input becomes an incident.

One request is one whole turn, capped at ``api.max_turns`` loop steps so a
chat client's HTTP timeout outlives the answer it asked for. A turn the cap
stopped is reported as ``finish_reason: "length"`` with the cut named in the
non-standard ``comodor`` block — never as a tool-call the client cannot run.
"""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..config import Config
from . import schema
from .session_map import SessionMap

#: A 2 MB request is a request somebody should have made with `@file`.
MAX_BODY = 2_000_000
#: One turn's patience. The web session's own cap for a hung worker is an
#: hour; a chat client's HTTP timeout is usually 60–120 s, so a turn that
#: outlives this is cut loose by the client first regardless — the cap here
#: keeps a stalled loop from holding server threads forever.
TURN_PATIENCE = 600.0

LOCAL = ("127.0.0.1", "::1", "localhost")


@dataclass
class Server:
    """The endpoint: one config, one session map, one token."""

    config: Config
    host: str = "127.0.0.1"
    port: int = 8787
    token: str = ""
    _httpd: ThreadingHTTPServer | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.token = self.token or secrets.token_urlsafe(24)
        # A chat client's HTTP timeout is a minute or two, not an agent's
        # patience. An unlimited loop behind this endpoint would hold a
        # request for as long as the work took, and the client would be gone
        # long before — so the endpoint's own cap applies when the user has
        # set none. A stricter personal limit is left stricter.
        if not self.config.agent.max_steps:
            self.config.agent.max_steps = self.config.api.max_turns
        self.map = SessionMap(self.config)

    @property
    def local(self) -> bool:
        return self.host in LOCAL

    def bind(self) -> int:
        """Take the port. Before the URL is printed, so a busy one is an
        error rather than a URL that connects to nothing."""
        self._httpd = ThreadingHTTPServer((self.host, self.port), _handler_for(self))
        self.port = self._httpd.server_address[1]     # when 0 was asked for
        return self.port

    def serve(self) -> None:
        if self._httpd is None:
            self.bind()
        try:
            self._httpd.serve_forever(poll_interval=0.3)
        finally:
            self.map.close_all()

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

        def log_message(self, *args: Any) -> None:
            pass                       # nothing on stdout; the token lives in args

        # -- plumbing ------------------------------------------------------ #

        def _send(self, status: int, body: bytes,
                  content_type: str = "application/json",
                  extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False)
                       .encode("utf-8"))

        def _bearer(self) -> str:
            """The token as presented. Both spellings, because the ecosystem
            disagrees about the space after the scheme."""
            header = self.headers.get("Authorization") or ""
            scheme, _, value = header.partition(" ")
            if scheme.lower() == "bearer":
                return value.strip()
            return header.strip()

        def _body(self) -> dict[str, Any]:
            """Read the body, all of it, cap or no cap.

            Always drained fully for the same reason the web server drains:
            unread bytes are read by the next request on the connection as
            its request line. Past the cap the bytes are dropped, not parsed.
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
                piece = self.rfile.read(min(remaining, 65536))
                if not piece:
                    break
                remaining -= len(piece)
                if len(raw) < MAX_BODY:
                    raw += piece
            if length > MAX_BODY:
                # Answered by the caller, which knows whether it wants a
                # 413 or can still route the request another way.
                self._too_large = True
                return {}
            self._too_large = False
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                raise schema.BadRequest("the body is not valid JSON") from None

        _too_large = False

        def do_GET(self) -> None:
            if self.headers.get("Content-Length"):
                try:
                    self._body()
                except schema.BadRequest:
                    self._json(400, schema.error_body("the body is not valid JSON"))
                    return
            if not server.authorised(self._bearer()):
                self._json(401, schema.error_body(
                    "send the token Comodor printed as "
                    "Authorization: Bearer <token>", "authentication_error"))
                return

            route = self.path.split("?", 1)[0]
            if route == "/v1/models":
                self._json(200, schema.models_listing())
                return
            self._json(404, schema.error_body("no such route"))

        def do_POST(self) -> None:
            route = self.path.split("?", 1)[0]
            if route not in ("/v1/chat/completions",):
                try:
                    self._body()
                except schema.BadRequest:
                    pass
                self._json(404, schema.error_body("no such route"))
                return

            self._too_large = False
            try:
                payload = self._body()
            except schema.BadRequest:
                self._json(400, schema.error_body("the body is not valid JSON"))
                return
            if self._too_large:
                self._json(413, schema.error_body(
                    f"the body is past the {MAX_BODY // 1_000_000} MB limit"))
                return

            # After the body: an unread body would poison keep-alive, and
            # the client would see a reset instead of the 401.
            if not server.authorised(self._bearer()):
                self._json(401, schema.error_body(
                    "send the token Comodor printed as "
                    "Authorization: Bearer <token>", "authentication_error"))
                return

            try:
                text, prior = schema.messages_from(payload)
            except schema.BadRequest as problem:
                self._json(400, schema.error_body(str(problem)))
                return

            wanted = str(payload.get("model") or schema.MODEL_ID)
            stream = bool(payload.get("stream"))
            comodor = payload.get("comodor")
            comodor = comodor if isinstance(comodor, dict) else {}
            mode = str(comodor.get("mode") or "").strip()
            if mode and not server.config.api.allow_mode_switch:
                mode = ""

            session_id = str(self.headers.get("X-Comodor-Session") or "")
            talk = server.map.for_session(session_id)

            created = time.time()
            request_id = f"chatcmpl-{secrets.token_hex(8)}"
            try:
                outcome = talk.run(text, prior=prior, mode=mode,
                                   patience=TURN_PATIENCE)
            except schema.BadRequest as problem:
                self._json(400, schema.error_body(str(problem)))
                return

            finish = _finish_reason(outcome)
            usage = schema.usage_of(outcome.get("result"))
            extra = {"comodor": {"session": talk.id, "steps": outcome.get("steps", 0),
                                 "stopped": outcome.get("stopped", "done"),
                                 "truncated": finish == "length"}}

            if stream:
                self._stream_sse(created, wanted, request_id, outcome, usage,
                                 finish, extra)
                return
            self._json(200, schema.final(
                created, wanted, request_id, str(outcome.get("text") or ""),
                usage, finish, extra=extra))

        def _stream_sse(self, created: float, model: str, request_id: str,
                        outcome: dict[str, Any], usage: dict[str, Any],
                        finish: str, extra: dict[str, Any]) -> None:
            """The answer as ``data: {...}\\n\\n`` frames, then ``[DONE]``.

            Comodor's turn is already finished by the time this runs — the
            loop has no mid-turn stream to hand over across a thread
            boundary it does not own, so the deltas here re-chunk a done
            answer. The result for the client is the same wire format at
            the same protocol version; what it is not is lower latency,
            and pretending otherwise would be the kind of honesty the rest
            of this program refuses.
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            def frame(payload: dict[str, Any]) -> None:
                self.wfile.write(
                    f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    .encode("utf-8"))

            try:
                frame(schema.chunk(created, model, request_id,
                                   delta={"role": "assistant"}))
                text = str(outcome.get("text") or "")
                for piece in _pieces(text):
                    frame(schema.chunk(created, model, request_id,
                                       delta={"content": piece}))
                last = schema.chunk(created, model, request_id, finish=finish)
                last["usage"] = usage
                last.update(extra)
                frame(last)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return                       # the client gave up; nothing to do

        def do_OPTIONS(self) -> None:
            if self.headers.get("Content-Length"):
                try:
                    self._body()
                except schema.BadRequest:
                    pass
            # No CORS for anyone, as at the web server. A browser frontend
            # pointed at Comodor across an origin gets nothing here — the
            # supported clients are server-side programs and desktop apps
            # that do not need the preflight.
            self._send(405, b"")

    return Handler


#: How a finished answer is streamed: paragraph-sized pieces, not
#: token-sized ones. The answer is already whole; the pieces exist so a
#: client that renders progressively shows something like typing rather
#: than one wall of text, and a hundred frames of one word each would be
#: the worst of both.
PIECE = 240


def _pieces(text: str) -> list[str]:
    if not text:
        return []
    if len(text) <= PIECE:
        return [text]
    out = []
    at = 0
    while at < len(text):
        stop = min(at + PIECE, len(text))
        if stop < len(text):
            # Prefer a paragraph, then a line, then a space — cut on
            # structure when there is any within reach.
            for look in ("\n\n", "\n", " "):
                found = text.rfind(look, at, stop)
                if found > at:
                    stop = found + len(look)
                    break
        out.append(text[at:stop])
        at = stop
    return out


def _finish_reason(outcome: dict[str, Any]) -> str:
    """``stop`` or ``length``, in OpenAI's vocabulary.

    ``length`` is "there was more to say": a turn the step cap stopped
    before it finished. The loop's tool calls are never handed to the
    client even then — a chat client that received a ``tool_calls`` answer
    would try to answer them, and it cannot; the tools run on this machine.
    The note that the turn was cut is in the ``comodor`` block, where a
    frontend that cares can find it and a standard client is untouched.
    """
    stopped = str(outcome.get("stopped") or "done")
    if stopped in ("max_steps", "budget", "timeout"):
        return "length"
    return "stop"


def run(config: Config, args: argparse.Namespace) -> int:
    """`comodor serve` — the whole entry point."""
    from rich.panel import Panel
    from rich.text import Text

    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)

    settings = config.api
    settings.enabled = True
    host = str(getattr(args, "host", "") or settings.bind or "127.0.0.1")
    port = int(getattr(args, "port", 0) or settings.port or 8787)
    token = str(getattr(args, "token", "") or settings.token or "")

    server = Server(config, host=host, port=port, token=token)
    shown_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host

    console.print()
    console.print(Panel(Text.from_markup(
        f"POST [bold]http://{shown_host}:{port}/v1/chat/completions[/bold]\n"
        f"GET  [bold]http://{shown_host}:{port}/v1/models[/bold]\n\n"
        f"Point an OpenAI-compatible client at it.\n"
        f"Authorization: [bold]Bearer {server.token}[/bold]\n"
        + ("[bold red]Every interface on this network may run commands on "
           "this machine. A reverse proxy with its own auth is not a "
           "suggestion.[/bold red]" if not server.local else
           "[dim]loopback only — use --host to open it, and a proxy when "
           "you do[/dim]")),
        title=" Comodor, speaking OpenAI ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()

    try:
        server.serve()
    except KeyboardInterrupt:
        console.print("\n  Stopping.\n")
    return 0
