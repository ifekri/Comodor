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

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.markdown import CodeBlock, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from .theme import Theme

_FENCE = re.compile(r"^\s*(```|~~~)", re.MULTILINE)
_TRAILING_MARKER = re.compile(r"(\*{1,3}|_{1,3}|`)$")


def balance(text: str) -> str:
    """Close anything the stream has left open.

    Order matters, and it used to be the other way round. The fence was closed
    first and the dangling-marker strip ran second — on text that now ended in
    the three backticks this function had just written, so it took one of them
    straight back off. Every streaming answer containing code went to the
    parser with a two-backtick fence, which closes nothing, and the code was
    laid out as prose until the model happened to finish the block.

    So the strip goes first. It leaves alone a run of backticks that is opening
    a fence rather than trailing a word.
    """
    lines = text.split("\n")
    # A lone trailing emphasis marker would otherwise swallow the next chunk.
    if text.endswith(("*", "_", "`")) and not _FENCE.match(lines[-1]):
        text = _TRAILING_MARKER.sub("", text)

    fences = _FENCE.findall(text)
    if len(fences) % 2 == 1:
        text = text.rstrip() + f"\n{fences[-1]}"
    return text


#: What a fence says it is, and what a person calls it.
_LANGUAGES = {
    "py": "python", "js": "javascript", "ts": "typescript", "sh": "shell",
    "bash": "shell", "zsh": "shell", "console": "shell", "yml": "yaml",
    "rs": "rust", "rb": "ruby", "kt": "kotlin", "cs": "c#", "md": "markdown",
    "": "code", "text": "code",
}


def _code_element(theme: Theme) -> type[CodeBlock]:
    """A fenced block, framed and named.

    Rich renders a code block as a bare rectangle of highlighted text. The
    highlighting was always there; what was missing is everything around it —
    where the code starts, where it stops, and what language it is in. In a
    transcript that scrolls past tool output, diffs and prose, an unlabelled
    rectangle is just a darker paragraph.

    So it gets the same treatment as everything else on screen: a hairline
    frame with the language on its top edge, in the interface's own colours
    rather than in the syntax theme's. The frame is what separates code from
    the sentence that introduced it; the label is what tells you whether you
    are looking at Python or at a shell command, which for a line like
    `comodor doctor --fix` is not otherwise obvious.

    Wrapping stays on. A long line that wraps is awkward; a long line that is
    cropped is a line of code the reader cannot see, and code is the one thing
    in an answer that has to arrive intact.
    """

    class ThemedCodeBlock(CodeBlock):
        def __rich_console__(self, console: Console,
                             options: ConsoleOptions) -> RenderResult:
            code = str(self.text).rstrip()
            name = (self.lexer_name or "").lower()
            label = _LANGUAGES.get(name, name or "code")

            syntax = Syntax(code, self.lexer_name or "text", theme=self.theme,
                            word_wrap=True, padding=0, background_color="default")
            yield Panel(
                syntax,
                box=theme.box,
                border_style=theme.style("border.dim"),
                title=Text(f" {label} ", style=theme.style("dim")),
                title_align="left",
                padding=(0, 1),
                expand=True,
            )

    return ThemedCodeBlock


class _Markdown(Markdown):
    """Markdown that renders code the way this interface renders everything."""

    def __init__(self, markup: str, theme: Theme, **kwargs: object) -> None:
        super().__init__(markup, **kwargs)  # type: ignore[arg-type]
        # A copy, not the class attribute: mutating Markdown.elements would
        # change every Markdown object in the process, including any a library
        # elsewhere is holding.
        self.elements = {**Markdown.elements, "fence": _code_element(theme),
                         "code_block": _code_element(theme)}


def render_markdown(text: str, theme: Theme, streaming: bool = False,
                    justify: str | None = None) -> RenderableType:
    """Markdown when we can, readable plain text when we cannot.

    `justify` is how a right-to-left answer gets set against the right margin.
    It reaches the paragraphs and leaves the code blocks alone, which is what
    is wanted: a Persian explanation of a Python function belongs on the right,
    and the function does not.
    """
    if not text:
        return Text("")
    if theme.no_color:
        return Text(text, justify=justify)

    source = balance(text) if streaming else text
    try:
        return _Markdown(source, theme, code_theme=theme.syntax, hyperlinks=False,
                         justify=justify)
    except Exception:
        # Malformed markdown must never cost the user their answer.
        return Text(text, style=theme.style("text"), justify=justify)


def render_streaming(text: str, theme: Theme, cursor: bool = True,
                     justify: str | None = None) -> RenderableType:
    """The in-flight assistant message, with a blinking cursor at the end."""
    body = render_markdown(text, theme, streaming=True, justify=justify)
    if not cursor:
        return body
    return Group(body, Text(theme.glyphs.cursor, style=theme.style("accent")))


def plain(text: str, theme: Theme, style: str = "text") -> Text:
    return Text(text, style=theme.style(style))


