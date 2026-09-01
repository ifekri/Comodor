"""The endpoint Meta posts inbound WhatsApp messages to.

Telegram asks for messages. WhatsApp delivers them, which means a URL of yours
has to be reachable from the internet over HTTPS. That single fact is the
reason this file exists and the reason it is the most security-sensitive part
of the WhatsApp support: a long poll can only be answered by Telegram, while an
endpoint can be reached by anybody who finds it.

So three things happen to every request before it becomes a message.

**The signature is checked.** Meta signs each payload with the app secret,
HMAC-SHA256, in `X-Hub-Signature-256`. Without that check anything that can
reach the endpoint can hand the agent instructions with somebody else's phone
number on them — which for a tool that runs shell commands is the whole game.
Comparison is constant time; a `==` on a signature leaks the answer a byte at a
time to anybody willing to measure.

**The body is the raw bytes.** The signature covers exactly what was sent, so
it has to be verified before the JSON is parsed and against the bytes rather
than against a re-serialised copy — one different space and a genuine payload
fails.

**It answers immediately.** Meta retries anything it does not get a 200 for
within a few seconds, and an agent turn takes minutes. The handler puts the
message on a queue and returns; the bot picks it up. A webhook that waits for
the work is a webhook that gets the same message delivered five times.

Bound to localhost by default. Meta will not deliver to plain HTTP and will not
accept a self-signed certificate, so something in front — a tunnel, or a proxy
that already terminates TLS — is required either way, and binding to every
interface as well would only add a second way in.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import queue
import secrets
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

#: Bigger than any plausible webhook and small enough that a hostile body
#: cannot be used to exhaust memory.
MOST_BYTES = 512 * 1024


def make_verify_token() -> str:
    """A fresh verify token. Generated, never chosen — it is a shared secret."""
    return secrets.token_urlsafe(24)


def signed(body: bytes, secret: str) -> str:
    """The header value Meta would send for this body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def signature_ok(body: bytes, header: str, secret: str) -> bool:
    """Whether this really came from Meta.

    False when there is no secret configured: a check that passes because
    nothing was set up is worse than no check, because it looks like one.
    """
    if not secret or not header:
        return False
    return hmac.compare_digest(signed(body, secret), header.strip())


# --------------------------------------------------------------------------- #
# what a delivery turns into
# --------------------------------------------------------------------------- #


@dataclass
class Inbound:
    """One thing a person did, flattened out of Meta's nesting.

    Meta wraps a message in `entry[].changes[].value.messages[]` and puts the
    sender's name somewhere else again, under `contacts`. Everything after this
    point deals with the four fields that matter.
    """

    wa_id: str = ""
    message_id: str = ""
    text: str = ""
    #: The id of a tapped reply button or list row, if that is what this was.
    action: str = ""
    name: str = ""
    timestamp: int = 0
    #: A media message, flattened to the two fields a download needs: the id
    #: Meta names the file by, and what the message called itself.
    media_id: str = ""
    media_kind: str = ""          # image | audio | video | document
    media_name: str = ""

    @property
    def tapped(self) -> bool:
        return bool(self.action)

    @property
    def is_media(self) -> bool:
        return bool(self.media_id)


def read(payload: dict[str, Any]) -> list[Inbound]:
    """Every message in one delivery. Status callbacks produce nothing.

    Meta posts delivery receipts — sent, delivered, read — through the same
    endpoint as messages, in the same shape but with `statuses` where
    `messages` would be. Treating one as the other answers the user's own read
    receipt with an agent turn.
    """
    found: list[Inbound] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            if not value.get("messages"):
                continue
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name", "")
                     for c in value.get("contacts") or []}
            for message in value["messages"]:
                item = _one(message, names)
                if item is not None:
                    found.append(item)
    return found


