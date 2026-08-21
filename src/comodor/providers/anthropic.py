"""The native Anthropic Messages API.

Three things differ from the OpenAI dialect and each one is a real bug if you
get it wrong:

* ``system`` is a top-level field, not a message with a system role;
* tool results are ``tool_result`` blocks inside a **user** message, and all
  results from one round of parallel calls must travel in a *single* message —
  splitting them teaches the model to stop calling tools in parallel;
* sampling parameters were removed on the Claude 4.6+ family, so sending
  ``temperature`` to those models returns a 400.
"""

from __future__ import annotations

from typing import Any, Iterator

from ..net import http
from ..net.sse import iter_sse
from . import caching, registry
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

API_VERSION = "2023-06-01"


class AnthropicProvider:
    """Streaming Messages API client."""

    def __init__(self, name: str = "anthropic", base_url: str = "https://api.anthropic.com/v1",
                 api_key: str = "", model: str = "claude-sonnet-4-5",
                 headers: dict[str, str] | None = None, timeout: float = 120.0,
                 label: str = "Anthropic") -> None:
        self.name = name
        self.label = label
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.extra_headers = dict(headers or {})
        self._session = http.Session(
            headers=self._default_headers(),
            timeout=http.Timeout(connect=15.0, read=timeout),
            retry=http.Retry(total=2, allowed_methods=frozenset({"GET"})),
        )

    def _default_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "anthropic-version": API_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        headers.update(self.extra_headers)
        return headers

    # -- encoding --------------------------------------------------------- #

    def _encode(self, messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        """Split off the system prompt and build the message array."""
        system_parts: list[str] = []
        encoded: list[dict[str, Any]] = []

        for message in messages:
            if message.role is Role.SYSTEM:
                system_parts.append(message.content)
                continue

            if message.role is Role.TOOL:
                block = {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.content or "(no output)",
                }
                if message.is_error:
                    block["is_error"] = True
                # Merge into the previous user turn when it is also results, so
                # one round of parallel calls stays one message.
                if (encoded and encoded[-1]["role"] == "user"
                        and isinstance(encoded[-1]["content"], list)
                        and all(part.get("type") == "tool_result"
                                for part in encoded[-1]["content"])):
                    encoded[-1]["content"].append(block)
                else:
                    encoded.append({"role": "user", "content": [block]})
                continue

            blocks: list[dict[str, Any]] = []
            if message.briefing:
                blocks.append({"type": "text", "text": message.briefing})
            for image in message.images:
                data = image.split(",", 1)[-1] if image.startswith("data:") else image
                blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": data},
                })
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append({
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.arguments,
                })
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            encoded.append({"role": message.role.value, "content": blocks})

        return "\n\n".join(part for part in system_parts if part), encoded

    def _cache(self, body: dict[str, Any], *, ttl: str = "5m",
               model: str = "") -> None:
        """Mark the parts of this request the provider has already seen.

        Every message before the last is byte-identical to the request that
        preceded this one — the conversation only ever grows at the end — so
        everything up to the final mark is a cache read at a tenth of the price.
        What that leaves at full price is exactly the new material: the tool
        result that caused this request to be made.
        """
        head = caching.weigh(body.get("system")) + caching.weigh(body.get("tools"))
        sizes = [caching.weigh(message) for message in body.get("messages") or []]
        marks = caching.plan(head, sizes,
                             minimum=caching.floor_for(model or self.model))
        if not marks:
            return
        caching.apply(body, marks, ttl=ttl)
        if ttl != "5m":
            # Holding a prefix for longer than the default hour is gated behind
            # an opt-in header; without it the request is rejected outright.
            self.extra_headers["anthropic-beta"] = caching.LONG_TTL_BETA
            self._session.headers.update(
                {"anthropic-beta": caching.LONG_TTL_BETA})

    def _raise_for_status(self, response: http.Response) -> None:
        if response.ok:
            return
        try:
            detail = response.json()
            message = detail.get("error", {}).get("message") or response.text[:400]
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
        system, encoded = self._encode(messages)

        body: dict[str, Any] = {
            "model": target,
            "max_tokens": min(max_tokens, registry.lookup(target).max_output),
            "messages": encoded,
            "stream": True,
        }
        if system:
            body["system"] = system
        if registry.supports_sampling(target):
            body["temperature"] = temperature
        if tools:
            body["tools"] = [tool.to_anthropic() for tool in tools]
        if kwargs.get("thinking"):
            # Adaptive is the only supported on-mode for current models, and a
            # summarised display is what makes a thinking panel possible.
            body["thinking"] = {"type": "adaptive", "display": "summarized"}
        if kwargs.get("effort"):
            body["output_config"] = {"effort": kwargs["effort"]}
        if kwargs.get("cache", True):
            self._cache(body, ttl=str(kwargs.get("cache_ttl") or "5m"),
                        model=target)

        with self._post(body) as response:
            yield from self._parse_stream(response, target)

    def _post(self, body: dict[str, Any]) -> http.Response:
        """Send the request, giving up the discount rather than the answer.

        Not every endpoint speaking this protocol is Anthropic's — proxies and
        self-hosted gateways use it too, and one that does not understand
        ``cache_control`` rejects the whole request. A cheaper prompt is not
        worth a broken agent, so a refusal that names the field costs the
        session its caching and nothing else.
        """
        try:
            response = self._session.post(f"{self.base_url}/messages", json=body, stream=True)
        except http.RequestError as exc:
            raise ProviderError(f"{self.label}: {exc}", provider=self.name) from exc

        try:
            self._raise_for_status(response)
        except ProviderError as exc:
            response.close()
            if not (exc.status == 400 and caching.refused(str(exc))
                    and caching.strip(body)):
                raise
            return self._post(body)
        return response

    def _parse_stream(self, response: http.Response, model: str) -> Iterator[StreamEvent]:
        blocks: dict[int, dict[str, Any]] = {}     # index -> partial content block
        input_tokens = 0
        cached_tokens = 0
        written_tokens = 0
        output_tokens = 0
        stop_reason = ""

        for frame in iter_sse(response):
            payload = frame.json()
            if payload is None:
                continue
            event_type = payload.get("type", frame.event)

            if event_type == "message_start":
                usage = (payload.get("message") or {}).get("usage") or {}
                input_tokens = int(usage.get("input_tokens") or 0)
                # These three do not overlap: `input_tokens` excludes both
                # the prefix served from cache and the one being stored.
                cached_tokens = int(usage.get("cache_read_input_tokens") or 0)
                written_tokens = int(usage.get("cache_creation_input_tokens") or 0)

            elif event_type == "content_block_start":
                index = int(payload.get("index", 0))
                block = payload.get("content_block") or {}
                blocks[index] = {
                    "type": block.get("type", "text"),
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "json": "",
                }

            elif event_type == "content_block_delta":
                index = int(payload.get("index", 0))
                delta = payload.get("delta") or {}
                kind = delta.get("type")
                if kind == "text_delta" and delta.get("text"):
                    yield StreamEvent(type=EventType.TEXT, text=delta["text"])
                elif kind == "thinking_delta" and delta.get("thinking"):
                    yield StreamEvent(type=EventType.REASONING, text=delta["thinking"])
                elif kind == "input_json_delta":
                    slot = blocks.setdefault(index, {"type": "tool_use", "id": "",
                                                     "name": "", "json": ""})
                    slot["json"] += delta.get("partial_json", "")

            elif event_type == "content_block_stop":
                index = int(payload.get("index", 0))
                slot = blocks.pop(index, None)
                if slot and slot["type"] == "tool_use" and slot["name"]:
                    yield StreamEvent(
                        type=EventType.TOOL_CALL,
                        tool_call=ToolCall(
                            id=slot["id"] or ToolCall.new_id(),
                            name=slot["name"],
                            arguments=parse_arguments(slot["json"]),
                        ),
                    )

            elif event_type == "message_delta":
                delta = payload.get("delta") or {}
                stop_reason = delta.get("stop_reason") or stop_reason
                usage = payload.get("usage") or {}
                output_tokens = int(usage.get("output_tokens") or output_tokens)

            elif event_type == "error":
                error = payload.get("error") or {}
                raise ProviderError(f"{self.label}: {error.get('message', 'stream error')}",
                                    provider=self.name)

            elif event_type == "message_stop":
                break

        cost = registry.estimate_cost(model, input_tokens, output_tokens,
                                      cached_tokens, written_tokens)
        yield StreamEvent(type=EventType.USAGE, usage=Usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            written_tokens=written_tokens,
            cost_usd=cost or 0.0,
        ))
        yield StreamEvent(type=EventType.DONE, finish_reason=stop_reason)

    # -- misc ------------------------------------------------------------- #

    def list_models(self) -> list[str]:
        try:
            response = self._session.get(f"{self.base_url}/models", timeout=(5.0, 20.0))
            self._raise_for_status(response)
            payload = response.json()
        except (http.RequestError, ProviderError, ValueError):
            # The catalogue we ship is a reasonable answer when the API is out.
            return [info.id for info in registry.known_models()
                    if info.id.startswith("claude-")]
        return sorted(str(entry["id"]) for entry in payload.get("data", [])
                      if isinstance(entry, dict) and entry.get("id"))

    def close(self) -> None:
        self._session.close()
