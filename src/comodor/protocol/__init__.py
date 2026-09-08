"""What Comodor Core and a Comodor client say to each other.

The agent was never the interface. It already runs behind an event bus that a
terminal, a browser and an editor each subscribe to in their own way — this
adds a fourth subscriber that speaks a wire format, so a client can be written
in another language and another process without any of them being special.

Three properties are the whole point:

**One definition.** `schemas/protocol/v1.json` is the source of truth. The
Python types here and the TypeScript types in `packages/protocol` are both
generated from it by `tools/protocol-codegen.py`, and a test regenerates both
and fails on a difference. Nobody edits a type by hand, so the two sides
cannot drift apart quietly.

**Transport-independent.** Nothing in this module knows about a pipe. The
envelope is a dict; turning it into bytes is `comodor.transport`'s job. A
future socket or WebSocket is a different transport around the same messages,
not a different protocol.

**Versioned from the first release.** Every envelope carries `version`, and
the handshake refuses a version this core does not speak rather than letting a
mismatched client run until something malformed reaches it.

Only stdlib. Comodor installs one dependency and this does not add a second.
"""

from __future__ import annotations

import json
from typing import Any

from ._generated import (
    ALREADY_INITIALIZED,
    CLIENT_CAPABILITIES,
    CORE_CAPABILITIES,
    ENVELOPE_FIELDS,
    ERRORS,
    EVENT_SHAPES,
    EVENTS,
    INTERNAL_ERROR,
    INVALID_ENVELOPE,
    INVALID_PARAMS,
    METHOD_SHAPES,
    METHODS,
    MODES,
    NOT_ALLOWED,
    NOT_INITIALIZED,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    SHAPES,
    UNKNOWN_METHOD,
    UNKNOWN_REQUEST,
    UNKNOWN_SESSION,
    UNSUPPORTED_VERSION,
)

__all__ = [
    "PROTOCOL_VERSION", "METHODS", "EVENTS", "MODES", "ERRORS",
    "CORE_CAPABILITIES", "CLIENT_CAPABILITIES",
    "ProtocolError", "Message",
    "request", "response", "error", "event",
    "decode", "validate",
    "PARSE_ERROR", "INVALID_ENVELOPE", "UNSUPPORTED_VERSION", "NOT_INITIALIZED",
    "ALREADY_INITIALIZED", "UNKNOWN_METHOD", "INVALID_PARAMS", "UNKNOWN_SESSION",
    "UNKNOWN_REQUEST", "NOT_ALLOWED", "INTERNAL_ERROR",
]