def _one(message: dict[str, Any], names: dict[str, str]) -> Inbound | None:
    kind = message.get("type")
    who = str(message.get("from") or "")
    common = {
        "wa_id": who,
        "message_id": str(message.get("id") or ""),
        "name": names.get(who, ""),
        "timestamp": int(message.get("timestamp") or 0),
    }

    if kind == "text":
        return Inbound(text=(message.get("text") or {}).get("body", ""),
                       **common)

    if kind == "interactive":
        inner = message.get("interactive") or {}
        reply = (inner.get("button_reply") or inner.get("list_reply") or {})
        if reply:
            return Inbound(action=str(reply.get("id") or ""),
                           text=str(reply.get("title") or ""), **common)
        return None

    if kind == "button":
        # A template's quick-reply button, which carries a payload rather than
        # an id. Not used by anything here, but arriving as one of these rather
        # than being dropped silently is the difference between "it ignored me"
        # and a line in the log.
        return Inbound(action=str((message.get("button") or {}).get("payload")
                                  or ""),
                       text=str((message.get("button") or {}).get("text") or ""),
                       **common)

    # Images, voice notes, documents — media Meta names with an id, downloaded
    # by the bot and routed by type. Locations and reactions stay "named
    # rather than dropped": silence from a bot is indistinguishable from a bot
    # that is off.
    media = message.get(kind) if isinstance(message.get(kind), dict) else None
    if media and "id" in media:
        return Inbound(media_id=str(media["id"]), media_kind=kind,
                       media_name=str(media.get("filename") or kind), **common)
    return Inbound(text="", action=f"unsupported:{kind}", **common)


# --------------------------------------------------------------------------- #
# the server
# --------------------------------------------------------------------------- #


@dataclass
class Endpoint:
    """The listening half, and the queue it feeds."""

    verify_token: str
    app_secret: str
    path: str = "/whatsapp"
    host: str = "127.0.0.1"
    port: int = 8770
    #: Deliveries waiting to be turned into turns.
    inbox: queue.Queue = field(default_factory=queue.Queue)
    #: Called with a line of text for whoever is watching.
    announce: Callable[[str], None] | None = None
    _server: Any = None
    _thread: threading.Thread | None = None
    #: Message ids already handled. Meta re-delivers anything it did not get a
    #: 200 for, and a re-delivered message must not become a second turn.
    _seen: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def say(self, line: str) -> None:
        if self.announce:
            try:
                self.announce(line)
            except Exception:
                pass

    def fresh(self, message_id: str) -> bool:
        """Whether this is the first time we have seen this message."""
        if not message_id:
            return True
        with self._lock:
            if message_id in self._seen:
                return False
            self._seen.add(message_id)
            # Unbounded, this is a slow leak in a process meant to run for
            # weeks. The oldest are the least likely to be redelivered.
            if len(self._seen) > 4000:
                for old in list(self._seen)[:2000]:
                    self._seen.discard(old)
            return True

    def start(self) -> None:
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                """Silence. The default logs every request to stderr, which in
                a background daemon means a log file that grows for ever."""

            def _answer(self, status: int, body: bytes = b"",
                        kind: str = "text/plain") -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_GET(self) -> None:                    # noqa: N802
                """Meta's one-time verification handshake."""
                parsed = urlparse(self.path)
                if parsed.path != endpoint.path:
                    self._answer(404)
                    return
                query = parse_qs(parsed.query)
                mode = (query.get("hub.mode") or [""])[0]
                token = (query.get("hub.verify_token") or [""])[0]
                challenge = (query.get("hub.challenge") or [""])[0]

                if mode == "subscribe" and hmac.compare_digest(
                        token, endpoint.verify_token):
                    endpoint.say("webhook verified by Meta")
                    self._answer(200, challenge.encode("utf-8"))
                    return
                # Deliberately the same answer as a wrong path. Somebody
                # probing does not learn that they found the endpoint and got
                # the token wrong.
                endpoint.say("webhook verification refused: wrong token")
                self._answer(403)

            def do_POST(self) -> None:                   # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != endpoint.path:
                    self._answer(404)
                    return

                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MOST_BYTES:
                    self._answer(400)
                    return
                body = self.rfile.read(length)

                if not signature_ok(
                        body, self.headers.get("X-Hub-Signature-256", ""),
                        endpoint.app_secret):
                    endpoint.say("refused a delivery with a bad signature")
                    self._answer(403)
                    return

                # Answered before the work, not after. Meta retries anything it
                # does not get a 200 for within seconds, and a turn takes
                # minutes.
                self._answer(200)

                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    return
                for item in read(payload):
                    if endpoint.fresh(item.message_id):
                        endpoint.inbox.put(item)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.4},
            name="comodor-whatsapp-webhook", daemon=True)
        self._thread.start()
        self.say(f"listening on http://{self.host}:{self.port}{self.path}")

    def stop(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
