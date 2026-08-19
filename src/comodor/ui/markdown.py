"""Rendering model output that is still arriving.

Markdown is written to be parsed once it is complete, but a streaming answer is
by definition incomplete: half a code fence, a dangling ``**``, a table with one
row so far. Rendering that naively makes the panel flicker between wildly
different layouts as tokens land.

The fix is to balance the text before handing it to Rich — close an open fence,
drop a trailing partial marker — and to fall back to plain text if the parser
still objects. The user sees a stable, progressively filling answer instead of a
strobing one.
"""

from __future__ import annotations

import re

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text

from .theme import Theme

_FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
_TRAILING_MARKER = re.compile(r"(\*{1,3}|_{1,3}|`)$")


def balance(text: str) -> str:
    """Close anything the stream has left open."""
    fences = _FENCE.findall(text)
    if len(fences) % 2 == 1:
        marker = fences[-1]
        text = text.rstrip() + f"\n{marker}"
    # A lone trailing emphasis marker would otherwise swallow the next chunk.
    return _TRAILING_MARKER.sub("", text) if text.endswith(("*", "_", "`")) else text


def render_markdown(text: str, theme: Theme, streaming: bool = False) -> RenderableType:
    """Markdown when we can, readable plain text when we cannot."""
    if not text:
        return Text("")
    if theme.no_color:
        return Text(text)

    source = balance(text) if streaming else text
    try:
        return Markdown(source, code_theme=theme.syntax, hyperlinks=False,
                        inline_code_theme=theme.syntax)
    except Exception:
        # Malformed markdown must never cost the user their answer.
        return Text(text, style=theme.style("text"))


def render_streaming(text: str, theme: Theme, cursor: bool = True) -> RenderableType:
    """The in-flight assistant message, with a blinking cursor at the end."""
    body = render_markdown(text, theme, streaming=True)
    if not cursor:
        return body
    return Group(body, Text(theme.glyphs.cursor, style=theme.style("accent")))


def plain(text: str, theme: Theme, style: str = "text") -> Text:
    return Text(text, style=theme.style(style))


def truncate_lines(text: str, limit: int, theme: Theme) -> Text:
    """Cap a block of output and say how much was hidden."""
    lines = text.splitlines()
    if len(lines) <= limit:
        return Text(text, style=theme.style("dim"))
    shown = "\n".join(lines[:limit])
    hidden = len(lines) - limit
    result = Text(shown, style=theme.style("dim"))
    result.append(f"\n… {hidden} more line{'s' if hidden != 1 else ''}",
                  style=theme.style("dim", dim=True))
    return result
