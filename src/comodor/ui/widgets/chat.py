"""The transcript.

Scrolling is done by rendering the recent entries to segment lines and slicing
the window we want. It is the only approach that stays correct when content
wraps: a markdown answer, a diff and a table each occupy an unpredictable number
of rows, so counting entries would put the viewport in the wrong place.

**Three things carry the speaker, and each works where the others do not.**
Indentation: what you asked sits at the margin, everything the agent did in
reply is indented under it, the way a reply is indented in a printed exchange.
A surface: a different quiet band behind each, one band per message rather than
per paragraph. And a name — `You`, `Comodor` — because the first two are the
first to go. A band needs colour, which `--no-color` does not have and a
red/green-blind reader may not see the point of; indentation survives being
copied out and pasted somewhere that reflows it, but only just. The word
survives all of it, and costs one column.

**The newest line is at the bottom**, against the composer, with the empty
space above. That is where a conversation ends, and it is where the eye already
is when the next line arrives.

Tool calls render as a mark, a verb and a target with the time on the right,
rather than as raw JSON: `✓ edit  src/app.py    0.2s` with a coloured diff
under it says what happened; an arguments blob does not. The mark has an ASCII
form, so the outcome of a call is legible on a terminal that can draw neither
the glyph nor the colour.
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


#: The entry kinds that mean a conversation has started.
#:
#: A notice or an error is not one of them, and that distinction is the whole
#: point of this list. A server that would not connect, or a setting the config
#: asked for and did not get, both arrive before anybody has typed anything —
#: and testing the transcript for emptiness would let either of them replace
#: the opening screen with a conversation containing one warning and nothing
#: else. What ends that screen is somebody saying something.
SPEAKERS = ("user", "assistant")


def is_new_session(entries: list[Entry]) -> bool:
    """Whether this session is still the one that has not started.

    True for a fresh session and for one that has just been cleared; false the
    instant the first message is added, and false for a restored conversation
    from its first frame, because restoring fills the transcript before the
    first frame is drawn.
    """
    return not any(entry.kind in SPEAKERS for entry in entries)


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

#: Who said it. The band behind a turn already answers this, and on most
#: terminals that is enough — but `--no-color` has no bands at all, and neither
#: does a screen reader. A word costs one column and works everywhere a colour
#: does not, which is the whole argument for putting it there.
YOU = "You"
ASSISTANT = "Comodor"


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
    """At the margin, named, on its own surface.

    The name goes on the same row as the words rather than above them. A
    one-line question with a label over it is two rows to say one thing, and a
    conversation is mostly one-line questions — measured on a twenty-row
    window, a row per turn is a whole exchange off the top of the screen. The
    answer below can afford the row; this cannot.

    Right-to-left text is set to the right of the column, which is where a
    Persian or Arabic reader's line begins. Left-aligning it would be the
    equivalent of setting an English paragraph ragged-right against the wrong
    margin: legible, and obviously not meant for you.
    """
    body = Text(justify="right" if is_rtl(entry.text) else "left")
    body.append(f"{YOU} ", style=theme.style("user", bold=True))
    body.append(f"{theme.glyphs.arrow} ", style=theme.style("user", dim=True))
    body.append(isolate(entry.text), style=theme.style("user"))
    return _banded(body, theme, "surface_user")


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

    # The name on a row of its own, which the question above could not afford
    # and this can. An answer is prose, a diff and a fenced block; prefixing
    # its first line would put a label inside the Markdown and lose it the
    # moment the answer opens with a heading or a list.
    name = Text(ASSISTANT, style=theme.style("assistant", bold=True))
    return _banded(Group(name, body), theme, "surface_assistant",
                   indent=len(INDENT))


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


def marker(theme: Theme, ok: bool = True, running: bool = False,
           queued: bool = False) -> tuple[str, str]:
    """What a tool call did, and the colour to say it in.

    Four states and four marks: done, working, waiting, failed. They are the
    marks a terminal has always used for this, not icons — a glyph that only
    renders in a patched font is a state nobody on a plain terminal can read,
    and every one of these has an ASCII form for the terminals that cannot
    draw even these.
    """
    glyphs = theme.glyphs
    if queued:
        return glyphs.queued, "muted"
    if running:
        return glyphs.running, "brand"
    if ok:
        return glyphs.ok, "success"
    return glyphs.failed, "danger"


def _tool(entry: Entry, theme: Theme, width: int) -> RenderableType:
    """``✓ edit  src/app.py                                        0.2s``

    A mark, a verb, a target, and the time against the right margin. Aligned in
    columns, because a run of tool calls is a table whether or not it is drawn
    as one, and a ragged left edge makes it unreadable.

    The mark is what makes the column scannable. Colour said the same thing
    already, and said it to nobody running `--no-color`, nobody colour-blind on
    the red/green axis, and nobody reading a copied transcript.
    """
    meta = entry.meta
    ok = meta.get("ok", True)
    running = meta.get("running", False)
    elapsed = meta.get("elapsed", 0.0)

    verb, _, target = (meta.get("summary") or entry.text).partition(" ")
    glyph, tone = marker(theme, ok=ok, running=running)
    header = Text()
    header.append(f"{glyph} ", style=theme.style(tone, bold=True))
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
                      console: Console, scroll: int = 0
                      ) -> tuple[RenderableType, int]:
    """Return the visible slice and the total number of rendered rows.

    ``scroll`` counts rows *up from the bottom*, so zero means pinned to the
    newest output — which is where a streaming interface should stay unless the
    user deliberately scrolls back.
    """
    width = max(10, rect.width)
    height = max(1, rect.height)

    if not entries:
        # An empty column, not a greeting. The opening screen is its own
        # layout now — logo, composer and the two rows under it — and drawing
        # a second one inside the transcript would mean two places deciding
        # what a fresh session looks like.
        return Lines(_exactly([], height)), 0

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
