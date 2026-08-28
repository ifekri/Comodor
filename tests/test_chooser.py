"""Moving through a list with the arrow keys.

The behaviour that matters is not "does Enter return something" — it is what
happens when the list is longer than the terminal, which is the case this
replaces. So most of what is checked here is the window: that the cursor is
always inside it, that the counts above and below add up, and that filtering
does not leave the cursor pointing at a row that is no longer there.

The key handler is driven directly with `KeyEvent`s. Nothing here opens a
terminal, because the decoder that turns escape sequences into those events is
already tested on its own in `test_input.py`, and a test that needs a real
keyboard is a test that does not run in CI.
"""

from __future__ import annotations

import pytest

from comodor.ui import theme as theme_module
from comodor.ui.chooser import Chooser, Option, choose
from comodor.ui.console import build
from comodor.ui.input.keys import KeyEvent


def make(count: int = 40, height: int = 24) -> Chooser:
    theme = theme_module.load("ember")
    console = build(theme, width=80, height=height)
    options = [Option(f"m{i}", f"model-{i:02d}", "recommended" if i == 0 else "")
               for i in range(count)]
    return Chooser(console, theme, options, title="Models")


def press(chooser: Chooser, *keys: str) -> object:
    outcome = None
    for key in keys:
        if key == "space":
            event = KeyEvent("char", char=" ")
        elif len(key) == 1 and key.isalnum():
            event = KeyEvent("char", char=key)
        else:
            event = KeyEvent(key)
        outcome = chooser._handle(event)
        chooser.render()          # what the loop does between keystrokes
    return outcome


def ticking(count: int = 6, height: int = 24) -> Chooser:
    theme = theme_module.load("ember")
    console = build(theme, width=80, height=height)
    options = [Option(f"skill-{i}", f"skill-{i}", f"does thing {i}")
               for i in range(count)]
    return Chooser(console, theme, options, title="Skills", multi=True,
                   verb="install")


# --------------------------------------------------------------------------- #
# the window
# --------------------------------------------------------------------------- #


def test_a_long_list_is_windowed_to_the_terminal():
    chooser = make(count=200, height=24)
    chooser.render()

    assert chooser.rows() < 200
    assert chooser.rows() <= 24


def test_the_cursor_never_leaves_the_window():
    chooser = make(count=200, height=24)

    for _ in range(150):
        press(chooser, "down")
        assert chooser.offset <= chooser.cursor < chooser.offset + chooser.rows()


def test_what_is_above_and_below_adds_up():
    chooser = make(count=60, height=24)
    press(chooser, *(["down"] * 30))
    window = chooser.rows()

    above = chooser.offset
    below = len(chooser.matching) - chooser.offset - window

    assert above + window + below == 60
    assert above > 0 and below > 0


def test_the_ends_wrap():
    """A list that stops dead at the top sends you looking for the mouse."""
    chooser = make(count=10)

    press(chooser, "up")
    assert chooser.cursor == 9

    press(chooser, "down")
    assert chooser.cursor == 0


def test_home_and_end_and_the_page_keys():
    chooser = make(count=100, height=24)

    press(chooser, "end")
    assert chooser.cursor == 99

    press(chooser, "home")
    assert chooser.cursor == 0

    press(chooser, "pgdn")
    assert chooser.cursor == chooser.rows()


def test_a_short_list_needs_no_window():
    chooser = make(count=3, height=40)
    chooser.render()

    assert chooser.rows() == 3
    assert chooser.offset == 0


# --------------------------------------------------------------------------- #
# filtering
# --------------------------------------------------------------------------- #


def test_typing_narrows_the_list():
    chooser = make(count=40)

    press(chooser, "3")
    assert chooser.filter == "3"
    # model-03, model-13, model-23, model-30..39
    assert all("3" in option.label for option in chooser.matching)
    assert 0 < len(chooser.matching) < 40


def test_backspace_widens_it_again():
    chooser = make(count=40)
    press(chooser, "3", "backspace")

    assert chooser.filter == ""
    assert len(chooser.matching) == 40


