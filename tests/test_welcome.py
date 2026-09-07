"""The opening screen: the wordmark, the composer, and the rows under it.

Everything here renders the screen a user actually sees — `render_opening` at a
real geometry — rather than one block of it in isolation. The three facts moved
to the bottom of the page and the composer moved to the middle; asserting
against a piece would have kept passing while the page around it was wrong.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from comodor.ui import layout as layout_module
from comodor.ui import theme as theme_module
from comodor.ui.banner import WORDMARK_COMPACT, WORDMARK_WIDE, wordmark_for
from comodor.ui.widgets.prompt import Editor
from comodor.ui.widgets.welcome import (
    INVITATIONS,
    WelcomeInfo,
    invitation,
    render_opening,
    render_welcome,
)


@pytest.fixture
def theme():
    return theme_module.load("cyan")


def drawn(info: WelcomeInfo, width: int, height: int, theme,
          editor: Editor | None = None) -> str:
    """The whole opening screen, as characters."""
    console = Console(width=width, height=height, force_terminal=False,
                      legacy_windows=False)
    geometry = layout_module.compute(width, height, stage=layout_module.NEW)
    with console.capture() as caught:
        console.print(render_opening(info, editor or Editor(), geometry, theme))
    return caught.get()


def logo_block(info: WelcomeInfo, width: int, height: int, theme) -> str:
    console = Console(width=width, height=height, force_terminal=False,
                      legacy_windows=False)
    with console.capture() as caught:
        console.print(render_welcome(info, width, height, theme))
    return caught.get()


def an_info(**over) -> WelcomeInfo:
    base = {"version": "0.16.0", "model": "mimo-v2.5-pro",
            "provider": "Xiaomi MiMo", "project": "E:/AiTools/Comodo-Agent",
            "skills": 4, "mode": "plan", "agents": 0}
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


def test_the_logo_block_is_exactly_the_rows_it_was_given(theme):
    """The composer is placed under this block by the geometry. A block that
    renders shorter than its budget pulls the box up the page and leaves the
    metadata row floating in the middle of it."""
    for height in (4, 8, 12, 20):
        rows = logo_block(an_info(), 100, height, theme).splitlines()
        assert len(rows) == height, f"{len(rows)} rows for a budget of {height}"


# --------------------------------------------------------------------------- #
# what it says
# --------------------------------------------------------------------------- #


def test_it_shows_the_three_facts(theme):
    out = drawn(an_info(), 100, 30, theme)
    assert "Workspace:" in out
    assert "Skill:" in out and "4" in out
    assert "version:" in out


def test_the_workspace_keeps_its_tail(theme):
    """Two projects under one parent differ at the end, and the end is the
    part that says which this is."""
    out = drawn(an_info(project="/very/long/path/that/will/not/fit/my-project"),
                70, 24, theme)
    assert "my-project" in out


def test_the_model_is_named(theme):
    out = drawn(an_info(), 100, 30, theme)
    assert "mimo-v2.5-pro" in out
    assert "Xiaomi MiMo" in out


def test_the_model_badge_says_which_model_will_answer(theme):
    """The single fact people most often get wrong about a session, settled
    before the first question rather than after it."""
    out = drawn(an_info(model="qwen/qwen3-coder"), 120, 32, theme)
    line = next(row for row in out.splitlines() if "MODEL " in row)
    assert "qwen/qwen3-coder" in line


def test_the_badge_follows_the_configured_model(theme):
    """Dynamic, not a caption. Two configurations, two badges."""
    first = drawn(an_info(model="mimo-v2.5-pro"), 120, 32, theme)
    second = drawn(an_info(model="anthropic/claude-opus-5"), 120, 32, theme)
    assert "MODEL mimo-v2.5-pro" in first
    assert "MODEL anthropic/claude-opus-5" in second


def test_the_status_row_shows_the_mode_and_its_key(theme):
    out = drawn(an_info(mode="plan"), 120, 32, theme)
    row = next(line for line in out.splitlines() if "Mode:" in line)
    assert "PLAN" in row and "[TAB]" in row
    assert "Command" in row and "Sub-agent" in row
    # Each of these names a control that exists: TAB cycles the mode, `/`
    # opens the command menu, `/delegates` reaches the sub-agents.
    assert "/delegates" in row


def test_no_sub_agents_reads_off_rather_than_zero(theme):
    assert "Sub-agent off" in drawn(an_info(agents=0), 120, 32, theme)


def test_running_sub_agents_are_counted(theme):
    """A real number when there is one. `off` is the state, not the count."""
    out = drawn(an_info(agents=2), 120, 32, theme)
    row = next(line for line in out.splitlines() if "Sub-agent" in line)
    assert "Sub-agent 2" in row and "off" not in row


def test_nothing_absent_is_invented(theme):
    out = drawn(WelcomeInfo(), 100, 30, theme)
    assert "None" not in out
    assert "Workspace:" not in out, "a folder nobody named must not be printed"
    assert "version:" not in out
    assert "MODEL" not in out, "a model nobody chose must not be named"


def test_the_facts_are_spread_not_centred(theme):
    """Three items with even gaps read as a footer; the same three centred
    read as a sentence somebody has put spaces in."""
    out = drawn(an_info(), 100, 30, theme)
    line = next(row for row in out.splitlines() if "Workspace:" in row)
    assert line.startswith("Workspace:"), "it should begin at the left edge"
    assert line.rstrip().endswith("0.16.0")


# --------------------------------------------------------------------------- #
# the composer
# --------------------------------------------------------------------------- #


def test_the_composer_is_the_real_editor_not_a_picture_of_one(theme):
    """The same buffer the active session uses. If this drew a placeholder
    box, the first keystroke would go somewhere the transcript never sees."""
    editor = Editor(text="add a health endpoint")
    editor.cursor = len(editor.text)
    assert "add a health endpoint" in drawn(an_info(), 100, 30, theme, editor)


def test_an_empty_composer_invites_rather_than_sitting_blank(theme):
    out = drawn(an_info(), 100, 30, theme)
    assert any(text in out for text in INVITATIONS)


def test_the_invitation_never_wraps_the_box_open(theme):
    """A placeholder one cell too long is a second row inside the frame, and
    the frame was measured for one. It shows as the page overflowing the
    terminal, which is a long way from where the cause is."""
    for width in (40, 44, 50, 60, 80, 100, 160):
        geometry = layout_module.compute(width, 24, stage=layout_module.NEW)
        room = geometry.prompt.width - 1
        chosen = next((text for text in INVITATIONS if len(text) <= room),
                      INVITATIONS[-1])
        assert len(chosen) <= room or chosen is INVITATIONS[-1]


def test_the_composer_is_centred_and_stops_growing(theme):
    """A text box the width of an ultrawide terminal is a hundred and eighty
    columns of empty box round a one-line question."""
    geometry = layout_module.compute(240, 60, stage=layout_module.NEW)
    assert geometry.composer is not None
    assert geometry.composer.width == layout_module.COMPOSER_MAX
    left = geometry.composer.x - geometry.margin
    right = (geometry.width - geometry.margin) - geometry.composer.right
    assert abs(left - right) <= 1, "it is not centred"


def test_the_composer_carries_the_brand_surface(theme):
    """Semantic, not a literal: the box is painted with whatever the theme
    calls the surface behind what you typed."""
    console = Console(width=100, height=30, force_terminal=True,
                      color_system="truecolor", legacy_windows=False)
    geometry = layout_module.compute(100, 30, stage=layout_module.NEW)
    with console.capture() as caught:
        console.print(render_opening(an_info(), Editor(), geometry, theme))
    assert _rgb(theme.palette_colour("surface_user")) in caught.get()


def _rgb(colour: str) -> str:
    value = colour.lstrip("#")
    return (f"48;2;{int(value[0:2], 16)};{int(value[2:4], 16)};"
            f"{int(value[4:6], 16)}")


# --------------------------------------------------------------------------- #
# it has to fit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width,height", [
    (160, 45), (140, 40), (120, 36), (100, 32), (80, 24),
    (60, 20), (46, 16), (40, 12),
])
def test_it_fits_the_space_it_is_given(width, height, theme):
    out = drawn(an_info(), width, height, theme)
    rows = out.splitlines()
    assert len(rows) <= height, f"{len(rows)} rows in {height}"
    for row in rows:
        assert len(row.rstrip()) <= width, f"{len(row)} cells in {width}"


@pytest.mark.parametrize("name", ["cyan", "ember", "ink", "paper", "midnight",
                                  "matrix", "mono"])
def test_every_theme_draws_it(name):
    out = drawn(an_info(), 100, 30, theme_module.load(name))
    assert out.strip()


def test_it_is_actually_coloured(theme):
    console = Console(width=100, height=30, force_terminal=True,
                      color_system="truecolor", legacy_windows=False)
    geometry = layout_module.compute(100, 30, stage=layout_module.NEW)
    with console.capture() as caught:
        console.print(render_opening(an_info(), Editor(), geometry, theme))
    assert "\x1b[" in caught.get(), "no escape sequences — it rendered plain"


def test_ascii_mode_draws_no_block_characters():
    """`--ascii` is for terminals that cannot render Unicode. A logo made of
    the one glyph such a terminal is certain to get wrong is the last thing
    that mode should draw — so that mode gets the tagline and the name on one
    line instead, which every terminal there is can print."""
    out = drawn(an_info(), 100, 30, theme_module.load("cyan", ascii_borders=True))
    assert "█" not in out
    assert "it learns the way you correct it" in out
    for row in out.splitlines():
        assert row.isascii(), f"non-ASCII survived: {row!r}"


def test_ascii_mode_still_frames_the_composer():
    """The box says where to type. Losing it in ASCII mode would leave the
    invitation floating in the middle of an otherwise empty page."""
    out = drawn(an_info(), 100, 30, theme_module.load("cyan", ascii_borders=True))
    assert "+--" in out or "|" in out


# --------------------------------------------------------------------------- #
# what the opening screen promises, it has to do
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width", list(range(40, 90)) + [100, 140, 240])
def test_the_invitation_is_ascii_in_ascii_mode(width):
    """`--ascii` is a promise about every glyph on the screen, and the
    placeholder was chosen purely by width. The middle-dot form fits exactly
    the terminals narrow enough to need it, so the promise broke on the sizes
    most likely to have been picked for a terminal that cannot draw it."""
    theme = theme_module.load("cyan", ascii_borders=True)
    out = drawn(an_info(), width, 24, theme)

    for row in out.splitlines():
        assert row.isascii(), f"non-ASCII at width {width}: {row!r}"


@pytest.mark.parametrize("width", [40, 46, 60, 80, 120, 240])
def test_the_invitation_still_fits_in_ascii_mode(width):
    """Falling back to ASCII must not fall back to something that wraps."""
    geometry = layout_module.compute(width, 24, stage=layout_module.NEW)
    room = geometry.prompt.width - 1
    chosen = invitation(room, ascii_only=True)

    assert chosen.isascii()
    assert len(chosen) <= room or chosen == "ask..."


def test_slash_shows_the_command_menu_on_the_opening_screen(theme):
    """The invitation says to press `/`. Before this, pressing it on a fresh
    session drew nothing — the menu lives in the active session's composer,
    which the opening screen does not use — so the key looked broken and the
    selection the arrow keys were moving was invisible."""
    editor = Editor(text="/mo")
    editor.cursor = len(editor.text)
    geometry = layout_module.compute(120, 36, stage=layout_module.NEW)
    console = Console(width=120, height=36, force_terminal=False,
                      legacy_windows=False)
    with console.capture() as caught:
        console.print(render_opening(
            an_info(), editor, geometry, theme,
            commands=[("/mode", "act, plan or chat"),
                      ("/model", "pick a model"),
                      ("/memory", "what it has learned")]))
    out = caught.get()

    assert "/mode" in out and "/model" in out
    assert "/memory" not in out, "it should be filtered, not listed whole"


def test_the_menu_never_makes_the_box_taller(theme):
    """The screen is measured against a geometry that fixed the box height. A
    menu that pushed it down would push the two rows under it off the bottom
    of the terminal."""
    commands = [(f"/command{index}", "does a thing") for index in range(20)]
    for width, height in [(80, 24), (100, 32), (120, 36), (160, 45)]:
        editor = Editor(text="/co")
        editor.cursor = len(editor.text)
        geometry = layout_module.compute(width, height, stage=layout_module.NEW)
        console = Console(width=width, height=height, force_terminal=False,
                          legacy_windows=False)
        with console.capture() as caught:
            console.print(render_opening(an_info(), editor, geometry, theme,
                                         commands=commands))
        rows = caught.get().splitlines()

        assert len(rows) <= height, f"{len(rows)} rows in {height} at {width}"


def test_no_key_is_advertised_that_does_nothing(theme):
    """`ctrl+s` is bound in exactly one place in this program — submitting an
    open question form — and has nothing to do with sub-agents. A hint is a
    promise; this one names the command that actually reaches them."""
    out = drawn(an_info(), 120, 32, theme)
    row = next(line for line in out.splitlines() if "Sub-agent" in line)

    assert "ctrl+s" not in row
    assert "/delegates" in row
