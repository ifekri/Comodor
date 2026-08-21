"""The OpenAI chat-completions dialect.

One adapter covers most of the market — OpenRouter, Xiaomi MiMo, DeepSeek,
Groq, Together, Ollama and LM Studio all speak this protocol and differ only in
base URL, headers and model names.

Streaming tool calls are the fiddly part: arguments arrive as JSON *fragments*
spread across many chunks and are addressed by an ``index``, not by id, so the
adapter reassembles them and emits each call only once it is complete.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from ..net import http
from ..net.sse import iter_sse
from . import registry
from .base import (
    AuthError,
    EventType,
    Message,
    ProviderError,
    RateLimited,
    Role,
    StreamEvent,
    ToolCall,
    ToolSpec,
    Usage,
    parse_arguments,
)


class OpenAICompatProvider:
    """Chat completions over SSE."""

    def __init__(self, name: str, base_url: str, api_key: str = "", model: str = "",
                 headers: dict[str, str] | None = None, timeout: float = 120.0,
                 label: str = "") -> None:
        self.name = name
        self.label = label or name.title()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_headers = dict(headers or {})
        self._session = http.Session(
            headers=self._default_headers(),
            timeout=http.Timeout(connect=15.0, read=timeout),
            # Streaming POSTs must never be replayed automatically: a retried
            # generation would bill twice and duplicate side effects.
            retry=http.Retry(total=2, allowed_methods=frozenset({"GET"})),
        )

    # -- wire helpers ----------------------------------------------------- #

    def _default_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.name == "openrouter":
            # OpenRouter attributes traffic with these; harmless elsewhere.
            headers["HTTP-Referer"] = "https://github.com/ifekri/comodor"
            headers["X-Title"] = "Comodor"
        headers.update(self.extra_headers)
        return headers

    @staticmethod
    def _content_blocks(message: Message) -> Any:
        """A plain string unless the turn carries images.

        The briefing leads, because it is context for what follows and because
        these providers cache by matching the longest identical prefix — the
        same reason it is not in the system prompt.
        """
        text = f"{message.briefing}\n\n{message.content}".strip() \
            if message.briefing else message.content
        if not message.images:
            return text
        blocks: list[dict[str, Any]] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for image in message.images:
            url = image if image.startswith("data:") else f"data:image/png;base64,{image}"
            blocks.append({"type": "image_url", "image_url": {"url": url}})
        return blocks

    def _encode_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        encoded: list[dict[str, Any]] = []
        for message in messages:
            if message.role is Role.TOOL:
                encoded.append({
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "(no output)",
                })
                # This dialect has no room for an image in a tool message, so a
                # screenshot follows as a user turn. It reads a little oddly in
                # a transcript and it is the only way the model gets to look.
                if message.images:
                    encoded.append({
                        "role": "user",
                        "content": [
                            {"type": "text",
                             "text": "The image from the tool call above:"},
                            *[{"type": "image_url", "image_url": {"url":
                               image if image.startswith("data:")
                               else f"data:image/png;base64,{image}"}}
                              for image in message.images],
                        ],
                    })
                continue

            entry: dict[str, Any] = {"role": message.role.value,
                                     "content": self._content_blocks(message)}
            if message.role is Role.ASSISTANT and message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments_json()},
                    }
                    for call in message.tool_calls
                ]
                # The API rejects a null content field alongside tool calls.
                entry["content"] = message.content or ""
            encoded.append(entry)
        return encoded

    def _raise_for_status(self, response: http.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json()
            message = (detail.get("error", {}).get("message")
                       if isinstance(detail.get("error"), dict) else None) or response.text[:400]
        except Exception:
            message = response.text[:400]

        status = response.status_code
        if status in (401, 403):
            raise AuthError(f"{self.label}: {message}", provider=self.name, status=status)
        if status == 429:
            raise RateLimited(f"{self.label}: {message}", provider=self.name,
                              retry_after=response.retry_after or 0.0)
        raise ProviderError(f"{self.label} [{status}]: {message}", status=status,
                            provider=self.name, retryable=status >= 500 or status == 408)

    # -- streaming -------------------------------------------------------- #

    def stream(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
               model: str = "", temperature: float = 0.3, max_tokens: int = 4096,
               **kwargs: Any) -> Iterator[StreamEvent]:
        target = model or self.model
        body: dict[str, Any] = {
            "model": target,
            "messages": self._encode_messages(messages),
            "stream": True,
            # Ask for a usage frame; providers that don't support it ignore it.
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        if registry.supports_sampling(target):
            body["temperature"] = temperature
        if tools:
            body["tools"] = [tool.to_openai() for tool in tools]
            body["tool_choice"] = kwargs.get("tool_choice", "auto")
        for key in ("top_p", "stop", "seed", "reasoning_effort", "response_format"):
            if key in kwargs and kwargs[key] is not None:
                body[key] = kwargs[key]

        try:
            response = self._session.post(
                f"{self.base_url}/chat/completions",
                json=body, stream=True,
                headers={"Accept": "text/event-stream"},
            )
        except http.RequestError as exc:
            raise ProviderError(f"{self.label}: {exc}", provider=self.name) from exc

        with response:
            self._raise_for_status(response)
            yield from self._parse_stream(response, target)

    def _parse_stream(self, response: http.Response, model: str) -> Iterator[StreamEvent]:
        # index -> partial call, because deltas identify calls positionally
        pending: dict[int, dict[str, str]] = {}
        finish_reason = ""
        usage_seen = False

        for frame in iter_sse(response):
            if frame.is_done:
                break
            payload = frame.json()
            if payload is None:
                continue
            if isinstance(payload, dict) and payload.get("error"):
                error = payload["error"]
                message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                raise ProviderError(f"{self.label}: {message}", provider=self.name)

            for choice in payload.get("choices", []) or []:
                delta = choice.get("delta") or {}

                text = delta.get("content")
                if isinstance(text, list):                 # some servers block-ify
                    text = "".join(part.get("text", "") for part in text
                                   if isinstance(part, dict))
                if text:
                    yield StreamEvent(type=EventType.TEXT, text=text)

                # DeepSeek/OpenRouter expose thinking under two different keys.
                reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                if reasoning:
                    yield StreamEvent(type=EventType.REASONING, text=str(reasoning))

                for fragment in delta.get("tool_calls") or []:
                    index = int(fragment.get("index", 0))
                    slot = pending.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if fragment.get("id"):
                        slot["id"] = fragment["id"]
                    function = fragment.get("function") or {}
                    if function.get("name"):
                        slot["name"] = function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

            usage = payload.get("usage")
            if usage:
                usage_seen = True
                yield StreamEvent(type=EventType.USAGE,
                                  usage=_usage_from(usage, model))

        for _, slot in sorted(pending.items()):
            if not slot["name"]:
                continue
            yield StreamEvent(
                type=EventType.TOOL_CALL,
                tool_call=ToolCall(
                    id=slot["id"] or ToolCall.new_id(),
                    name=slot["name"],
                    arguments=parse_arguments(slot["arguments"]),
                ),
            )

        if not usage_seen:
            # Without a usage frame the agent still needs *some* accounting;
            # the caller's estimator fills in from message text.
            yield StreamEvent(type=EventType.USAGE, usage=Usage())
        yield StreamEvent(type=EventType.DONE, finish_reason=finish_reason)

    # -- misc ------------------------------------------------------------- #

    def list_models(self) -> list[str]:
        try:
            response = self._session.get(f"{self.base_url}/models", timeout=(5.0, 20.0))
            self._raise_for_status(response)
            payload = response.json()
        except (http.RequestError, ProviderError, ValueError):
            return []
        entries = payload.get("data", payload) if isinstance(payload, dict) else payload
        models: list[str] = []
        for entry in entries or []:
            if isinstance(entry, dict) and entry.get("id"):
                models.append(str(entry["id"]))
            elif isinstance(entry, str):
                models.append(entry)
        return sorted(models)

    def close(self) -> None:
        self._session.close()


def _usage_from(raw: dict[str, Any], model: str) -> Usage:
    input_tokens = int(raw.get("prompt_tokens") or raw.get("input_tokens") or 0)
    output_tokens = int(raw.get("completion_tokens") or raw.get("output_tokens") or 0)
    details = raw.get("prompt_tokens_details") or {}
    # Unlike Anthropic, this dialect counts the cached prefix *inside*
    # `prompt_tokens`, so the plainly billed part is the difference.
    cached = int(details.get("cached_tokens") or 0)
    input_tokens = max(0, input_tokens - cached)
    completion_details = raw.get("completion_tokens_details") or {}
    reasoning = int(completion_details.get("reasoning_tokens") or 0)
    cost = raw.get("cost")
    if cost is None:
        cost = registry.estimate_cost(model, input_tokens, output_tokens, cached)
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached,
        reasoning_tokens=reasoning,
        cost_usd=float(cost) if cost is not None else 0.0,
    )


def dump_request(messages: list[Message], tools: list[ToolSpec] | None = None) -> str:
    """Debug helper: the JSON body we would send, minus credentials."""
    provider = OpenAICompatProvider("debug", "http://localhost", model="debug")
    return json.dumps({
        "messages": provider._encode_messages(messages),
        "tools": [tool.to_openai() for tool in tools or []],
    }, indent=2, ensure_ascii=False)
