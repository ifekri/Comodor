"""The transcript.

Scrolling is done by rendering the recent entries to segment lines and slicing
the window we want. It is the only approach that stays correct when content
wraps: a markdown answer, a diff and a table each occupy an unpredictable number
of rows, so counting entries would put the viewport in the wrong place.

**Indentation carries the speaker.** What you asked sits at the margin with a
caret; everything the agent did in reply is indented under it, the way a reply
is indented in a printed exchange. There is no coloured badge and no bracketed
role name, because a page has never needed one.

**The newest line is at the bottom**, against the composer, with the empty
space above. That is where a conversation ends, and it is where the eye already
is when the next line arrives.

Tool calls render as a verb and a target with the time on the right, rather
than as raw JSON: `edit  src/app.py    0.2s` with a coloured diff under it says
what happened; an arguments blob does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.segment import Segment
from rich.text import Text

from ..bidi import is_rtl, isolate
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


#: How far the agent's side of the exchange sits from what you asked.
INDENT = "    "
#: The verb column: `edit`, `run`, `learned`, `recalled`. One width, so a run
#: of them reads as the table it already is.
VERB = 8


def render_entry(entry: Entry, theme: Theme, width: int) -> RenderableType:
    if entry.kind == "user":
        return _user(entry, theme)
    if entry.kind == "assistant":
        return _assistant(entry, theme, width)
    if entry.kind == "tool":
        return _tool(entry, theme, width)
    if entry.kind == "memory":
        return _memory(entry, theme)
    if entry.kind == "error":
        return _indented(_line(entry.text, theme, "bad"), theme)
    if entry.kind == "notice":
        return _indented(_line(entry.text, theme, "dim"), theme)
    if entry.kind == "reasoning":
        return _indented(Text(isolate(entry.text),
                              style=theme.style("dim", dim=True)), theme)
    return _indented(_line(entry.text, theme, "text"), theme)


def _line(text: str, theme: Theme, style: str) -> Text:
    """One line of somebody else's words, fenced and set to its own margin."""
    return Text(isolate(text), style=theme.style(style),
                justify="right" if is_rtl(text) else "left")


def _indented(body: RenderableType, theme: Theme) -> RenderableType:
    from rich.padding import Padding

    return Padding(body, (0, 0, 0, len(INDENT)))


def _user(entry: Entry, theme: Theme) -> RenderableType:
    """At the margin, with the caret. The only thing that starts a column.

    Right-to-left text is set to the right of the column, which is where a
    Persian or Arabic reader's line begins. Left-aligning it would be the
    equivalent of setting an English paragraph ragged-right against the wrong
    margin: legible, and obviously not meant for you.
    """
    body = Text(justify="right" if is_rtl(entry.text) else "left")
    body.append(f"{theme.glyphs.arrow} ", style=theme.style("user", bold=True))
    body.append(isolate(entry.text), style=theme.style("user"))
    return _banded(body, theme, "user_bg")


def _banded(body: RenderableType, theme: Theme, token: str,
            indent: int = 0) -> RenderableType:
    """A quiet band behind a turn, the full width of the column.

    Through `Padding` rather than a style on the text: a background applied to
    `Text` covers the characters and stops, so a paragraph of uneven lines
    comes out looking torn. The padding paints as well, which carries the
    colour to both margins and across the blank lines inside a paragraph.

    No vertical padding at all, and that is the interesting decision. A row
    above and below looked better and cost two rows of the terminal for every
    single turn - measured on a twenty-row window, it pushed half of a
    four-turn exchange off the screen. One row still cost a turn.

    The change of colour is the boundary. Two bands that touch are still two
    bands, and a conversation you can see more of is worth more than a gap
    between the blocks.
    """
    from rich.padding import Padding

    colour = theme.palette_colour(token)
    if not colour or colour == "default":
        # A theme that wants no colour, or a terminal that was told not to.
        return body if not indent else Padding(body, (0, 0, 0, indent))
    return Padding(body, (0, 1, 0, indent + 1), style=f"on {colour}")


def _assistant(entry: Entry, theme: Theme, width: int) -> RenderableType:
    """Prose from the model, set to whichever margin its language starts at.

    Only the prose. A fenced code block inside a right-to-left answer is still
    code, and code is left-to-right in every language there is — the markdown
    renderer keeps its own alignment, so a Persian explanation of a Python
    function comes out with the sentence on the right and the function on the
    left, which is exactly how it would be printed.
    """
    justify = "right" if is_rtl(entry.text) else None
    if entry.streaming:
        body = render_streaming(entry.text, theme, justify=justify)
    else:
        body = render_markdown(entry.text, theme, justify=justify)
    return _banded(body, theme, "assistant_bg", indent=len(INDENT))


def _memory(entry: Entry, theme: Theme) -> RenderableType:
    """What it recalled, or what it just learned.

    The word carries it. `learned` and `recalled` are what happened; a glyph
    beside them was a second way of saying the same thing.
    """
    text = Text()
    text.append(entry.meta.get("verb", "recalled").ljust(VERB)[:VERB],
                style=theme.style("tool"))
    # Isolated: the verb is ours and left-to-right, the rule is theirs and may
    # not be. Without a fence between them the spaces in the middle resolve
    # against the wrong side and the two halves swap.
    text.append(isolate(entry.text), style=theme.style("dim"))
    if entry.meta.get("expanded"):
        for item in entry.meta.get("items", []):
            text.append(f"\n        {item.get('guidance', '')}",
                        style=theme.style("dim", dim=True))
    return _indented(text, theme)


