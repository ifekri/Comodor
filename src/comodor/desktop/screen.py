"""Deciding what the model gets to look at, and how large.

A screenshot is the most expensive thing this feature sends and the only thing
that makes it work, so the size is a real decision rather than a constant.

The advice everywhere is "capture at about 1280 wide". That advice assumes a
16:9 or 4:3 desktop. On the 3840x1080 screen this was built against it means a
three-times reduction, and at that size the model is handed a picture of text
it cannot read - which is worse than no picture, because it guesses instead of
asking. Measured on that screen: menu labels and file names were illegible at
1280 wide and perfectly clear at 2068.

So the size is fitted to the two limits that actually exist:

  * the long edge, at most 2576 pixels
  * the visual tokens, ``ceil(w/28) * ceil(h/28)``

and the token budget is a setting, because it is the dial between cost and
legibility and the right position for it depends on the screen and the task.
The same rule gives 1480x833 on an ordinary 1920x1080 laptop and 2068x582 on
an ultrawide - in both cases the biggest readable image the budget allows.

Coordinates are the other half. The model works in the pixels of the image it
was sent; the mouse works in the pixels of the screen. Every coordinate coming
back has to be divided by the scale before anything is clicked, and that
conversion lives in one place - :meth:`Shot.to_screen` - because a second copy
of it is a second chance to get it wrong.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

#: The model will not accept an image whose longest side is larger than this.
LONG_EDGE = 2576
#: Visual tokens, at 28 pixels to a side. The ceiling the API enforces.
MAX_TOKENS = 4784
#: What a screenshot costs by default. Legible on every screen tried, and about
#: a third of the ceiling - a thirty-step task is then thousands of tokens of
#: pixels rather than tens of thousands.
DEFAULT_TOKENS = 1600
#: Below this the picture is not worth sending.
MIN_TOKENS = 200


def tokens_for(width: int, height: int) -> int:
    """What an image of this size costs the model to look at."""
    return math.ceil(width / 28) * math.ceil(height / 28)


def fit(width: int, height: int, budget: int = DEFAULT_TOKENS) -> tuple[int, int, float]:
    """The largest size within both limits, and the scale that gets there.

    Tokens go as the area, so the first guess is the square root of the ratio;
    rounding to whole pixels can push it back over a cell boundary, so it is
    walked down until it fits. Two or three steps at most.
    """
    budget = max(MIN_TOKENS, min(int(budget), MAX_TOKENS))
    scale = min(1.0, LONG_EDGE / max(width, height, 1))

    cost = tokens_for(max(1, round(width * scale)), max(1, round(height * scale)))
    if cost > budget:
        scale *= math.sqrt(budget / cost)

    while scale > 0.05:
        wide, high = max(1, round(width * scale)), max(1, round(height * scale))
        if tokens_for(wide, high) <= budget:
            return wide, high, scale
        scale -= 0.01

    return max(1, round(width * 0.05)), max(1, round(height * 0.05)), 0.05


# --------------------------------------------------------------------------- #
# what came back
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Shot:
    """One capture: the bytes, and everything needed to act on what is in them."""

    data: bytes                     # PNG
    width: int                      # of the image
    height: int
    scale: float                    # image pixels per screen pixel
    origin: tuple[int, int]         # top-left of the captured region, on screen
    region: tuple[int, int]         # size of that region, in screen pixels

    @property
    def tokens(self) -> int:
        return tokens_for(self.width, self.height)

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        """A coordinate the model gave, in real screen pixels.

        The one conversion the whole feature turns on. The model answers in the
        pixels of the picture it was shown, which is a shrunken crop of a
        screen that starts at an origin it has never been told about.
        """
        return (round(self.origin[0] + x / self.scale),
                round(self.origin[1] + y / self.scale))

    def to_image(self, x: int, y: int) -> tuple[int, int]:
        """The reverse, for drawing where something on screen is in the picture."""
        return (round((x - self.origin[0]) * self.scale),
                round((y - self.origin[1]) * self.scale))

    def describe(self) -> str:
        percent = self.scale * 100
        return (f"{self.width}x{self.height} of a "
                f"{self.region[0]}x{self.region[1]} screen ({percent:.0f}%), "
                f"{self.tokens} tokens")


# --------------------------------------------------------------------------- #
# the backend
# --------------------------------------------------------------------------- #


class NotSupported(RuntimeError):
    """This platform has no backend yet, said rather than half-worked."""


def backend():
    """The module that knows how to touch this machine.

    Windows only for now, and it says so plainly. A macOS backend is a file
    beside `win32.py` with the same handful of functions, which is why nothing
    above here imports ctypes.
    """
    if sys.platform == "win32":
        from . import win32

        return win32
    raise NotSupported(
        f"Comodor can only drive the screen on Windows so far, and this is "
        f"{sys.platform}. The browser tool works everywhere.")


def capture(budget: int = DEFAULT_TOKENS, region: tuple[int, int, int, int] | None = None,
            *, whole_desktop: bool = False) -> Shot:
    """A picture of the screen, sized to the budget.

    Without a region it takes the display holding the focused window, because
    that is where the work is; `whole_desktop` widens it to every monitor for
    the times the question is "where did that window go".
    """
    machine = backend()
    from . import png

    if region is not None:
        left, top, width, height = region
        area = machine.Rect(left, top, max(1, width), max(1, height))
    elif whole_desktop:
        area = machine.virtual_screen()
    else:
        area = machine.active_monitor()

    wide, high, scale = fit(area.width, area.height, budget)
    raw = machine.grab(area, wide, high)
    return Shot(data=png.encode(raw, wide, high), width=wide, height=high,
                scale=scale, origin=(area.left, area.top),
                region=(area.width, area.height))


def zoom(box: tuple[int, int, int, int], budget: int = DEFAULT_TOKENS) -> Shot:
    """A region of the screen, at its own resolution where that fits.

    The answer to small text on a large screen. A crop is a fraction of the
    pixels, so the same budget buys it at full size - which is how the model
    reads a label it could not make out in the wide shot.
    """
    x0, y0, x1, y1 = box
    left, top = min(x0, x1), min(y0, y1)
    width, height = max(1, abs(x1 - x0)), max(1, abs(y1 - y0))
    return capture(budget, region=(left, top, width, height))
