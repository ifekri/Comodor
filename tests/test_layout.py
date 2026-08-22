"""Responsive layout and rendering, at sizes no developer will remember to try.

Every case renders the real interface through a fixed-size console and asserts
the frame is exactly the terminal's dimensions with nothing overflowing. That is
the whole "works in any terminal" claim, checked mechanically.
"""

from __future__ import annotations

import io
from itertools import pairwise

import pytest
from rich.console import Console

from comodor.ui import layout as layout_module
from comodor.ui import theme as theme_module
from comodor.ui.screen import Screen, ScreenState
from comodor.ui.widgets.chat import Entry
from comodor.ui.widgets.history import HistoryModel
from comodor.ui.widgets.statusbar import StatusModel

SIZES = [
    (40, 12),      # the documented minimum
    (50, 15),
    (60, 20),
    (80, 24),      # the classic default
    (100, 30),
    (128, 36),     # the reference design
    (160, 45),
    (240, 60),     # ultrawide
    (200, 14),     # wide and very short
    (44, 50),      # narrow and very tall
]


def make_state(populated: bool = True) -> ScreenState:
    state = ScreenState()
    state.status = StatusModel(
        provider="Openrouter", model="anthropic/claude-fable-5", connected=True,
        mode="act", loop=True, gateway="Disable",
        context_limit=1_000_000, context_used=143_000, cost_usd=0.0412, lessons=7,
    )
    if populated:
        state.entries = [
            Entry("user", "add a health endpoint and a test for it"),
            Entry("memory", "recalled 3 lessons"),
            Entry("assistant", "I'll add the route.\n\n```python\nx = 1\n```"),
            Entry("tool", "edit_file", meta={
                "summary": "edit src/app.py", "ok": True, "elapsed": 0.2, "diff": True,
                "preview": "--- a/src/app.py\n+++ b/src/app.py\n+    return {'ok': True}\n",
            }),
            Entry("error", "provider timed out"),
        ]
        state.history = HistoryModel(todos=[
            {"text": "read the app factory", "state": "done"},
            {"text": "write the test", "state": "active"},
            {"text": "run the suite", "state": "pending"},
        ])
        state.editor.text = "now add a /version endpoint too, please"
        state.editor.cursor = len(state.editor.text)
    return state


def render(width: int, height: int, state: ScreenState | None = None,
           theme_name: str = "ember", ascii_borders: bool = False) -> list[str]:
    theme = theme_module.load(theme_name, ascii_borders=ascii_borders)
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, height=height,
                      theme=theme.rich_theme(), force_terminal=True,
                      color_system="truecolor", legacy_windows=False,
                      highlight=False, soft_wrap=False)
    geometry = layout_module.compute(width, height)
    console.print(Screen(console, theme).render(state or make_state(), geometry))
    return strip_ansi(buffer.getvalue()).splitlines()


def strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;:?]*[a-zA-Z]", "", text)


# --------------------------------------------------------------------------- #
# geometry
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width,expected", [
    (40, "xs"), (59, "xs"), (60, "sm"), (99, "sm"),
    (100, "md"), (139, "md"), (140, "lg"), (300, "lg"),
])
def test_breakpoints(width, expected):
    assert layout_module.tier_for(width) == expected


@pytest.mark.parametrize("width,height", SIZES)
def test_regions_never_overlap_or_leave_the_screen(width, height):
    geometry = layout_module.compute(width, height)
    if geometry.too_small:
        return

    rects = [rect for rect in (geometry.sidebar, geometry.chat, geometry.header,
                               geometry.footer, geometry.prompt)
             if rect is not None]
    rects += list(geometry.hints.values())

    for rect in rects:
        assert rect.x >= 0 and rect.y >= 0
        assert rect.right <= width, f"{rect} runs past the right edge"
        assert rect.bottom <= height, f"{rect} runs past the bottom edge"
        assert rect.width > 0 and rect.height > 0

    # The sidebar and the chat must not share columns.
    if geometry.sidebar is not None:
        assert geometry.sidebar.right <= geometry.chat.x


def test_a_tiny_terminal_is_reported_not_drawn():
    geometry = layout_module.compute(30, 8)
    assert geometry.too_small

    lines = render(30, 8)
    assert any("too small" in line.lower() for line in lines)


def test_the_sidebar_disappears_when_there_is_no_room_for_it():
    assert layout_module.compute(50, 20).sidebar is None
    assert layout_module.compute(128, 36).sidebar is not None


def test_the_key_hints_are_dropped_before_the_composer_is_squeezed():
    narrow = layout_module.compute(50, 20)
    assert not narrow.show_buttons
    assert narrow.prompt.width >= 40


def test_hit_testing_finds_the_hints():
    """The buttons are gone; what they did is not.

    Somebody who reaches for the mouse should find that the words at the bottom
    right are the words they were about to click.
    """
    geometry = layout_module.compute(128, 36)

    send = geometry.hints["send"]
    assert geometry.hit(send.x + 1, send.y) == "button:send"
    assert geometry.hit(geometry.chat.x + 5, geometry.chat.y + 5) == "chat"
    assert geometry.hit(geometry.prompt.x + 2, geometry.prompt.y) == "prompt"
    assert geometry.hit(geometry.header.x, geometry.header.y) == "header"


