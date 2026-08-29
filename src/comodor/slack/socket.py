"""Socket Mode: events over a websocket the app opens outward.

This is the whole reason Slack is as easy to set up as Telegram and not as
hard as WhatsApp. Slack's other way of delivering events is the Events API,
which posts to a URL and therefore needs a public HTTPS address, a certificate
and a tunnel. Socket Mode inverts it: the app asks Slack for a websocket
address and connects *out*, so nothing has to be reachable from the internet
and there is no address to keep up to date.

Three things it has to get right, and each of them is a way a bot goes quiet
without anybody noticing.

**Every envelope is acknowledged.** Slack wraps each event in an envelope with
an id and expects that id sent back. An unacknowledged event is redelivered,
and then redelivered again — for an agent that runs commands, one message
becoming three turns is not merely noisy.

**The connection is meant to be replaced.** Slack sends `disconnect` with
`reason: refresh_requested` on a schedule and closes shortly after. That is
routine, not a fault: the answer is to open a new socket, not to log an error
and stop. Treating it as failure produces a bot that dies every few hours.

**A quiet workspace still needs pings.** A socket nobody has spoken on is a
socket some middlebox will drop, and the case that matters most — nobody has
messaged the bot for an hour — is exactly the quiet one.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..net.ws import WebSocket, WebSocketError
from .api import Slack, SlackError, backoff

#: How often to ping when nothing else is happening.
PING_EVERY = 30.0

#: Slack's own ping interval is under a minute, so silence for much longer
#: than that means the connection is gone whatever the socket believes.
SILENCE_LIMIT = 90.0


@dataclass
class Envelope:
    """One thing Slack sent, unwrapped."""

    kind: str = ""
    envelope_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    accepts_response: bool = False

    @property
    def event(self) -> dict[str, Any]:
        """The inner event, for `events_api` envelopes."""
        return dict(self.payload.get("event") or {})


class SocketMode:
    """One long-lived connection to Slack, reopened as often as it takes."""

    def __init__(self, slack: Slack,
                 on_envelope: Callable[[Envelope], None],
                 announce: Callable[[str], None] | None = None) -> None:
        self.slack = slack
        self.on_envelope = on_envelope
        self.announce = announce or (lambda line: None)
        self.stopping = threading.Event()
        self._ws: WebSocket | None = None
        self._lock = threading.Lock()
        #: Envelope ids already handled. Slack redelivers anything it did not
        #: get an acknowledgement for, and a redelivery must not become a
        #: second turn.
        self._seen: set[str] = set()

    def say(self, line: str) -> None:
        try:
            self.announce(line)
        except Exception:
            pass

    def stop(self) -> None:
        self.stopping.set()
        with self._lock:
            if self._ws is not None:
                self._ws.close()
                self._ws = None

    # -- the loop ----------------------------------------------------------- #

    def run(self) -> None:
        """Connect, read, reconnect. Returns only when stopped."""
        attempt = 0
        while not self.stopping.is_set():
            try:
                url = self.slack.open_socket()
            except SlackError as problem:
                # A wrong app token will never come right by waiting, and a
                # loop that retries it for ever looks like a network fault.
                if "invalid_auth" in str(problem) or "not_allowed" in str(problem):
                    self.say(f"Slack refused the app-level token: {problem}")
                    return
                attempt += 1
                wait = backoff(attempt)
                self.say(f"could not open a socket ({problem}) — "
                         f"retrying in {wait:.0f}s")
                if self.stopping.wait(wait):
                    return
                continue

            if not url:
                attempt += 1
                if self.stopping.wait(backoff(attempt)):
                    return
                continue

            try:
                self._session(url)
                attempt = 0          # a session that ran is a working setup
            except WebSocketError as problem:
                attempt += 1
                wait = backoff(attempt)
                self.say(f"socket closed ({problem}) — reconnecting in "
                         f"{wait:.0f}s")
                if self.stopping.wait(wait):
                    return

    def _session(self, url: str) -> None:
        """One connection, until Slack asks for a new one or it breaks."""
        socket = WebSocket(url, timeout=10.0)
        with self._lock:
            self._ws = socket
        self.say("connected to Slack")

        last_heard = time.time()
        last_ping = time.time()
        try:
            while not self.stopping.is_set():
                try:
                    raw = socket.receive()
                except WebSocketError:
                    # A read timeout is the ordinary quiet case, not a fault.
                    now = time.time()
                    if now - last_heard > SILENCE_LIMIT:
                        raise
                    if now - last_ping > PING_EVERY:
                        socket.ping()
                        last_ping = now
                    continue

                last_heard = time.time()
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue

                kind = str(message.get("type") or "")
                if kind == "hello":
                    continue
                if kind == "disconnect":
                    # Routine. Slack rotates these on a schedule; the answer
                    # is a new socket, not an error.
                    why = str(message.get("reason") or "")
                    self.say(f"Slack asked for a new connection ({why})")
                    return

                envelope = Envelope(
                    kind=kind,
                    envelope_id=str(message.get("envelope_id") or ""),
                    payload=dict(message.get("payload") or {}),
                    accepts_response=bool(message.get("accepts_response_payload")),
                )

                # Acknowledged first, and always. Slack redelivers anything it
                # does not hear about, and the handler below can take minutes.
                if envelope.envelope_id:
                    self._ack(socket, envelope.envelope_id)
                    if envelope.envelope_id in self._seen:
                        continue
                    self._seen.add(envelope.envelope_id)
                    if len(self._seen) > 4000:
                        for old in list(self._seen)[:2000]:
                            self._seen.discard(old)

                try:
                    self.on_envelope(envelope)
                except Exception as problem:      # one message must not stop it
                    self.say(f"failed on an event: {problem}")
        finally:
            with self._lock:
                if self._ws is socket:
                    self._ws = None
            socket.close()

    def _ack(self, socket: WebSocket, envelope_id: str) -> None:
        try:
            socket.send(json.dumps({"envelope_id": envelope_id}))
        except WebSocketError as problem:
            self.say(f"could not acknowledge an event: {problem}")
