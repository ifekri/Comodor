"""GW — the model gateway.

With the gateway **disabled** (the default, and what the status bar shows as
``GW: Disable``) Comodor talks to exactly the provider you picked. Nothing is
rerouted, so what you see in the status bar is always what answered.

With it **enabled**, a request is tried against a ranked list of healthy
providers and falls over to the next one when a call fails. Ranking follows the
configured policy: cheapest, fastest, or most capable.

One rule keeps failover honest: **once a stream has emitted output, it is never
retried elsewhere.** Re-running a half-delivered answer on another model would
duplicate text and double-bill; a mid-stream failure is surfaced instead.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import Config, ProviderConfig
from . import registry
from .anthropic import AnthropicProvider
from .base import (
    AuthError,
    EventType,
    Message,
    Provider,
    ProviderError,
    StreamEvent,
    ToolSpec,
)
from .fake import FakeProvider, Script
from .openai_compat import OpenAICompatProvider
from .pool import KeyPool, pool_keys

# --------------------------------------------------------------------------- #
# construction
# --------------------------------------------------------------------------- #


def build_provider(entry: ProviderConfig, scripts: list[Script] | None = None,
                   key_pool: Any = None) -> Provider:
    """Instantiate the adapter for one configured backend."""
    if entry.kind == "fake":
        return FakeProvider(scripts=scripts, model=entry.model or "fake-1")
    if entry.kind == "local":
        # A model on this disk. The provider is lazy on purpose: loading four
        # gigabytes takes tens of seconds and would happen on every `comodor`
        # invocation, including the ones that never ask the model anything.
        from ..local.provider import build as build_local
        from ..paths import resolve

        return build_local(entry, user_dir=resolve().user)
    if entry.kind == "anthropic":
        return AnthropicProvider(
            name=entry.name, base_url=entry.base_url, api_key=entry.api_key,
            model=entry.model, headers=entry.headers, timeout=entry.timeout,
            label=entry.display, key_pool=key_pool,
        )
    return OpenAICompatProvider(
        name=entry.name, base_url=entry.base_url, api_key=entry.api_key,
        model=entry.model, headers=entry.headers, timeout=entry.timeout,
        label=entry.display, key_pool=key_pool,
    )


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #


@dataclass
class Health:
    """Rolling view of how well one provider is behaving."""

    calls: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    latency_ema: float = 0.0             # seconds to first token
    tripped_until: float = 0.0
    last_error: str = ""

    def record_success(self, first_token_seconds: float) -> None:
        self.calls += 1
        self.consecutive_failures = 0
        self.tripped_until = 0.0
        # Exponential moving average: recent behaviour dominates without
        # letting one slow call dictate routing.
        self.latency_ema = (first_token_seconds if not self.latency_ema
                            else 0.7 * self.latency_ema + 0.3 * first_token_seconds)

    def record_failure(self, error: str, cooldown: float, threshold: int) -> None:
        self.calls += 1
        self.failures += 1
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= threshold:
            self.tripped_until = time.monotonic() + cooldown

    @property
    def available(self) -> bool:
        return time.monotonic() >= self.tripped_until

@dataclass
class Route:
    """Which backend served a request, and how it went."""

    provider: str
    model: str
    attempts: int = 1
    failed_over_from: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# the gateway
# --------------------------------------------------------------------------- #


class Gateway:
    """Owns provider instances, health state, and routing decisions."""

    def __init__(self, config: Config, scripts: list[Script] | None = None) -> None:
        self.config = config
        self._scripts = scripts
        self._instances: dict[str, Provider] = {}
        self._health: dict[str, Health] = {}
        self._pools: dict[str, KeyPool] = {}
        # Reentrant because provider() holds this while consulting pool().
        self._lock = threading.RLock()
        self.last_route: Route | None = None

    # -- instances -------------------------------------------------------- #

    def provider(self, name: str) -> Provider:
        with self._lock:
            instance = self._instances.get(name)
            if instance is None:
                entry = self.config.providers.get(name)
                if entry is None:
                    raise ProviderError(f"unknown provider: {name}", retryable=False)
                instance = build_provider(
                    entry, self._scripts, key_pool=self.pool(name))
                self._instances[name] = instance
            return instance

    def pool(self, name: str) -> KeyPool | None:
        """The key pool of one provider, or None when it has a single key."""
        with self._lock:
            pool = self._pools.get(name)
            if pool is None:
                entry = self.config.providers.get(name)
                keys = pool_keys(entry) if entry is not None else []
                if len(keys) > 1:
                    pool = KeyPool(provider=name, keys=keys)
                    self._pools[name] = pool
            return pool

    def pool_status(self, name: str) -> list[dict[str, object]]:
        """Per-key state for the interface — masked keys only."""
        pool = self.pool(name)
        return pool.status() if pool else []

    def health(self, name: str) -> Health:
        with self._lock:
            return self._health.setdefault(name, Health())

    # -- routing ---------------------------------------------------------- #

    def candidates(self) -> list[str]:
        """Providers to try, best first.

        With the gateway off this is a single entry — the pinned provider —
        which is exactly what ``GW: Disable`` promises.
        """
        primary = self.config.provider
        if not self.config.gateway.enabled:
            return [primary]

        chain = [name for name in self.config.gateway.chain
                 if name in self.config.providers]
        if not chain:
            chain = [entry.name for entry in self.config.available()]
        if primary in chain:
            chain.remove(primary)
        ordered = self._rank(chain)
        return [primary, *ordered]

    def _rank(self, names: list[str]) -> list[str]:
        policy = self.config.gateway.policy

        def cost_key(name: str) -> tuple[float, str]:
            entry = self.config.providers[name]
            info = registry.lookup(entry.model)
            # Unknown prices sort last rather than pretending to be free.
            return (info.output_per_mtok if info.priced else float("inf"), name)

        def speed_key(name: str) -> tuple[float, str]:
            latency = self.health(name).latency_ema
            return (latency or 999.0, name)

        def quality_key(name: str) -> tuple[int, str]:
            entry = self.config.providers[name]
            model = entry.model.lower()
            for rank, marker in enumerate(("fable", "opus", "sonnet", "gpt-4", "pro")):
                if marker in model:
                    return (rank, name)
            return (99, name)

        keys = {"cost": cost_key, "speed": speed_key, "quality": quality_key}
        return sorted(names, key=keys.get(policy, quality_key))

    # -- the call --------------------------------------------------------- #

    def stream(self, messages: list[Message], *, tools: list[ToolSpec] | None = None,
               model: str = "", **kwargs: Any) -> Iterator[StreamEvent]:
        """Stream a completion, failing over only before the first token."""
        gateway = self.config.gateway
        attempted: list[str] = []
        last_error: ProviderError | None = None

        for name in self.candidates():
            health = self.health(name)
            if attempted and not health.available:
                continue                          # circuit still open, skip it

            entry = self.config.providers.get(name)
            if entry is None or not entry.ready:
                continue

            target_model = model if (model and name == self.config.provider) else entry.model
            started = time.monotonic()
            produced = False

            try:
                for event in self.provider(name).stream(
                    messages, tools=tools, model=target_model, **kwargs
                ):
                    if not produced and event.type in (EventType.TEXT, EventType.REASONING,
                                                       EventType.TOOL_CALL):
                        produced = True
                        health.record_success(time.monotonic() - started)
                    yield event
                if not produced:
                    health.record_success(time.monotonic() - started)
                self.last_route = Route(provider=name, model=target_model,
                                        attempts=len(attempted) + 1,
                                        failed_over_from=list(attempted))
                return

            except ProviderError as exc:
                health.record_failure(str(exc), gateway.cooldown_seconds,
                                      gateway.failure_threshold)
                last_error = exc
                attempted.append(name)
                # Anything already streamed to the user cannot be replayed, and
                # a bad key will fail the same way everywhere.
                if produced or isinstance(exc, AuthError) or not exc.retryable:
                    raise
                if not gateway.enabled:
                    raise

        if last_error is not None:
            raise last_error
        raise ProviderError(
            "no provider is configured — run `comodor setup`, or /provider here",
            retryable=False,
        )

    def close(self) -> None:
        with self._lock:
            for instance in self._instances.values():
                close = getattr(instance, "close", None)
                if close:
                    try:
                        close()
                    except Exception:
                        pass
            self._instances.clear()

    # -- introspection ---------------------------------------------------- #

    def describe(self) -> str:
        """One-line summary for the status bar."""
        if not self.config.gateway.enabled:
            return "Disable"
        return self.config.gateway.policy.title()

