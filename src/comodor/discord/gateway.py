"""Discord's gateway: the websocket every event arrives on.

Slack's Socket Mode and Discord's gateway are the same shape — a websocket
the bot opens *out*, events pushed in, an ack expected — and Discord adds
three things Slack does not ask for:

**IDENTIFY.** The first thing sent after HELLO: the token, the intents wanted,
and connection properties. The intents decide what the gateway will send; a
bot that asks for none of the message ones hears silence forever, which looks
exactly like a wrong token.

**HEARTBEAT.** Discord says how often to ping (`heartbeat_interval`, in
milliseconds) and expects the reply within its window. A missed heartbeat is
a closed socket a few seconds later — the one way a bot goes quiet on an
evening nobody is watching.

**RESUME.** On reconnect, a session id and the last event number received let
the gateway replay everything sent since — the same guarantee Telegram's
update offset gives, and the reason a network blip loses no messages.

Dispatch events are acknowledged with nothing; the flow control is the
heartbeat alone. This file owns the protocol; `bot.py` owns what events mean.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from ..channels.breaker import CircuitBreaker
from ..net.ws import WebSocket, WebSocketError
from .api import Unauthorised

#: Op codes the protocol runs on. Only these; the rest are ignored.
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9

#: The intents this bot needs. MESSAGE_CONTENT is a *privileged* intent: it
#: must be toggled in the developer portal for the app, and without it the
#: gateway connects but message bodies arrive empty — a failure that looks
#: like a bot that answers "I got nothing".
INTENTS = 1 << 15          # message content
# 1 << 9  guild messages, 1 << 12 direct messages
INTENTS |= (1 << 9) | (1 << 12)

#: Cap on one reconnect wait. Without it a day-long outage backs off into
#: hours before the first retry of the evening.
MAX_BACKOFF = 60.0


class Gateway:
    """The connection, its heartbeat, and the resume state.

    `run` blocks; `stop` ends it. Events reach the caller as decoded
    `MESSAGE_CREATE` payloads; everything else the protocol needs is handled
    here.
    """

    def __init__(self, token: str, on_event: Callable[[dict[str, Any]], None],
                 announce: Callable[[str], None] = lambda line: None,
                 breaker: CircuitBreaker | None = None) -> None:
        self._token = token
        self._on_event = on_event
        self._announce = announce
        self._breaker = breaker
        self.stopping = threading.Event()
        self._session_id = ""
        self._last_seq: int | None = None
        self._heartbeat: float = 41.25      # until HELLO says otherwise

    def stop(self) -> None:
        self.stopping.set()

    def run(self) -> None:
        """Connect, and keep connecting, until stopped or refused.

        A refused token ends the loop — retrying a 4001 every ten seconds
        hammers Discord with a credential nobody fixed. A dropped socket
        resumes; that is the routine case, not a fault.
        """
        backoff = 1.0
        while not self.stopping.is_set():
            try:
                self._session()
                backoff = 1.0
            except Unauthorised:
                self._announce("Discord refused the token — not retrying")
                return
            except (WebSocketError, OSError) as problem:
                self._announce(f"the gateway dropped: {problem} — resuming")
            except Exception as problem:
                if self._breaker and self._breaker.fail(str(problem)):
                    return
            if not self.stopping.wait(min(backoff, MAX_BACKOFF)):
                return
            backoff = min(backoff * 2, MAX_BACKOFF)

    # -- one connection ---------------------------------------------------- #

    def _session(self) -> None:
        socket = WebSocket(
            "wss://gateway.discord.gg/?v=10&encoding=json",
            timeout=self._heartbeat + 5.0)
        try:
            while not self.stopping.is_set():
                socket.settimeout(min(self._heartbeat, 5.0))
                try:
                    raw = socket.receive()
                except WebSocketError as problem:
                    if "stopped answering" in str(problem):
                        self._beat(socket)      # a quiet socket still pings
                        continue
                    raise
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    continue                    # gateways speak text
                try:
                    packet = json.loads(raw)
                except ValueError:
                    continue
                self._handle(socket, packet)
        finally:
            socket.close()

    def _handle(self, socket: WebSocket, packet: dict[str, Any]) -> None:
        op = packet.get("op")

        if op == OP_HELLO:
            self._heartbeat = float(
                (packet.get("d") or {}).get("heartbeat_interval")
                or 41250) / 1000.0
            if self._session_id and self._last_seq is not None:
                socket.send(json.dumps({
                    "op": OP_RESUME, "d": {
                        "token": self._token, "session_id": self._session_id,
                        "seq": self._last_seq}}))
            else:
                socket.send(json.dumps({
                    "op": OP_IDENTIFY, "d": {
                        "token": self._token,
                        "intents": INTENTS,
                        "properties": {
                            "os": "linux", "browser": "comodor",
                            "device": "comodor"}}}))

        elif op == OP_DISPATCH:
            self._last_seq = packet.get("s")
            kind = packet.get("t")
            if kind == "READY":
                self._session_id = str((packet.get("d") or {}).get(
                    "session_id") or "")
                self._announce("connected to the Discord gateway")
            elif kind == "MESSAGE_CREATE":
                try:
                    self._on_event(dict(packet.get("d") or {}))
                except Exception:               # an event must not kill the socket
                    pass
            elif kind == "RESUMED":
                self._announce("resumed; nothing was lost")

        elif op == OP_HEARTBEAT:
            self._beat(socket)

        elif op == OP_HEARTBEAT_ACK:
            pass                                # proof of life; nothing owed

        elif op == OP_RECONNECT:
            raise WebSocketError("the gateway asked for a reconnect")

        elif op == OP_INVALID_SESSION:
            # resumable=False means the session is gone: start over.
            self._session_id = ""
            self._last_seq = None
            raise WebSocketError("the session was dropped; starting over")

    def _beat(self, socket: WebSocket) -> None:
        socket.send(json.dumps({"op": OP_HEARTBEAT, "d": self._last_seq}))
