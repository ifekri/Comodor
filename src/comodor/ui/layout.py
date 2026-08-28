"""Responsive geometry.

The interface must be usable in a 40-column SSH window and in a 240-column
ultrawide, so the layout is recomputed from ``console.size`` on every frame
rather than fixed at startup. Resizing the terminal therefore just works.

Geometry is computed *here* and the widgets are then rendered at exactly those
sizes, instead of letting a layout engine decide and asking it afterwards where
things landed. That is what makes mouse hit-testing reliable: the rectangle
used to draw a control is the same rectangle a click is tested against.

**There are no panels.** The interface used to be four bordered boxes, and four
borders is four things competing to be looked at first — the transcript, which
is the only part anybody is reading, was framed exactly as loudly as the
context gauge. What holds it together now is a rule at the top, a rule above
the composer, and space: the same arrangement the printed page settled on a
few centuries ago, and for the same reason.

The rows, from the top:

======== ===========================================================
 rows     what
======== ===========================================================
 1        the name, and what it is talking to
 1        a rule
 1        air
 *        the transcript, and a task column beside it when there is room
 1        air
 1        a rule
 1-6      what you are typing
 1        air
 1        where you are, and what the keys do
======== ===========================================================

Breakpoints:

======== ===========================================================
 width    layout
======== ===========================================================
 < 60     one column; the task list becomes an overlay on F2
 60-99    one column; the task list is still on F2
 100-139  a task column of 24, and generous margins
 >= 140   a task column of 30; the transcript stops growing at 110
======== ===========================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_WIDTH = 40
MIN_HEIGHT = 12

TASKS_NARROW = 24
TASKS_WIDE = 30
GAP = 3
#: A line of prose stops being readable somewhere past this, and a transcript
#: is prose. Past it the extra width becomes margin rather than longer lines.
MAX_MEASURE = 110


@dataclass(frozen=True)
class Rect:
    """A screen rectangle in cells, top-left origin."""

    x: int
    y: int
    width: int
    height: int

    def contains(self, x: int, y: int) -> bool:
        return (self.x <= x < self.x + self.width
                and self.y <= y < self.y + self.height)

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


@dataclass
class Geometry:
    """Where everything goes for one frame."""

    width: int
    height: int
    tier: str                       # xs | sm | md | lg
    chat: Rect
    prompt: Rect
    header: Rect
    footer: Rect
    sidebar: Rect | None = None
    #: One rectangle per hint on the footer line, so the mouse still works even
    #: though the buttons it used to click are gone.
    hints: dict[str, Rect] = field(default_factory=dict)
    too_small: bool = False
    margin: int = 2

    @property
    def show_sidebar(self) -> bool:
        return self.sidebar is not None

    @property
    def show_buttons(self) -> bool:
        """Kept for callers that ask whether the pointer has anything to hit."""
        return bool(self.hints)

    #: The old name for the footer strip, which used to be a bordered block.
    @property
    def status(self) -> Rect:
        return self.footer

    def hit(self, x: int, y: int) -> str:
        """Which region a click landed in."""
        for name, rect in self.hints.items():
            if rect.contains(x, y):
                return f"button:{name}"
        if self.header.contains(x, y):
            return "header"
        if self.sidebar is not None and self.sidebar.contains(x, y):
            return "sidebar"
        if self.chat.contains(x, y):
            return "chat"
        if self.prompt.contains(x, y):
            return "prompt"
        if self.footer.contains(x, y):
            return "status"
        return ""


def tier_for(width: int) -> str:
    if width < 60:
        return "xs"
    if width < 100:
        return "sm"
    if width < 140:
        return "md"
    return "lg"


def sidebar_width(tier: str) -> int:
    return {"md": TASKS_NARROW, "lg": TASKS_WIDE}.get(tier, 0)


def prompt_height(height: int) -> int:
    """How many rows the composer gets.

    It is the input and nothing else now — no border, no footer inside it — so
    the same number of rows buys three times as much room to type in.
    """
    if height >= 34:
        return 5
    if height >= 24:
        return 4
    if height >= 18:
        return 3
    return 2


def compute(width: int, height: int, sidebar: bool = True,
            buttons: bool = True) -> Geometry:
    """Lay out one frame for a terminal of this size."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return Geometry(width=width, height=height, tier="xs",
                        chat=Rect(0, 0, max(1, width), max(1, height)),
                        prompt=Rect(0, 0, max(1, width), 1),
                        header=Rect(0, 0, max(1, width), 1),
                        footer=Rect(0, 0, max(1, width), 1),
                        too_small=True)

    tier = tier_for(width)
    # Air at the sides, which is most of what makes this read as typeset rather
    # than as a form. Narrow terminals cannot spare it.
    margin = 2 if width >= 80 else 1
    left = margin
    inner_width = width - 2 * margin

    header = Rect(left, 0, inner_width, 1)           # the rule is the row below

    editor_height = prompt_height(height)
    # rule + editor + air + hints
    footer_block = 1 + editor_height + 1 + 1
    # Nothing above the body any more: the name moved into the sidebar and
    # the model on to the status line, so the two rows the header used and
    # the one of air under it all go back to the transcript.
    body_top = 0
    body_height = height - body_top - footer_block - 1
    if body_height < 3:
        editor_height = max(1, editor_height - (3 - body_height))
        footer_block = 1 + editor_height + 1 + 1
        body_height = max(1, height - body_top - footer_block - 1)

    side_width = sidebar_width(tier) if sidebar else 0
    if side_width and inner_width - side_width - GAP < 48:
        side_width = 0                               # not enough left to read in

    sidebar_rect: Rect | None = None
    chat_x = left
    chat_width = inner_width

    if side_width:
        # The sidebar sits on the right and the transcript takes the rest.
        #
        # It used to be on the left, on the reasoning that a reader's eye
        # starts there. That is true, and it is the argument against: what a
        # reader's eye should land on first is the conversation, not a column
        # of counters. The sidebar is reference material — how many tokens,
        # which servers, which folder — consulted rather than read, and
        # reference material belongs where the eye goes second.
        sidebar_rect = Rect(left + inner_width - side_width, body_top,
                            side_width, body_height)
        chat_x = left
        chat_width = inner_width - side_width - GAP

    # Past a certain measure the line stops being readable; the surplus becomes
    # margin rather than longer lines.
    chat_width = min(chat_width, MAX_MEASURE)

    chat = Rect(chat_x, body_top, chat_width, body_height)

    rule_y = body_top + body_height + 1
    prompt = Rect(left, rule_y + 1, inner_width, editor_height)
    footer = Rect(left, prompt.bottom + 1, inner_width, 1)

    hints: dict[str, Rect] = {}
    if buttons and tier != "xs" and inner_width >= 52:
        hints = _hint_rects(footer)

    return Geometry(
        width=width, height=height, tier=tier,
        chat=chat, prompt=prompt, header=header, footer=footer,
        sidebar=sidebar_rect, hints=hints, margin=margin,
    )


#: What the footer offers, right to left, and how wide each one reads.
HINTS: tuple[tuple[str, str], ...] = (
    ("send", "⏎ send"),
    ("attach", "^O attach"),
    ("mode", "F3 mode"),
)
HINT_GAP = 3


def _hint_rects(footer: Rect) -> dict[str, Rect]:
    """Where each hint sits, so a pointer can still reach it.

    The buttons are gone; what they did has not. Somebody who reaches for the
    mouse should find that the words at the bottom right are the words they
    were going to click.
    """
    rects: dict[str, Rect] = {}
    x = footer.right
    for name, label in reversed(HINTS):
        width = len(label)
        x -= width
        rects[name] = Rect(x, footer.y, width, 1)
        x -= HINT_GAP
    return dict(reversed(list(rects.items())))
