"""Where a wire message becomes an operation.

Three responsibilities and no more:

**The handshake.** `client.hello` first, and every other method refused until
it succeeds. A client that speaks a version this core does not is told so at
the first message rather than allowed to run until something malformed reaches
it — which is the failure mode a version field exists to prevent and does not
prevent on its own.

**Dispatch.** A method name to a `CoreService` verb, with the parameters
checked against the schema's shape first. The check is what turns a missing
field into `invalid_params` naming it, rather than a `KeyError` from inside
the application.

**Relay.** The service reports events as `(session_id, name, params)`; this
puts them in an envelope and writes a line. Events are emitted from turn
threads, which is why the channel locks its writes.

The service does not know this file exists. Swap the channel for a socket and
the same verbs answer.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .. import protocol as P
from ..application import CoreService, Refused, UnknownRequest, UnknownSession
from .jsonl import Channel

__all__ = ["Server"]


class Server:
    """One client, attached to one core."""

    def __init__(self, service: CoreService, channel: Channel, *,
                 name: str = "comodor-core", version: str = "") -> None:
        self.service = service
        self.channel = channel
        self.name = name
        self.version = version or _version()
        self.initialized = False
        self.client: dict[str, Any] = {}
        self.client_capabilities: tuple[str, ...] = ()
        self.running = False
        # Events raised *by* a call, held until that call has been answered.
        # See `_event`.
        self._deferred: threading.local = threading.local()
        service.on_event = self._event

    # -- the loop ---------------------------------------------------------- #

    def serve(self) -> None:
        self.running = True
        try:
            for line in self.channel.lines():
                if not self.running:
                    break
                self._handle(line)
        finally:
            self.running = False
            self.service.close()

    def _handle(self, line: str) -> None:
        try:
            message = P.decode(line)
        except P.ProtocolError as problem:
            # No id to answer against — the line could not be read far enough
            # to have one. `null` is honest about that.
            self.channel.send(problem.envelope(None))
            return

        if message.type != "request":
            # A core answers requests and sends events. A response or an event
            # arriving here means the other end is confused about which side
            # it is, and silently dropping it would hide that.
            self.channel.send(P.error(
                message.id, P.INVALID_ENVELOPE,
                f"a core does not accept a {message.type}"))
            return

        # Events raised *while* the call runs are held so that the answer goes
        # out first. Without this a client correlating on the request id is
        # told about a session before it is told it created one — and an
        # ordering that happens to work is not one a second client can be
        # written against.
        self._deferred.queue = []
        answer = self._answer(message)
        self.channel.send(answer)
        # After the answer, in the order they were raised.
        self._flush()
        if answer["type"] == "response" and message.method == "shutdown":
            self.running = False
            self.channel.close()

    def _answer(self, message: P.Message) -> dict[str, Any]:
        """The envelope to send back: a result, or the failure as an error.

        One function that turns every outcome into an envelope, so `_handle`
        has a single exit. As six early returns it needed six flushes, and the
        one eventually forgotten would have reordered events for exactly one
        error case — the kind of bug that is found by a client, not by a test.
        """
        try:
            return P.response(message.id, self._dispatch(message.method,
                                                         message.params))
        except P.ProtocolError as problem:
            return problem.envelope(message.id)
        except UnknownSession as missing:
            return P.error(message.id, P.UNKNOWN_SESSION,
                           f"no session {missing.args[0]!r}")
        except UnknownRequest as missing:
            return P.error(message.id, P.UNKNOWN_REQUEST,
                           f"nothing is waiting under {missing.args[0]!r}")
        except Refused as refusal:
            return P.error(message.id, P.NOT_ALLOWED, str(refusal))
        except Exception as fault:  # pragma: no cover - defensive
            # The message is safe to show; the traceback is for whoever is
            # reading stderr, and must not travel to a client.
            self.channel.warn(f"internal error in {message.method}: {fault!r}")
            return P.error(message.id, P.INTERNAL_ERROR,
                           "the core could not complete that")

    # -- dispatch ---------------------------------------------------------- #

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in P.METHODS:
            raise P.ProtocolError(P.UNKNOWN_METHOD, f"no method named {method!r}")

        if method == "client.hello":
            if self.initialized:
                raise P.ProtocolError(P.ALREADY_INITIALIZED,
                                      "the handshake has already happened")
            return self._hello(params)

        if not self.initialized:
            raise P.ProtocolError(
                P.NOT_INITIALIZED,
                "send client.hello before anything else")

        P.validate(P.params_shape(method), params)
        handler = self._handlers()[method]
        return handler(params)

    def _hello(self, params: dict[str, Any]) -> dict[str, Any]:
        P.validate("HelloParams", params)
        asked = params.get("protocol_version")
        if asked != P.PROTOCOL_VERSION:
            raise P.ProtocolError(
                P.UNSUPPORTED_VERSION,
                f"this core speaks protocol {P.PROTOCOL_VERSION}, "
                f"and the client asked for {asked!r}",
                {"supported": [P.PROTOCOL_VERSION]})

        client = params.get("client") or {}
        P.validate("PeerInfo", client)
        self.client = dict(client)
        # Only names this core knows are kept. An unknown capability is
        # ignored rather than refused, so a newer client can announce
        # something this core has never heard of and still connect.
        offered = params.get("capabilities") or []
        self.client_capabilities = tuple(
            name for name in offered if name in P.CLIENT_CAPABILITIES)
        self.initialized = True
        return {
            "protocol_version": P.PROTOCOL_VERSION,
            "core": {"name": self.name, "version": self.version},
            "capabilities": list(P.CORE_CAPABILITIES),
        }

    def _handlers(self) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
        service = self.service
        return {
            "session.create": lambda p: {
                "session": service.create_session(
                    workspace=str(p.get("workspace", "")),
                    mode=str(p.get("mode", "")))},
            "session.get": lambda p: {
                "session": service.get_session(p["session_id"])},
            "session.list": lambda p: {"sessions": service.list_sessions()},
            "session.send": lambda p: service.send(p["session_id"], p["text"]),
            "session.cancel": lambda p: service.cancel(p["session_id"]),
            "session.set_mode": lambda p: {
                "session": service.set_mode(p["session_id"], p["mode"])},
            "model.get": lambda p: service.model(),
            "model.set": lambda p: service.set_model(
                p["model"], str(p.get("provider", ""))),
            "workspace.get": lambda p: service.workspace(),
            "question.answer": lambda p: service.answer_question(
                p["id"], list(p.get("selected") or []),
                str(p.get("custom", "")), bool(p.get("cancelled", False))),
            "permission.reply": lambda p: service.reply_permission(
                p["id"], p["choice"]),
            "shutdown": lambda p: {"ok": True},
        }

    # -- events ------------------------------------------------------------ #

    def _event(self, session_id: str, name: str, params: dict[str, Any]) -> None:
        """One protocol event: onto the wire, or into this call's queue.

        Events before the handshake are dropped: a client that has not said
        hello has not agreed a version, and sending it a v1 envelope would be
        answering a question nobody asked.

        An event raised on the thread that is answering a request waits for
        that answer. Events from a turn's worker thread find no queue and go
        straight out, which is what makes streaming arrive as it happens
        rather than in a batch at the end.
        """
        if not self.initialized or self.channel.closed:
            return
        queue = getattr(self._deferred, "queue", None)
        if queue is not None:
            queue.append((name, params))
            return
        self._send_event(name, params)

    def _flush(self) -> None:
        """Release the events this call raised, in the order it raised them."""
        queue = getattr(self._deferred, "queue", None)
        self._deferred.queue = None
        for name, params in queue or ():
            self._send_event(name, params)

    def _send_event(self, name: str, params: dict[str, Any]) -> None:
        try:
            self.channel.send(P.event(name, params))
        except ValueError as problem:
            # An event name the schema does not have. A bug here would
            # otherwise be invisible — the client simply never sees it.
            self.channel.warn(f"refusing to send {name!r}: {problem}")


def _version() -> str:
    try:
        from .. import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - a source checkout without a tag
        return "0"
