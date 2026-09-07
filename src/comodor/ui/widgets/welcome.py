"""The opening screen.

The wordmark, a composer in the middle of the page, one row saying what will
answer, and one along the bottom saying where it is pointed. Nothing else, and
in particular no sidebar: every section of one would read zero before a
conversation exists, and a column of zeros beside a wordmark is furniture.

It is deliberately not a dashboard. The only thing on this screen you can act
on is the box in the middle, so the box in the middle is what everything else
is arranged around — the logo above it, the two rows of state beneath it, and
the air in between doing the framing.

**The composer is the real editor**, not a picture of one. It is the same
buffer, cursor and history the active session uses, drawn at the geometry's
size; typing the first character and pressing enter moves straight into the
conversation with that text intact, because there was never a second widget for
it to be lost between.

The three facts along the bottom are the ones somebody checks before typing
anything: am I in the right directory, is my setup loaded, what am I running.
None of them changes during a session, which is why they are here and not on
the status line.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.align import Align
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.text import Text

from ..banner import TAGLINE, short, wordmark_for
from ..layout import Geometry
from ..theme import Theme
from .prompt import (
    Editor,
    completions,
    menu_budget,
    render_completions,
    render_editor,
)

#: What the composer says before anything is typed into it, longest first.
#:
#: The widest one that fits is used, and there is always the last one. A
#: placeholder that wraps is two rows where the geometry allowed one, which
#: pushes the box a line taller than the screen was measured for — so this is
#: chosen against the width rather than trimmed with an ellipsis afterwards.
#:
#: Two of these are the same sentence twice, once with a middle dot and once
#: with a hyphen. `--ascii` is a promise about every glyph on the screen, and a
#: placeholder chosen purely by width breaks it on exactly the terminals that
#: are narrow enough to need the shorter form.
INVITATIONS = (
    "ask for anything, or press / for a command",
    "ask for anything  ·  / for a command",
    "ask for anything  -  / for a command",
    "ask for anything",
    "ask...",
)


def invitation(room: int, ascii_only: bool = False) -> str:
    """The widest invitation that fits, and that this terminal can draw."""
    choices = [text for text in INVITATIONS
               if not ascii_only or text.isascii()]
    return next((text for text in choices if len(text) <= room), choices[-1])


@dataclass
class WelcomeInfo:
    """Everything the opening screen might show. Anything empty is left out.

    Every field is read from live state. There is no placeholder here and no
    example value: a screen that invents a model name or a version is worse
    than one that leaves the row out, because the invented one gets believed.
    """

    version: str = ""
    model: str = ""
    provider: str = ""
    project: str = ""
    skills: int = 0
    mode: str = ""
    #: How many sub-agents are running. Zero is a real answer and prints as
    #: "off"; it is not the same as not knowing.
    agents: int = 0


def _wordmark(theme: Theme, width: int) -> RenderableType | None:
    """The logo, in one colour.

    It used to be drawn with a vertical gradient across its rows. On a
    five-row logo that is five shades nobody reads as a gradient — it reads as
    a logo that is fading out, which is the opposite of what a wordmark is for.
    """
    art = wordmark_for(width, ascii_only=theme.ascii)
    if art is None:
        return None
    block = Text(no_wrap=True)
    brand = theme.style("brand", bold=True)
    for index, line in enumerate(art):
        block.append(line, style=brand)
        if index < len(art) - 1:
            block.append("\n")
    return block


def facts_line(info: WelcomeInfo, theme: Theme, width: int) -> Text | None:
    """Folder, skills and version, spread across the bottom.

    Spread rather than centred: three items in a row with even gaps read as a
    footer, and the same three centred read as a sentence somebody has put
    spaces in.
    """
    label = theme.style("label")
    value = theme.style("secondary_text")

    pairs: list[tuple[str, str]] = []
    if info.project:
        pairs.append(("Workspace: ",
                      _tail(info.project, max(12, width // 3 - 12), theme.ascii)))
    pairs.append(("Skill: ", str(info.skills)))
    if info.version:
        pairs.append(("version: ", short(info.version)))

    parts = []
    for name, text in pairs:
        piece = Text(no_wrap=True)
        piece.append(name, style=label)
        piece.append(text, style=value)
        parts.append(piece)

    total = sum(part.cell_len for part in parts)
    if total + 4 * (len(parts) - 1) > width:
        # Not enough room to spread them; the version is the one that goes.
        parts = parts[:2]
        total = sum(part.cell_len for part in parts)
        if total + 4 > width:
            return None

    gaps = len(parts) - 1
    spare = max(gaps, width - total)
    each, extra = divmod(spare, gaps) if gaps else (0, 0)

    line = Text(no_wrap=True)
    for index, part in enumerate(parts):
        line.append_text(part)
        if index < gaps:
            line.append(" " * (each + (1 if index < extra else 0)))
    return line


def status_line(info: WelcomeInfo, theme: Theme, width: int) -> Text:
    """Mode, the two things a key does, and which model is going to answer.

    The model is the fact people most often get wrong about a session and the
    one this screen exists to settle before the first question, so it is set
    apart at the right rather than queued behind the keys. It is named from
    live configuration; when nothing has been chosen the badge is dropped
    rather than filled in with a guess.
    """
    dim = theme.style("muted", dim=True)
    glyphs = theme.glyphs

    left = Text(no_wrap=True)
    left.append("Mode: ", style=theme.style("label"))
    left.append((info.mode or "act").upper(), style=theme.style("brand", bold=True))
    left.append(" [TAB]", style=dim)

    left.append("   ")
    left.append(f"{glyphs.check} ", style=theme.style("muted"))
    left.append("Command ", style=theme.style("secondary_text"))
    left.append("/", style=dim)

    left.append("   ")
    running = info.agents > 0
    left.append(f"{glyphs.check} ", style=theme.style(
        "success" if running else "muted", dim=not running))
    left.append("Sub-agent ", style=theme.style("secondary_text"))
    left.append(str(info.agents) if running else "off",
                style=theme.style("success" if running else "muted"))
    # The command that actually reaches them. A key hint is a promise, and the
    # only thing bound to ctrl+s anywhere in this program submits an open
    # question form — so naming it here would advertise a control that does
    # not exist for a feature it has nothing to do with.
    left.append(" /delegates", style=dim)

    if not info.model:
        return _clipped(left, width)

    badge = Text(no_wrap=True)
    badge.append("MODEL ", style=theme.style("label"))
    badge.append(info.model, style=theme.style("brand", bold=True))

    # The keys go before the badge does. Knowing what is answering is worth
    # more on this screen than being reminded that `/` opens the commands.
    if left.cell_len + badge.cell_len + 3 > width:
        return _clipped(badge, width) if badge.cell_len <= width else _clipped(left, width)

    line = Text(no_wrap=True)
    line.append_text(left)
    line.append(" " * (width - left.cell_len - badge.cell_len))
    line.append_text(badge)
    return line


def _clipped(text: Text, width: int) -> Text:
    """One row, always. A status line that wraps takes a row off the composer."""
    if text.cell_len <= width:
        return text
    text.truncate(max(1, width), overflow="ellipsis")
    return text


def _composer(editor: Editor, geometry: Geometry, theme: Theme, focused: bool,
              commands: list[tuple[str, str]] | None = None,
              selected: int = 0, top: int = 0) -> RenderableType:
    """The real editor, in a box, in the middle of the page.

    A box here and a bare rule in the active session, which looks like an
    inconsistency and is not. In a conversation the composer is a strip under
    the thing you are reading and a frame round it would compete with the
    transcript; on this screen it is the subject, and the frame is what says
    where to type. It is drawn with the theme's own box, so `--ascii` gets an
    ASCII frame rather than a row of question marks.

    The command menu is drawn *inside* the box, over the editor's own rows, the
    same way the active session draws it over the composer strip. The box
    cannot grow: the whole screen is measured against a geometry that gave it
    a fixed height, and a menu that pushed it taller would push the two rows
    beneath it off the bottom of the terminal.
    """
    rect = geometry.prompt
    box = geometry.composer
    rows = max(1, rect.height)

    matches = completions(editor.text, commands or [])
    # Rows for the menu including its overflow indicator, leaving the editor
    # at least one row to type on.
    listed = menu_budget(len(matches), rows - 1) if rows > 1 else 0

    # One cell for the cursor block that is drawn in front of it.
    body: RenderableType = render_editor(
        editor, rect, theme,
        placeholder=invitation(max(1, rect.width - 1), theme.ascii),
        focused=focused, rows=max(1, rows - listed))
    if listed:
        body = Group(body, render_completions(matches, theme, selected,
                                              limit=listed, top=top,
                                              width=rect.width))

    surface = theme.palette_colour("surface_user")
    panel = Panel(
        body,
        box=theme.box,
        width=box.width if box is not None else rect.width + 4,
        padding=(0, 1),
        border_style=theme.style("border_active" if focused else "border"),
        style=f"on {surface}" if surface and surface != "default" else "",
    )
    return Align.center(panel, width=geometry.width - 2 * geometry.margin)


def render_welcome(info: WelcomeInfo, width: int, height: int,
                   theme: Theme) -> RenderableType:
    """The logo block: the wordmark, the tagline, and what is answering.

    Exactly ``height`` rows, and vertically centred inside them. Both halves of
    that matter. Centred, because a logo against the first row reads as a
    header and this is not one. Exactly, because the composer is placed under
    this block by the geometry — a block that renders shorter than its budget
    pulls the box up the screen and leaves the metadata row floating in the
    middle of the page.
    """
    width = max(20, width)
    blocks: list[RenderableType] = []

    art = _wordmark(theme, width)
    if art is not None:
        blocks.append(Align.center(art, width=width))
        blocks.append(Text(""))

    blocks.append(Align.center(Text(TAGLINE, style=theme.style("muted")),
                               width=width))

    if info.model:
        who = Text(no_wrap=True)
        if info.provider:
            who.append(info.provider, style=theme.style("muted"))
            who.append(" / ", style=theme.style("muted", dim=True))
        who.append(info.model, style=theme.style("brand"))
        blocks.append(Text(""))
        blocks.append(Align.center(who, width=width))

    drawn = sum(_rows(block) for block in blocks)
    while blocks and drawn > height:
        # Too little room for all of it. The model line goes first, then the
        # tagline, then the wordmark — least useful first, and the logo last
        # because it is the only one still saying which program this is. It
        # goes too rather than overflowing: a screen with three startup
        # warnings on it has spent its rows on something that matters more,
        # and the block has to be the height it was given either way.
        blocks.pop()
        drawn = sum(_rows(block) for block in blocks)

    lead = max(0, (height - drawn) // 2)
    trail = max(0, height - drawn - lead)
    return Group(*([Text("")] * lead + blocks + [Text("")] * trail))


def render_opening(info: WelcomeInfo, editor: Editor, geometry: Geometry,
                   theme: Theme, focused: bool = True,
                   notices: list[RenderableType] | None = None,
                   logo_rows: int | None = None,
                   commands: list[tuple[str, str]] | None = None,
                   selected: int = 0, top: int = 0) -> RenderableType:
    """The whole screen, in the order it is read.

    ``notices`` are anything that happened before the first message — a server
    that would not connect, a setting the config asked for and did not get.
    They are drawn under the logo rather than suppressed: this screen appears
    because nobody has said anything yet, which is not a reason to hide what
    the program has already found out.

    ``logo_rows`` is how much of the block above the composer is left once
    those have taken their share. The caller measures them, because measuring
    needs the console that will draw them; passing the remainder in is what
    keeps a long warning from pushing the box off the bottom of the screen.

    ``commands`` is the slash-command table, so that typing `/` here shows the
    same menu it shows in a conversation. The invitation says to press it; a
    screen that then showed nothing would be advertising a key that appears not
    to work, and the selection the arrow keys were moving would be invisible.
    """
    inner = geometry.width - 2 * geometry.margin
    if logo_rows is None:
        logo_rows = geometry.chat.height
    blocks: list[RenderableType] = [
        render_welcome(info, inner, max(0, logo_rows), theme),
    ]
    if notices:
        blocks.extend(notices)

    blocks.append(_composer(editor, geometry, theme, focused,
                            commands=commands, selected=selected, top=top))
    blocks.append(Text(""))
    blocks.append(status_line(info, theme, inner))

    if geometry.metadata is not None:
        facts = facts_line(info, theme, inner)
        if facts is not None:
            blocks.append(Text(""))
            blocks.append(facts)
    return Group(*blocks)


def _rows(block: RenderableType) -> int:
    if isinstance(block, Text):
        return len(block.split("\n")) or 1
    if isinstance(block, Align):
        return _rows(block.renderable)
    if isinstance(block, Group):
        return sum(_rows(part) for part in block.renderables)
    return 1


def _tail(path: str, width: int, ascii_only: bool = False) -> str:
    """The end of a path, which is the part that identifies it.

    The mark says something was cut. In ASCII mode it has to be three dots:
    a single ellipsis is one more character a terminal in that mode cannot
    draw, and it appears on a line whose whole job is to be readable.
    """
    mark = "..." if ascii_only else "…"
    if width <= len(mark) or len(path) <= width:
        return path
    return mark + path[-(width - len(mark)):]
