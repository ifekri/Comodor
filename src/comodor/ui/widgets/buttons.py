"""SEND, ATTACH and MODE — clickable, and reachable from the keyboard.

Every button has a key binding as well as a hit rectangle. Mouse support depends
on the terminal cooperating; a key binding does not, so the interface is fully
operable either way. Where the mouse is unavailable the labels still show their
shortcut, rather than silently becoming decoration.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.style import Style
from rich.text import Text

from ..layout import Rect
from ..theme import Theme


@dataclass(frozen=True)
class ButtonSpec:
    name: str
    label: str
    hotkey: str            # what the key handler matches
    hint: str              # how the shortcut is shown
    primary: bool = False


BUTTONS: tuple[ButtonSpec, ...] = (
    ButtonSpec("send", "SEND", "ctrl+enter", "^↵", primary=True),
    ButtonSpec("attach", "ATTACH", "ctrl+o", "^O"),
    ButtonSpec("mode", "MODE", "f3", "F3"),
)

BY_NAME = {spec.name: spec for spec in BUTTONS}


def button_style(spec: ButtonSpec, theme: Theme, active: bool = False,
                 enabled: bool = True) -> Style:
    if theme.no_color:
        return Style(reverse=True, bold=spec.primary)
    if not enabled:
        return theme.style("dim")
    palette = theme.palette
    return Style(
        color=palette.button_primary_fg if spec.primary else palette.button_fg,
        bgcolor=palette.button_primary_bg if spec.primary else palette.button_bg,
        bold=True,
        reverse=active,
    )


def render_button(spec: ButtonSpec, rect: Rect, theme: Theme, active: bool = False,
                  enabled: bool = True) -> RenderableType:
    """One button: a solid colour block, filled by what is in it.

    Drawn as filled rows rather than as a bordered panel — that is the shape in
    the design, and a border would leave a two-row button no room at all for a
    label.

    The rows are earned rather than padded. A two-row button used to put the
    label on the lower row and leave the upper one blank, which on screen is
    not a button with a label in it: it is a coloured bar with a word under it,
    and the gap reads as a mistake. Two rows is exactly enough for the label
    and the keystroke that does the same thing, so that is what goes there —
    and the shortcut, which the interface already knew and had nowhere to
    print, stops being invisible.
    """
    style = button_style(spec, theme, active, enabled)
    width = max(4, rect.width)
    height = max(1, rect.height)

    def row(text: str) -> Text:
        return Text(text.center(width)[:width], style=style)

    if height == 1:
        return row(spec.label)
    if height == 2:
        return Group(row(spec.label), row(spec.hint))

    # Taller than it needs to be: centre the pair and fill around it.
    top = (height - 2) // 2
    rows = [row("") for _ in range(top)]
    rows.extend((row(spec.label), row(spec.hint)))
    rows.extend(row("") for _ in range(height - len(rows)))
    return Group(*rows)


def keyboard_hints(theme: Theme) -> list[tuple[str, str]]:
    """What the bottom right offers, in the order the geometry places it."""
    from ..layout import HINTS

    return [(label.split(" ", 1)[0], label.split(" ", 1)[1]) for _, label in HINTS]


def hint_line(pairs: list[tuple[str, str]], theme: Theme) -> Text:
    """``⏎ send   ^O attach   F3 mode`` — the key lit, the word quiet.

    This is what the three coloured buttons became. They were the loudest
    thing on the screen and the least often used; a word you can still click
    costs one line and no attention.
    """
    line = Text()
    for index, (key, what) in enumerate(pairs):
        if index:
            line.append("   ", style=theme.style("dim"))
        line.append(key, style=theme.style("accent"))
        line.append(f" {what}", style=theme.style("dim"))
    return line
