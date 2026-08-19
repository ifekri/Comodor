"""Server-sent events, the wire format every streaming LLM API speaks.

Built on :meth:`comodor.net.http.Response.iter_lines`, so it inherits that
client's timeouts, retries and TLS handling. The parser follows the WHATWG
event-stream rules: fields accumulate until a blank line dispatches the frame,
comment lines (starting with ``:``) are ignored, and a lone ``data`` value of
``[DONE]`` — the OpenAI convention — ends the stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from .http import Response

DONE_SENTINEL = "[DONE]"


@dataclass(slots=True)
class SSEEvent:
    """One dispatched frame."""

    event: str = "message"
    data: str = ""
    id: str = ""
    retry: int | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        return self.data.strip() == DONE_SENTINEL

    def json(self) -> Any | None:
        """Decode the payload, or ``None`` when it is not JSON.

        Providers occasionally interleave keep-alive or plain-text frames; a
        malformed one should be skipped, never crash a running generation.
        """
        payload = self.data.strip()
        if not payload or payload == DONE_SENTINEL:
            return None
        try:
            return json.loads(payload)
        except ValueError:
            return None


def iter_sse(response: Response, chunk_size: int = 8192) -> Iterator[SSEEvent]:
    """Yield frames from a streaming response until the server closes it."""
    event_type = "message"
    data_lines: list[str] = []
    event_id = ""
    retry: int | None = None
    extra: dict[str, str] = {}

    def flush() -> SSEEvent | None:
        nonlocal event_type, data_lines, retry, extra
        if not data_lines and not extra:
            event_type, data_lines, retry, extra = "message", [], None, {}
            return None
        frame = SSEEvent(
            event=event_type,
            data="\n".join(data_lines),
            id=event_id,
            retry=retry,
            raw_fields=extra,
        )
        event_type, data_lines, retry, extra = "message", [], None, {}
        return frame

    for line in response.iter_lines(chunk_size=chunk_size, decode_unicode=True):
        if line == "":                       # blank line dispatches the frame
            frame = flush()
            if frame is not None:
                yield frame
                if frame.is_done:
                    return
            continue
        if line.startswith(":"):             # comment / keep-alive
            continue

        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value

        if name == "data":
            data_lines.append(value)
        elif name == "event":
            event_type = value
        elif name == "id":
            event_id = value
        elif name == "retry":
            try:
                retry = int(value)
            except ValueError:
                pass
        else:
            extra[name] = value

    frame = flush()                           # stream ended without a blank line
    if frame is not None:
        yield frame


def iter_json(response: Response) -> Iterator[Any]:
    """Convenience: the decoded JSON payload of every frame that has one."""
    for frame in iter_sse(response):
        if frame.is_done:
            return
        payload = frame.json()
        if payload is not None:
            yield payload
