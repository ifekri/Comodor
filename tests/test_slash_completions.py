"""Moving through the slash-command menu, and seeing where you are.

Typing `/` opens a list of thirty-four commands. Arrow-down moved the selection
through all of them and the menu drew the first four every time, so past the
fourth command there was no highlight anywhere on screen: the key looked dead,
and Enter accepted something the user could not see they had chosen.

Selection and viewport were one thing by omission. These tests keep them two.

The shape of what follows:

* the arithmetic on its own, where every boundary is cheap to state;
* the menu as it renders, because "the selection is visible" is a claim about
  pixels rather than about an integer;
* the app through real key events, because the bug lived in the join between
  a handler that moved an index and a renderer that ignored it;
* the decoder, unchanged, tested so that the next person can rule it out.
"""

from __future__ import annotations

import pytest
from rich.console import Console

from comodor.ui import layout as layout_module
from comodor.ui.app import COMMANDS, App
from comodor.ui.input.keys import (
    WINDOWS_SPECIAL,
    KeyDecoder,
    KeyEvent,
    PasteEvent,
)
from comodor.ui.theme import Theme
from comodor.ui.widgets.prompt import (
    MENU_CEILING,
    menu_budget,
    render_completions,
    scroll_into_view,
    visible_items,
)

# --------------------------------------------------------------------------- #
# scaffolding
# --------------------------------------------------------------------------- #


def a_menu(count: int) -> list[tuple[str, str]]:
    """`count` commands, named so their index is readable in a failure."""
    return [(f"/cmd{index:02d}", f"description {index}") for index in range(count)]


def drawn(matches, selected, limit, top=0, width=60) -> list[str]:
    """The menu as rows of text, exactly as a terminal would show it."""
    console = Console(width=width, no_color=True)
    with console.capture() as captured:
        console.print(render_completions(matches, Theme(), selected, limit, top))
    return [line.rstrip() for line in captured.get().splitlines() if line.strip()]


def marked(rows: list[str]) -> str | None:
    """The command the menu is pointing at, or None if it points at nothing."""
    arrow = Theme().glyphs.arrow
    for row in rows:
        if row.lstrip().startswith(arrow):
            return row.lstrip()[len(arrow):].split()[0]
    return None


@pytest.fixture
def app(config):
    """An app with a real geometry, so the menu has a real height to fit in."""
    instance = App(config, demo=True)
    instance.geometry = layout_module.compute(128, 36)
    return instance


def key(name: str, char: str = "", **flags) -> KeyEvent:
    return KeyEvent(name, char, **flags)


def opened(app: App) -> int:
    """Type `/` and return how many commands that matches."""
    app._on_key(key("char", "/"))
    return len(app._completions())


def selected_name(app: App) -> str:
    return app._completions()[app.state.completion_index][0]


