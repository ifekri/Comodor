"""The empty transcript: the wordmark, and the three facts under it."""

from __future__ import annotations

import pytest
from rich.console import Console

from comodor.ui import theme as theme_module
from comodor.ui.banner import WORDMARK_COMPACT, WORDMARK_WIDE, wordmark_for
from comodor.ui.widgets.welcome import WelcomeInfo, render_welcome


@pytest.fixture
def theme():
    return theme_module.load("cyan")


def drawn(info: WelcomeInfo, width: int, height: int, theme) -> str:
    console = Console(width=width, height=height, force_terminal=False,
                      legacy_windows=False)
    with console.capture() as caught:
        console.print(render_welcome(info, width, height, theme))
    return caught.get()


def an_info(**over) -> WelcomeInfo:
    base = {"version": "0.16.0", "model": "mimo-v2.5-pro",
            "provider": "Xiaomi MiMo", "project": "E:/AiTools/Comodo-Agent",
            "skills": 4}
    base.update(over)
    return WelcomeInfo(**base)


# --------------------------------------------------------------------------- #
# the wordmark
# --------------------------------------------------------------------------- #


def test_the_wordmark_columns_line_up():
    """Block art one cell out on the fourth letter is only visible in a
    screenshot, which is after it has shipped."""
    for art in (WORDMARK_WIDE, WORDMARK_COMPACT):
        assert len({len(line) for line in art}) == 1


def test_it_is_drawn_with_cells_not_slashes():
    """Slashes and underscores render at a different angle in every monospace
    font. A filled cell is the one glyph a terminal cannot get wrong."""
    joined = "".join(WORDMARK_WIDE) + "".join(WORDMARK_COMPACT)
    assert "█" in joined
    assert "/" not in joined and "\\" not in joined and "_" not in joined


@pytest.mark.parametrize("width,expect", [
    (140, WORDMARK_WIDE), (120, WORDMARK_WIDE), (90, WORDMARK_WIDE),
    (60, WORDMARK_COMPACT), (46, WORDMARK_COMPACT), (30, None),
])
def test_the_heaviest_that_fits_is_chosen(width, expect):
    assert wordmark_for(width) is expect


def test_a_narrow_screen_drops_it_rather_than_wrapping(theme):
    out = drawn(an_info(), 30, 16, theme)
    assert "█" not in out
    # And still says something.
    assert out.strip()


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #


def test_it_shows_the_three_facts(theme):
    out = drawn(an_info(), 100, 24, theme)
    assert "Workspace:" in out
    assert "Skill:" in out and "4" in out
    assert "version:" in out


def test_the_workspace_keeps_its_tail(theme):
    """Two projects under one parent differ at the end, and the end is the
    part that says which this is."""
    out = drawn(an_info(project="/very/long/path/that/will/not/fit/my-project"),
                70, 20, theme)
    assert "my-project" in out


def test_the_model_is_named(theme):
    out = drawn(an_info(), 100, 24, theme)
    assert "mimo-v2.5-pro" in out
    assert "Xiaomi MiMo" in out


def test_nothing_absent_is_invented(theme):
    out = drawn(WelcomeInfo(), 100, 24, theme)
    assert "None" not in out
    assert "Workspace:" not in out, "a folder nobody named must not be printed"
    assert "version:" not in out


def test_the_facts_are_spread_not_centred(theme):
    """Three items with even gaps read as a footer; the same three centred
    read as a sentence somebody has put spaces in."""
    out = drawn(an_info(), 100, 24, theme)
    line = next(row for row in out.splitlines() if "Workspace:" in row)
    assert line.startswith("Workspace:"), "it should begin at the left edge"
    assert line.rstrip().endswith("0.16.0")


# --------------------------------------------------------------------------- #
# it has to fit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width,height", [
    (120, 34), (100, 30), (80, 24), (60, 20), (46, 16), (30, 12), (24, 8),
])
def test_it_fits_the_space_it_is_given(width, height, theme):
    out = drawn(an_info(), width, height, theme)
    rows = out.splitlines()
    assert len(rows) <= height + 1, f"{len(rows)} rows in {height}"
    for row in rows:
        assert len(row.rstrip()) <= width, f"{len(row)} cells in {width}"


@pytest.mark.parametrize("name", ["cyan", "ember", "ink", "paper", "midnight",
                                  "matrix", "mono"])
def test_every_theme_draws_it(name):
    out = drawn(an_info(), 100, 24, theme_module.load(name))
    assert out.strip()


def test_it_is_actually_coloured(theme):
    console = Console(width=100, height=24, force_terminal=True,
                      color_system="truecolor", legacy_windows=False)
    with console.capture() as caught:
        console.print(render_welcome(an_info(), 100, 24, theme))
    assert "\x1b[" in caught.get(), "no escape sequences — it rendered plain"


def test_ascii_mode_draws_no_block_characters():
    """`--ascii` is for terminals that cannot render Unicode. A logo made of
    the one glyph such a terminal is certain to get wrong is the last thing
    that mode should draw."""
    out = drawn(an_info(), 100, 24, theme_module.load("cyan", ascii_borders=True))
    assert "█" not in out
    assert "#" in out, "the wordmark should still be there, in ASCII"
    for row in out.splitlines():
        assert row.isascii(), f"non-ASCII survived: {row!r}"
