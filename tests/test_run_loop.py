"""The frame loop itself, driven through stub terminal I/O.

``App.run`` is the one place where input, agent events and rendering meet, and
it is the hardest part to check by hand — a mistake there shows up as a frozen
interface, not an exception. Here it runs against a stub terminal that replays a
scripted keystream and a stub ``Live`` that counts repaints.
"""

from __future__ import annotations

import threading
import time

import pytest

from comodor.providers.base import ToolCall
from comodor.providers.fake import FakeProvider, Script
from comodor.ui import app as app_module
from comodor.ui.input.keys import KeyEvent, MouseEvent


class StubTerminal:
    """Replays queued events, then reports nothing forever."""

    def __init__(self, events: list) -> None:
        self.queued = list(events)
        self.stopped = False
        self.mouse_enabled = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stopped = True

    def poll(self, limit: int = 128) -> list:
        batch, self.queued = self.queued[:limit], self.queued[limit:]
        return batch

    def stop(self):
        self.stopped = True


class StubLive:
    """Counts frames instead of painting them."""

    def __init__(self, renderable, **kwargs):
        self.frames = 0
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def update(self, renderable, refresh: bool = False):
        self.frames += 1


@pytest.fixture
def loop_app(config, monkeypatch):
    instance = app_module.App(config, demo=True)
    instance.gateway._instances["fake"] = FakeProvider([
        Script(text="Looking around.", tool_calls=[
            ToolCall(id="c1", name="list_dir", arguments={"path": "."})]),
        Script(text="All done."),
    ])
    return instance


def run_with(app, events, monkeypatch, budget: float = 3.0):
    """Run the loop until it quits or the budget expires."""
    terminal = StubTerminal(events)
    live = StubLive(None)
    monkeypatch.setattr(app_module, "TerminalInput", lambda **kwargs: terminal)
    monkeypatch.setattr(app_module, "Live", lambda *args, **kwargs: live)

    deadline = time.monotonic() + budget
    watchdog = threading.Timer(budget, lambda: setattr(app, "running", False))
    watchdog.start()
    try:
        app.run()
    finally:
        watchdog.cancel()
    # Shutting down is allowed to wait for a turn still in flight, so the
    # exit cannot be quicker than that however fast the loop itself is. The
    # tolerance is that budget plus slack, taken from the source rather than
    # guessed, or the two drift apart and the test fails on a loaded machine
    # for a reason that is not a bug.
    allowed = app_module.SHUTDOWN_JOIN_SECONDS + 1.5
    assert time.monotonic() < deadline + allowed, "the loop did not exit"
    return terminal, live


def test_the_loop_starts_paints_and_exits_cleanly(loop_app, monkeypatch):
    quit_keys = [KeyEvent("char", "d", ctrl=True)]
    terminal, live = run_with(loop_app, quit_keys, monkeypatch)

    assert live.frames >= 1, "nothing was ever drawn"
    assert loop_app.running is False
    assert terminal.stopped, "the terminal must be restored on the way out"


def test_a_whole_conversation_runs_through_the_loop(loop_app, monkeypatch):
    events = [KeyEvent("char", char) for char in "look around"]
    events.append(KeyEvent("enter"))

    run_with(loop_app, events, monkeypatch, budget=4.0)

    kinds = [entry.kind for entry in loop_app.state.entries]
    assert "user" in kinds
    assert "assistant" in kinds
    assert "tool" in kinds
    assert loop_app.state.status.busy is False


def test_a_click_on_send_works_through_the_loop(loop_app, monkeypatch):
    loop_app.state.editor.text = "do something"
    loop_app.state.editor.cursor = len(loop_app.state.editor.text)

    # The geometry is computed on the first frame, so aim at where SEND lands
    # for the console size the stub reports.
    from comodor.ui import layout as layout_module

    geometry = layout_module.compute(loop_app.console.size.width,
                                     loop_app.console.size.height)
    events = []
    if geometry.hints:
        send = geometry.hints["send"]
        events.append(MouseEvent(send.x + 1, send.y, "press"))
    else:
        events.append(KeyEvent("enter"))

    run_with(loop_app, events, monkeypatch, budget=4.0)
    assert any(entry.kind == "user" for entry in loop_app.state.entries)


def test_the_session_is_saved_on_exit(loop_app, monkeypatch):
    events = [KeyEvent("char", char) for char in "hello"]
    events += [KeyEvent("enter"), KeyEvent("char", "d", ctrl=True)]

    run_with(loop_app, events, monkeypatch, budget=4.0)

    stored = loop_app.sessions.list_sessions()
    assert stored, "the session should be recoverable afterwards"
    assert stored[0].messages > 0

    replayed = loop_app.sessions.load(stored[0].id)
    assert any(message.content == "hello" for message in replayed)


def test_export_writes_a_readable_transcript(loop_app, monkeypatch):
    events = [KeyEvent("char", char) for char in "hello"] + [KeyEvent("enter")]
    run_with(loop_app, events, monkeypatch, budget=4.0)

    loop_app._command("/export", "md")
    exports = list(loop_app.config.paths.exports.glob("*.md"))
    assert exports
    text = exports[0].read_text(encoding="utf-8")
    assert "## User" in text and "hello" in text