def composer_rows(app: App) -> list[str]:
    console = Console(width=128, no_color=True)
    with console.capture() as captured:
        console.print(app.screen._composer(app.state, app.geometry))
    return [line.rstrip() for line in captured.get().splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# the arithmetic
# --------------------------------------------------------------------------- #


def test_a_selection_already_on_screen_does_not_move_the_window():
    """The half that is easy to get wrong. A window that re-centres on every
    keypress is as hard to read as one that never moves."""
    for selected in range(4):
        assert scroll_into_view(selected, 0, 34, 4) == 0


def test_the_window_follows_the_selection_off_the_bottom():
    assert scroll_into_view(4, 0, 34, 4) == 1
    assert scroll_into_view(5, 1, 34, 4) == 2
    assert scroll_into_view(33, 29, 34, 4) == 30


def test_the_window_follows_the_selection_off_the_top():
    assert scroll_into_view(9, 10, 34, 4) == 9
    assert scroll_into_view(0, 10, 34, 4) == 0


def test_the_window_never_leaves_the_list():
    assert scroll_into_view(33, 99, 34, 4) == 30      # never past the end
    assert scroll_into_view(0, -5, 34, 4) == 0        # never before the start
    assert scroll_into_view(5, 0, 3, 4) == 0          # shorter than the window
    assert scroll_into_view(0, 0, 0, 4) == 0          # nothing to show
    assert scroll_into_view(0, 0, 34, 0) == 0         # nowhere to show it


@pytest.mark.parametrize("total", [1, 2, 5, 34, 100])
@pytest.mark.parametrize("capacity", [1, 3, 4, 7])
def test_the_selection_is_inside_the_window_for_every_position(total, capacity):
    """The invariant the whole change exists for, over every list length and
    every window size, walked in both directions."""
    top = 0
    for selected in list(range(total)) + list(reversed(range(total))):
        top = scroll_into_view(selected, top, total, capacity)
        assert top <= selected < top + capacity
        assert 0 <= top <= max(0, total - capacity)


def test_the_budget_is_rows_and_never_more_than_it_is_given():
    assert menu_budget(0, 10) == 0                    # nothing to list
    assert menu_budget(34, 10) == MENU_CEILING        # capped
    assert menu_budget(34, 3) == 3                    # a short prompt
    assert menu_budget(2, 10) == 2                    # only what exists
    assert menu_budget(34, 0) == 0
    assert menu_budget(34, -1) == 0


def test_a_row_goes_to_the_indicator_only_when_it_has_something_to_say():
    assert visible_items(3, 3) == 3                   # all of them fit
    assert visible_items(34, 5) == 4                  # four and an indicator
    assert visible_items(34, 1) == 1                  # one row: show a command
    assert visible_items(0, 5) == 0


# --------------------------------------------------------------------------- #
# the menu, as it is drawn
# --------------------------------------------------------------------------- #


def test_a_short_list_is_shown_whole_with_no_indicator():
    rows = drawn(a_menu(3), selected=0, limit=MENU_CEILING)

    assert len(rows) == 3
    assert not any("…" in row for row in rows)
    assert marked(rows) == "/cmd00"


def test_a_long_list_shows_a_window_and_says_what_is_outside_it():
    rows = drawn(a_menu(34), selected=0, limit=5)

    assert len(rows) == 5
    assert marked(rows) == "/cmd00"
    assert rows[-1].strip() == "… 30 more"


def test_the_indicator_describes_the_window_that_is_actually_drawn():
    """It used to say `len(matches) - limit` wherever the window was, which is
    true only for the first screenful and then quietly wrong."""
    assert drawn(a_menu(34), 10, 5, top=7)[-1].strip() == "… 7 above · 23 more"
    assert drawn(a_menu(34), 33, 5, top=30)[-1].strip() == "… 30 above"
    assert drawn(a_menu(34), 0, 5, top=0)[-1].strip() == "… 30 more"


def test_the_reported_bug_in_one_assertion():
    """Thirty-four commands, a five-row menu, every selection in turn.

    Deliberately uses only what the renderer took before this change -- no
    `top` argument -- so it is a real before-and-after. On the code this
    replaces it reports:

        selections with nothing highlighted : 29/34
        renders exceeding the 5-row budget  : 34/34

    Twenty-nine of the thirty-four positions drew a menu with no highlight
    anywhere. That is what "arrow-down does nothing" looked like from the
    inside, and it is why the user could not tell which command Enter would
    take.
    """
    matches = a_menu(34)
    arrow = Theme().glyphs.arrow

    invisible, oversized = [], []
    for selected in range(34):
        rows = drawn(matches, selected, limit=5)
        if not any(row.lstrip().startswith(arrow)
                   and f"/cmd{selected:02d}" in row for row in rows):
            invisible.append(selected)
        if len(rows) > 5:
            oversized.append(selected)

    assert invisible == [], f"no highlight on screen for {invisible}"
    assert oversized == [], f"drew more than five rows for {oversized}"


@pytest.mark.parametrize("selected", range(34))
def test_the_selected_command_is_always_on_screen(selected):
    """The failure exactly: with `selected` past the window, the old renderer
    drew the first four commands and marked none of them."""
    top = scroll_into_view(selected, 0, 34, visible_items(34, 5))
    rows = drawn(a_menu(34), selected, limit=5, top=top)

    assert marked(rows) == f"/cmd{selected:02d}"


@pytest.mark.parametrize("limit", range(1, 8))
def test_the_menu_never_draws_more_rows_than_it_was_given(limit):
    """`limit` is rows, indicator included. The composer budgets against it,
    so one row over is a prompt that moves while somebody scrolls."""
    for total in (1, 2, 5, 34):
        rows = drawn(a_menu(total), selected=0, limit=limit)
        assert len(rows) <= limit, f"{total} matches in {limit} rows"


def test_a_stale_selection_cannot_produce_a_menu_pointing_at_nothing():
    """The renderer clamps as well as the state does. Whatever arrives, the
    menu must never be drawn with no highlight — that failure is silent."""
    rows = drawn(a_menu(5), selected=99, limit=5)
    assert marked(rows) == "/cmd04"

    rows = drawn(a_menu(5), selected=-3, limit=5)
    assert marked(rows) == "/cmd00"


def test_an_empty_list_draws_nothing():
    assert drawn([], selected=0, limit=5) == []


# --------------------------------------------------------------------------- #
# the app, through real keys
# --------------------------------------------------------------------------- #


def test_slash_opens_the_menu_with_every_command(app):
    assert opened(app) == len(COMMANDS)


def test_down_reaches_every_command_and_stops_at_the_last(app):
    """The report: arrow-down past the first screenful appeared to do nothing.
    Every index must be reachable, once, in order."""
    total = opened(app)

    visited = []
    for _ in range(total + 5):
        visited.append(app.state.completion_index)
        app._on_key(key("down"))

    assert visited[:total] == list(range(total))
    assert app.state.completion_index == total - 1, "down past the end"


def test_up_returns_through_every_command_and_stops_at_the_first(app):
    total = opened(app)
    for _ in range(total):
        app._on_key(key("down"))

    for _ in range(total + 5):
        app._on_key(key("up"))

    assert app.state.completion_index == 0, "up past the start"
    assert app.state.completion_top == 0


def test_the_window_scrolls_down_only_when_it_has_to(app):
    """Three presses inside the first window move nothing; the fourth scrolls."""
    opened(app)
    capacity = visible_items(len(app._completions()),
                             menu_budget(len(app._completions()),
                                         app.geometry.prompt.height - 1))

    for _ in range(capacity - 1):
        app._on_key(key("down"))
    assert app.state.completion_top == 0, "the window moved for no reason"

    app._on_key(key("down"))
    assert app.state.completion_top == 1, "the window did not follow"


def test_the_window_scrolls_back_up_when_it_has_to(app):
    opened(app)
    for _ in range(12):
        app._on_key(key("down"))
    assert app.state.completion_top > 0

    for _ in range(12):
        app._on_key(key("up"))
    assert app.state.completion_top == 0


def test_the_selection_is_on_screen_after_every_press(app):
    """Through the composer, not the renderer alone: this is the join where
    the index and the drawing were disagreeing."""
    total = opened(app)
    arrow = app.theme.glyphs.arrow

    for _ in range(total):
        name = selected_name(app)
        rows = composer_rows(app)
        assert any(row.lstrip().startswith(arrow) and name in row
                   for row in rows), f"{name} was selected and not drawn"
        app._on_key(key("down"))


def test_the_composer_stays_the_same_height_while_scrolling(app):
    """The prompt must not move under the cursor, and the footer must not be
    pushed. The menu used to draw one row more than it was budgeted."""
    total = opened(app)
    budget = app.geometry.prompt.height

    heights = set()
    for _ in range(total):
        heights.add(len(composer_rows(app)))
        app._on_key(key("down"))

    assert heights == {budget}, f"composer height varied: {sorted(heights)}"


# --------------------------------------------------------------------------- #
# accepting what is selected
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("accept", ["enter", "tab"])
def test_it_accepts_the_command_that_is_selected_far_down_the_list(app, accept):
    """The consequence of the bug that was not merely cosmetic: the user
    scrolls to something they cannot see, and Enter takes something else."""
    opened(app)
    for _ in range(20):
        app._on_key(key("down"))
    wanted = selected_name(app)

    app._on_key(key(accept))

    assert app.state.editor.text == f"{wanted} "
    assert wanted not in {"/help", "/model", "/provider"}, \
        "the test is not exercising anything past the first window"


def test_accepting_puts_the_menu_back_to_the_top(app):
    opened(app)
    for _ in range(20):
        app._on_key(key("down"))

    app._on_key(key("tab"))

    assert app.state.completion_index == 0
    assert app.state.completion_top == 0


# --------------------------------------------------------------------------- #
# the list changing underneath the selection
# --------------------------------------------------------------------------- #


def test_typing_a_narrower_prefix_leaves_a_valid_selection(app):
    """Thirty-four matches, a selection near the bottom, then a keystroke that
    leaves three. The index must not survive into a list that has no such
    position."""
    opened(app)
    for _ in range(25):
        app._on_key(key("down"))

    app._on_key(key("char", "m"))

    total = len(app._completions())
    assert total < 25
    assert 0 <= app.state.completion_index < total
    assert app.state.completion_top <= app.state.completion_index


def test_backspace_leaves_a_valid_selection(app):
    """Backspace never reset the index at all — only typing did."""
    for char in "/mo":
        app._on_key(key("char", char))
    for _ in range(3):
        app._on_key(key("down"))

    app._on_key(key("backspace"))

    total = len(app._completions())
    assert 0 <= app.state.completion_index < total


def test_deleting_forwards_leaves_a_valid_selection(app):
    """`delete` can narrow the list as well as widen it, and reset nothing."""
    for char in "/model":
        app._on_key(key("char", char))
    app._on_key(key("home"))
    app._on_key(key("right"))
    for _ in range(2):
        app._on_key(key("down"))

    app._on_key(key("delete"))

    total = len(app._completions())
    assert total == 0 or 0 <= app.state.completion_index < total


def test_cutting_the_line_leaves_a_valid_selection(app):
    """ctrl+u, ctrl+k and ctrl+w all change the text without a char event."""
    for shortcut in ("ctrl+u", "ctrl+k", "ctrl+w"):
        app.state.editor.text = ""
        app.state.editor.cursor = 0
        opened(app)
        for _ in range(20):
            app._on_key(key("down"))

        name, _, _ = shortcut.partition("+")
        app._on_key(KeyEvent("char", shortcut[-1], ctrl=True))

        total = len(app._completions())
        assert total == 0 or 0 <= app.state.completion_index < total, shortcut


class _Pasting:
    """A terminal whose only event is one paste, then nothing."""

    def __init__(self, text: str) -> None:
        self._events = [PasteEvent(text)]

    def poll(self):
        events, self._events = self._events, []
        return events


def test_a_paste_leaves_a_valid_selection(app):
    """A paste changes the text and does not pass through the key handler.

    Driven through `_pump_input` rather than by calling `insert` directly,
    because the thing being checked is the wiring: a paste that skipped the
    settling would leave the index pointing into the list it used to be.
    """
    opened(app)
    for _ in range(25):
        app._on_key(key("down"))
    assert app.state.completion_index == 25

    app._pump_input(_Pasting("mo"))

    total = len(app._completions())
    assert total < 25, "the paste should have narrowed the list"
    assert 0 <= app.state.completion_index < total
    assert app.state.completion_top <= app.state.completion_index


def test_scrolling_then_filtering_does_not_accept_the_wrong_command(app):
    """The three failures the report asked about, in one sequence: no
    IndexError, no invisible selection, no wrong acceptance."""
    opened(app)
    for _ in range(30):
        app._on_key(key("down"))

    app._on_key(key("char", "s"))
    wanted = selected_name(app)
    app._on_key(key("enter"))

    assert app.state.editor.text == f"{wanted} "
    assert wanted.startswith("/s")


# --------------------------------------------------------------------------- #
# when there is no menu
# --------------------------------------------------------------------------- #


def test_arrows_fall_through_to_history_when_nothing_matches(app):
    """A prefix nothing answers must not swallow the arrow keys: they belong
    to the editor and to history."""
    for char in "/zzzz":
        app._on_key(key("char", char))
    assert app._completions() == []

    rows = composer_rows(app)
    assert not any("…" in row for row in rows), "a menu with nothing in it"

    app._on_key(key("up"))          # history, not a selection
    assert app.state.completion_index == 0


def test_ordinary_text_opens_no_menu(app):
    app._on_key(key("char", "h"))
    assert app._completions() == []


# --------------------------------------------------------------------------- #
# terminals of other sizes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("size", [(80, 12), (100, 20), (128, 36), (200, 60)])
def test_the_menu_fits_whatever_the_terminal_is(config, size):
    """Narrow enough that the prompt is nearly all of the screen, and wide
    enough that it is a rounding error. Neither may overrun the budget."""
    width, height = size
    app = App(config, demo=True)
    app.geometry = layout_module.compute(width, height)
    total = opened(app)

    budget = app.geometry.prompt.height
    for _ in range(total):
        assert len(composer_rows(app)) <= budget
        app._on_key(key("down"))


def test_a_very_short_prompt_still_shows_the_selection(config):
    """One row of menu is the hardest case: an indicator alone would be a list
    showing none of the list, so the row goes to the command."""
    app = App(config, demo=True)
    app.geometry = layout_module.compute(80, 12)
    total = opened(app)
    arrow = app.theme.glyphs.arrow

    for _ in range(min(total, 8)):
        rows = composer_rows(app)
        if any("…" in row or row.lstrip().startswith(arrow) for row in rows):
            assert any(row.lstrip().startswith(arrow) for row in rows), \
                "a menu was drawn with nothing selected"
        app._on_key(key("down"))


# --------------------------------------------------------------------------- #
# the decoder, which was never the problem
# --------------------------------------------------------------------------- #


# `test_input.py` already pins `\x1b[B` and `\x1bOB` to "down", so that is not
# restated here. What follows is the part that had no coverage: the Windows
# fallback, and the whole path from the bytes a terminal sends to the command
# the menu points at. The decoder was never the fault — it is tested here so
# that the next person can rule it out without reading three files.


def test_the_windows_console_fallback_still_sends_down():
    """When VT input cannot be enabled, msvcrt hands back a two-byte code and
    nothing in the suite covered the mapping."""
    assert WINDOWS_SPECIAL["P"].key == "down"
    assert WINDOWS_SPECIAL["H"].key == "up"


@pytest.mark.parametrize("sequence", ["\x1b[B", "\x1bOB"])
def test_a_decoded_arrow_moves_the_selection(app, sequence):
    """End to end, in both cursor modes: the bytes a terminal actually sends,
    through the decoder, into the index, out to the drawn menu.

    This is the test that would have located the bug. Every link in it was
    working except the last one.
    """
    total = opened(app)
    decoder = KeyDecoder()
    arrow = app.theme.glyphs.arrow

    for _ in range(5):
        for event in decoder.feed(sequence):
            if isinstance(event, KeyEvent):
                app._on_key(event)

    assert app.state.completion_index == 5, "the decoder or the handler"
    assert app.state.completion_top > 0, "five presses and the window sat still"

    name = app._completions()[5][0]
    rows = composer_rows(app)
    assert any(row.lstrip().startswith(arrow) and name in row for row in rows), \
        "the selection moved and the menu did not follow it"
    assert total > 5
