"""Model facts: context windows and prices.

Two rules shape this module.

*Never invent a price.* A wrong cost readout is worse than no cost readout, so
an unknown model reports ``None`` and the UI shows a dash instead of a number.

*Prefer live data.* OpenRouter publishes per-model pricing and context length on
its ``/models`` endpoint; when that is reachable it overrides the static table
below, which is only a cached fallback.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# static catalogue
# --------------------------------------------------------------------------- #


#: Multiples of the base input rate. Anthropic charges 0.1 to read a cached
#: prefix and 1.25 to write one; DeepSeek reads at 0.1 with no write premium,
#: OpenAI at 0.5. The Anthropic figures are used everywhere because they are the
#: most conservative pair — a spend meter that guesses should guess high.
CACHE_READ = 0.10
CACHE_WRITE = 1.25


@dataclass(frozen=True)
class ModelInfo:
    """What we know about one model."""

    id: str
    context: int                          # input tokens the model accepts
    input_per_mtok: float | None = None   # USD per million input tokens
    output_per_mtok: float | None = None
    max_output: int = 8192
    label: str = ""
    supports_tools: bool = True
    supports_vision: bool = False

    @property
    def priced(self) -> bool:
        return self.input_per_mtok is not None and self.output_per_mtok is not None

    def cost(self, input_tokens: int, output_tokens: int,
             cached_tokens: int = 0, written_tokens: int = 0) -> float | None:
        """What one request cost, at the rates the providers actually charge.

        Cached input is not free and it is not full price. Reading a prefix the
        provider already holds costs a tenth of the input rate; storing one for
        later costs a quarter more than sending it plainly, paid once. Ignoring
        either — which is what counting only ``input_tokens`` does, since that
        field excludes both — makes the spend meter understate a long session
        badly, and the spend guard is built on that meter.
        """
        if not self.priced:
            return None
        billable = (input_tokens
                    + cached_tokens * CACHE_READ
                    + written_tokens * CACHE_WRITE)
        return (billable * self.input_per_mtok / 1_000_000
                + output_tokens * self.output_per_mtok / 1_000_000)


# Anthropic first-party rates, current as of 2026-06.
_ANTHROPIC: tuple[ModelInfo, ...] = (
    ModelInfo("claude-fable-5", 1_000_000, 10.00, 50.00, 128_000, "Claude Fable 5", supports_vision=True),
    ModelInfo("claude-opus-5", 1_000_000, 5.00, 25.00, 128_000, "Claude Opus 5", supports_vision=True),
    ModelInfo("claude-opus-4-8", 1_000_000, 5.00, 25.00, 128_000, "Claude Opus 4.8", supports_vision=True),
    ModelInfo("claude-opus-4-7", 1_000_000, 5.00, 25.00, 128_000, "Claude Opus 4.7", supports_vision=True),
    ModelInfo("claude-opus-4-6", 1_000_000, 5.00, 25.00, 128_000, "Claude Opus 4.6", supports_vision=True),
    ModelInfo("claude-sonnet-5", 1_000_000, 3.00, 15.00, 128_000, "Claude Sonnet 5", supports_vision=True),
    ModelInfo("claude-sonnet-4-6", 1_000_000, 3.00, 15.00, 128_000, "Claude Sonnet 4.6", supports_vision=True),
    ModelInfo("claude-haiku-4-5", 200_000, 1.00, 5.00, 64_000, "Claude Haiku 4.5", supports_vision=True),
)

# Everything else: context windows only where they are well established, prices
# left unset unless we are confident. The gateway fills the gaps from live data.
_OTHERS: tuple[ModelInfo, ...] = (
    ModelInfo("mimo-v2.5-pro", 256_000, None, None, 16_384, "MiMo v2.5 Pro"),
    ModelInfo("deepseek-chat", 128_000, None, None, 8_192, "DeepSeek Chat"),
    ModelInfo("deepseek-reasoner", 128_000, None, None, 8_192, "DeepSeek Reasoner"),
    ModelInfo("gpt-4o", 128_000, None, None, 16_384, "GPT-4o", supports_vision=True),
    ModelInfo("gpt-4o-mini", 128_000, None, None, 16_384, "GPT-4o mini", supports_vision=True),
    ModelInfo("llama-3.3-70b-versatile", 128_000, None, None, 32_768, "Llama 3.3 70B"),
)

_CATALOGUE: dict[str, ModelInfo] = {info.id: info for info in (*_ANTHROPIC, *_OTHERS)}

# Anthropic dropped sampling parameters on this family: sending `temperature`
# (or top_p/top_k) returns a 400, so the adapter must omit them.
_NO_SAMPLING = ("claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-opus-4-8",
                "claude-opus-4-7", "claude-sonnet-5")

DEFAULT_CONTEXT = 128_000
DEFAULT_MAX_OUTPUT = 8_192


def _normalise(model: str) -> str:
    """Strip provider routing prefixes: ``anthropic/claude-opus-5`` -> the id."""
    name = (model or "").strip()
    if "/" in name:
        name = name.split("/")[-1]
    return name


def lookup(model: str) -> ModelInfo:
    """Best-effort facts for a model id; unknown models get safe defaults."""
    name = _normalise(model)
    info = _CATALOGUE.get(name)
    if info is not None:
        return info
    # Try a prefix match so dated snapshots resolve to their base model.
    for known_id, known in _CATALOGUE.items():
        if name.startswith(known_id):
            return known
    return ModelInfo(id=name or "unknown", context=DEFAULT_CONTEXT,
                     max_output=DEFAULT_MAX_OUTPUT, label=name or "unknown")


def context_window(model: str) -> int:
    return lookup(model).context


def estimate_cost(model: str, input_tokens: int, output_tokens: int,
                  cached_tokens: int = 0, written_tokens: int = 0) -> float | None:
    return lookup(model).cost(input_tokens, output_tokens,
                              cached_tokens, written_tokens)


def supports_sampling(model: str) -> bool:
    """Whether ``temperature`` may be sent for this model."""
    name = _normalise(model)
    return not any(name.startswith(family) for family in _NO_SAMPLING)


def register(info: ModelInfo) -> None:
    """Add or replace an entry — used when live pricing is fetched."""
    _CATALOGUE[info.id] = info


def known_models() -> list[ModelInfo]:
    return sorted(_CATALOGUE.values(), key=lambda info: info.id)


# --------------------------------------------------------------------------- #
# live pricing
# --------------------------------------------------------------------------- #

_refreshed_at: float = 0.0
REFRESH_INTERVAL = 6 * 3600.0


def refresh_from_openrouter(base_url: str, api_key: str = "", timeout: float = 10.0) -> int:
    """Pull real context sizes and prices from OpenRouter's public catalogue.

    Returns the number of models learned. Failures are silent: stale-but-known
    prices, or no price at all, are both better than blocking the UI.
    """
    global _refreshed_at
    if time.time() - _refreshed_at < REFRESH_INTERVAL:
        return 0

    from ..net import http

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = http.get(f"{base_url.rstrip('/')}/models", headers=headers,
                            timeout=(5.0, timeout))
        payload = response.json()
    except Exception:
        return 0

    learned = 0
    for entry in payload.get("data", []) if isinstance(payload, dict) else []:
        try:
            model_id = str(entry["id"])
            pricing: dict[str, Any] = entry.get("pricing") or {}
            # OpenRouter quotes USD per token; our table is per million.
            prompt_price = float(pricing.get("prompt", 0) or 0) * 1_000_000
            completion_price = float(pricing.get("completion", 0) or 0) * 1_000_000
            top = entry.get("top_provider") or {}
            register(ModelInfo(
                id=model_id,
                context=int(entry.get("context_length") or DEFAULT_CONTEXT),
                input_per_mtok=prompt_price or None,
                output_per_mtok=completion_price or None,
                max_output=int(top.get("max_completion_tokens") or DEFAULT_MAX_OUTPUT),
                label=str(entry.get("name") or model_id),
                supports_vision="image" in str(entry.get("architecture", {})),
            ))
            learned += 1
        except (KeyError, TypeError, ValueError):
            continue

    _refreshed_at = time.time()
    return learned
