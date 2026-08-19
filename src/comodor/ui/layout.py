"""Responsive geometry.

The interface must be usable in a 40-column SSH window and in a 240-column
ultrawide, so the layout is recomputed from ``console.size`` on every frame
rather than fixed at startup. Resizing the terminal therefore just works.

Geometry is computed *here* and the widgets are then rendered at exactly those
sizes, instead of letting a layout engine decide and asking it afterwards where
things landed. That is what makes mouse hit-testing reliable: the rectangle used
to draw the SEND button is the same rectangle a click is tested against.

Breakpoints:

======== ===========================================================
 width    layout
======== ===========================================================
 < 60     one column; the sidebar becomes an overlay on F2
 60-99    narrow sidebar (22), compact status block
 100-139  the reference design: sidebar 26, three stacked buttons
 >= 140   wide sidebar (32); the chat panel takes the extra room
======== ===========================================================
"""

from __future__ import annotations

from dataclasses import dataclass, field

MIN_WIDTH = 40
MIN_HEIGHT = 12

SIDEBAR_NARROW = 22
SIDEBAR_NORMAL = 26
SIDEBAR_WIDE = 32
BUTTON_WIDTH = 12
GAP = 1


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
    sidebar: Rect | None = None
    status: Rect | None = None
    buttons: dict[str, Rect] = field(default_factory=dict)
    too_small: bool = False
    margin: int = 1

    @property
    def show_sidebar(self) -> bool:
        return self.sidebar is not None

    @property
    def show_buttons(self) -> bool:
        return bool(self.buttons)

    def hit(self, x: int, y: int) -> str:
        """Which region a click landed in."""
        for name, rect in self.buttons.items():
            if rect.contains(x, y):
                return f"button:{name}"
        if self.status is not None and self.status.contains(x, y):
            return "status"
        if self.sidebar is not None and self.sidebar.contains(x, y):
            return "sidebar"
        if self.chat.contains(x, y):
            return "chat"
        if self.prompt.contains(x, y):
            return "prompt"
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
    return {"sm": SIDEBAR_NARROW, "md": SIDEBAR_NORMAL, "lg": SIDEBAR_WIDE}.get(tier, 0)


def prompt_height(height: int) -> int:
    """How many rows the bottom band gets.

    The full band is a bordered editor plus a status footer. On short terminals
    it collapses to a single input line, because losing the transcript is worse
    than losing the decoration.
    """
    if height >= 30:
        return 8
    if height >= 22:
        return 7
    if height >= 16:
        return 6
    return 5


def compute(width: int, height: int, sidebar: bool = True,
            buttons: bool = True) -> Geometry:
    """Lay out one frame for a terminal of this size."""
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return Geometry(width=width, height=height, tier="xs",
                        chat=Rect(0, 0, max(1, width), max(1, height)),
                        prompt=Rect(0, 0, max(1, width), 1), too_small=True)

    tier = tier_for(width)
    margin = 1 if width >= 60 and height >= 16 else 0
    left = margin
    top = margin
    inner_width = width - 2 * margin
    inner_height = height - 2 * margin

    footer_height = prompt_height(height)
    body_height = inner_height - footer_height - GAP
    if body_height < 4:                       # give the transcript priority
        footer_height = max(3, inner_height - 5)
        body_height = inner_height - footer_height - GAP

    side_width = sidebar_width(tier) if sidebar else 0
    if side_width and inner_width - side_width - GAP < 40:
        side_width = 0                        # not enough left for the chat

    sidebar_rect: Rect | None = None
    status_rect: Rect | None = None
    chat_x = left
    chat_width = inner_width

    if side_width:
        sidebar_rect = Rect(left, top, side_width, body_height)
        status_rect = Rect(left, top + body_height + GAP, side_width, footer_height)
        chat_x = left + side_width + GAP
        chat_width = inner_width - side_width - GAP

    chat_rect = Rect(chat_x, top, chat_width, body_height)

    footer_top = top + body_height + GAP
    button_rects: dict[str, Rect] = {}
    prompt_width = chat_width

    show_buttons = buttons and tier != "xs" and chat_width >= 46 and footer_height >= 5
    if show_buttons:
        prompt_width = chat_width - BUTTON_WIDTH - GAP
        button_x = chat_x + prompt_width + GAP
        # Three stacked buttons separated by a one-row gap, sized to fill the
        # footer band exactly so the column lines up with the prompt panel.
        each = max(1, (footer_height - 2 * GAP) // 3)
        for index, name in enumerate(("send", "attach", "mode")):
            button_rects[name] = Rect(button_x, footer_top + index * (each + GAP),
                                      BUTTON_WIDTH, each)

    prompt_rect = Rect(chat_x, footer_top, prompt_width, footer_height)

    return Geometry(
        width=width, height=height, tier=tier,
        chat=chat_rect, prompt=prompt_rect,
        sidebar=sidebar_rect, status=status_rect,
        buttons=button_rects, margin=margin,
    )