class ProtocolError(Exception):
    """A refusal with a code the other side can branch on.

    The message is written to be shown to a person; anything that would only
    help somebody debugging the core belongs on stderr, not in `data`.
    """

    def __init__(self, code: str, message: str = "",
                 data: dict[str, Any] | None = None) -> None:
        super().__init__(message or ERRORS.get(code, code))
        self.code = code
        self.message = message or ERRORS.get(code, code)
        self.data = data or {}

    def envelope(self, id: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data:
            body["data"] = self.data
        return {"version": PROTOCOL_VERSION, "type": "error", "id": id,
                "error": body}


class Message:
    """One decoded envelope.

    A small class rather than four, because every consumer immediately asks
    `which kind is this` and a hierarchy would make that an isinstance ladder
    without making any of the four carry different behaviour.
    """

    __slots__ = ("type", "id", "method", "params", "result", "error")

    def __init__(self, type: str, id: str | None = None, method: str = "",
                 params: dict[str, Any] | None = None,
                 result: dict[str, Any] | None = None,
                 error: dict[str, Any] | None = None) -> None:
        self.type = type
        self.id = id
        self.method = method
        self.params = params if params is not None else {}
        self.result = result if result is not None else {}
        self.error = error if error is not None else {}

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        what = self.method or self.params.get("__event__", "")
        return f"<Message {self.type} {what or self.id!r}>"


# --------------------------------------------------------------------------- #
# building
# --------------------------------------------------------------------------- #

def request(id: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "type": "request", "id": id,
            "method": method, "params": params or {}}


def response(id: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "type": "response", "id": id,
            "result": result or {}}


def error(id: str | None, code: str, message: str = "",
          data: dict[str, Any] | None = None) -> dict[str, Any]:
    return ProtocolError(code, message, data).envelope(id)


def event(name: str, params: dict[str, Any] | None = None,
          seq: int = 0) -> dict[str, Any]:
    """One event, and its place in its session's sequence.

    `seq` is what lets a snapshot and a live stream be reconciled: a snapshot
    says which number it includes up to, and the client applies what is above
    it. It is on the envelope rather than in every payload because ordering is
    a property of the connection, not of any one message.
    """
    if name not in EVENTS:
        # A typo in an event name is otherwise invisible: the client simply
        # never sees the event and the core looks like it hung.
        raise ValueError(f"unknown event {name!r}")
    return {"version": PROTOCOL_VERSION, "type": "event", "event": name,
            "seq": seq, "params": params or {}}


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #

def decode(line: str) -> Message:
    """One line of wire text into a `Message`, or `ProtocolError`.

    Raises rather than returning a sentinel, because every caller has to do
    something different about a malformed line — a server answers with an
    error envelope, a client logs and keeps reading — and a sentinel makes
    forgetting to check the default.
    """
    try:
        raw = json.loads(line)
    except (ValueError, TypeError) as problem:
        raise ProtocolError(PARSE_ERROR, f"not JSON: {problem}") from None

    if not isinstance(raw, dict):
        raise ProtocolError(PARSE_ERROR, "top level is not an object")

    version = raw.get("version")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(
            UNSUPPORTED_VERSION,
            f"this core speaks protocol {PROTOCOL_VERSION}, not {version!r}")

    kind = raw.get("type")
    if kind not in ENVELOPE_FIELDS:
        raise ProtocolError(INVALID_ENVELOPE, f"unknown envelope type {kind!r}")

    missing = [name for name in ENVELOPE_FIELDS[kind] if name not in raw]
    if missing:
        raise ProtocolError(
            INVALID_ENVELOPE,
            f"{kind} is missing {', '.join(missing)}")

    if kind == "request":
        method = raw["method"]
        if not isinstance(method, str):
            raise ProtocolError(INVALID_ENVELOPE, "method must be a string")
        params = raw["params"]
        if not isinstance(params, dict):
            raise ProtocolError(INVALID_ENVELOPE, "params must be an object")
        return Message("request", id=_identifier(raw["id"]), method=method,
                       params=params)

    if kind == "response":
        result = raw["result"]
        if not isinstance(result, dict):
            raise ProtocolError(INVALID_ENVELOPE, "result must be an object")
        return Message("response", id=_identifier(raw["id"]), result=result)

    if kind == "error":
        body = raw["error"]
        if not isinstance(body, dict) or "code" not in body:
            raise ProtocolError(INVALID_ENVELOPE, "error must carry a code")
        identifier = None if raw["id"] is None else _identifier(raw["id"])
        return Message("error", id=identifier, error=body)

    name = raw["event"]
    params = raw["params"]
    if not isinstance(params, dict):
        raise ProtocolError(INVALID_ENVELOPE, "params must be an object")
    return Message("event", method=name, params=params)


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(INVALID_ENVELOPE, "id must be a non-empty string")
    return value


# --------------------------------------------------------------------------- #
# validating
# --------------------------------------------------------------------------- #

_PYTHON_TYPES: dict[str, Any] = {
    "str": str, "int": int, "float": (int, float), "bool": bool,
    "list": list, "dict": dict,
}


def validate(shape: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Check a payload against a named shape from the schema.

    Deliberately shallow: required keys present, and each present key of the
    right JSON type. It is not a JSON Schema engine, and it is not trying to
    be — a full validator would be a dependency, and the deep structure it
    would check is checked by the code that reads it anyway.

    What this does catch is the class of mistake that is otherwise silent: a
    field missing, a number where a string belongs, an array sent as a bare
    value. Those turn into an `invalid_params` refusal naming the field
    instead of a `KeyError` twelve frames later.
    """
    fields = SHAPES.get(shape)
    if fields is None:
        raise ProtocolError(INTERNAL_ERROR, f"no shape named {shape!r}")

    for name, (kind, required) in fields.items():
        if name not in payload:
            if required:
                raise ProtocolError(INVALID_PARAMS, f"{shape}: {name} is required")
            continue
        expected = _PYTHON_TYPES.get(kind)
        if expected is None:
            # A nested named shape. Check it is an object and leave the
            # depth to whoever consumes it.
            if not isinstance(payload[name], dict):
                raise ProtocolError(INVALID_PARAMS,
                                    f"{shape}: {name} must be an object")
            continue
        # `bool` is an `int` in Python and would slip through a number check,
        # which is how a `true` ends up stored as a count.
        value = payload[name]
        if expected is not bool and isinstance(value, bool):
            raise ProtocolError(INVALID_PARAMS,
                                f"{shape}: {name} must be {kind}, not a boolean")
        if not isinstance(value, expected):
            raise ProtocolError(INVALID_PARAMS,
                                f"{shape}: {name} must be {kind}")
    return payload


def params_shape(method: str) -> str:
    if method not in METHOD_SHAPES:
        raise ProtocolError(UNKNOWN_METHOD, f"no method named {method!r}")
    return METHOD_SHAPES[method][0]


def event_shape(name: str) -> str:
    return EVENT_SHAPES[name]
