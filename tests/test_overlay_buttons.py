"""The two buttons on the overlay panel, and what happens when they are hit.

The panel says how much of the grant is left and, until now, that the way to
end it was to move the mouse into a corner. That gesture is good for the moment
it was designed for — something going wrong, no time to aim — and invisible
otherwise: it works only if you read the caption, and by then you are reading
instead of stopping.

A button is what people look for. Two, in fact, because there are two different
wants and one control would answer neither: *make it stop*, and *stop covering
what I am reading*.

The hard part is not drawing them. The window is click-through on purpose — it
draws over a desktop the agent is clicking, and a window that swallowed those
clicks would break the thing it exists to illustrate. So the clicks have to be
taken for exactly as long as the pointer is over a button, and not one frame
longer. That is what most of this file is about.
"""

from __future__ import annotations

import sys

import pytest

from comodor.desktop.overlay import BUTTON_GAP, BUTTON_SIZE, Overlay


class Recorder:
    """Stands in for a canvas, remembering what was drawn on it."""

    def __init__(self, width: int = 1920) -> None:
        self.rectangles: list[tuple] = []
        self.texts: list[tuple] = []
        self._width = width
        self.bound: dict[str, object] = {}

    def __getitem__(self, key):
        if key == "width":
            return self._width
        raise KeyError(key)

    def create_rectangle(self, *box, **kwargs):
        self.rectangles.append((box, kwargs))

    def create_text(self, x, y, **kwargs):
        self.texts.append((x, y, kwargs))

    def create_line(self, *args, **kwargs):
        pass

    def create_oval(self, *args, **kwargs):
        pass

    def bind(self, event, handler):
        self.bound[event] = handler


def an_overlay(*, status="14m 46s left, anywhere on screen",
               on_stop=None, on_hide=None, width=1920) -> Overlay:
    """An Overlay with a fake canvas, drawable without a screen."""
    overlay = Overlay(status=lambda: status, on_stop=on_stop, on_hide=on_hide)
    overlay._canvas = Recorder(width)
    overlay._note = ""
    overlay._note_until = 0.0
    overlay._note_alarm = False
    overlay._hits = []
    overlay._clickable = False
    return overlay


class Press:
    """A click at a point on the canvas."""

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


# --------------------------------------------------------------------------- #
# they are drawn, and they are icons
# --------------------------------------------------------------------------- #


def test_both_buttons_are_drawn_when_both_can_do_something():
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    assert [name for name, *_ in overlay._hits] == ["stop", "hide"]


def test_they_carry_an_icon_and_not_a_word():
    """The panel is already three lines of text. Two more labels would make it
    a paragraph, and these two shapes mean the same thing everywhere."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    glyphs = [call[2].get("text") for call in overlay._canvas.texts
              if len(str(call[2].get("text", ""))) == 1]

    assert glyphs, "no single-character labels were drawn"
    for glyph in glyphs:
        assert not str(glyph).isascii() or not str(glyph).isalpha(), \
            f"{glyph!r} is a letter, not an icon"


def test_a_button_with_nothing_behind_it_is_not_drawn():
    """A control that does nothing is worse than no control: somebody presses
    it while something is going wrong and concludes the stop is broken."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=None)
    overlay._badge()

    assert [name for name, *_ in overlay._hits] == ["stop"]


def test_nothing_is_drawn_at_all_without_callbacks():
    overlay = an_overlay()
    overlay._badge()

    assert overlay._hits == []


def test_the_text_is_not_drawn_underneath_them():
    """Both are in the same panel, and the panel is sized to fit both."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    leftmost_button = min(x1 for _, x1, _, _, _ in overlay._hits)
    for x, _, kwargs in overlay._canvas.texts:
        if len(str(kwargs.get("text", ""))) > 1:      # a line, not an icon
            assert x < leftmost_button, \
                f"{kwargs['text']!r} is drawn under the buttons"


def test_they_are_big_enough_to_hit_in_a_hurry():
    """The stop button exists for the moment somebody wants it *now*. A
    twelve-pixel target is a target you miss, and missing it means clicking
    through to whatever the agent is driving."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    for name, x1, y1, x2, y2 in overlay._hits:
        assert x2 - x1 >= 20, f"{name} is {x2 - x1}px wide"
        assert y2 - y1 >= 20, f"{name} is {y2 - y1}px tall"
        assert x2 - x1 == BUTTON_SIZE and y2 - y1 == BUTTON_SIZE


