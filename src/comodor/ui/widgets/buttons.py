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
    """One button: a solid colour block with the label centred inside it.

    Drawn as filled rows rather than a bordered panel — that is the shape in the
    design, and it also survives a two-row-high button, where a border would
    leave no room at all for the label.
    """
    style = button_style(spec, theme, active, enabled)
    width = max(4, rect.width)
    height = max(1, rect.height)
    label_row = height // 2 if height > 1 else 0

    rows: list[Text] = []
    for index in range(height):
        if index == label_row:
            rows.append(Text(spec.label.center(width)[:width], style=style))
        elif index == label_row + 1 and height >= 3:
            rows.append(Text(spec.hint.center(width)[:width], style=style))
        else:
            rows.append(Text(" " * width, style=style))
    return Group(*rows)


def button_column(rects: dict[str, Rect], theme: Theme, busy: bool = False,
                  active: str = "") -> list[RenderableType]:
    """The stacked buttons, with the one-row gaps the geometry allotted."""
    rendered: list[RenderableType] = []
    previous_bottom: int | None = None

    for spec in BUTTONS:
        rect = rects.get(spec.name)
        if rect is None:
            continue
        if previous_bottom is not None and rect.y > previous_bottom:
            rendered.extend(Text("") for _ in range(rect.y - previous_bottom))
        # While the agent is working, SEND becomes STOP — the same position,
        # the action the user actually wants at that moment.
        display = spec
        if busy and spec.name == "send":
            display = ButtonSpec("send", "STOP", "escape", "esc", primary=True)
        rendered.append(render_button(display, rect, theme, active=active == spec.name))
        previous_bottom = rect.bottom
    return rendered


def keyboard_hints(theme: Theme) -> list[tuple[str, str]]:
    """Shown instead of buttons on a narrow terminal."""
    return [
        ("^↵", "send"),
        ("^O", "attach"),
        ("F3", "mode"),
        ("F2", "history"),
        ("^C", "quit"),
    ]