def test_a_changed_filter_puts_the_cursor_back_at_the_top():
    """Otherwise it points at a row that is no longer in the list."""
    chooser = make(count=40)
    press(chooser, *(["down"] * 20))
    assert chooser.cursor == 20

    press(chooser, "7")

    assert chooser.cursor == 0
    assert chooser.cursor < len(chooser.matching)


def test_a_filter_that_matches_nothing_says_so_and_returns_nothing():
    chooser = make(count=10)
    press(chooser, "z", "z", "z")

    assert chooser.matching == []
    assert "nothing matches" in _text(chooser)
    # Enter on an empty list cannot invent an answer.
    from comodor.ui.chooser import _CANCEL

    assert chooser._handle(KeyEvent("enter")) is _CANCEL


def test_the_filter_reads_the_note_as_well_as_the_label():
    chooser = make(count=10)
    press(chooser, "r", "e", "c")

    assert [option.value for option in chooser.matching] == ["m0"]


# --------------------------------------------------------------------------- #
# choosing, and not choosing
# --------------------------------------------------------------------------- #


def test_enter_returns_the_row_under_the_cursor():
    chooser = make(count=10)
    press(chooser, "down", "down")

    assert chooser._handle(KeyEvent("enter")) == "m2"


def test_enter_returns_the_row_under_the_cursor_after_filtering():
    """The cursor indexes the filtered list, not the original one."""
    chooser = make(count=40)
    press(chooser, "1", "2")

    assert chooser._handle(KeyEvent("enter")) == "m12"


@pytest.mark.parametrize("event", [KeyEvent("escape"), KeyEvent("c", ctrl=True)])
def test_backing_out_returns_nothing(event):
    from comodor.ui.chooser import _CANCEL

    assert make()._handle(event) is _CANCEL


def test_without_a_terminal_there_is_no_list_to_drive():
    """The caller falls back to the numbered prompt, which always works."""
    theme = theme_module.load("ember")
    console = build(theme, width=80, height=24)

    assert choose(console, theme, [Option("a", "A")], title="x") is None


def test_ctrl_and_alt_combinations_are_not_typed_into_the_filter():
    chooser = make(count=10)
    chooser._handle(KeyEvent("char", char="k", ctrl=True))

    assert chooser.filter == ""


def _text(chooser: Chooser) -> str:
    console = chooser.console
    with console.capture() as captured:
        console.print(chooser.render())
    return captured.get()


# --------------------------------------------------------------------------- #
# ticking more than one
#
# The skills question was a list you could take exactly one thing out of, which
# is the wrong shape: wanting the review skill and the test skill is the
# ordinary case.
# --------------------------------------------------------------------------- #


def test_space_ticks_the_row_under_the_cursor():
    chooser = ticking()

    press(chooser, "space")

    assert chooser.picked == {"skill-0"}


def test_space_again_unticks_it():
    chooser = ticking()

    press(chooser, "space", "space")

    assert chooser.picked == set()


def test_several_can_be_ticked_and_enter_takes_them_all():
    chooser = ticking()

    press(chooser, "space", "down", "down", "space", "down", "space")
    taken = press(chooser, "enter")

    assert taken == ["skill-0", "skill-2", "skill-3"]


def test_they_come_back_in_the_order_they_were_offered():
    """Not the order they were ticked: the list on screen is what a reader
    remembers, and a summary line in a different order reads as a mistake."""
    chooser = ticking()

    press(chooser, "end", "space", "home", "space")
    taken = press(chooser, "enter")

    assert taken == ["skill-0", "skill-5"]


def test_enter_with_nothing_ticked_is_an_answer_not_a_refusal():
    """It is what the "None for now" row used to be for. An option meaning
    "no options", among real ones, is a thing to explain rather than use."""
    chooser = ticking()

    taken = press(chooser, "enter")

    assert taken == []
    assert taken is not None


def test_escape_is_still_a_refusal():
    from comodor.ui.chooser import _CANCEL

    chooser = ticking()
    press(chooser, "space")

    assert press(chooser, "escape") is _CANCEL


