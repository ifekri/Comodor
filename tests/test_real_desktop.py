"""Against a real screen and a real mouse, when somebody has asked for one.

What is checked here cannot be checked against a stand-in: that the capture is
a picture of the screen rather than a black rectangle, that `SendInput` really
moves the pointer, and that the coordinate arithmetic survives contact with a
display whose shape nobody chose.

**These take over the machine they run on.** The pointer jumps across the
screen and clicks land wherever the test aims them. That is fine on a machine
set aside for it and unacceptable on the one somebody is working at — and the
platform check that used to gate them, `sys.platform != "win32"`, is true of
every Windows developer who types `pytest`. Their mouse moved, mid-sentence,
with no explanation, on every run. The fixture below that puts the pointer back
does not make that acceptable: the machine is unusable while they run, and a
run that crashes puts nothing back at all.

So they are opt-in. `COMODOR_REAL_DESKTOP=1` to run them, and CI does not set
it — a hosted runner has no screen worth measuring anyway.

    COMODOR_REAL_DESKTOP=1 pytest tests/test_real_desktop.py -n 0

`-n 0` because two of these move the same pointer, and in parallel each would
be measuring the other one's move.
"""

from __future__ import annotations

import os
import sys

import pytest

#: Set deliberately, on a machine nobody is using. Never in CI, never by
#: default, and never from a plain `pytest` on somebody's laptop.
ASKED_FOR = os.environ.get("COMODOR_REAL_DESKTOP", "").strip() not in ("", "0")

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32",
                       reason="the desktop backend is Windows-only so far"),
    pytest.mark.skipif(not ASKED_FOR,
                       reason="moves the real pointer — set "
                              "COMODOR_REAL_DESKTOP=1 on a machine you are "
                              "not using"),
]


@pytest.fixture
def machine():
    from comodor.desktop import screen

    return screen.backend()


@pytest.fixture(autouse=True)
def put_the_mouse_back(machine):
    """Whatever a test does to the pointer, the developer gets it back."""
    was = machine.cursor()
    yield
    machine.move_to(*was)


# --------------------------------------------------------------------------- #
# looking
# --------------------------------------------------------------------------- #


def test_the_screen_can_be_captured(machine):
    from comodor.desktop import png, screen

    shot = screen.capture(700)

    assert shot.data.startswith(b"\x89PNG")
    assert png.dimensions(shot.data) == (shot.width, shot.height)
    assert shot.tokens <= 700


def test_the_capture_is_a_picture_and_not_black(machine):
    """The failure a unit test cannot see. An empty buffer encodes to a
    perfectly valid PNG, and the model is handed a black rectangle every step
    without anything raising."""
    from comodor.desktop import screen

    shot = screen.capture(700)
    area = machine.active_monitor()
    raw = machine.grab(area, 64, 64)

    assert len(set(raw)) > 8, "the screen came back uniform"
    assert len(shot.data) > 2_000, "a PNG this small is not a screen"


def test_a_coordinate_from_a_capture_lands_where_it_should(machine):
    from comodor.desktop import screen

    shot = screen.capture(700)
    area = machine.active_monitor()

    for image_x, image_y in ((0, 0), (shot.width // 2, shot.height // 2),
                             (shot.width - 1, shot.height - 1)):
        x, y = shot.to_screen(image_x, image_y)
        assert area.left - 2 <= x <= area.right + 2
        assert area.top - 2 <= y <= area.bottom + 2


def test_zoom_is_sharper_than_the_wide_shot(machine):
    """The answer to small text on a large screen: a crop is a fraction of the
    pixels, so the same budget buys it at a higher scale."""
    from comodor.desktop import screen

    area = machine.active_monitor()
    wide = screen.capture(700)
    close = screen.zoom((area.left + 100, area.top + 100,
                         area.left + 400, area.top + 300), 700)

    assert close.scale > wide.scale


def test_the_process_is_dpi_aware(machine):
    """Without this the screen appears to be its scaled size and every click
    lands short by the scale factor - on the majority of Windows laptops,
    which ship at 125% or 150%."""
    assert machine.AWARENESS in ("per-monitor-v2", "per-monitor", "system")


# --------------------------------------------------------------------------- #
# touching
# --------------------------------------------------------------------------- #


def test_the_pointer_goes_where_it_is_sent(machine):
    """This one moves the real mouse, so it can lose a race with a hand.

    It failed once during a run while somebody was using the machine, and a
    person's hand on the mouse is not a defect in `move_to`. Asked twice: a
    move that is genuinely wrong is wrong both times, and interference is not.
    """
    area = machine.active_monitor()
    target = (area.left + area.width // 3, area.top + area.height // 3)

    for _attempt in (1, 2):
        machine.move_to(*target)
        at = machine.cursor()
        if abs(at[0] - target[0]) <= 1 and abs(at[1] - target[1]) <= 1:
            return
    raise AssertionError(f"asked for {target}, pointer sat at {at} twice")


def test_it_travels_rather_than_teleporting(machine):
    """The pause between setting off and arriving is the safety model made
    visible: it is the window in which a person can stop it."""
    import time

    from comodor.desktop import Desktop

    area = machine.active_monitor()
    desk = Desktop()
    desk.move(area.left + 50, area.top + 50)

    started = time.monotonic()
    desk.move(area.left + area.width // 2, area.top + area.height // 2)
    elapsed = time.monotonic() - started

    assert 0.15 < elapsed < 1.5, f"a move took {elapsed:.2f}s"


def test_the_foreground_window_can_be_read(machine):
    """The deny-list is built on this. A backend that always answered "" would
    let every refused window through, quietly."""
    assert isinstance(machine.foreground_title(), str)


def test_the_screen_is_not_locked_while_the_tests_run(machine):
    assert machine.screen_is_locked() is False


def test_every_monitor_is_found(machine):
    monitors = machine.monitors()
    virtual = machine.virtual_screen()

    assert monitors
    for rect in monitors:
        assert rect.width > 0 and rect.height > 0
        assert rect.left >= virtual.left and rect.top >= virtual.top
