"""What fills the transcript before the first message.

The wordmark, centred, and three facts along the bottom: which folder, how many
skills are loaded, which version. Nothing else.

It is deliberately not a panel. A box drawn around a greeting is a border
around empty space, and the screen already has a composer under it with its own
edge — two frames stacked is the look this was rewritten to get away from. The
air around the wordmark is what does the framing.

The three facts along the bottom are the ones somebody checks before typing
anything: am I in the right directory, is my setup loaded, what am I running.
None of them changes during a session, which is why they are here and not in
the status bar.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.align import Align
from rich.console import Group, RenderableType
from rich.text import Text

from ..banner import TAGLINE, short, wordmark_for
from ..theme import Theme


@dataclass
class WelcomeInfo:
    """Everything the welcome screen might show. Anything empty is left out."""

    version: str = ""
    model: str = ""
    provider: str = ""
    project: str = ""
    skills: int = 0


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
    accent = theme.style("accent", bold=True)
    for index, line in enumerate(art):
        block.append(line, style=accent)
        if index < len(art) - 1:
            block.append("\n")
    return block


def _facts(info: WelcomeInfo, theme: Theme, width: int) -> RenderableType | None:
    """Folder, skills and version, spread across the bottom.

    Spread rather than centred: three items in a row with even gaps read as a
    footer, and the same three centred read as a sentence somebody has put
    spaces in.
    """
    label = theme.style("label")
    value = theme.style("dim")

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


def render_welcome(info: WelcomeInfo, width: int, height: int,
                   theme: Theme) -> RenderableType:
    """The empty transcript."""
    width = max(20, width)
    blocks: list[RenderableType] = []

    art = _wordmark(theme, width)
    if art is not None:
        # Pushed down a little rather than pinned to the top: a logo against
        # the first row reads as a header, and this is not one.
        lead = 2 if height >= 14 else 1
        blocks.extend(Text("") for _ in range(lead))
        blocks.append(Align.center(art, width=width))
        blocks.append(Text(""))

    tagline = Text(TAGLINE, style=theme.style("dim"))
    blocks.append(Align.center(tagline, width=width))

    if info.model:
        who = Text(no_wrap=True)
        if info.provider:
            who.append(info.provider, style=theme.style("dim"))
            who.append(" / ", style=theme.style("dim", dim=True))
        who.append(info.model, style=theme.style("accent"))
        blocks.append(Text(""))
        blocks.append(Align.center(who, width=width))

    # The facts sit at the bottom of whatever room there is, so the block reads
    # as a page with a footer rather than as a stack that stopped.
    facts = _facts(info, theme, width)
    if facts is not None:
        drawn = sum(_rows(block) for block in blocks)
        padding = max(1, height - drawn - 2)
        blocks.extend(Text("") for _ in range(padding))
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