def _tool(entry: Entry, theme: Theme, width: int) -> RenderableType:
    """``edit  src/app.py                                          0.2s``

    A verb, a target, and the time against the right margin. Aligned in
    columns, because a run of tool calls is a table whether or not it is drawn
    as one, and a ragged left edge makes it unreadable.
    """
    meta = entry.meta
    ok = meta.get("ok", True)
    running = meta.get("running", False)
    elapsed = meta.get("elapsed", 0.0)

    verb, _, target = (meta.get("summary") or entry.text).partition(" ")
    header = Text()
    header.append(verb.ljust(VERB - 1)[:VERB - 1],
                  style=theme.style("accent" if running else
                                    ("tool" if ok else "bad"), bold=True))
    header.append(" ")
    header.append(isolate(target.strip()),
                  style=theme.style("value" if ok else "bad"))

    right = ""
    if running:
        right = "running…"
    elif elapsed:
        right = f"{elapsed:.1f}s"
    if right:
        measure = max(0, width - len(INDENT) - header.cell_len - len(right))
        header.append(" " * measure + right, style=theme.style("dim", dim=True))

    preview = meta.get("preview", "")
    if not preview:
        return _indented(header, theme)

    body = (_diff(preview, theme) if meta.get("diff")
            else _preview(preview, theme, TOOL_PREVIEW_LINES))
    return _indented(Group(header, body), theme)


def _preview(text: str, theme: Theme, limit: int) -> Text:
    lines = text.splitlines()
    shown = lines[:limit]
    body = Text("\n".join(f"        {line}" for line in shown),
                style=theme.style("dim"))
    if len(lines) > limit:
        body.append(f"\n        … {len(lines) - limit} more lines",
                    style=theme.style("dim", dim=True))
    return body


def _diff(text: str, theme: Theme) -> Text:
    """A unified diff, coloured the way every developer already reads diffs."""
    body = Text()
    lines = text.splitlines()[:DIFF_PREVIEW_LINES]
    for line in lines:
        if line.startswith(("+++", "---")):
            style = theme.style("dim", dim=True)
        elif line.startswith("+"):
            style = theme.style("good")
        elif line.startswith("-"):
            style = theme.style("bad")
        elif line.startswith("@@"):
            style = theme.style("accent")
        else:
            style = theme.style("dim")
        body.append(f"        {line}\n", style=style)
    remaining = len(text.splitlines()) - len(lines)
    if remaining > 0:
        body.append(f"        … {remaining} more diff lines",
                    style=theme.style("dim", dim=True))
    # No trailing newline: the transcript already puts a blank row between
    # entries, and two of them reads as a gap somebody forgot to close.
    # `Text.rstrip` edits in place and returns None, which is a very quiet way
    # to hand the renderer nothing at all.
    body.rstrip()
    return body


# --------------------------------------------------------------------------- #
# the panel body
# --------------------------------------------------------------------------- #


def render_transcript(entries: list[Entry], rect: Rect, theme: Theme,
                      console: Console, scroll: int = 0,
                      status: object | None = None) -> tuple[RenderableType, int]:
    """Return the visible slice and the total number of rendered rows.

    ``scroll`` counts rows *up from the bottom*, so zero means pinned to the
    newest output — which is where a streaming interface should stay unless the
    user deliberately scrolls back.
    """
    width = max(10, rect.width)
    height = max(1, rect.height)

    if not entries:
        # The branded welcome box for a fresh session, or the simplified
        # greeting when the terminal is too narrow for the panel.
        from .welcome import WelcomeInfo, render_welcome
        info = WelcomeInfo(
            version=getattr(status, "version", "") if status else "",
            model=getattr(status, "model", "") if status else "",
            provider=getattr(status, "provider", "") if status else "",
            project=getattr(status, "project", "") if status else "",
            skills=getattr(status, "skills", 0) if status else 0,
        )
        welcome = render_welcome(info, width, height, theme)
        options = console.options.update(width=width, height=None)
        lines = console.render_lines(welcome, options, pad=False)
        return Lines(_exactly(lines, height)), 0

    recent = entries[-MAX_RENDERED_ENTRIES:]
    blocks: list[RenderableType] = []
    for index, entry in enumerate(recent):
        if index:
            blocks.append(Text(""))
        blocks.append(render_entry(entry, theme, width))

    options = console.options.update(width=width, height=None)
    lines = console.render_lines(Group(*blocks), options, pad=False)

    total = len(lines)
    if total <= height:
        # Against the composer, with the space above it. There is no frame to
        # hold the column open any more, so the padding has to be real rows —
        # and a conversation that grows upward from the bottom is what every
        # other one on the machine does.
        return Lines(_exactly([[]] * (height - total) + lines, height)), total

    scroll = max(0, min(scroll, total - height))
    end = total - scroll
    start = max(0, end - height)
    return Lines(_exactly(lines[start:end], height)), total


def _exactly(lines: list, height: int) -> list:
    """Exactly this many rows, padded or cropped.

    With the frames gone there is nothing else holding the column open, so the
    transcript has to be its own full height — otherwise a short conversation
    pulls the composer and the footer up the screen, and every reply moves them
    back down again.
    """
    if len(lines) < height:
        return lines + [[]] * (height - len(lines))
    return lines[:height]


def _welcome(theme: Theme) -> RenderableType:
    """The empty state — the first thing a new user reads.

    Centred rather than pinned to the bottom. A transcript grows upward from
    the composer because that is where its last line belongs; an empty screen
    has no last line, and a paragraph hanging off the bottom edge of an
    otherwise blank page reads as a mistake.
    """
    rows = (
        ("type a task", "and press Enter"),
        ("/help", "every command"),
        ("/mode", "act, plan or chat"),
        ("/memory", "what it has learned"),
        ("F2", "the task list"),
    )

    body = Text()
    body.append("It learns the way you correct it.\n\n", style=theme.style("title"))
    for key, description in rows:
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
