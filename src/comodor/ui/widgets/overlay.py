"""Modal dialogs: approvals, pickers, help, and the memory browser.

Overlays take the whole screen rather than floating over the transcript. In a
terminal that is the honest choice — there is no shadow or blur to separate a
floating panel from the text behind it, and a permission dialog that can be
misread as part of the conversation is a permission dialog that gets approved
without being read.

The approval dialog is the important one. It shows the exact command, or the
exact diff, before anything happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from ...events import Request
from ..theme import Theme


@dataclass
class Choice:
    key: str                       # the key that selects it
    label: str
    value: str
    style: str = "value"


@dataclass
class Overlay:
    """A modal. ``kind`` decides how it renders and what keys it accepts."""

    kind: str                      # permission | select | info | confirm
    title: str
    body: str = ""
    detail: str = ""
    choices: list[Choice] = field(default_factory=list)
    items: list[tuple[str, str]] = field(default_factory=list)   # (label, description)
    selected: int = 0
    filter_text: str = ""
    request: Request | None = None
    on_select: Callable[[str], None] | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    # -- navigation -------------------------------------------------------- #

    @property
    def visible_items(self) -> list[tuple[str, str]]:
        if not self.filter_text:
            return self.items
        needle = self.filter_text.lower()
        return [item for item in self.items
                if needle in item[0].lower() or needle in item[1].lower()]

    def move(self, delta: int) -> None:
        count = len(self.visible_items)
        if count:
            self.selected = max(0, min(count - 1, self.selected + delta))

    def current(self) -> str:
        items = self.visible_items
        if items and 0 <= self.selected < len(items):
            return items[self.selected][0]
        return ""


# --------------------------------------------------------------------------- #
# constructors
# --------------------------------------------------------------------------- #


PERMISSION_CHOICES = [
    Choice("y", "Yes, once", "allow", "good"),
    Choice("a", "Yes, and don't ask again this session", "allow_always", "warn"),
    Choice("n", "No", "deny", "bad"),
]


def permission_overlay(request: Request) -> Overlay:
    risk = int(request.meta.get("risk", 1))
    title = {0: "Permission", 1: "Approve file change", 2: "Approve command"}.get(
        risk, "Permission")
    return Overlay(kind="permission", title=title, body=request.prompt,
                   detail=request.detail, choices=PERMISSION_CHOICES,
                   request=request)


def select_overlay(title: str, items: list[tuple[str, str]],
                   on_select: Callable[[str], None], meta: dict | None = None) -> Overlay:
    return Overlay(kind="select", title=title, items=items, on_select=on_select,
                   meta=meta or {})


def info_overlay(title: str, body: str) -> Overlay:
    return Overlay(kind="info", title=title, body=body)


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def render_overlay(overlay: Overlay, width: int, height: int,
                   theme: Theme) -> RenderableType:
    panel_width = max(40, min(width - 4, 110))
    panel_height = max(8, min(height - 4, 32))
    inner_height = panel_height - 4

    if overlay.kind == "permission":
        body = _permission_body(overlay, panel_width - 6, inner_height, theme)
    elif overlay.kind == "select":
        body = _select_body(overlay, panel_width - 6, inner_height, theme)
    else:
        body = _info_body(overlay, inner_height, theme)

    panel = Panel(
        body,
        title=Text(f" {overlay.title} ", style=theme.style("title")),
        title_align="left",
        subtitle=Text(_footer_hint(overlay, theme), style=theme.style("dim")),
        subtitle_align="right",
        box=theme.heavy_box,
        border_style=theme.style("bad" if overlay.kind == "permission" else "border"),
        width=panel_width,
        height=panel_height,
        padding=(1, 2),
    )
    return Align.center(panel, vertical="middle")


def _footer_hint(overlay: Overlay, theme: Theme) -> str:
    """The theme comes in because the arrows do.

    Written as literals, this line stayed in `↑↓` on a terminal that had just
    had its borders downgraded to `+-|` for being unable to draw them.
    """
    if overlay.kind == "permission":
        return " y / a / n "
    if overlay.kind == "select":
        glyphs = theme.glyphs
        return (f" {glyphs.rise}{glyphs.fall} select {glyphs.dot} enter confirm "
                f"{glyphs.dot} esc cancel ")
    return " esc to close "


def _permission_body(overlay: Overlay, width: int, height: int,
                     theme: Theme) -> RenderableType:
    blocks: list[RenderableType] = [
        Text(overlay.body, style=theme.style("value", bold=True)),
        Text(""),
    ]

    if overlay.detail:
        detail_rows = max(3, height - len(overlay.choices) - 4)
        blocks.append(_detail(overlay.detail, detail_rows, theme))
        blocks.append(Text(""))

    for choice in overlay.choices:
        row = Text()
        row.append(f"  [{choice.key}] ", style=theme.style("accent", bold=True))
        row.append(choice.label, style=theme.style(choice.style))
        blocks.append(row)

    return Group(*blocks)


def _detail(detail: str, rows: int, theme: Theme) -> RenderableType:
    """Show a diff coloured, a command as a command, anything else as text."""
    lines = detail.splitlines()
    body = Text()
    is_diff = any(line.startswith(("+++", "---", "@@")) for line in lines[:6])

    for line in lines[:rows]:
        if is_diff:
            if line.startswith(("+++", "---")):
                style = theme.style("dim")
            elif line.startswith("+"):
                style = theme.style("good")
            elif line.startswith("-"):
                style = theme.style("bad")
            elif line.startswith("@@"):
                style = theme.style("accent")
            else:
                style = theme.style("text")
        elif line.startswith("$"):
            style = theme.style("warn", bold=True)
        else:
            style = theme.style("text")
        body.append(line + "\n", style=style)

    if len(lines) > rows:
        body.append(f"… {len(lines) - rows} more lines\n", style=theme.style("dim"))
    return body


def _select_body(overlay: Overlay, width: int, height: int,
                 theme: Theme) -> RenderableType:
    blocks: list[RenderableType] = []

    search = Text()
    search.append("search: ", style=theme.style("label"))
    search.append(overlay.filter_text or "", style=theme.style("value"))
    search.append(theme.glyphs.cursor, style=theme.style("accent"))
    blocks.append(search)
    blocks.append(Text(""))

    items = overlay.visible_items
    rows = max(3, height - 3)
    start = max(0, min(overlay.selected - rows // 2, max(0, len(items) - rows)))

    for index, (label, description) in enumerate(items[start:start + rows], start=start):
        selected = index == overlay.selected
        row = Text()
        row.append(f"{theme.glyphs.arrow} " if selected else "  ",
                   style=theme.style("accent"))
        row.append(_fit(label, min(46, width // 2)),
                   style=theme.style("value" if selected else "text", bold=selected))
        if description:
            row.append("  " + _fit(description, width - 50), style=theme.style("dim"))
        blocks.append(row)

    if not items:
        blocks.append(Text("  no matches", style=theme.style("dim")))
    elif len(items) > rows:
        blocks.append(Text(f"  {overlay.selected + 1} of {len(items)}",
                           style=theme.style("dim")))
    return Group(*blocks)


def _info_body(overlay: Overlay, height: int, theme: Theme) -> RenderableType:
    from ..markdown import render_markdown

    # Some panels build their own renderable — /progress draws sparklines that
    # no amount of markdown would express.
    prepared = overlay.meta.get("renderable")
    if prepared is not None:
        return prepared

    if "\n" in overlay.body and any(marker in overlay.body
                                    for marker in ("**", "- ", "#", "`")):
        return render_markdown(overlay.body, theme)
    return Text(overlay.body, style=theme.style("text"))


def _fit(text: str, width: int) -> str:
    width = max(4, width)
    return text if len(text) <= width else text[: width - 1] + "…"
