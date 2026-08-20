"""How an answer containing code is drawn.

Code is the part of an answer that has to survive the trip intact and be
recognisable as code at a glance, in a panel that is also carrying prose, tool
output and diffs. Rich highlights a fenced block and stops there — a darker
rectangle with no edges and no name — so what is checked here is the rest: that
the block is framed, that it says what language it is in, and that the frame is
drawn in the interface's colours rather than the syntax theme's.

Rendered to a real console at a real width and read back as text, because the
question is what lands on the terminal, not what object was constructed.
"""

from __future__ import annotations

from rich.markdown import Markdown

from comodor.ui import console as console_module
from comodor.ui import theme as theme_module
from comodor.ui.markdown import balance, render_markdown

PYTHON = (
    "Here is the fix:\n"
    "\n"
    "```python\n"
    "def load(path):\n"
    "    return Config()\n"
    "```\n"
)


def draw(text: str, width: int = 76, **theme_args: object) -> str:
    theme = theme_module.load("ember", **theme_args)  # type: ignore[arg-type]
    console = console_module.build(theme, width=width, record=True)
    console.print(render_markdown(text, theme))
    return console.export_text()


def test_a_fenced_block_is_framed_and_named():
    output = draw(PYTHON)

    assert "python" in output
    # The frame, in the same box characters the panels use.
    assert "┌" in output and "└" in output
    assert "def load(path):" in output


def test_a_fence_with_no_language_still_says_what_it_is():
    output = draw("```\nsome text\n```\n")

    assert "code" in output
    assert "some text" in output


def test_the_label_is_what_a_person_calls_it():
    """`bash` is a program; the thing on screen is a shell command."""
    assert "shell" in draw("```bash\nls -l\n```\n")
    assert "typescript" in draw("```ts\nconst a = 1\n```\n")


def test_the_prose_around_it_is_not_in_the_frame():
    output = draw(PYTHON)
    heading, _, rest = output.partition("┌")

    assert "Here is the fix" in heading
    assert "def load" in rest


def test_rich_is_left_as_we_found_it():
    """The element table is a class attribute shared by the whole process.

    Registering the themed block on `Markdown.elements` directly would change
    how every other Markdown object in the program renders, including any a
    library elsewhere is holding.
    """
    before = dict(Markdown.elements)
    draw(PYTHON)

    assert Markdown.elements == before


def test_a_monochrome_terminal_gets_the_text_and_nothing_else():
    output = draw(PYTHON, no_color=True)

    assert "def load(path):" in output
    assert "┌" not in output


def test_an_unclosed_fence_is_closed_before_it_is_parsed():
    """Half a code fence arrives on the way to a whole one."""
    assert balance("text\n```python\ndef f():").endswith("```")
    # A finished block is left exactly as it is.
    assert balance(PYTHON) == PYTHON


def test_a_block_still_arriving_is_already_framed():
    theme = theme_module.load("ember")
    console = console_module.build(theme, width=76, record=True)
    console.print(render_markdown("```python\ndef f():", theme, streaming=True))
    output = console.export_text()

    assert "python" in output
    assert "def f():" in output