def test_the_hints_sit_inside_the_footer_and_do_not_overlap():
    geometry = layout_module.compute(128, 36)
    rects = sorted(geometry.hints.values(), key=lambda rect: rect.x)

    for rect in rects:
        assert rect.y == geometry.footer.y
        assert geometry.footer.x <= rect.x and rect.right <= geometry.footer.right
    for earlier, later in pairwise(rects):
        assert earlier.right < later.x


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width,height", SIZES)
def test_every_size_renders_within_its_bounds(width, height):
    lines = render(width, height)
    assert lines, "the frame must not be empty"
    assert len(lines) <= height, f"{len(lines)} rows drawn into a {height}-row terminal"
    for line in lines:
        assert len(line) <= width, f"a row is {len(line)} cells wide in {width} columns"


@pytest.mark.parametrize("width,height", SIZES)
def test_every_size_renders_when_the_session_is_empty(width, height):
    lines = render(width, height, state=make_state(populated=False))
    assert len(lines) <= height
    for line in lines:
        assert len(line) <= width


def test_the_reference_size_shows_the_designed_furniture():
    text = "\n".join(render(128, 36))
    for expected in ("Comodor", "TASKS", "act", "loop on",
                     "send", "attach", "mode"):
        assert expected in text, f"{expected!r} is missing from the interface"

    # Nothing but the rule character: a fenced code block in the transcript has
    # a frame made of the same glyph, and that one has corners on it.
    rules = [line for line in text.splitlines() if set(line.strip()) == {"─"}]
    assert len(rules) == 2, "one rule under the name, one above the composer"


def test_ascii_mode_avoids_box_drawing_characters():
    text = "\n".join(render(128, 36, ascii_borders=True))
    assert "─" not in text and "│" not in text and "┌" not in text
    assert "Comodor" in text


@pytest.mark.parametrize("name", ["ember", "ink", "paper", "midnight", "matrix", "mono"])
def test_every_theme_renders(name):
    lines = render(120, 34, theme_name=name)
    assert len(lines) <= 34


def test_scrolling_shows_earlier_output():
    state = make_state()
    state.entries = [Entry("assistant", f"paragraph number {i}") for i in range(60)]

    bottom = "\n".join(render(100, 24, state))
    state.scroll = 20
    scrolled = "\n".join(render(100, 24, state))

    assert bottom != scrolled
    assert "paragraph number 59" in bottom
    assert "paragraph number 59" not in scrolled


def test_a_long_unbroken_token_cannot_overflow_the_panel():
    state = make_state()
    state.entries = [Entry("assistant", "x" * 4000)]
    for line in render(90, 26, state):
        assert len(line) <= 90


def test_wide_characters_are_measured_in_cells_not_code_points():
    state = make_state()
    state.entries = [Entry("user", "日本語のテキストです " * 20)]
    for line in render(80, 24, state):
        assert len(line) <= 80


# --------------------------------------------------------------------------- #
# the palettes
# --------------------------------------------------------------------------- #


def test_every_palette_is_offered_and_loads():
    from comodor.ui.theme import PALETTES, load, theme_names

    assert set(theme_names()) == set(PALETTES)
    for name in theme_names():
        assert load(name).palette.name in (name, "mono")


def test_a_light_palette_paints_its_own_background():
    """Dark ink on somebody's dark terminal is not a light theme.

    No program can ask a terminal to change colour, so a light palette has to
    fill every cell itself. A dark one must not: it should sit on whatever
    black the user already chose.
    """
    from comodor.ui.theme import load

    assert load("paper").palette.paint
    assert load("ink").palette.paint
    assert not load("ember").palette.paint
    assert not load("midnight").palette.paint


def test_a_light_palette_asks_for_a_light_syntax_theme():
    """Monokai on paper renders half its tokens in near-white on near-white."""
    from comodor.ui.theme import load

    assert load("paper").syntax != "monokai"
    assert load("ember").syntax == "monokai"
    # An explicit choice still wins.
    assert load("paper", syntax="dracula").syntax == "dracula"


def test_the_painted_background_reaches_the_empty_rows():
    """Half a painted page is worse than none: the seam is the whole problem."""
    theme = theme_module.load("paper")
    buffer = io.StringIO()
    console = Console(file=buffer, width=100, height=30, theme=theme.rich_theme(),
                      force_terminal=True, color_system="truecolor",
                      legacy_windows=False, highlight=False, soft_wrap=False)
    console.print(Screen(console, theme).render(
        make_state(populated=False), layout_module.compute(100, 30)))

    background = theme.palette.background.lstrip("#")
    red, green, blue = (int(background[i:i + 2], 16) for i in (0, 2, 4))
    wanted = f"48;2;{red};{green};{blue}"
    rows = buffer.getvalue().splitlines()

    assert all(wanted in row for row in rows if row.strip()), "a row went unpainted"
