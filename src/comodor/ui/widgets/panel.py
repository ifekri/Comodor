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


def plain_box(body: RenderableType, rect: Rect, theme: Theme,
              focused: bool = False) -> Panel:
    """An untitled frame — the status block and the buttons use this."""
    return framed(body, rect, theme, title="", focused=focused)


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


def hint_line(pairs: list[tuple[str, str]], theme: Theme, separator: str = "  ") -> Text:
    """A key-hint strip: ``^C quit   F2 history   Tab focus``."""
    text = Text()
    for index, (key, label) in enumerate(pairs):
        if index:
            text.append(separator, style=theme.style("dim"))
        text.append(key, style=theme.style("accent", bold=True))
        text.append(" ", style=theme.style("dim"))
        text.append(label, style=theme.style("dim"))
    return text


def pad(body: RenderableType, top: int = 0, right: int = 0, bottom: int = 0,
        left: int = 0) -> Padding:
    return Padding(body, (top, right, bottom, left))
