"""The sidebar.

It shows two things, in priority order: the agent's current task list, and the
sessions you can go back to. The task list wins the space when there is a task
running, because during a long autonomous run "what is it doing and how far has
it got" is the only question that matters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from ..layout import Rect
from ..theme import Theme


@dataclass
class SessionRef:
    """One resumable session."""

    id: str
    title: str
    when: str = ""
    messages: int = 0
    current: bool = False


@dataclass
class HistoryModel:
    todos: list[dict[str, Any]] = field(default_factory=list)
    sessions: list[SessionRef] = field(default_factory=list)
    selected: int = 0
    learned_today: int = 0


_STATE_STYLE = {"done": "good", "active": "accent", "blocked": "bad", "pending": "dim"}
_STATE_GLYPH = {"done": "check", "active": "active", "blocked": "blocked",
                "pending": "pending"}


def render_history(model: HistoryModel, rect: Rect, theme: Theme) -> RenderableType:
    width = max(8, rect.width - 4)
    height = max(1, rect.height - 2)
    blocks: list[RenderableType] = []
    used = 0

    if model.todos:
        block, rows = _task_list(model.todos, width, theme, limit=height - 2)
        blocks.append(block)
        used += rows

    remaining = height - used - (2 if blocks else 0)
    if model.sessions and remaining > 2:
        if blocks:
            blocks.append(Text(""))
            blocks.append(_heading("Sessions", width, theme))
        blocks.append(_sessions(model, width, theme, limit=remaining - 1))

    if not blocks:
        return _empty(theme, width)
    return Group(*blocks)


def _heading(title: str, width: int, theme: Theme) -> Text:
    text = Text()
    text.append(title.upper(), style=theme.style("label", bold=True))
    filler = max(0, width - len(title) - 1)
    text.append(" " + theme.glyphs.divider * filler, style=theme.style("border.dim"))
    return text


def _task_list(todos: list[dict[str, Any]], width: int, theme: Theme,
               limit: int) -> tuple[RenderableType, int]:
    done = sum(1 for item in todos if item.get("state") == "done")
    rows: list[Text] = [_heading(f"Tasks {done}/{len(todos)}", width, theme)]

    # When the list is longer than the panel, keep the window around whatever
    # is active — that is the row the user is watching.
    visible = todos
    if limit > 0 and len(todos) > limit:
        active = next((index for index, item in enumerate(todos)
                       if item.get("state") == "active"), 0)
        start = max(0, min(active - limit // 2, len(todos) - limit))
        visible = todos[start:start + limit]

    glyphs = theme.glyphs
    for item in visible:
        state = str(item.get("state", "pending"))
        glyph = getattr(glyphs, _STATE_GLYPH.get(state, "pending"))
        style = theme.style(_STATE_STYLE.get(state, "dim"),
                            bold=state == "active")
        row = Text()
        row.append(f"{glyph} ", style=style)
        row.append(_fit(str(item.get("text", "")), width - 3),
                   style=style if state != "done" else theme.style("dim"))
        rows.append(row)
    return Group(*rows), len(rows)


def _sessions(model: HistoryModel, width: int, theme: Theme,
              limit: int) -> RenderableType:
    rows: list[Text] = []
    for index, session in enumerate(model.sessions[:max(1, limit)]):
        selected = index == model.selected
        row = Text()
        marker = theme.glyphs.arrow if selected else " "
        row.append(f"{marker} ", style=theme.style("accent"))
        row.append(_fit(session.title or "(untitled)", width - 3),
                   style=theme.style("value" if selected or session.current else "text",
                                     bold=session.current))
        rows.append(row)
        if session.when and width > 18:
            detail = Text(f"    {session.when}", style=theme.style("dim", dim=True))
            rows.append(detail)
    return Group(*rows)


def _empty(theme: Theme, width: int) -> RenderableType:
    return Text("no tasks yet\n\nthe agent writes its\nplan here as it works",
                style=theme.style("dim"))


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"
