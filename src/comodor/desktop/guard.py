"""Whether the agent may touch the machine, asked again before every action.

The rest of this package is a way to move a mouse. This file is the reason it
is safe to have.

A permission dialog that appears once and never again teaches people to click
past it, and "allow for this session" on a tool that can do anything to a
computer is not a meaningful limit. So a grant here is three things at once:

* **a scope** - everything, or one application named by its window title
* **a clock** - it expires, and the time left is on screen the whole time
* **a way out that works while the pointer is being held** - the mouse in a
  screen corner stops everything, immediately

That last one is the important one. Every other stop needs the user to reach a
keyboard or a window that the agent may currently be typing into. Pulling the
mouse away is what a person actually does when something on their screen starts
moving on its own, and it is the one gesture that cannot be intercepted: it
happens in the physical layer, and the check is simply whether the pointer
ended up somewhere the agent did not put it.

Refused whatever the grant says: a locked screen, a window on the deny list,
and Comodor's own window. The last is not paranoia - an agent that clicks into
the terminal it is being driven from can type into its own prompt.
"""

from __future__ import annotations

import fnmatch
import re
import threading
import time
from dataclasses import dataclass, field

#: How close to a corner counts as "get out". Generous, because the gesture is
#: a person throwing the mouse rather than aiming it, and because a slightly
#: over-eager stop costs a sentence while a missed one costs trust.
CORNER_PIXELS = 12

#: If the pointer is further than this from where the agent left it, somebody
#: else is holding the mouse. Not a stop on its own - people nudge a desk - but
#: it is how a corner is told from the agent's own travel.
DRIFT_PIXELS = 40

#: Window titles that are never driven, whatever has been granted. Matched
#: case-insensitively anywhere in the title.
NEVER = (
    "1password", "bitwarden", "keepass", "lastpass", "dashlane", "nordpass",
    "keychain access", "credential manager", "windows security",
    "user account control", "sign in", "sign-in", "authenticator",
    "bitlocker", "seed phrase", "recovery phrase", "private key",
    "wallet", "metamask", "ledger live", "trezor",
    "online banking", "internetbanking",
)


class Refused(PermissionError):
    """The guard said no. The message is written to be shown to the user."""


class Stopped(Refused):
    """The user stopped it, by the corner or by asking."""


@dataclass
class Grant:
    """Permission to drive the machine, for a while, over some of it."""

    seconds: float
    scope: str = ""                     # empty means every window
    granted_at: float = field(default_factory=time.monotonic)
    reason: str = ""

    @property
    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.granted_at))

    @property
    def expired(self) -> bool:
        return self.remaining <= 0

    @property
    def scoped(self) -> bool:
        return bool(self.scope)

    def covers(self, title: str) -> bool:
        """Whether this window is in scope.

        A glob rather than an exact title, because a window's title changes
        with what is open in it - `report.docx - Word` becomes
        `notes.docx - Word` and a grant for one should not evaporate.
        """
        if not self.scope:
            return True
        pattern = self.scope.lower()
        name = (title or "").lower()
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name, f"*{pattern}*"):
            return True
        return pattern in name

    def describe(self) -> str:
        left = self.remaining
        clock = f"{int(left // 60)}m {int(left % 60):02d}s" if left >= 60 \
            else f"{int(left)}s"
        where = f"in {self.scope}" if self.scope else "anywhere on screen"
        return f"{clock} left, {where}"