def test_a_tick_survives_the_filter_that_hides_it():
    """Ticks are held by value, not by row.

    Type to narrow the list, tick something, clear the filter: holding an
    index would have moved the mark onto whatever landed in that row.
    """
    chooser = ticking(count=6)

    press(chooser, "space")                       # skill-0
    for char in "5":                              # narrows to skill-5
        press(chooser, char)
    assert [option.value for option in chooser.matching] == ["skill-5"]
    press(chooser, "space")
    press(chooser, "backspace")

    taken = press(chooser, "enter")
    assert taken == ["skill-0", "skill-5"]


def test_space_still_types_when_the_list_takes_one_answer():
    """Only the ticking list steals it. Everywhere else it filters."""
    chooser = make(count=6)

    press(chooser, "space")

    assert chooser.filter == " "
    assert not hasattr(chooser, "picked") or chooser.picked == set()


def test_the_hint_says_what_enter_will_do():
    chooser = ticking()
    chooser.render()
    assert "install nothing" in chooser._hint().plain
    assert "space" in chooser._hint().plain

    press(chooser, "space", "down", "space")
    assert "install 2" in chooser._hint().plain


def test_the_boxes_are_drawn_and_change_when_ticked():
    from rich.console import Console

    chooser = ticking()
    theme = chooser.theme

    def drawn() -> str:
        buffer = Console(width=80, height=24, record=True, file=open_devnull())
        buffer.print(chooser.render())
        return buffer.export_text()

    before = drawn()
    assert theme.glyphs.unticked in before
    assert theme.glyphs.ticked not in before

    press(chooser, "space")
    assert theme.glyphs.ticked in drawn()


def open_devnull():
    import io

    return io.StringIO()


def test_the_count_of_what_is_taken_is_on_screen():
    from rich.console import Console

    chooser = ticking()
    press(chooser, "space", "down", "space")

    buffer = Console(width=80, height=24, record=True, file=open_devnull())
    buffer.print(chooser.render())

    assert "2 selected" in buffer.export_text()


def test_choose_many_gives_up_quietly_without_a_terminal():
    """The wizard has to answer in a pipe, so this returning None is the
    signal to ask some other way — and it must not be confused with []."""
    from comodor.ui.chooser import choose_many

    theme = theme_module.load("ember")
    console = build(theme, width=80, height=24)

    assert choose_many(console, theme, [Option("a", "A")]) is None
    assert choose(console, theme, [Option("a", "A")]) is None


# --------------------------------------------------------------------------- #
# terminals that cannot draw the glyphs
#
# `cmd.exe` still opens on cp437 for a lot of people, and cp437 has the
# box-drawing characters the probe was testing but not the bullet, the tick,
# or the arrow that marks which row the cursor is on.
# --------------------------------------------------------------------------- #


def test_the_unicode_probe_asks_about_every_glyph_it_will_draw(monkeypatch):
    from comodor.ui.console import supports_unicode
    from comodor.ui.theme import Glyphs

    class Stdout:
        def __init__(self, encoding):
            self.encoding = encoding

    for encoding in ("cp437", "cp850", "cp1252", "latin-1", "ascii", "utf-8"):
        monkeypatch.setattr("sys.stdout", Stdout(encoding))
        answered = supports_unicode()

        def encodable(value: str, page: str = encoding) -> bool:
            try:
                value.encode(page)
                return True
            except (UnicodeEncodeError, LookupError):
                return False

        everything = all(encodable(value) for value in vars(Glyphs()).values()
                         if isinstance(value, str))
        assert answered is everything, (
            f"{encoding}: said {answered}, and the glyphs "
            f"{'all fit' if everything else 'do not all fit'}")


def test_a_glyph_added_later_widens_the_probe():
    """The point of building it from the table. The old probe was a literal,
    so every glyph added after it was outside what had been checked."""
    import inspect

    from comodor.ui import console as console_module

    source = inspect.getsource(console_module.supports_unicode)
    assert "Glyphs" in source, "the probe has gone back to a fixed string"


