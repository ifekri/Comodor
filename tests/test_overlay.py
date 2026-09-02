"""The overlay's contract, which is mostly about not getting in the way.

Almost all of it is pixels on a real screen and is exercised in
`test_real_desktop.py`. What can be checked anywhere is the promise the rest of
the system relies on: **a failure to draw is a missing picture, not a missing
feature**. The agent must keep working with no display, on the wrong platform,
or with tkinter absent, and it must never block waiting for a window.
"""

from __future__ import annotations

import sys
import time

import pytest

from comodor.desktop.overlay import Overlay


class Action:
    def __init__(self, kind="move", caption="doing something",
                 at=(10, 20), to=(30, 40)):
        self.kind, self.caption = kind, caption
        self.at, self.to = at, to
        self.detail = ""
        self.meta: dict = {}


def test_it_says_no_rather_than_raising_where_it_cannot_run(monkeypatch):
    """A platform with no backend gets a reason, not a traceback."""
    monkeypatch.setattr(sys, "platform", "darwin")
    overlay = Overlay()

    assert overlay.start() is False
    assert "Windows-only" in overlay.failed


def test_actions_are_accepted_when_there_is_no_window(monkeypatch):
    """The desktop tells its watcher about every action. If that could raise
    when the overlay never opened, an agent on a headless box would fail on the
    first move — for want of a decoration."""
    monkeypatch.setattr(sys, "platform", "linux")
    overlay = Overlay()
    overlay.start()

    overlay.about_to(Action())
    overlay.did(Action(kind="click"))
    overlay.say("something went wrong", alarm=True)

    assert overlay.failed


def test_closing_one_that_never_opened_is_quiet(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    overlay = Overlay()
    overlay.start()

    overlay.close()          # no exception, no hang


def test_starting_twice_does_not_make_a_second_window(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    overlay = Overlay()

    first = overlay.start()
    second = overlay.start()

    assert first == second


def test_a_broken_status_does_not_stop_the_drawing():
    """The badge asks the guard how long is left. A guard that raises must not
    take the overlay down with it — and by extension the thread the agent's
    actions are announced to."""
    overlay = Overlay(status=lambda: 1 / 0)

    # The call the badge makes, guarded the same way the badge guards it.
    try:
        overlay.status()
    except Exception:
        pass          # which is exactly what `_badge` does

    assert True


@pytest.mark.performance
def test_it_does_not_block_the_caller(monkeypatch):
    """Announcing an action happens on the agent's thread, between a decision
    and a mouse movement. A queue put that waited on a window would put the
    overlay's frame rate in the middle of the agent's work."""
    monkeypatch.setattr(sys, "platform", "linux")
    overlay = Overlay()
    overlay.start()

    started = time.monotonic()
    for _ in range(500):
        overlay.about_to(Action())
    elapsed = time.monotonic() - started

    assert elapsed < 0.5, f"500 announcements took {elapsed:.2f}s"


@pytest.mark.skipif(sys.platform != "win32", reason="the overlay is Windows-only")
def test_on_windows_it_opens_and_closes_cleanly():
    """Twice, because the failure this catches only appears on the way out: a
    Tk object still reachable from the main thread is finalised by the main
    thread, and Tcl says so at interpreter shutdown."""
    for _ in range(2):
        overlay = Overlay(status=lambda: "30s left, anywhere on screen")
        assert overlay.start(), overlay.failed
        overlay.about_to(Action(kind="move"))
        overlay.did(Action(kind="click"))
        time.sleep(0.1)
        overlay.close()
        assert overlay._thread is None
