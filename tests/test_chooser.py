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
