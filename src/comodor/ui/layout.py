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

**There are two screens, and only two.** Before anything has been said there is
nothing to read, so that screen is arranged round the one thing you can act on:
the wordmark, a composer in the middle, and two rows underneath saying what
will answer and where it is pointed. It has no sidebar at any width — every
section of one would read zero, and room is not a reason to draw something
empty. Once a conversation exists the layout below takes over and the sidebar
appears if the terminal is wide enough to hold it.

The active session's rows, from the top:

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

#: The two screens this interface has. There is no third: a session either has
#: something in it or it does not, and every question the layout asks — is
#: there a sidebar, where does the composer sit — is answered by which.
NEW = "new"
ACTIVE = "active"

#: How wide the composer is allowed to get on the opening screen.
#:
#: It is the only thing on that screen you can act on, so it is drawn large;
#: but a text box the width of an ultrawide terminal is a hundred and eighty
#: columns of empty box, and the sentence somebody types into it is short. The
#: measure is the same argument as `MAX_MEASURE` below, applied to input.
COMPOSER_MAX = 76
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
    #: Which of the two screens this frame is. `NEW` is the opening one; every
    #: other frame is `ACTIVE`.
    stage: str = ACTIVE
    #: The box drawn round the composer on the opening screen, borders
    #: included. `prompt` is the editable area inside it, which is what a click
    #: is tested against. `None` in an active session, which has no box.
    composer: Rect | None = None
    #: Where the folder, skill count and version go on the opening screen.
    #: `None` when the terminal is too short to spend a row on them.
    metadata: Rect | None = None
    sidebar: Rect | None = None
    #: One rectangle per hint on the footer line, so the mouse still works even
    #: though the buttons it used to click are gone.
    hints: dict[str, Rect] = field(default_factory=dict)
    too_small: bool = False
    margin: int = 2

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
        # Anywhere in the opening screen's box, including its border, puts the
        # cursor in the editor. Requiring the two-cell inset would leave a
        # frame you can see, aim at and miss.
        if self.composer is not None and self.composer.contains(x, y):
            return "prompt"
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
            buttons: bool = True, stage: str = ACTIVE) -> Geometry:
    """Lay out one frame for a terminal of this size."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return Geometry(width=width, height=height, tier="xs",
                        chat=Rect(0, 0, max(1, width), max(1, height)),
                        prompt=Rect(0, 0, max(1, width), 1),
                        header=Rect(0, 0, max(1, width), 1),
                        footer=Rect(0, 0, max(1, width), 1),
                        stage=stage, too_small=True)

    if stage == NEW:
        return _opening(width, height)

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
        width=width, height=height, tier=tier, stage=ACTIVE,
        chat=chat, prompt=prompt, header=header, footer=footer,
        sidebar=sidebar_rect, hints=hints, margin=margin,
    )


def _opening(width: int, height: int) -> Geometry:
    """The screen before anything has been said.

    **No sidebar, at any width.** Every section of one would read zero on this
    screen, and a column of zeros beside a wordmark is furniture. The rule is
    the width, not the room: a two-hundred-column terminal has space for a
    sidebar and still has nothing to put in it.

    The composer is the only thing here you can act on, so it is drawn as a box
    in the middle rather than as a line at the bottom. Everything else is set
    around it: the wordmark above, and two rows underneath saying what will
    answer and where it is pointed. Those two rows are pinned to the bottom, so
    the air collects between the logo and the box rather than under the page.
    """
    margin = 2 if width >= 80 else 1
    left = margin
    inner_width = width - 2 * margin

    # Built from the bottom, because everything below the box has a fixed
    # height and the logo block is what absorbs the difference. Doing it the
    # other way round is how a short terminal ends up drawing the metadata row
    # one line below its last row.
    #
    # Air, the status row, air, the metadata row — and on a terminal too short
    # to spend four rows on furniture, the metadata goes. It is the least
    # urgent of the four: a folder and a version are worth a row when there is
    # one, and not worth the box being a line shorter when there is not.
    with_metadata = height >= MIN_HEIGHT + 6
    tail = 4 if with_metadata else 2

    rows = _composer_rows(height)
    while rows > 1 and height - (rows + 2) - tail < 1:
        rows -= 1                                    # the logo block goes first
    box_height = rows + 2                            # its two borders

    box_width = min(inner_width, COMPOSER_MAX)
    box_x = left + (inner_width - box_width) // 2

    logo_height = max(1, height - box_height - tail)
    box_y = logo_height

    composer = Rect(box_x, box_y, box_width, box_height)
    # The editable area, which is what a click has to land in and what the
    # editor is rendered at. One cell of padding inside each border, so the
    # first character is not against the frame.
    prompt = Rect(box_x + 2, box_y + 1, max(1, box_width - 4), rows)

    status_y = min(height - 1, box_y + box_height + 1)
    header = Rect(left, 0, inner_width, 1)
    footer = Rect(left, status_y, inner_width, 1)
    chat = Rect(left, 0, inner_width, logo_height)
    metadata = (Rect(left, min(height - 1, status_y + 2), inner_width, 1)
                if with_metadata else None)

    return Geometry(
        width=width, height=height, tier=tier_for(width), stage=NEW,
        chat=chat, prompt=prompt, header=header, footer=footer,
        composer=composer, metadata=metadata, sidebar=None, hints={},
        margin=margin,
    )


def _composer_rows(height: int) -> int:
    """How many rows you get to type on before the first message.

    More than the active session's composer at the same height. It is the
    subject of this screen rather than a strip under a conversation, and a
    first instruction to an agent is usually a paragraph.
    """
    if height >= 34:
        return 6
    if height >= 26:
        return 5
    if height >= 20:
        return 4
    if height >= 16:
        return 3
    return 1


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