def test_the_ticking_list_still_draws_where_unicode_will_not_go():
    """The ASCII table has boxes of its own, and they have to be legible."""
    import io

    from rich.console import Console

    theme = theme_module.load("ember", ascii_borders=True, no_color=True)
    console = build(theme, width=76, height=20)
    options = [Option(f"skill-{i}", f"skill-{i}", "") for i in range(3)]
    chooser = Chooser(console, theme, options, title="Skills", multi=True,
                      verb="install")
    chooser.picked.add("skill-0")

    buffer = Console(width=76, height=20, record=True, file=io.StringIO(),
                     no_color=True)
    buffer.print(chooser.render())
    drawn = buffer.export_text()

    assert "[x]" in drawn and "[ ]" in drawn
    drawn.encode("ascii")            # every character of it, on a dumb terminal


# --------------------------------------------------------------------------- #
# long notes
#
# The skills catalogue has descriptions four hundred characters long, and every
# fault below was seen with it: the frame ran off the bottom of the screen, the
# arrow saying where you were disappeared, and the window lagged several
# keypresses behind the cursor. All three were one thing — the note column
# wrapped, so an option was not a row.
# --------------------------------------------------------------------------- #


def wordy(count: int = 60, height: int = 24, width: int = 80) -> Chooser:
    theme = theme_module.load("ember")
    console = build(theme, width=width, height=height)
    note = ("Accessibility engineering for product interfaces. Use when "
            "building or reviewing UI components and custom widgets, or when "
            "the user reports a keyboard or screen-reader problem. Triggers "
            "on accessibility, a11y, WCAG, aria, focus ring, focus trap, "
            "keyboard navigation, tabindex, screen reader, sr-only, alt text.")
    options = [Option(f"s{i}", f"skill-{i:02d}", note) for i in range(count)]
    return Chooser(console, theme, options, title="Skills", multi=True,
                   verb="install")


def drawn(chooser: Chooser) -> list[str]:
    import io

    from rich.console import Console

    buffer = Console(width=chooser.console.width, height=chooser.console.height,
                     record=True, file=io.StringIO(), no_color=True)
    buffer.print(chooser.render())
    return buffer.export_text().splitlines()


@pytest.mark.parametrize("height", [20, 24, 30, 45])
def test_a_paragraph_of_note_still_leaves_one_row_per_option(height):
    chooser = wordy(height=height)
    assert len(drawn(chooser)) <= height


@pytest.mark.parametrize("height", [20, 24, 30, 45])
def test_and_still_fits_with_the_detail_open(height):
    chooser = wordy(height=height)
    chooser.detail = True
    assert len(drawn(chooser)) <= height


def test_the_arrow_survives_a_note_wider_than_the_screen():
    """It was squeezed to nothing: Rich gave the width to the longest cell."""
    chooser = wordy()
    chooser.cursor = 3
    body = [line for line in drawn(chooser) if "skill-03" in line]
    assert body
    assert chooser.theme.glyphs.arrow in body[0][:6]
    assert chooser.theme.glyphs.unticked in body[0][:8]


def test_the_window_follows_the_cursor_one_press_at_a_time():
    chooser = wordy()
    window = chooser.rows()
    for _ in range(len(chooser.options) - 1):
        press(chooser, "down")
        assert chooser.offset <= chooser.cursor < chooser.offset + window


def test_tab_opens_the_whole_note_and_tab_closes_it():
    chooser = wordy()
    assert "keyboard navigation" not in "".join(drawn(chooser))
    press(chooser, "tab")
    assert "keyboard navigation" in "".join(drawn(chooser))
    press(chooser, "tab")
    assert "keyboard navigation" not in "".join(drawn(chooser))


def test_the_detail_names_the_row_under_the_cursor_and_moves_with_it():
    chooser = wordy()
    press(chooser, "tab", "down", "down")
    text = "\n".join(drawn(chooser))
    assert f"{chooser.theme.glyphs.divider * 3} skill-02" in text


def test_a_note_too_long_for_the_pane_is_cut_rather_than_pushing_the_frame():
    chooser = wordy(height=20, width=60)
    chooser.detail = True
    assert len(drawn(chooser)) <= 20
    assert chooser.theme.glyphs.ellipsis in "\n".join(drawn(chooser))


def test_the_hint_says_which_way_tab_goes():
    chooser = wordy()
    assert "tab more" in chooser._hint().plain
    press(chooser, "tab")
    assert "tab less" in chooser._hint().plain


