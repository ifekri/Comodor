"""JSON-RPC 2.0 over a pipe, the way ACP frames it.

One message per line, UTF-8, no embedded newlines. That is the whole framing —
no Content-Length headers, no length prefixes — which makes this small and
makes the one rule that matters absolute: **nothing but ACP messages may ever
reach stdout**. An editor parses every line it gets; a stray `print` is a
protocol error, and a banner is several.

So stdout is taken away from the rest of the program the moment a connection
starts, and handed to this. Anything else that writes goes to stderr, which
the specification sets aside for exactly that.

Three things this handles that a naive reader does not:

**Batches.** JSON-RPC allows an array of requests, and ACP inherits the rules
including the awkward ones: an empty array is an error, a batch of
notifications gets no reply at all, and a batch that is partly invalid still
answers the parts that were not.

**Requests in both directions.** The agent asks the client for permission
while the client is asking the agent for a turn, so this cannot be a loop that
reads a request and writes a response. Outgoing calls carry their own ids and
wait on their own events.

**A write from any thread.** Tool output arrives on a worker; the reader runs
on the main thread. One lock around the write, and a message is never
interleaved with another.
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

#: The codes JSON-RPC reserves, and the one ACP adds for "you have not logged
#: in yet", which a client is expected to recognise and act on.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
AUTH_REQUIRED = -32000

#: How long an outgoing request waits before giving up. Long, because the
#: thing on the other end is a person deciding whether to allow a command.
CALL_TIMEOUT = 600.0


class RpcError(Exception):
    """An error to send back as a JSON-RPC error object."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


@dataclass
class Pending:
    """An outgoing request waiting for its answer."""

    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: dict[str, Any] | None = None


