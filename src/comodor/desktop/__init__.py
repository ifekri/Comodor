"""Driving the machine: what the agent can see and what it can touch.

One object, :class:`Desktop`, over a per-platform backend. Everything above it
- the tool, the overlay, the guard - talks to this and never to ctypes.

The movement deserves a word, because it is the part that looks like a
decoration and is not. A pointer could be put where it needs to be in a single
call; nothing would be faster. It travels instead, over about a third of a
second, with a halo drawn at the destination before it sets off.

That pause is the whole safety model made visible. A person watching an agent
work needs a moment in which stopping it is still possible, and a cursor that
teleports and clicks in the same instant does not give them one. It also makes
the thing legible: you can see it reach for the wrong button and know why the
next screenshot is wrong.

Every action is announced to a watcher before it happens and after, so the
overlay and the web view are fed from one place rather than each reaching in.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from . import keys as keymap
from .screen import (
    DEFAULT_TOKENS,
    LONG_EDGE,
    MAX_TOKENS,
    NotSupported,
    Shot,
    backend,
    capture,
    fit,
    tokens_for,
    zoom,
)

__all__ = ["Desktop", "Shot", "Action", "NotSupported", "DesktopError",
           "capture", "zoom", "fit", "tokens_for", "available", "why_not",
           "DEFAULT_TOKENS", "MAX_TOKENS", "LONG_EDGE"]


class DesktopError(RuntimeError):
    """Something the machine refused to do."""


# --------------------------------------------------------------------------- #
# what a watcher is told
# --------------------------------------------------------------------------- #


@dataclass
class Action:
    """One thing about to happen, or that just has.

    Carried to the overlay and to the web view. `caption` is written for a
    person watching, not for a log: it says "clicking Save", not
    "left_click(842,517)".
    """

    kind: str                                   # move | click | type | key | scroll
    caption: str
    at: tuple[int, int] | None = None           # screen pixels
    to: tuple[int, int] | None = None           # for a drag or a move
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class Watcher(Protocol):
    """Anything that wants to show what is happening."""

    def about_to(self, action: Action) -> None: ...
    def did(self, action: Action) -> None: ...


class _Nobody:
    """The watcher used when nothing is watching."""

    def about_to(self, action: Action) -> None:
        return None

    def did(self, action: Action) -> None:
        return None


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #


def available() -> bool:
    try:
        backend()
        return True
    except NotSupported:
        return False


def why_not() -> str:
    try:
        backend()
        return ""
    except NotSupported as error:
        return str(error)


# --------------------------------------------------------------------------- #
# the desktop
# --------------------------------------------------------------------------- #

#: How long the pointer takes to cross the screen, and in how many steps. Fast
#: enough not to be tedious over a long task, slow enough that an eye can
#: follow it and a hand can intervene.
TRAVEL_SECONDS = 0.32
TRAVEL_STEPS = 24
#: The beat between arriving somewhere and clicking it. The last chance to stop.
SETTLE_SECONDS = 0.12
#: Between keystrokes. Real applications drop characters typed faster than this,
#: and a search box that debounces needs the gaps to fire at all.
KEYSTROKE_SECONDS = 0.012


class Desktop:
    """The screen, the pointer and the keyboard, as one thing.

    A `guard` is asked before every action and may refuse; a `watcher` is told
    about every action and cannot. Both are optional, so the class is usable on
    its own in a test.
    """

    def __init__(self, watcher: Watcher | None = None,
                 guard: Callable[[Action], None] | None = None,
                 *, travel: float = TRAVEL_SECONDS) -> None:
        self.machine = backend()
        self.watcher: Watcher = watcher or _Nobody()
        self.guard = guard
        self.travel = travel
        self.last: Shot | None = None

    # -- permission ------------------------------------------------------- #

    def _allow(self, action: Action) -> None:
        if self.guard is not None:
            self.guard(action)                  # raises to refuse
        self.watcher.about_to(action)

    def _done(self, action: Action) -> None:
        self.watcher.did(action)

    # -- looking ---------------------------------------------------------- #

    def look(self, budget: int = DEFAULT_TOKENS, *, whole_desktop: bool = False) -> Shot:
        action = Action("screenshot", "looking at the screen")
        self._allow(action)
        self.last = capture(budget, whole_desktop=whole_desktop)
        action.detail = self.last.describe()
        self._done(action)
        return self.last

    def magnify(self, box: tuple[int, int, int, int],
                budget: int = DEFAULT_TOKENS) -> Shot:
        action = Action("screenshot", "looking closer", meta={"box": box})
        self._allow(action)
        shot = zoom(box, budget)
        action.detail = shot.describe()
        self._done(action)
        return shot

    def where(self) -> tuple[int, int]:
        return self.machine.cursor()

    # -- pointing --------------------------------------------------------- #

    def move(self, x: int, y: int, *, caption: str = "") -> None:
        """Travel there, visibly.

        Eased rather than linear: a pointer that starts and stops gently reads
        as deliberate, and a constant-speed one reads as a glitch. The
        difference is one line and it is the difference between watchable and
        not.
        """
        action = Action("move", caption or f"moving to ({x}, {y})",
                        at=self.machine.cursor(), to=(x, y))
        self._allow(action)

        start_x, start_y = self.machine.cursor()
        steps = max(1, int(TRAVEL_STEPS * min(1.0, self.travel / TRAVEL_SECONDS or 1)))
        pause = self.travel / steps if steps else 0

        for step in range(1, steps + 1):
            fraction = step / steps
            eased = _ease(fraction)
            self.machine.move_to(round(start_x + (x - start_x) * eased),
                                 round(start_y + (y - start_y) * eased))
            if pause:
                time.sleep(pause)

        self.machine.move_to(x, y)               # exactly, after the easing
        self._done(action)

    def click(self, x: int | None = None, y: int | None = None, *,
              button: str = "left", count: int = 1,
              modifiers: str = "", caption: str = "") -> None:
        if x is not None and y is not None:
            # The travel says "moving" and the click says "clicking". Passing
            # one caption down to both made the overlay announce the same
            # sentence twice for one action.
            self.move(x, y)
            time.sleep(SETTLE_SECONDS)           # the last chance to stop it
        at = self.machine.cursor()

        what = {1: "clicking", 2: "double-clicking", 3: "triple-clicking"}.get(
            count, f"clicking {count} times")
        action = Action("click", caption or f"{what} at {at}", at=at,
                        detail=f"{button} button", meta={"button": button,
                                                         "count": count})
        self._allow(action)

        held = self._hold(modifiers)
        try:
            for index in range(count):
                self.machine.button(button, down=True)
                self.machine.button(button, down=False)
                if index + 1 < count:
                    # Inside the double-click interval, or the system sees two
                    # single clicks and the application does the wrong thing.
                    time.sleep(0.06)
        finally:
            self._release(held)
        self._done(action)

    def press(self, button: str = "left", *, down: bool = True) -> None:
        at = self.machine.cursor()
        action = Action("click", f"{'holding' if down else 'releasing'} the "
                                 f"{button} button", at=at)
        self._allow(action)
        self.machine.button(button, down=down)
        self._done(action)

    def drag(self, start: tuple[int, int], end: tuple[int, int], *,
             modifiers: str = "") -> None:
        self.move(*start, caption=f"dragging from {start}")
        time.sleep(SETTLE_SECONDS)
        action = Action("drag", f"dragging to {end}", at=start, to=end)
        self._allow(action)

        held = self._hold(modifiers)
        try:
            self.machine.button("left", down=True)
            time.sleep(0.05)
            self.move(*end, caption=f"dragging to {end}")
            time.sleep(0.05)
        finally:
            self.machine.button("left", down=False)
            self._release(held)
        self._done(action)

    def scroll(self, direction: str, amount: int = 3,
               at: tuple[int, int] | None = None, *, modifiers: str = "") -> None:
        if at is not None:
            self.move(*at, caption=f"scrolling at {at}")
        where = self.machine.cursor()
        action = Action("scroll", f"scrolling {direction}", at=where,
                        meta={"direction": direction, "amount": amount})
        self._allow(action)

        held = self._hold(modifiers)
        try:
            steps = {"up": (amount, False), "down": (-amount, False),
                     "right": (amount, True), "left": (-amount, True)}.get(direction)
            if steps is None:
                raise DesktopError(
                    f"scroll direction must be up, down, left or right, "
                    f"not {direction!r}")
            clicks, horizontal = steps
            self.machine.wheel(clicks, horizontal=horizontal)
        finally:
            self._release(held)
        self._done(action)

    # -- typing ----------------------------------------------------------- #

    def type_text(self, text: str) -> None:
        """Type characters, as characters.

        By code point rather than by key position, so what arrives is what was
        asked for on every keyboard layout. A layout-dependent `@` is the
        classic version of this bug and it only shows up on someone else's
        machine.
        """
        preview = text if len(text) <= 40 else text[:39] + "…"
        action = Action("type", f"typing {preview!r}",
                        at=self.machine.cursor(), meta={"length": len(text)})
        self._allow(action)
        for character in text:
            if character == "\n":
                self._tap(keymap.code_for("Return"))
            elif character == "\t":
                self._tap(keymap.code_for("Tab"))
            else:
                self.machine.unicode_char(character)
            time.sleep(KEYSTROKE_SECONDS)
        self._done(action)

    def key(self, combination: str, repeat: int = 1) -> None:
        modifiers, code = keymap.parse(combination)
        action = Action("key", f"pressing {combination}",
                        at=self.machine.cursor(),
                        meta={"key": combination, "repeat": repeat})
        self._allow(action)

        for held in modifiers:
            self.machine.key(held, down=True, extended=keymap.is_extended(held))
        try:
            for _ in range(max(1, min(int(repeat), 100))):
                self._tap(code)
                time.sleep(KEYSTROKE_SECONDS)
        finally:
            for held in reversed(modifiers):
                self.machine.key(held, down=False,
                                 extended=keymap.is_extended(held))
        self._done(action)

    def hold(self, combination: str, seconds: float) -> None:
        modifiers, code = keymap.parse(combination)
        action = Action("key", f"holding {combination} for {seconds:g}s",
                        meta={"key": combination, "seconds": seconds})
        self._allow(action)

        every = modifiers + [code]
        for held in every:
            self.machine.key(held, down=True, extended=keymap.is_extended(held))
        try:
            time.sleep(max(0.0, min(float(seconds), 300.0)))
        finally:
            for held in reversed(every):
                self.machine.key(held, down=False,
                                 extended=keymap.is_extended(held))
        self._done(action)

    # -- helpers ---------------------------------------------------------- #

    def _tap(self, code: int) -> None:
        extended = keymap.is_extended(code)
        self.machine.key(code, down=True, extended=extended)
        self.machine.key(code, down=False, extended=extended)

    def _hold(self, modifiers: str) -> list[int]:
        if not modifiers:
            return []
        codes: list[int] = []
        for name in modifiers.replace(" ", "").split("+"):
            if not name:
                continue
            code = keymap.MODIFIERS.get(name.lower())
            if code is None:
                raise DesktopError(f"{name!r} is not a modifier key")
            codes.append(code)
        for code in codes:
            self.machine.key(code, down=True, extended=keymap.is_extended(code))
        return codes

    def _release(self, codes: list[int]) -> None:
        # Backwards, or the first one held stays held.
        for code in reversed(codes):
            self.machine.key(code, down=False, extended=keymap.is_extended(code))

    # -- what is in front ------------------------------------------------- #

    def foreground(self) -> str:
        return self.machine.foreground_title()

    def locked(self) -> bool:
        return self.machine.screen_is_locked()


def _ease(fraction: float) -> float:
    """Slow at both ends, quick in the middle - how a hand moves a mouse.

    Quadratic in and out. A linear travel arrives at full speed and stops dead,
    which reads as a glitch rather than as something deciding where to go.
    """
    if fraction < 0.5:
        return 2 * fraction * fraction
    remaining = 1 - fraction
    return 1 - 2 * remaining * remaining
