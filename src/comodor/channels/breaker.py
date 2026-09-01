"""A circuit breaker for the channel adapters.

A channel daemon talks to one network for its whole life. When that network
goes away — token expired, DNS broken, the platform having an incident — the
old behaviour was a backoff loop that kept polling forever, announcing the
same failure once a minute for as long as the outage lasted. That is not a
bot; that is a machine knocking on a door that nobody is behind, and every
knock is another request the platform may rate-limit for.

This is the fix, and it stays deliberately small:

* a run of consecutive transport errors — the kind worth retrying, not
  refusals the token deserved — trips the breaker after a few in a row;
* while paused, the daemon's poll loop does not talk to the platform at
  all. It sleeps and waits to be told, because polling a paused adapter is
  only a way of tripping it again;
* resume is a command, not a timer. Auto-resume would re-enter the outage
  on a guess; a human saying "try again" means the outage is plausibly
  over. The command is `/platform` in the channel itself, which is where
  the person who noticed the silence already is.

One breaker per adapter, in the daemon that owns the connection. There is
no shared registry: a paused Telegram says nothing about Slack, and a
`/platform` command is read by the one daemon whose network may be down.
"""

from __future__ import annotations

import threading
import time

#: How many consecutive transport errors trip the breaker. Five is enough
#: to mean "the platform is not answering" and few enough to not punish a
#: single unlucky minute.
TRIP_AFTER = 5

#: How long a paused daemon sleeps between wake-ups. Not polling — just
#: waiting for `stopping` or a resume, at a rate a human could live with.
RESUME_POLL = 5.0


class CircuitBreaker:
    """Counts consecutive send failures and pauses the adapter at the cap."""

    def __init__(self, platform: str, trip_after: int = TRIP_AFTER) -> None:
        self.platform = platform
        self.trip_after = trip_after
        self._streak = 0
        self._paused = False
        self._last_error = ""
        self._when = 0.0
        self._lock = threading.Lock()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def ok(self) -> None:
        """A clean poll: the streak resets, and a pause stands no longer."""
        with self._lock:
            self._streak = 0

    def fail(self, problem: str) -> bool:
        """One more transport failure. True when the breaker just tripped.

        A tripped breaker is announced exactly once — the moment it trips —
        so a long outage reads as one notice, not a notice a minute.
        """
        with self._lock:
            if self._paused:
                return False
            self._streak += 1
            if self._streak < self.trip_after:
                return False
            self._paused = True
            self._last_error = problem
            self._when = time.time()
            return True

    def resume(self) -> None:
        """A human said try again: the streak clears and polling returns."""
        with self._lock:
            self._paused = False
            self._streak = 0

    def describe(self) -> str:
        """One line about the adapter, for a /platform answer."""
        with self._lock:
            if self._paused:
                ago = _since(self._when)
                return (f"{self.platform} is paused — {self._last_error} "
                        f"({ago} ago). Send /platform resume to try again.")
            if self._streak:
                return (f"{self.platform} is sending, but {self._streak} "
                        "send(s) have failed recently.")
            return f"{self.platform} is up and sending."


def _since(when: float) -> str:
    seconds = max(1, int(time.time() - when))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"