class Connection:
    """One ACP connection: reads a pipe, writes a pipe, dispatches by name."""

    def __init__(self, reader: TextIO | None = None, writer: TextIO | None = None,
                 log: TextIO | None = None) -> None:
        self.reader = reader if reader is not None else sys.stdin
        self.writer = writer if writer is not None else sys.stdout
        self.log = log if log is not None else sys.stderr
        #: Method name to handler. A handler returning None answers `{}`.
        self.methods: dict[str, Callable[[dict[str, Any]], Any]] = {}
        #: Notifications have no reply, so a missing one is ignored rather
        #: than being an error — that is what the specification asks for.
        self.notifications: dict[str, Callable[[dict[str, Any]], None]] = {}

        self._write_lock = threading.Lock()
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._waiting: dict[Any, Pending] = {}
        self._stop = threading.Event()

    # -- writing ----------------------------------------------------------- #

    def _send(self, message: dict[str, Any] | list[Any]) -> None:
        """One line, one message, never interleaved with another.

        Tool output arrives on a worker thread while the reader is on the main
        one, so two writes can meet. Half of one message inside another is a
        parse error at the far end and the end of the session.
        """
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        # The framing forbids embedded newlines, and `json.dumps` escapes any
        # that appear in strings — so this only guards against a caller
        # handing us something already serialised.
        line = line.replace("\n", " ").replace("\r", " ")
        with self._write_lock:
            try:
                self.writer.write(line + "\n")
                self.writer.flush()
            except (BrokenPipeError, ValueError):
                # The editor went away. Nothing to report it to.
                self._stop.set()

    def notify(self, method: str, params: Any = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def call(self, method: str, params: Any = None,
             timeout: float | None = None) -> Any:
        """Ask the client something and wait for the answer.

        Used for permission, which means the wait is a person reading a
        prompt. Raises :class:`RpcError` when the client answers with one, and
        on a timeout — a caller that cannot tell "refused" from "never
        answered" would treat a dead editor as a denial and carry on.
        """
        # Read now, not when this function was defined: a default argument
        # freezes the constant at import, and then the constant is a number
        # nobody can change.
        if timeout is None:
            timeout = CALL_TIMEOUT
        with self._id_lock:
            self._next_id += 1
            request_id = self._next_id
        pending = Pending()
        self._waiting[request_id] = pending

        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id,
                                   "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

        try:
            if not pending.event.wait(timeout):
                raise RpcError(INTERNAL_ERROR,
                               f"{method} was not answered in {timeout:.0f}s")
            if pending.error is not None:
                raise RpcError(int(pending.error.get("code", INTERNAL_ERROR)),
                               str(pending.error.get("message", "the client refused")),
                               pending.error.get("data"))
            return pending.result
        finally:
            self._waiting.pop(request_id, None)

    # -- reading ------------------------------------------------------------ #

    def serve(self) -> None:
        """Read until the pipe closes. Returns when the client goes away."""
        while not self._stop.is_set():
            try:
                line = self.reader.readline()
            except (KeyboardInterrupt, ValueError):
                break
            if line == "":
                break                       # stdin closed: the session is over
            line = line.strip()
            if not line:
                continue
            self._handle_line(line)

    def stop(self) -> None:
        self._stop.set()

    def _handle_line(self, line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            self._send({"jsonrpc": "2.0", "id": None,
                        "error": RpcError(PARSE_ERROR, "invalid JSON").as_dict()})
            return

        if isinstance(message, list):
            self._handle_batch(message)
            return
        if not isinstance(message, dict):
            self._send({"jsonrpc": "2.0", "id": None,
                        "error": RpcError(INVALID_REQUEST,
                                          "expected an object or an array").as_dict()})
            return

        reply = self._handle_one(message)
        if reply is not None:
            self._send(reply)

    def _handle_batch(self, batch: list[Any]) -> None:
        if not batch:
            self._send({"jsonrpc": "2.0", "id": None,
                        "error": RpcError(INVALID_REQUEST,
                                          "an empty batch is not a request").as_dict()})
            return

        replies: list[dict[str, Any]] = []
        for message in batch:
            if not isinstance(message, dict):
                replies.append({"jsonrpc": "2.0", "id": None,
                                "error": RpcError(INVALID_REQUEST,
                                                  "not an object").as_dict()})
                continue
            reply = self._handle_one(message)
            if reply is not None:
                replies.append(reply)
        # A batch of notifications gets nothing back, not an empty array.
        if replies:
            self._send(replies)

    def _handle_one(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Dispatch one object. Returns what to send, or None for silence."""
        # A response to something *we* asked, rather than a request to us.
        if "method" not in message and ("result" in message or "error" in message):
            self._settle(message)
            return None

        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params")
        if params is None:
            params = {}
        if not isinstance(method, str) or not isinstance(params, (dict, list)):
            if request_id is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": RpcError(INVALID_REQUEST,
                                      "malformed request").as_dict()}
        if isinstance(params, list):
            # ACP uses named parameters everywhere; positional ones are valid
            # JSON-RPC and meaningless here.
            return None if request_id is None else {
                "jsonrpc": "2.0", "id": request_id,
                "error": RpcError(INVALID_PARAMS,
                                  "this protocol uses named parameters").as_dict()}

        if request_id is None:
            handler = self.notifications.get(method)
            if handler is not None:
                try:
                    handler(params)
                except Exception as error:            # a notification cannot fail
                    self.warn(f"{method}: {type(error).__name__}: {error}")
            return None

        handler = self.methods.get(method)
        if handler is None:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": RpcError(METHOD_NOT_FOUND,
                                      f"no method named {method!r}").as_dict()}
        try:
            result = handler(params)
        except RpcError as error:
            return {"jsonrpc": "2.0", "id": request_id, "error": error.as_dict()}
        except Exception as error:
            self.warn(f"{method}: {type(error).__name__}: {error}")
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": RpcError(INTERNAL_ERROR,
                                      f"{type(error).__name__}: {error}").as_dict()}
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {} if result is None else result}

    def _settle(self, message: dict[str, Any]) -> None:
        pending = self._waiting.get(message.get("id"))
        if pending is None:
            return                          # answered twice, or already gone
        if "error" in message and isinstance(message["error"], dict):
            pending.error = message["error"]
        else:
            pending.result = message.get("result")
        pending.event.set()

    # -- saying something that is not a message ----------------------------- #

    def warn(self, text: str) -> None:
        """To stderr, which is the only place a log may go.

        The specification sets stderr aside for this and forbids anything on
        stdout that is not a message. A `print` in the wrong place is a parse
        error at the far end, so there is exactly one way to say anything.
        """
        try:
            self.log.write(text.rstrip() + "\n")
            self.log.flush()
        except Exception:
            pass