def test_there_is_space_between_them():
    """Adjacent to a button that cannot be undone, a mis-aimed pixel matters."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    stop = next(hit for hit in overlay._hits if hit[0] == "stop")
    hide = next(hit for hit in overlay._hits if hit[0] == "hide")

    assert hide[1] - stop[3] >= BUTTON_GAP


def test_they_sit_inside_the_panel():
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    panel = overlay._canvas.rectangles[0][0]          # drawn first, as backing
    for name, x1, y1, x2, y2 in overlay._hits:
        assert panel[0] <= x1 and x2 <= panel[2], f"{name} is off the panel"
        assert panel[1] <= y1 and y2 <= panel[3], f"{name} is off the panel"


def test_the_caption_names_both_ways_of_stopping():
    """The corner still works and still suits a different moment. A caption
    that mentioned only the button would be teaching somebody to aim in the
    situation where aiming is hardest."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    said = " ".join(str(kwargs.get("text", ""))
                    for _, _, kwargs in overlay._canvas.texts)

    assert "corner" in said
    assert "stop here" in said


# --------------------------------------------------------------------------- #
# pressing them
# --------------------------------------------------------------------------- #


def test_pressing_stop_calls_back():
    stopped = []
    overlay = an_overlay(on_stop=lambda: stopped.append(True),
                         on_hide=lambda: None)
    overlay._badge()

    name, x1, y1, x2, y2 = next(hit for hit in overlay._hits
                                if hit[0] == "stop")
    overlay._pressed(Press((x1 + x2) // 2, (y1 + y2) // 2))

    assert stopped == [True]


def test_pressing_hide_puts_the_panel_away_and_says_so():
    hidden = []
    overlay = an_overlay(on_stop=lambda: None,
                         on_hide=lambda: hidden.append(True))
    overlay._badge()

    _, x1, y1, x2, y2 = next(hit for hit in overlay._hits if hit[0] == "hide")
    overlay._pressed(Press((x1 + x2) // 2, (y1 + y2) // 2))

    assert hidden == [True]
    assert overlay._hidden is True

    overlay._canvas.texts.clear()
    overlay._badge()
    assert overlay._canvas.texts == [], "the panel is still on screen"


def test_a_press_between_the_buttons_does_nothing():
    """They are small and close together, and stopping is not undoable."""
    done = []
    overlay = an_overlay(on_stop=lambda: done.append("stop"),
                         on_hide=lambda: done.append("hide"))
    overlay._badge()

    stop = next(hit for hit in overlay._hits if hit[0] == "stop")
    hide = next(hit for hit in overlay._hits if hit[0] == "hide")
    between = (stop[3] + hide[1]) // 2
    overlay._pressed(Press(between, (stop[2] + stop[4]) // 2))

    assert done == [], "a click in the gap did something"


def test_a_press_nowhere_near_them_does_nothing():
    done = []
    overlay = an_overlay(on_stop=lambda: done.append("stop"),
                         on_hide=lambda: done.append("hide"))
    overlay._badge()

    overlay._pressed(Press(10, 600))

    assert done == []


def test_a_callback_that_raises_does_not_take_the_overlay_with_it():
    """The panel is the only thing telling the person what is happening. It
    has to survive whatever it calls."""
    def explode():
        raise RuntimeError("boom")

    overlay = an_overlay(on_stop=explode, on_hide=lambda: None)
    overlay._badge()

    _, x1, y1, x2, y2 = next(hit for hit in overlay._hits if hit[0] == "stop")
    overlay._pressed(Press((x1 + x2) // 2, (y1 + y2) // 2))     # must not raise


def test_stopping_says_it_stopped():
    """Nothing else on screen changes at the moment of the press — the grant
    ends silently — so the panel has to say it happened."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._badge()

    _, x1, y1, x2, y2 = next(hit for hit in overlay._hits if hit[0] == "stop")
    overlay._pressed(Press((x1 + x2) // 2, (y1 + y2) // 2))

    queued = [payload for what, payload in list(overlay._queue.queue)
              if what == "say"]
    assert queued and "Stopped" in queued[0][0]
    assert queued[0][1] is True, "a stop is not a quiet notice"


# --------------------------------------------------------------------------- #
# hidden, and back again
# --------------------------------------------------------------------------- #


def test_hiding_does_not_silence_an_alarm():
    """Hiding asks for the corner of the screen back. A refusal is not a
    countdown, and losing it would be a different feature than the one that
    was asked for."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._hidden = True
    overlay._note = "Refused: that window is not in scope"
    overlay._note_until = float("inf")
    overlay._note_alarm = True

    overlay._badge()

    said = " ".join(str(kwargs.get("text", ""))
                    for _, _, kwargs in overlay._canvas.texts)
    assert "Refused" in said


def test_show_brings_it_back():
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._hidden = True

    overlay.show()
    overlay._badge()

    assert overlay._hits, "the buttons did not come back"


# --------------------------------------------------------------------------- #
# the click-through problem, which is the whole difficulty
# --------------------------------------------------------------------------- #


def test_the_window_takes_clicks_only_while_the_pointer_is_on_a_button(
        monkeypatch):
    """The window must stay click-through, or it swallows the clicks the agent
    is making. It must also receive a click on a button. Both hold only if the
    style changes with the pointer."""
    if sys.platform != "win32":
        pytest.skip("the style flag is a Windows idea")

    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._origin = (0, 0)
    overlay._handle = 1
    overlay._badge()

    changes: list[bool] = []
    monkeypatch.setattr(overlay, "_set_clickable",
                        lambda wanted: changes.append(wanted))

    _, x1, y1, x2, y2 = overlay._hits[0]
    monkeypatch.setattr("comodor.desktop.win32.cursor",
                        lambda: ((x1 + x2) // 2, (y1 + y2) // 2))
    overlay._watch_the_pointer()
    assert changes[-1] is True, "a click on the button would pass through"

    monkeypatch.setattr("comodor.desktop.win32.cursor", lambda: (5, 900))
    overlay._watch_the_pointer()
    assert changes[-1] is False, "the overlay would swallow the agent's clicks"


def test_it_stays_click_through_when_there_are_no_buttons(monkeypatch):
    overlay = an_overlay()
    overlay._origin = (0, 0)
    overlay._handle = 1
    overlay._badge()

    changes: list[bool] = []
    monkeypatch.setattr(overlay, "_set_clickable",
                        lambda wanted: changes.append(wanted))
    overlay._watch_the_pointer()

    assert changes == [False]


def test_a_pointer_that_cannot_be_read_leaves_it_click_through(monkeypatch):
    """Without a position this cannot be decided, and the safe answer is the
    one that never interferes with somebody's desktop."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._origin = (0, 0)
    overlay._handle = 1
    overlay._badge()

    changes: list[bool] = []
    monkeypatch.setattr(overlay, "_set_clickable",
                        lambda wanted: changes.append(wanted))

    def refuse():
        raise OSError("no cursor here")

    monkeypatch.setattr("comodor.desktop.win32.cursor", refuse)
    overlay._watch_the_pointer()

    assert changes == [False]


def test_the_pointer_is_read_in_the_same_space_the_buttons_are_drawn_in(
        monkeypatch):
    """The canvas starts at the virtual screen's origin, which is not (0, 0)
    on a multi-monitor desk with a second screen to the left. Comparing a
    screen coordinate against a canvas one puts the hit region somewhere
    nobody can reach."""
    if sys.platform != "win32":
        pytest.skip("the style flag is a Windows idea")

    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._origin = (-1920, 0)          # a monitor to the left of the main
    overlay._handle = 1
    overlay._badge()

    changes: list[bool] = []
    monkeypatch.setattr(overlay, "_set_clickable",
                        lambda wanted: changes.append(wanted))

    _, x1, y1, x2, y2 = overlay._hits[0]
    # Where that button actually is on the desk.
    monkeypatch.setattr("comodor.desktop.win32.cursor",
                        lambda: ((x1 + x2) // 2 - 1920, (y1 + y2) // 2))
    overlay._watch_the_pointer()

    assert changes[-1] is True, \
        "the origin was not subtracted — the buttons are unreachable"


def test_the_agents_own_pointer_does_not_arm_the_buttons(monkeypatch):
    """The agent drives the same system cursor a person does.

    So a `left_click` aimed at anything the panel happens to cover moves the
    pointer into a button, the window takes clicks, and the agent's own click
    lands on Stop — silently ending the grant, and making the whole top-centre
    strip of the screen unusable to it. Which is where menus live.

    `Guard` already answers "did a hand do this?" for the corner gesture. The
    overlay asks the same question.
    """
    if sys.platform != "win32":
        pytest.skip("the style flag is a Windows idea")

    from comodor.desktop.guard import Guard

    guard = Guard()
    guard.allow(600, reason="test")

    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._origin = (0, 0)
    overlay._handle = 1
    overlay.a_hand_is_on_it = guard.a_hand_is_on_it
    overlay._badge()

    _, x1, y1, x2, y2 = overlay._hits[0]
    middle = ((x1 + x2) // 2, (y1 + y2) // 2)

    changes: list[bool] = []
    monkeypatch.setattr(overlay, "_set_clickable",
                        lambda wanted: changes.append(wanted))
    monkeypatch.setattr("comodor.desktop.win32.cursor", lambda: middle)

    guard.note_pointer(middle)          # the agent put it there
    overlay._watch_the_pointer()
    assert changes[-1] is False, \
        "the overlay would swallow a click the agent aimed underneath it"

    guard.note_pointer((10, 900))       # the agent left it elsewhere
    overlay._watch_the_pointer()
    assert changes[-1] is True, "the stop button now ignores a person"


def test_with_nothing_driving_the_pointer_every_move_is_a_persons():
    """An overlay built without a guard — a test, a preview — must not decide
    that nobody is there."""
    overlay = an_overlay(on_stop=lambda: None)

    assert overlay.a_hand_is_on_it((5, 5)) is True


def test_the_style_is_only_written_when_it_changes(monkeypatch):
    """`_watch_the_pointer` runs sixty times a second. Setting a window style
    that often, for no change, is a syscall per frame for nothing."""
    overlay = an_overlay(on_stop=lambda: None, on_hide=lambda: None)
    overlay._handle = 1
    overlay._clickable = False

    calls: list[int] = []

    class FakeUser32:
        @staticmethod
        def GetWindowLongW(handle, index):
            return 0x00000020

        @staticmethod
        def SetWindowLongW(handle, index, style):
            calls.append(style)

    monkeypatch.setattr("comodor.desktop.win32.user32", FakeUser32)

    overlay._set_clickable(False)
    assert calls == [], "wrote a style that was already set"

    overlay._set_clickable(True)
    assert len(calls) == 1

    overlay._set_clickable(True)
    assert len(calls) == 1, "wrote the same style twice"


# --------------------------------------------------------------------------- #
# what the tool wires them to
# --------------------------------------------------------------------------- #


def test_the_stop_button_ends_the_grant(config, bus):
    """Pressed, it has to do what the corner does — not merely say something."""
    from comodor.tools.computer import Computer

    tool = Computer(overlay=False)
    tool.guard.allow(600, reason="test")
    assert tool.guard.active

    tool._stopped_from_the_screen()

    assert not tool.guard.active, "the grant survived the stop button"


def test_the_stop_button_says_why_it_stopped():
    """A refusal that says "stopped" and not why reads as a crash."""
    from comodor.tools.computer import Computer

    tool = Computer(overlay=False)
    tool.guard.allow(600, reason="test")
    tool._stopped_from_the_screen()

    assert "stop" in tool.guard.status().lower()


def test_hiding_does_not_end_the_grant():
    """The two buttons mean different things, and confusing them would either
    leave a panel nobody wants or stop work nobody wanted stopped."""
    from comodor.tools.computer import Computer

    tool = Computer(overlay=False)
    tool.guard.allow(600, reason="test")

    tool._hidden_from_the_screen()

    assert tool.guard.active, "hiding the panel stopped the work"
    assert tool.overlay_hidden is True


def test_the_overlay_is_told_how_to_recognise_the_agent():
    """Without this the panel is a trap: the agent clicks its own stop button
    the first time it aims at anything underneath the countdown."""
    import inspect

    from comodor.tools.computer import Computer

    source = inspect.getsource(Computer._show)

    assert "a_hand_is_on_it=" in source, \
        "the overlay cannot tell the agent's pointer from a person's"


def test_the_guard_answers_that_question_the_same_way_it_does_for_corners():
    """One mechanism, two callers. A second implementation would be a second
    thing to get wrong, and this one decides whether a stop works."""
    from comodor.desktop.guard import Guard

    guard = Guard()
    guard.allow(600, reason="test")
    guard.note_pointer((500, 500))

    assert guard.a_hand_is_on_it((500, 500)) is False
    assert guard.a_hand_is_on_it((900, 500)) is True

    # And the corner check still goes through it, rather than repeating it.
    corners = [(0, 0, 1920, 1080)]
    assert guard.user_moved_away((500, 500), corners) is False
    assert guard.user_moved_away((2, 2), corners) is True


def test_the_overlay_is_given_both_callbacks():
    """Checked against the source: the buttons are drawn only when there is
    something behind them, so a `_show` that forgot to pass these would
    silently produce a panel with no buttons at all."""
    import inspect

    from comodor.tools.computer import Computer

    source = inspect.getsource(Computer._show)

    assert "on_stop=" in source, "the panel would have no stop button"
    assert "on_hide=" in source, "the panel would have no hide button"
