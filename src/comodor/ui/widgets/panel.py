"""The bordered panel every part of the interface is built from.

One shape, used everywhere: a square border in the theme's amber, with the title
inset at the top-left — ``┌─ History ──────┐`` — which is the design's signature
and the thing that makes the interface recognisable at a glance.

Panels are always rendered at an explicit width and height taken from the
geometry, never left to size themselves, so what is drawn matches what the mouse
hit-tests against.
"""

from __future__ import annotations

from rich.align import Align
from rich.console import RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from ..layout import Rect
from ..theme import Theme


def rule(width: int, theme: Theme, style: str = "border.dim") -> Text:
    """A hairline across the measure.

    The whole of the chrome, now, along with the space either side of it. A
    rule separates without enclosing, which is the difference between a page
    and a form — and unlike a border it has no corners to get in the way of
    what is next to it.
    """
    return Text(theme.glyphs.divider * max(1, width), style=theme.style(style))


def heading(text: str, theme: Theme) -> Text:
    """A small capitalised label over a column. Sits outside anything."""
    return Text(text.upper(), style=theme.style("dim", dim=True))


def framed(body: RenderableType, rect: Rect, theme: Theme, title: str = "",
           focused: bool = False, subtitle: str = "") -> Panel:
    """A titled panel sized exactly to ``rect``."""
    border_style = theme.style("border" if focused else "border.dim")
    if theme.no_color:
        border_style = theme.style("border", bold=focused)

    return Panel(
        body,
        title=Text(f" {title} ", style=theme.style("title")) if title else None,
        title_align="left",
        subtitle=Text(f" {subtitle} ", style=theme.style("dim")) if subtitle else None,
        subtitle_align="right",
        box=theme.box,
        border_style=border_style,
        width=rect.width,
        height=rect.height,
        padding=(0, 1),
        expand=True,
    )


def centred(text: str, rect: Rect, theme: Theme, style: str = "dim") -> RenderableType:
    """A message in the middle of an otherwise empty panel."""
    return Align.center(
        Text(text, style=theme.style(style), justify="center"),
        vertical="middle",
        height=max(1, rect.height - 2),
    )


def too_small_notice(width: int, height: int, theme: Theme) -> RenderableType:
    """What to show when the terminal cannot hold the interface.

    A clear instruction beats a corrupted layout: the user can act on "make the
    window bigger", but not on a screen of overlapping fragments.
    """
    body = Text.assemble(
        ("Terminal too small\n\n", theme.style("bad", bold=True)),
        (f"current: {width}×{height}\n", theme.style("dim")),
        ("minimum: 40×12\n\n", theme.style("dim")),
        ("Resize the window, or reduce the font size.", theme.style("text")),
        justify="center",
    )
    return Align.center(body, vertical="middle")


def pad(body: RenderableType, top: int = 0, right: int = 0, bottom: int = 0,
        left: int = 0) -> Padding:
    return Padding(body, (top, right, bottom, left))
