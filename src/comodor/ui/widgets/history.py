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

from ..bidi import isolate
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
    """The task column. No frame; the space to its right is the separation."""
    width = max(8, rect.width)
    height = max(1, rect.height)
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
    """A small capital label with the count against the right edge.

    It used to be a word followed by a rule running to the edge of the panel,
    which was a second border inside a border. A column that already has
    nothing else in it does not need a line drawn under its name.
    """
    name, _, count = title.partition(" ")
    text = Text()
    text.append(name.upper(), style=theme.style("dim", dim=True))
    if count:
        gap = max(1, width - len(name) - len(count))
        text.append(" " * gap)
        text.append(count, style=theme.style("dim", dim=True))
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
        # Trimmed first, then fenced: truncating an isolated string throws
        # away its closing mark, and an unbalanced isolate leaks into the rest
        # of the line, which is worse than not fencing it at all.
        row.append(isolate(_fit(str(item.get("text", "")), width - 3)),
                   style=style if state != "done" else theme.style("dim"))
        rows.append(row)
    # A blank row under the heading, which is what separates it now.
    rows.insert(1, Text(""))
    return Group(*rows), len(rows)


def _sessions(model: HistoryModel, width: int, theme: Theme,
              limit: int) -> RenderableType:
    rows: list[Text] = []
    for index, session in enumerate(model.sessions[:max(1, limit)]):
        selected = index == model.selected
        row = Text()
        marker = theme.glyphs.arrow if selected else " "
        row.append(f"{marker} ", style=theme.style("accent"))
        row.append(isolate(_fit(session.title or "(untitled)", width - 3)),
                   style=theme.style("value" if selected or session.current else "text",
                                     bold=session.current))
        rows.append(row)
        if session.when and width > 18:
            detail = Text(f"    {session.when}", style=theme.style("dim", dim=True))
            rows.append(detail)
    return Group(*rows)


def _empty(theme: Theme, width: int) -> RenderableType:
    """Nothing yet, said once and quietly."""
    body = Text("TASKS", style=theme.style("dim", dim=True))
    body.append("\n\nthe plan appears here\nonce there is one",
                style=theme.style("dim", dim=True))
    return body


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"
