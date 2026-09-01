"""The endpoint external systems post to, and what an accepted event does.

The WhatsApp webhook's rules, generalised. Every one of them was learned
the hard way there and applies here with the same force:

*The signature is checked against the raw bytes.* Before JSON parsing, with
HMAC-SHA256 over exactly what arrived, compared in constant time. A
re-serialised copy fails one byte at a time; a `==` leaks the answer to
anybody willing to measure.

*Nothing is answered with information about itself.* A wrong signature gets
404, the same as an unknown path — an endpoint that says "this one exists,
but you may not" has drawn a map for whoever is probing it.

*The response is immediate.* An agent turn is minutes; a webhook caller is
seconds. The turn is queued, ``{"status": "accepted"}`` goes back, and the
work happens on a thread. A bounded queue keeps ten simultaneous events
orderly rather than unbounded: the queue is what makes at-least-once
delivery a property instead of a hope.

*The agent runs like a cron job, not like a session.* Fresh agent per
event, no shared conversation, question forms answered "cancelled" at once
— there is nobody at a keyboard here either. Writes stay behind the
subscription's ``allow_writes``, which sets plan mode when it is off.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..config import Config
from .subs import MOST_BYTES, Sub, Subscriptions, load, render

#: Events waiting to run at once. Past this, the server answers 503 and the
#: sender retries — which is what every webhook sender already knows how to
#: do, and better than a queue that swallows the difference.
QUEUE_DEPTH = 32


def signature_ok(body: bytes, header: str, secret: str) -> bool:
    """Whether this really came from the subscription's partner."""
    if not secret or not header:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", header.strip())


@dataclass
class Event:
    """One accepted delivery, waiting to become a turn."""

    sub: Sub
    payload: dict[str, Any]
    received: float = field(default_factory=time.time)


class Server:
    """One port, every subscription's paths, one queue of work."""

    def __init__(self, config: Config, host: str = "127.0.0.1",
                 port: int = 8790, subs: Subscriptions | None = None) -> None:
        self.config = config
        self.host = host
        self.port = port
        self.subs = subs or load(config)
        self._httpd: ThreadingHTTPServer | None = None
        self._queue: "queue.Queue[Event]" = queue.Queue(maxsize=QUEUE_DEPTH)
        self._workers: list[threading.Thread] = []
        #: The last few events, for `comodor webhook list` and the TUI —
        #: accepted, refused, and why.
        self.recent: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self.stopping = threading.Event()

    def bind(self) -> int:
        self._httpd = ThreadingHTTPServer((self.host, self.port),
                                          _handler_for(self))
        self.port = self._httpd.server_address[1]
        return self.port

    def serve(self) -> None:
        if self._httpd is None:
            self.bind()
        for number in range(2):
            worker = threading.Thread(target=self._work,
                                      name=f"comodor-webhook-{number}",
                                      daemon=True)
            worker.start()
            self._workers.append(worker)
        try:
            self._httpd.serve_forever(poll_interval=0.3)
        finally:
            self.stopping.set()

    def stop(self) -> None:
        httpd = self._httpd
        if httpd is not None:
            threading.Thread(target=httpd.shutdown, daemon=True).start()

    # -- what a request becomes ------------------------------------------- #

    def accept(self, sub: Sub, payload: dict[str, Any]) -> tuple[bool, str]:
        """Queue one verified event. False when the queue is full."""
        try:
            self._queue.put_nowait(Event(sub=sub, payload=payload))
        except queue.Full:
            return False, "the queue is full; try again"
        self._note({"path": sub.path, "event": "accepted",
                    "when": time.strftime("%H:%M:%S")})
        return True, ""

    def _work(self) -> None:
        while not self.stopping.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._run(event)
            except Exception as problem:      # never lose the worker
                self._note({"path": event.sub.path, "event": "failed",
                            "why": f"{type(problem).__name__}: {problem}",
                            "when": time.strftime("%H:%M:%S")})

    def _run(self, event: Event) -> None:
        from ..cron.runner import run_job

        prompt = render(event.sub.template, event.payload)
        config = self.config
        # Trust is per-subscription and decided here, once: a webhook that
        # could inherit whichever channel's settings were live would be a
        # way for a repo's config to widen a machine's permissions.
        config.safety.auto_approve_writes = event.sub.allow_writes
        config.safety.auto_approve_shell = event.sub.allow_writes
        if not event.sub.allow_writes:
            config.agent.mode = "plan"

        answer = run_job(config, _Job(prompt))
        self._note({"path": event.sub.path, "event": "finished",
                    "ok": answer.ok, "when": time.strftime("%H:%M:%S")})
        if event.sub.reply_url and answer.answer:
            _deliver(event.sub.reply_url, answer.answer)

    def _note(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.recent.append(entry)
            del self.recent[:-50]


class _Job:
    """The one field the cron runner reads off a job: its prompt."""

    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.model = ""


def _deliver(url: str, text: str) -> None:
    """POST the finished answer to the subscription's reply URL.

    Best-effort by design: the work is done and logged either way, and a
    delivery failure must not look like a run failure in the history.
    """
    try:
        from ..net.http import post

        post(url, json={"text": text[:8000]}, timeout=15.0)
    except Exception:
        pass


def _handler_for(server: Server) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        server_version = "comodor"
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:
            # Even the 404 drains the body: keep-alive sees a reset
            # otherwise, and the caller reads that as a network fault
            # rather than a refusal.
            self._drain()
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            body = self._drain()

            sub = server.subs.by_path(path)
            if sub is None or not body or not signature_ok(
                    body, self.headers.get("X-Comodor-Signature-256", ""),
                    sub.secret):
                # One answer for unknown paths, wrong sizes and bad
                # signatures: nothing here tells a prober what exists.
                self._send(404, {"error": "not found"})
                return

            try:
                payload = json.loads(body)
            except ValueError:
                self._send(400, {"error": "the body is not JSON"})
                return
            if not isinstance(payload, dict):
                payload = {"payload": payload}

            accepted, why = server.accept(sub, payload)
            if not accepted:
                self._send(503, {"error": why})
                return
            self._send(202, {"status": "accepted"})

        def _drain(self) -> bytes:
            """Read the whole body; oversized ones are read and dropped."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                return b""
            chunks: list[bytes] = []
            remaining = length
            while remaining > 0:
                piece = self.rfile.read(min(remaining, 65536))
                if not piece:
                    break
                remaining -= len(piece)
                if sum(len(c) for c in chunks) < MOST_BYTES:
                    chunks.append(piece)
            if length > MOST_BYTES:
                return b""
            return b"".join(chunks)

    return Handler


def run(config: Config, args: argparse.Namespace) -> int:
    """`comodor webhook serve` — the entry point."""
    from rich.panel import Panel
    from rich.text import Text

    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)

    subs = load(config)
    server = Server(config, host=config.webhook.bind, port=config.webhook.port)

    console.print()
    lines = [f"POST [bold]http://{server.host}:{server.port}<path>[/bold]\n"]
    found = subs.load()
    if not found:
        lines.append("No subscriptions yet.\n"
                     "  [bold]comodor webhook add[/bold] to make one")
    else:
        for sub in found:
            lines.append(f"  [bold]{sub.path}[/bold]  {sub.name}"
                         + ("  [dim]may edit[/dim]" if sub.allow_writes
                            else ""))
    console.print(Panel(Text.from_markup("\n".join(lines)),
                        title=" Webhook channel ", title_align="left",
                        border_style="accent", padding=(1, 2)))
    console.print()

    try:
        server.serve()
    except KeyboardInterrupt:
        console.print("\n  Stopping.\n")
    return 0