def test_an_option_with_no_note_says_so_rather_than_showing_a_gap():
    theme = theme_module.load("ember")
    console = build(theme, width=80, height=24)
    chooser = Chooser(console, theme, [Option("a", "alpha")], title="One")
    chooser.detail = True
    assert "Nothing more to say" in "\n".join(drawn(chooser))


def test_the_wordy_list_still_draws_where_unicode_will_not_go():
    theme = theme_module.load("ember", ascii_borders=True, no_color=True)
    console = build(theme, width=76, height=20)
    note = "a very long note " * 40
    options = [Option(f"s{i}", f"skill-{i}", note) for i in range(30)]
    chooser = Chooser(console, theme, options, title="Skills", multi=True,
                      verb="install")
    chooser.detail = True
    text = "\n".join(drawn(chooser))
    text.encode("ascii")
    assert len(text.splitlines()) <= 20


def test_the_pane_grows_to_the_note_rather_than_being_one_size():
    """The catalogue's descriptions run from one line to nine hundred
    characters. A fixed pane wastes rows on the short ones and cuts the long
    ones, and cutting is the worse of the two — the pane exists to be read."""
    theme = theme_module.load("ember")
    console = build(theme, width=100, height=30)
    brief = Option("a", "alpha", "Short.")
    essay = Option("b", "beta", "A sentence that goes on. " * 30)
    chooser = Chooser(console, theme, [brief, essay], title="Two")
    chooser.detail = True

    small = chooser.detail_rows()
    chooser.cursor = 1
    assert chooser.detail_rows() > small


def test_a_long_note_is_shown_whole_when_the_screen_can_take_it():
    theme = theme_module.load("ember")
    console = build(theme, width=100, height=40)
    note = ("Generate genuinely beautiful, on-brand UI instead of generic "
            "output. " * 9)
    chooser = Chooser(console, theme, [Option("a", "alpha", note)], title="One")
    chooser.detail = True

    lines = drawn(chooser)
    # Only the pane. The row above it ellipsises at its column, which is the
    # point of the row — this is about what the pane does with the rest.
    rule = f"{theme.glyphs.divider * 3} alpha"
    start = next(index for index, line in enumerate(lines) if rule in line)
    pane = " ".join(lines[start:])

    assert note.split()[-1] in pane, "the end of the note is missing"
    assert theme.glyphs.ellipsis not in pane, "it was cut with room to spare"


def test_the_pane_never_takes_the_whole_screen():
    """A pane that hides the list makes the comparison it was opened for
    impossible."""
    theme = theme_module.load("ember")
    for height in (18, 24, 30, 45):
        console = build(theme, width=90, height=height)
        chooser = Chooser(console, theme,
                          [Option(f"o{n}", f"opt-{n}", "words " * 400)
                           for n in range(40)], title="Many")
        chooser.detail = True
        assert chooser.detail_rows() <= height // 2 or chooser.detail_rows() <= 4
        assert chooser.rows() >= 3, "the list disappeared"
        assert len(drawn(chooser)) <= height


@pytest.mark.parametrize("width", [76, 80, 90, 100, 120, 140])
def test_the_pane_draws_exactly_the_rows_it_reserved(width):
    """It wrapped at one width and was re-wrapped by Rich at a narrower one,
    so a pane that had reserved eight rows drew ten — and the two extra came
    off the bottom of the screen."""
    theme = theme_module.load("ember")
    console = build(theme, width=width, height=32)
    note = ("Accessibility engineering for product interfaces, described at "
            "considerable length. " * 12)
    chooser = Chooser(console, theme, [Option("a", "alpha", note)], title="One")
    chooser.detail = True

    lines = drawn(chooser)
    rule = f"{theme.glyphs.divider * 3} alpha"
    start = next(index for index, line in enumerate(lines) if rule in line)
    # To the closing border, which is the line after the pane.
    pane = len(lines) - start - 2

    assert pane == chooser.detail_rows(), \
        f"reserved {chooser.detail_rows()} rows and drew {pane}"
    assert len(lines) <= console.size.height
