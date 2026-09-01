"""OpenAI's request and response shapes, mapped onto Comodor's.

Two translations live here. The incoming one is forgiving — the ecosystem's
clients disagree about optional fields, and a field that can be ignored
should be, loudly, rather than failing the request. The outgoing one is
exact: a client that reads ``choices[0].message.content`` must find the
answer there, and a client that reads ``usage`` must find numbers, whatever
the agent did to produce either.

Nothing from the agent's interior leaks by accident. Tool calls, reasoning
and permission prompts are the loop's business; the client asked a question
and gets the answer. ``comodor.allow_tools`` is the one door out, and even
it returns an *unfinished* turn with the pending calls attached — never the
transcript of the loop's own tool traffic.
"""

from __future__ import annotations

from typing import Any

#: Models advertised by ``GET /v1/models``. The agent is one intelligence
#: behind one endpoint; the id is what the client sends back in ``model``,
#: and it is accepted whatever it says, because refusing a name the user
#: typed into their frontend would teach them nothing except to leave.
MODEL_ID = "comodor"


class BadRequest(ValueError):
    """A request that could not be read as OpenAI-shaped at all."""


def messages_from(payload: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """The request's conversation as ``(the last user message, prior turns)``.

    OpenAI clients send the whole history every time, and they are right to:
    the protocol has no memory. Comodor's session continuity is optional and
    explicit, so the default mapping is: the newest ``user`` message is the
    task, and everything before it is summarised into the prompt as context
    — joined, not sent to the model as a transcript to re-read, because the
    agent's own recall already decides what of a conversation matters.

    A client that wants real continuity sends ``X-Comodor-Session`` and gets
    the agent's own history instead, in which case prior turns are ignored
    — sending both would answer from a transcript twice.
    """
    raw = payload.get("messages")
    if not isinstance(raw, list) or not raw:
        raise BadRequest("messages must be a non-empty list")

    # The task is the *last* user message — clients send history oldest
    # first, and the newest thing they said is the thing being asked.
    last_user = max(i for i, item in enumerate(raw)
                    if isinstance(item, dict)
                    and str(item.get("role") or "") == "user") \
        if any(isinstance(item, dict) and str(item.get("role") or "") == "user"
               for item in raw) else -1
    if last_user < 0:
        raise BadRequest("no user message to answer")

    prior: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BadRequest("every message must be an object")
        if index == last_user:
            continue
        role = str(item.get("role") or "")
        content = _content_of(item.get("content"))
        if role == "system":
            prior.append({"role": "system", "text": content})
        elif role in ("user", "assistant"):
            # Only turns *before* the task are prior; the task is the one
            # being answered. An assistant message carrying client-side
            # tool calls is refused rather than ignored: answering a tool
            # result the loop never made would be inventing history.
            if role == "assistant" and item.get("tool_calls"):
                raise BadRequest(
                    "tool_calls in the client's history cannot be continued "
                    "here — send what you meant as a user message")
            if content:
                prior.append({"role": role, "text": content})
        elif role == "tool":
            raise BadRequest(
                "tool messages belong to a loop this server runs itself; "
                "send what you meant as a user message")
        # Unknown roles (``developer``, ``function`` on old clients) are
        # carried as user text when they carry text at all.
        elif role and content:
            prior.append({"role": "user", "text": content})

    return _content_of(raw[last_user].get("content")), prior


def _content_of(content: Any) -> str:
    """Text out of a content field, in either of its two shapes.

    A string is the common case. The array form is what multimodal clients
    send; text parts are joined, and image parts are named rather than
    decoded — this endpoint takes the loop's word for what a picture is
    worth, and a client that needs vision through the API is not served by
    a silent drop of their image into a text answer.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                parts.append("[an image was sent — this endpoint answers text]")
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return str(content)




def chunk(created: float, model: str, request_id: str, *,
          delta: dict[str, Any] | None = None,
          finish: str | None = None) -> dict[str, Any]:
    """One streaming chunk, in the exact shape OpenAI clients parse."""
    piece: dict[str, Any] = {"role": "assistant"}
    if delta:
        piece.update(delta)
    return {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(created),
        "model": model,
        "choices": [{"index": 0, "delta": piece, "finish_reason": finish}],
    }


def final(created: float, model: str, request_id: str, text: str,
          usage: dict[str, Any], finish: str, *,
          tool_calls: list[dict[str, Any]] | None = None,
          extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The non-streaming response, or the last streamed one's meaning."""
    message: dict[str, Any] = {"role": "assistant", "content": text or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = text or None
    payload = {
        "id": request_id,
        "object": "chat.completion",
        "created": int(created),
        "model": model,
        "choices": [{"index": 0, "message": message,
                     "finish_reason": finish}],
        "usage": usage,
    }
    if extra:
        payload.update(extra)
    return payload


def usage_of(result: Any) -> dict[str, Any]:
    """The turn's token accounting, as OpenAI names it."""
    usage = getattr(result, "usage", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total", 0) or 0,
    }


def models_listing() -> dict[str, Any]:
    """The one model, named the way the endpoint is named after."""
    return {
        "object": "list",
        "data": [{
            "id": MODEL_ID,
            "object": "model",
            "created": 0,
            "owned_by": "comodor",
        }],
    }


def error_body(message: str, kind: str = "invalid_request_error") -> dict[str, Any]:
    """Errors in OpenAI's error envelope, so a client can show them."""
    return {"error": {"message": message, "type": kind, "param": None,
                      "code": kind}}
