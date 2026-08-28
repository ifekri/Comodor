"""The sidebar.

Reference material, not reading material: how much context is left, which
folder, which servers are up, which sub-agents are running. It sits on the
right because the transcript is what the eye should land on first.

Sections are titled with a chevron rather than a rule, because a rule under
every heading in a twenty-four-column strip is four horizontal lines competing
with the words between them. The chevron is one character and it points at
what it names.

**Long lists fade rather than truncate.** Four MCP servers in a column with
room for two is a list that has to stop somewhere, and the two honest ways to
say so are a count or a fade. A count costs a line the column does not have;
the fade costs nothing and says the same thing — there is more here — using
the space the last row already occupies.
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
    working_dir: str = ""
    #: (name, state) where state is "connected", "connecting" or anything else.
    mcp_servers: list[tuple[str, str]] = field(default_factory=list)
    #: What this session is called, shown at the top.
    title: str = ""
    #: Context accounting, mirrored from the status model so the sidebar does
    #: not have to be handed two objects.
    tokens_used: int = 0
    tokens_limit: int = 0
    tokens_cost: float | None = None
    #: (id, state) for sub-agents that have been spawned.
    agents: list[tuple[str, str]] = field(default_factory=list)
    version: str = ""


_STATE_STYLE = {"done": "good", "active": "accent", "blocked": "bad", "pending": "dim"}
_STATE_GLYPH = {"done": "check", "active": "active", "blocked": "blocked",
                "pending": "pending"}

#: How many rows a section is allowed before it fades. Anything longer is a
#: list somebody should be reading somewhere else.
MOST_ROWS = 4


def render_history(model: HistoryModel, rect: Rect, theme: Theme) -> RenderableType:
    """The reference column. No frame; the gap to its left is the separation."""
    width = max(8, rect.width)
    height = max(1, rect.height)
    blocks: list[RenderableType] = []
    used = 0

    def room() -> int:
        return height - used - 1

    if model.title:
        head = _title(model.title, width, theme)
        blocks.append(head)
        used += _rows(head)

    if model.tokens_limit or model.tokens_used or model.agents:
        block = _context(model, width, theme)
        blocks.append(block)
        used += _rows(block)

    if model.working_dir and room() > 2:
        block = _workspace(model.working_dir, width, theme)
        blocks.append(block)
        used += _rows(block)

    if model.todos and room() > 2:
        block, rows = _task_list(model.todos, width, theme,
                                 limit=min(MOST_ROWS, room() - 1))
        blocks.append(block)
        used += rows

    if model.mcp_servers and room() > 2:
        block = _dotted("MCP", "(Active)", model.mcp_servers, width, theme,
                        limit=min(MOST_ROWS, room() - 1))
        blocks.append(block)
        used += _rows(block)

    if model.agents and room() > 2:
        block = _dotted("Agents", "", model.agents, width, theme,
                        limit=min(MOST_ROWS, room() - 1))
        blocks.append(block)
        used += _rows(block)

    if model.sessions and room() > 3:
        blocks.append(_heading("Sessions", "", width, theme))
        blocks.append(_sessions(model, width, theme, limit=room() - 2))
        used = height          # whatever is left, it took

    if not blocks:
        return _empty(theme, width)

    # Pinned to the bottom rather than appended. Appended, it sat directly
    # under whichever section happened to be last and moved up the column
    # every time a server connected — and on a full sidebar it fell off the
    # end entirely, which is how a version number stops being checkable.
    if model.version:
        drawn = sum(_rows(block) for block in blocks)
        blocks.extend(Text("") for _ in range(max(0, height - drawn - 1)))
        blocks.append(_footer(model.version, width, theme))

    return Group(*blocks)


def _rows(block: RenderableType) -> int:
    """How many lines a built block occupies."""
    if isinstance(block, Text):
        return len(block.split("\n")) or 1
    if isinstance(block, Group):
        return sum(_rows(part) for part in block.renderables)
    return 1


# --------------------------------------------------------------------------- #
# the pieces
# --------------------------------------------------------------------------- #


def _title(title: str, width: int, theme: Theme) -> RenderableType:
    """The session's name, wrapped, with a rule under it.

    The one place in the sidebar with a rule, because it is the only heading
    that names the whole column rather than a section of it.
    """
    text = Text(no_wrap=False, overflow="fold")
    text.append(isolate(title), style=theme.style("accent", bold=True))
    return Group(text, Text(theme.glyphs.divider * width,
                            style=theme.style("border")))


def _heading(name: str, note: str, width: int, theme: Theme) -> Text:
    """`❯ Name (note)` — a chevron, the name, and an optional quiet aside."""
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append(f"{theme.glyphs.arrow} ", style=theme.style("user", bold=True))
    row.append(name, style=theme.style("title", bold=True))
    if note:
        row.append(f" {note}", style=theme.style("dim"))
    return row


def _context(model: HistoryModel, width: int, theme: Theme) -> RenderableType:
    """Tokens, the limit, and how many sub-agents are out.

    Every number here is one the agent actually holds. A limit of zero is
    printed as a dash rather than as zero, because zero is a number and the
    truth is that nobody has said.
    """
    rows: list[RenderableType] = [_heading("Context", "", width, theme)]

    def line(label: str, value: str, style: str = "text") -> Text:
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append("  ")
        row.append(value, style=theme.style(style))
        row.append(f" {label}" if label else "", style=theme.style("dim"))
        return row

    if model.tokens_used:
        rows.append(line("used", f"{model.tokens_used:,}"))
    if model.tokens_limit:
        rows.append(line("", f"Limit : {_short_count(model.tokens_limit)}", "dim"))
    if model.tokens_cost is not None and model.tokens_cost > 0:
        rows.append(line("", f"${model.tokens_cost:.4f}", "dim"))
    rows.append(line("", f"Sub-agent: {len(model.agents)}", "dim"))
    rows.append(Text(""))
    return Group(*rows)


def _short_count(number: int) -> str:
    if number >= 1_000_000:
        whole = number / 1_000_000
        return f"{whole:.0f}M" if whole == int(whole) else f"{whole:.1f}M"
    if number >= 1_000:
        return f"{number // 1000}K"
    return str(number)


def _workspace(path: str, width: int, theme: Theme) -> RenderableType:
    rows: list[RenderableType] = [_heading("Workspace", "", width, theme)]
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append("  ")
    # The tail, not the head: two projects under the same parent differ at the
    # end, and the end is what identifies this one.
    row.append(_fit(path, width - 2, theme.ascii), style=theme.style("dim"))
    rows.append(row)
    rows.append(Text(""))
    return Group(*rows)


def _dotted(name: str, note: str, entries: list[tuple[str, str]], width: int,
            theme: Theme, limit: int) -> RenderableType:
    """A titled list of things with a state, fading out when it is too long."""
    rows: list[RenderableType] = [_heading(name, note, width, theme)]
    shown = entries[:max(1, limit)]

    for index, (label, state) in enumerate(shown):
        # The last rows of a truncated list are dimmed, so the column says
        # "there is more" without spending a row saying it.
        remaining = len(shown) - index
        faded = len(entries) > len(shown) and remaining <= 2
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append(f" {theme.glyphs.check} ",
                   style=theme.style(_dot_style(state), dim=faded))
        row.append(_fit(label, width - 3, theme.ascii),
                   style=theme.style("text" if not faded else "dim", dim=faded))
        rows.append(row)

    rows.append(Text(""))
    return Group(*rows)


def _dot_style(state: str) -> str:
    return {"connected": "good", "running": "good", "active": "good",
            "connecting": "warn", "starting": "warn",
            "failed": "bad", "error": "bad"}.get(state, "dim")


def _footer(version: str, width: int, theme: Theme) -> Text:
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append("© ", style=theme.style("dim"))
    row.append("Comodor ", style=theme.style("title", bold=True))
    row.append(f"v{version}", style=theme.style("dim"))
    return row


def _task_list(todos: list[dict[str, Any]], width: int, theme: Theme,
               limit: int) -> tuple[RenderableType, int]:
    done = sum(1 for item in todos if item.get("state") == "done")
    rows: list[RenderableType] = [
        _heading("Tasks", f"{done}/{len(todos)}", width, theme)]

    # An active task is the one being asked about, so it is never the one
    # dropped when the list does not fit.
    ordered = sorted(todos, key=lambda item: item.get("state") != "active")
    for item in ordered[:max(1, limit)]:
        state = str(item.get("state", "pending"))
        glyph = getattr(theme.glyphs, _STATE_GLYPH.get(state, "pending"))
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append(f" {glyph} ", style=theme.style(_STATE_STYLE.get(state, "dim")))
        row.append(_fit(str(item.get("text", "")), width - 3, theme.ascii),
                   style=theme.style("text" if state == "active" else "dim"))
        rows.append(row)

    rows.append(Text(""))
    return Group(*rows), len(rows)


def _sessions(model: HistoryModel, width: int, theme: Theme,
              limit: int) -> RenderableType:
    rows: list[Text] = []
    for index, session in enumerate(model.sessions[:max(1, limit)]):
        row = Text(no_wrap=True, overflow="ellipsis")
        here = index == model.selected
        row.append(f" {theme.glyphs.arrow} " if here else "   ",
                   style=theme.style("accent"))
        row.append(_fit(isolate(session.title or session.id), width - 3, theme.ascii),
                   style=theme.style("value" if here else "dim"))
        rows.append(row)
    return Group(*rows)


def _empty(theme: Theme, width: int) -> RenderableType:
    return Text("", style=theme.style("dim"))


def _fit(text: str, width: int, ascii_only: bool = False) -> str:
    mark = "..." if ascii_only else "…"
    if width <= len(mark) or len(text) <= width:
        return text
    return mark + text[-(width - len(mark)):]
