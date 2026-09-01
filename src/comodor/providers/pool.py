"""A pool of keys for one provider, rotated when a rate limit says to.

The gateway fails over between *providers*; this fails over between *keys*
of one provider. The two compose: a 429 that survives a key change still
moves to the next provider, and a healthy provider whose single key is
throttled keeps working instead of stalling the session.

The rules are deliberately few:

* **Round-robin from the healthy.** Calls spread across keys so a limit is
  reached later, not so a favourite key is worn out first.
* **A 429 cools the key down.** The cooldown honours the response's
  ``retry_after`` when the provider sent one, or sixty seconds when it did
  not. The gateway's health tracking is untouched — that is per provider,
  this is per key.
* **When every key is cooling, use the one that unlocks soonest**, and say
  so. Refusing outright would turn a slow path into a failed turn; the
  caller (and the user watching) deserve the honest message.
* **Keys are masked everywhere.** ``sk-abc…wxyz`` is the only form this
  module ever returns for display.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

#: A rate limit with no ``retry_after`` cools the key for this long.
DEFAULT_COOLDOWN_SECONDS = 60.0


@dataclass
class KeyState:
    """One key, its identity masked, and how long until it may be used."""

    key: str
    cooldown_until: float = 0.0
    uses: int = 0
    rate_limits: int = 0

    @property
    def masked(self) -> str:
        """The only form of the key safe to show, log, or store."""
        key = self.key
        if len(key) <= 8:
            # A short key has no honest prefix and suffix — both would
            # overlap — so it is reduced to a length alone.
            return f"…({len(key)})" if len(key) > 2 else "…"
        return f"{key[:6]}…{key[-4:]}"

    @property
    def cooling(self) -> bool:
        return time.monotonic() < self.cooldown_until

    def cooldown_left(self) -> float:
        return max(0.0, self.cooldown_until - time.monotonic())


@dataclass
class KeyPool:
    """The keys of one provider, with rotation state."""

    provider: str
    keys: list[str] = field(default_factory=list)
    _states: list[KeyState] = field(default_factory=list, repr=False)
    _cursor: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._states = [KeyState(key=key) for key in self.keys]

    def __bool__(self) -> bool:
        return bool(self.keys)

    def __len__(self) -> int:
        return len(self.keys)

    # -- choosing --------------------------------------------------------- #

    def next_key(self) -> tuple[str, str]:
        """The key to use now, as (key, masked).

        Round-robin over the healthy keys; if every key is cooling, the one
        that unlocks soonest is used and a message explains why — a slow
        request beats a refused one, and the message is what keeps that
        trade visible.
        """
        with self._lock:
            if not self._states:
                return "", ""
            healthy = [state for state in self._states if not state.cooling]
            if healthy:
                start = self._cursor % len(healthy)
                chosen = healthy[start]
                self._cursor = start + 1
            else:
                chosen = min(self._states, key=KeyState.cooldown_left)
                self._cursor = 0
            chosen.uses += 1
            return chosen.key, chosen.masked

    def wait_message(self) -> str:
        """What to tell the user when only a cooling key is left."""
        with self._lock:
            soonest = min(self._states, key=KeyState.cooldown_left) \
                if self._states else None
        if soonest is None:
            return ""
        return (f"every key of {self.provider} is rate-limited; waiting "
                f"{soonest.cooldown_left():.0f}s for {soonest.masked}")

    # -- reporting -------------------------------------------------------- #

    def report_rate_limited(self, key: str, retry_after: float = 0.0) -> None:
        """Cool the key down. The provider's ``retry_after`` is honoured
        when it sent one; sixty seconds when it did not."""
        seconds = max(retry_after, DEFAULT_COOLDOWN_SECONDS)
        with self._lock:
            for state in self._states:
                if state.key == key:
                    state.rate_limits += 1
                    state.cooldown_until = time.monotonic() + seconds
                    return

    def report_ok(self, key: str) -> None:
        """A successful call clears any doubt about the key's health."""
        with self._lock:
            for state in self._states:
                if state.key == key:
                    state.cooldown_until = 0.0
                    return

    # -- introspection ----------------------------------------------------- #

    def status(self) -> list[dict[str, object]]:
        """Per-key state for /provider and doctor — masked keys only."""
        with self._lock:
            return [
                {
                    "key": state.masked,
                    "healthy": not state.cooling,
                    "cooldown_left": round(state.cooldown_left(), 1),
                    "uses": state.uses,
                    "rate_limits": state.rate_limits,
                }
                for state in self._states
            ]


def pool_keys(entry: Any) -> list[str]:
    """The full key list of a provider config, deduplicated, order kept.

    ``api_key`` is the canonical first key; ``api_keys`` holds the rest. A
    single-key user has a pool of one and this module is invisible to them.
    """
    keys: list[str] = []
    for key in (getattr(entry, "api_key", ""), *getattr(entry, "api_keys", [])):
        if key and key not in keys:
            keys.append(key)
    return keys
