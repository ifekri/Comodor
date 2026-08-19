"""The transcript panel.

Scrolling is done by rendering the recent entries to segment lines and slicing
the window we want. It is the only approach that stays correct when content
wraps: a markdown answer, a diff and a table each occupy an unpredictable number
of rows, so counting entries would put the viewport in the wrong place.

Tool calls render as compact cards rather than raw JSON. Seeing
``⚙ edit_file(path=src/app.py)  0.2s`` with a coloured diff underneath tells the
user what happened; seeing the arguments blob does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.segment import Segment
from rich.text import Text

from ..layout import Rect
from ..markdown import render_markdown, render_streaming
from ..theme import Theme

MAX_RENDERED_ENTRIES = 80          # how far back we bother re-rendering
DIFF_PREVIEW_LINES = 24
TOOL_PREVIEW_LINES = 8


@dataclass
class Entry:
    """One thing that happened, in order."""

    kind: str                       # user | assistant | tool | notice | error | memory
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    streaming: bool = False


class Lines:
    """A pre-rendered slice of segment lines, ready to place in a panel."""

    def __init__(self, lines: list[list[Segment]]) -> None:
        self.lines = lines

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        newline = Segment.line()
        for line in self.lines:
            yield from line
            yield newline


# --------------------------------------------------------------------------- #
# entry rendering
# --------------------------------------------------------------------------- #


def render_entry(entry: Entry, theme: Theme, width: int) -> RenderableType:
    if entry.kind == "user":
        return _user(entry, theme)
    if entry.kind == "assistant":
        return _assistant(entry, theme)
    if entry.kind == "tool":
        return _tool(entry, theme, width)
    if entry.kind == "memory":
        return _memory(entry, theme)
    if entry.kind == "error":
        return Text(f"{theme.glyphs.warn} {entry.text}", style=theme.style("bad"))
    if entry.kind == "notice":
        return Text(f"  {entry.text}", style=theme.style("dim"))
    if entry.kind == "reasoning":
        return Text(entry.text, style=theme.style("dim", dim=True))
    return Text(entry.text, style=theme.style("text"))


def _user(entry: Entry, theme: Theme) -> RenderableType:
    body = Text()
    body.append(f"{theme.glyphs.arrow} ", style=theme.style("user", bold=True))
    body.append(entry.text, style=theme.style("user"))
    return body


def _assistant(entry: Entry, theme: Theme) -> RenderableType:
    if entry.streaming:
        return render_streaming(entry.text, theme)
    return render_markdown(entry.text, theme)


def _memory(entry: Entry, theme: Theme) -> RenderableType:
    text = Text()
    text.append(f"{theme.glyphs.memory} ", style=theme.style("tool"))
    text.append(entry.text, style=theme.style("dim"))
    if entry.meta.get("expanded"):
        for item in entry.meta.get("items", []):
            text.append(f"\n   · {item.get('guidance', '')}", style=theme.style("dim", dim=True))
    return text


def _tool(entry: Entry, theme: Theme, width: int) -> RenderableType:
    meta = entry.meta
    ok = meta.get("ok", True)
    running = meta.get("running", False)
    elapsed = meta.get("elapsed", 0.0)

    header = Text()
    if running:
        header.append(f"{theme.glyphs.tool} ", style=theme.style("accent"))
    elif ok:
        header.append(f"{theme.glyphs.tool} ", style=theme.style("tool"))
    else:
        header.append(f"{theme.glyphs.warn} ", style=theme.style("bad"))

    header.append(meta.get("summary") or entry.text,
                  style=theme.style("value" if ok else "bad"))
    if elapsed:
        header.append(f"  {elapsed:.1f}s", style=theme.style("dim"))
    if running:
        header.append("  running…", style=theme.style("dim"))

    preview = meta.get("preview", "")
    if not preview:
        return header

    if meta.get("diff"):
        return Group(header, _diff(preview, theme))
    return Group(header, _preview(preview, theme, TOOL_PREVIEW_LINES))


def _preview(text: str, theme: Theme, limit: int) -> Text:
    lines = text.splitlines()
    shown = lines[:limit]
    body = Text("\n".join(f"  {line}" for line in shown), style=theme.style("dim"))
    if len(lines) > limit:
        body.append(f"\n  … {len(lines) - limit} more lines",
                    style=theme.style("dim", dim=True))
    return body


def _diff(text: str, theme: Theme) -> Text:
    """A unified diff, coloured the way every developer already reads diffs."""
    body = Text()
    lines = text.splitlines()[:DIFF_PREVIEW_LINES]
    for line in lines:
        if line.startswith("+++") or line.startswith("---"):
            style = theme.style("dim")
        elif line.startswith("+"):
            style = theme.style("good")
        elif line.startswith("-"):
            style = theme.style("bad")
        elif line.startswith("@@"):
            style = theme.style("accent")
        else:
            style = theme.style("dim")
        body.append(f"  {line}\n", style=style)
    remaining = len(text.splitlines()) - len(lines)
    if remaining > 0:
        body.append(f"  … {remaining} more diff lines\n", style=theme.style("dim", dim=True))
    return body


# --------------------------------------------------------------------------- #
# the panel body
# --------------------------------------------------------------------------- #


def render_transcript(entries: list[Entry], rect: Rect, theme: Theme,
                      console: Console, scroll: int = 0) -> tuple[RenderableType, int]:
    """Return the visible slice and the total number of rendered rows.

    ``scroll`` counts rows *up from the bottom*, so zero means pinned to the
    newest output — which is where a streaming interface should stay unless the
    user deliberately scrolls back.
    """
    inner_width = max(10, rect.width - 4)
    inner_height = max(1, rect.height - 2)

    if not entries:
        return _welcome(theme, inner_height), 0

    recent = entries[-MAX_RENDERED_ENTRIES:]
    blocks: list[RenderableType] = []
    for index, entry in enumerate(recent):
        if index:
            blocks.append(Text(""))
        blocks.append(render_entry(entry, theme, inner_width))

    options = console.options.update(width=inner_width, height=None)
    lines = console.render_lines(Group(*blocks), options, pad=False)

    total = len(lines)
    if total <= inner_height:
        return Lines(lines), total

    scroll = max(0, min(scroll, total - inner_height))
    end = total - scroll
    start = max(0, end - inner_height)
    return Lines(lines[start:end]), total


def _welcome(theme: Theme, height: int) -> RenderableType:
    """The empty state — the first thing a new user reads."""
    glyphs = theme.glyphs
    body = Text()
    body.append("Comodor\n", style=theme.style("accent", bold=True))
    body.append("a terminal agent that learns from every session\n\n",
                style=theme.style("dim"))
    for key, description in (
        ("type a task", "and press Enter"),
        ("/help", "every command"),
        ("/mode", "switch Act / Plan / Chat"),
        ("/memory", "see what it has learned"),
        ("F2", "toggle the sidebar"),
    ):
        body.append(f"  {glyphs.bullet} ", style=theme.style("accent"))
        body.append(key.ljust(14), style=theme.style("value"))
        body.append(f"{description}\n", style=theme.style("dim"))
    return body


def entries_from(messages: Iterable[Any]) -> list[Entry]:
    """Rebuild a transcript from stored messages, for session resume."""
    entries: list[Entry] = []
    for message in messages:
        role = getattr(message.role, "value", str(message.role))
        if role == "user":
            entries.append(Entry("user", message.content))
        elif role == "assistant" and message.content:
            entries.append(Entry("assistant", message.content))
        elif role == "tool":
            entries.append(Entry("tool", message.name, meta={
                "summary": message.name,
                "ok": not message.is_error,
                "preview": message.content[:2000],
            }))
    return entries
