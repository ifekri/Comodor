"""Installation access tokens: fetched, held briefly, never written down.

GitHub gives an installation token an hour. That is short enough to be worth
caching — a turn that touches six files should not ask six times — and long
enough that a naive cache would hand back an expired one right at the end.

So the cache carries the expiry GitHub reported and treats a token as spent
before it actually is. The margin exists because the token is checked here and
used a moment later, over a network: a token with four seconds left passes the
check and fails the request, and the failure surfaces as a 401 from the middle
of an operation rather than as a refresh.

Nothing here is persisted. A token in a config file outlives the session that
fetched it, is readable by anything that can read the file, and buys nothing
over asking again — the Worker mints another in one round trip.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

#: Treat a token as spent this long before GitHub does. A request has to be
#: made and answered after the check, and a token that expires in flight is a
#: 401 nobody can act on.
EXPIRY_MARGIN = 120.0

#: How long a mint request may take. Generous — it is one call to the Worker,
#: which makes one call to GitHub — but bounded, because a hung mint would
#: otherwise hold the turn.
MINT_TIMEOUT = 30.0


class TokenError(RuntimeError):
    """A token could not be obtained. The message is safe to show."""


@dataclass(frozen=True)
class InstallationToken:
    """One short-lived token, and when it stops being usable.

    `token` is opaque: GitHub does not document its shape and nothing here
    parses it. It is never included in a repr — a dataclass would print it by
    default, and a stack trace with an installation token in it is a
    credential in a log file.
    """

    token: str
    expires_at: float
    installation_id: int

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        left = max(0, int(self.expires_at - time.time()))
        return (f"<InstallationToken installation={self.installation_id} "
                f"expires_in={left}s>")

    @property
    def spent(self) -> bool:
        return time.time() >= self.expires_at - EXPIRY_MARGIN


class Tokens:
    """A per-installation token cache that refreshes what it hands out.

    Shared between threads: a background delegate and the turn that spawned it
    both reach GitHub, and two simultaneous misses on the same installation
    should be one mint rather than two. The lock is per instance and held only
    around the dictionary, never across the network call — a mint that hung
    would otherwise block every other installation as well.
    """

    def __init__(self, mint: Callable[[int], InstallationToken]) -> None:
        #: Given an installation id, produce a fresh token. Supplied rather
        #: than built in so a test can drive this without a network, and so
        #: the transport — which knows about the Worker — stays in one place.
        self._mint = mint
        self._held: dict[int, InstallationToken] = {}
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()
        #: How many times a token was actually fetched. Read by the tests, and
        #: by anyone wondering whether the cache is doing anything.
        self.mints = 0

    def _lock_for(self, installation_id: int) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(installation_id)
            if lock is None:
                lock = self._locks[installation_id] = threading.Lock()
            return lock

    def for_installation(self, installation_id: int) -> InstallationToken:
        """A usable token for this installation, minting one if needed."""
        installation_id = int(installation_id)

        held = self._held.get(installation_id)
        if held is not None and not held.spent:
            return held

        # One mint per installation at a time. Two turns starting together
        # would otherwise each ask, and GitHub counts both against the rate
        # limit for a token only one of them will keep.
        with self._lock_for(installation_id):
            held = self._held.get(installation_id)
            if held is not None and not held.spent:
                return held

            fresh = self._mint(installation_id)
            if not isinstance(fresh, InstallationToken) or not fresh.token:
                raise TokenError("the token service returned nothing usable")
            self._held[installation_id] = fresh
            self.mints += 1
            return fresh

    def forget(self, installation_id: int) -> None:
        """Drop a cached token.

        Called when GitHub refuses one — a revoked installation, a narrowed
        permission — so the next attempt asks for a new one rather than
        replaying the rejected token until it expires on its own.
        """
        self._held.pop(int(installation_id), None)

    def forget_everything(self) -> None:
        self._held.clear()


def redact(text: Any) -> str:
    """Remove anything that looks like a GitHub credential from a string.

    Applied to every error message that might carry one. GitHub's tokens have
    documented prefixes, which is what makes this possible at all — and the
    reason a token is never interpolated into a message on purpose is that
    this is a net, not a policy.
    """
    out = str(text)
    for prefix in ("ghs_", "ghu_", "gho_", "ghp_", "ghr_", "github_pat_"):
        out = _scrub(out, prefix)
    # A JWT: three base64url segments. Only ever the app's, and only ever a
    # mistake if it is here at all.
    return _scrub(out, "eyJ")


def _scrub(text: str, prefix: str) -> str:
    while True:
        at = text.find(prefix)
        if at < 0:
            return text
        end = at + len(prefix)
        while end < len(text) and (text[end].isalnum() or text[end] in "_-."):
            end += 1
        text = text[:at] + "<redacted>" + text[end:]