class Guard:
    """Asked before every action, and able to say no to any of them."""

    def __init__(self, deny: tuple[str, ...] = NEVER,
                 corner_pixels: int = CORNER_PIXELS,
                 own_titles: tuple[str, ...] = ("comodor",)) -> None:
        self.deny = tuple(entry.lower() for entry in deny)
        self.corner_pixels = corner_pixels
        self.own_titles = tuple(entry.lower() for entry in own_titles)
        self._lock = threading.RLock()
        self._grant: Grant | None = None
        self._stopped_because = ""
        self._expected: tuple[int, int] | None = None
        self.refusals: list[str] = []

    # -- the grant -------------------------------------------------------- #

    def allow(self, seconds: float, scope: str = "", reason: str = "") -> Grant:
        with self._lock:
            self._stopped_because = ""
            self._grant = Grant(seconds=float(seconds), scope=scope.strip(),
                                reason=reason)
            return self._grant

    def revoke(self, why: str = "") -> None:
        with self._lock:
            self._grant = None
            self._stopped_because = why

    @property
    def grant(self) -> Grant | None:
        with self._lock:
            if self._grant is not None and self._grant.expired:
                self._grant = None
                self._stopped_because = "the time you allowed ran out"
            return self._grant

    @property
    def active(self) -> bool:
        return self.grant is not None

    def status(self) -> str:
        grant = self.grant
        if grant is not None:
            return grant.describe()
        return self._stopped_because or "not allowed"

    # -- the pointer, which is also the stop button ----------------------- #

    def note_pointer(self, at: tuple[int, int]) -> None:
        """Remember where the agent left the mouse.

        What makes the corner check meaningful: without it, an agent that
        legitimately clicks something in the corner would stop itself.
        """
        with self._lock:
            self._expected = at

    def a_hand_is_on_it(self, actual: tuple[int, int]) -> bool:
        """Whether the pointer got where it is by a hand rather than by us.

        The same reasoning the corner check rests on, asked as its own
        question because two things need it now. `note_pointer` records where
        the agent left the mouse; anywhere else means somebody moved it.

        Used by the overlay: its buttons must answer a person and ignore the
        agent, which drives the very same system cursor. Without this, a
        `left_click` aimed at anything underneath the panel would move the
        pointer into a button, make the window take clicks, and land the
        agent's own click on Stop.

        With no expectation recorded there is nothing to compare against, and
        the safe answer is yes: a stop button that ignores a person is worse
        than one that occasionally believes the agent is a person, because the
        agent has no reason to be pointing at the panel in the first place.
        """
        with self._lock:
            expected = self._expected
        if expected is None:
            return True
        drift = max(abs(actual[0] - expected[0]), abs(actual[1] - expected[1]))
        return drift >= DRIFT_PIXELS

    def user_moved_away(self, actual: tuple[int, int],
                        corners: list[tuple[int, int, int, int]]) -> bool:
        """Whether a human has taken the mouse to a corner."""
        if not self.a_hand_is_on_it(actual):
            return False                         # this is where we left it

        edge = self.corner_pixels
        for left, top, right, bottom in corners:
            near_x = actual[0] <= left + edge or actual[0] >= right - 1 - edge
            near_y = actual[1] <= top + edge or actual[1] >= bottom - 1 - edge
            if near_x and near_y:
                return True
        return False

    # -- the question itself ---------------------------------------------- #

    def check(self, *, pointer: tuple[int, int],
              corners: list[tuple[int, int, int, int]],
              foreground: str, locked: bool, what: str = "") -> None:
        """Raise if this must not happen. Return quietly if it may."""
        if locked:
            self._refuse("the screen is locked")

        if self.user_moved_away(pointer, corners):
            self.revoke("you moved the mouse to a corner")
            raise Stopped(
                "Stopped: you moved the mouse into a corner. Computer control "
                "is off; ask again when you want it back.")

        grant = self.grant
        if grant is None:
            self._refuse(
                self._stopped_because
                or "Comodor has not been allowed to use the screen. "
                   "`/computer 15m` allows it for fifteen minutes.")

        title = foreground or ""
        blocked = self._on_the_deny_list(title)
        if blocked:
            self._refuse(
                f"not while {title.strip() or 'that window'} is in front - it "
                f"looks like {blocked}, and Comodor never drives those.")

        if self._is_our_own(title):
            self._refuse(
                "that is Comodor's own window, and driving it would mean "
                "typing into its own prompt.")

        if not grant.covers(title):
            self._refuse(
                f"you allowed {grant.scope!r} only, and the window in front is "
                f"{title.strip() or 'something else'}.")

    def _refuse(self, message: str) -> None:
        self.refusals.append(message)
        raise Refused(message)

    def _on_the_deny_list(self, title: str) -> str:
        name = (title or "").lower()
        if not name:
            return ""
        for entry in self.deny:
            if entry in name:
                return f"a {entry} window" if " " not in entry else entry
        # A window asking for a password, whatever it is called.
        if re.search(r"\b(password|passphrase|2fa|one[- ]time code)\b", name):
            return "something asking for a password"
        return ""

    def _is_our_own(self, title: str) -> bool:
        name = (title or "").lower()
        return any(entry in name for entry in self.own_titles)
