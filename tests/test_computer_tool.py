"""The computer tool: what it refuses, what it says, and where it clicks.

Driven against a stand-in for the machine rather than a real one, so it runs on
every platform and in CI. What the stand-in cannot check — that `SendInput`
really moves a pointer — is checked in `test_real_desktop.py` on a real screen.

The interesting cases are all refusals. A tool that can do anything to a
computer is mostly interesting for the moments it declines.
"""

from __future__ import annotations

import base64
import time

import pytest

from comodor.desktop.guard import Guard
from comodor.events import Cancellation, EventBus, Kind
from comodor.safety import CheckpointStore, PermissionEngine, Redactor
from comodor.tools.base import ToolContext
from comodor.tools.computer import Computer

# --------------------------------------------------------------------------- #
# a machine that is not one
# --------------------------------------------------------------------------- #


class Rect:
    def __init__(self, left, top, width, height):
        self.left, self.top = left, top
        self.width, self.height = width, height
        self.right, self.bottom = left + width, top + height


class FakeMachine:
    """Records what it was asked to do, and answers plausibly."""

    def __init__(self) -> None:
        self.at = (400, 300)
        self.did: list[str] = []
        self.typed = ""
        self.title = "Untitled - Notepad"
        self.is_locked = False

    def cursor(self):
        return self.at

    def move_to(self, x, y):
        self.at = (x, y)

    def button(self, which, *, down):
        self.did.append(f"{which} {'down' if down else 'up'}")

    def wheel(self, clicks, *, horizontal=False):
        self.did.append(f"wheel {clicks} {'h' if horizontal else 'v'}")

    def key(self, code, *, down, extended=False):
        self.did.append(f"key {code:#x} {'down' if down else 'up'}")

    def unicode_char(self, character):
        self.typed += character

    def foreground_title(self):
        return self.title

    def screen_is_locked(self):
        return self.is_locked

    def monitors(self):
        return [Rect(0, 0, 1920, 1080)]

    def virtual_screen(self):
        return Rect(0, 0, 1920, 1080)

    def active_monitor(self):
        return Rect(0, 0, 1920, 1080)

    def grab(self, area, width, height):
        return bytes(width * height * 4)


@pytest.fixture
def machine(monkeypatch):
    fake = FakeMachine()
    monkeypatch.setattr("comodor.desktop.screen.backend", lambda: fake)
    monkeypatch.setattr("comodor.desktop.backend", lambda: fake)
    return fake


@pytest.fixture
def tool(machine):
    made = Computer(guard=Guard())
    made._desk()                     # build it now, against the fake
    return made


@pytest.fixture
def ctx(config, tmp_path):
    bus = EventBus()
    bus.subscribe(lambda event: None)          # somebody is listening
    return ToolContext(config=config, permissions=PermissionEngine(config, bus),
                       checkpoints=CheckpointStore(tmp_path), bus=bus,
                       redact=Redactor([]), cancel=Cancellation(), cwd=tmp_path)


def granted(tool, seconds=300, scope=""):
    tool.guard.allow(seconds, scope=scope)
    return tool


def look(tool, ctx):
    """A screenshot, so coordinates mean something afterwards."""
    return tool.invoke(ctx, {"action": "screenshot"})


# --------------------------------------------------------------------------- #
# nothing happens without permission
# --------------------------------------------------------------------------- #


def test_it_asks_before_the_first_action(tool, ctx):
    answered: list[str] = []

    def reply(event):
        if event.kind is Kind.REQUEST:
            request = event.payload["request"]
            answered.append(request.prompt)
            request.answer("15 minutes")

    ctx.bus.subscribe(reply)

    result = tool.invoke(ctx, {"action": "cursor_position"})

    assert result.ok
    assert answered and "screen" in answered[0]
    assert tool.guard.active


def test_the_question_says_what_it_costs(tool, ctx):
    """Consent to something invisible is not consent. The screenshot going to
    the model, and everything visible going with it, is the part people do not
    think of."""
    seen: list[str] = []

    def reply(event):
        if event.kind is Kind.REQUEST:
            seen.append(event.payload["request"].detail)
            event.payload["request"].answer("no")

    ctx.bus.subscribe(reply)
    tool.invoke(ctx, {"action": "cursor_position"})

    detail = seen[0]
    assert "Screenshots go to the model" in detail
    assert "corner" in detail
    assert "password" in detail


def test_declining_touches_nothing(tool, ctx, machine):
    def refuse(event):
        if event.kind is Kind.REQUEST:
            event.payload["request"].answer("no")

    ctx.bus.subscribe(refuse)

    result = tool.invoke(ctx, {"action": "left_click", "coordinate": [10, 10]})

    assert not result.ok
    assert "did not allow" in result.content
    assert machine.did == []


def test_nobody_listening_is_not_the_same_as_refused(tool, ctx):
    """A bus with no subscribers is not None, so the question went to an empty
    room and the timeout was reported as the user saying no."""
    quiet = EventBus()
    ctx.bus = quiet

    result = tool.invoke(ctx, {"action": "cursor_position"})

    assert not result.ok
    assert "nobody here to ask" in result.content
    assert "comodor computer" in result.content


def test_plan_mode_blocks_it(tool, ctx):
    ctx.config.agent.mode = "plan"
    granted(tool)

    result = tool.invoke(ctx, {"action": "left_click", "coordinate": [1, 1]})

    assert not result.ok
    assert "Plan mode" in result.content


# --------------------------------------------------------------------------- #
# the guard, on every action
# --------------------------------------------------------------------------- #


def test_the_corner_stops_an_action_that_touches_nothing(tool, ctx, machine):
    """`cursor_position` moves nothing, so the desktop never consulted the
    guard for it — and the tool answered normally while the user was holding
    the mouse in a corner asking it to stop."""
    granted(tool)
    tool.guard.note_pointer((900, 500))
    machine.at = (2, 2)

    result = tool.invoke(ctx, {"action": "cursor_position"})

    assert not result.ok
    assert "corner" in result.content
    assert not tool.guard.active


def test_a_grant_that_ran_out_asks_again_and_says_why(tool, ctx):
    """Refusing outright would strand a task halfway. "Your time is up, more?"
    is the question the moment actually poses — and somebody who granted
    fifteen minutes should be told that is why they are being asked again,
    rather than shown the same first-time prompt."""
    asked: list[str] = []

    def reply(event):
        if event.kind is Kind.REQUEST:
            asked.append(event.payload["request"].prompt)
            event.payload["request"].answer("no")

    ctx.bus.subscribe(reply)
    granted(tool, seconds=0.05)
    time.sleep(0.08)

    result = tool.invoke(ctx, {"action": "cursor_position"})

    assert not result.ok
    assert asked and "ran out" in asked[0]


def test_a_question_nobody_answers_does_not_take_ten_minutes(tool, ctx):
    """It waits as long as the permission engine does, and no longer. A
    hardcoded two minutes here reported one refused action as having taken two
    minutes."""
    ctx.permissions.prompt_timeout = 0.05

    result = tool.invoke(ctx, {"action": "cursor_position"})

    assert not result.ok
    assert result.elapsed < 5.0
    assert "Nobody answered" in result.content


def test_a_password_window_is_refused_mid_task(tool, ctx, machine):
    """The check is per action, so a window that appears halfway through a
    granted run is caught."""
    granted(tool)
    look(tool, ctx)
    machine.title = "1Password — Vault"

    result = tool.invoke(ctx, {"action": "type", "text": "hunter2"})

    assert not result.ok
    assert machine.typed == ""


# --------------------------------------------------------------------------- #
# what it does when it is allowed to
# --------------------------------------------------------------------------- #


def test_a_screenshot_comes_back_as_an_image(tool, ctx):
    granted(tool)

    result = look(tool, ctx)

    assert result.ok
    assert result.meta["image"], "the loop attaches meta['image'] for vision"
    assert base64.b64decode(result.meta["image"]).startswith(b"\x89PNG")
    assert "Coordinates you give are in these pixels" in result.content


def test_a_coordinate_is_read_in_the_pixels_of_the_screenshot(tool, ctx, machine):
    """The model answers in image pixels; the mouse works in screen pixels.
    Getting this wrong puts every click off by the scale factor."""
    granted(tool)
    shot = look(tool, ctx)
    scale = shot.meta["scale"]

    tool.invoke(ctx, {"action": "mouse_move", "coordinate": [100, 50]})

    assert machine.at == (round(100 / scale), round(50 / scale))


def test_clicking_without_a_screenshot_says_to_take_one(tool, ctx):
    granted(tool)

    result = tool.invoke(ctx, {"action": "left_click", "coordinate": [10, 10]})

    assert not result.ok
    assert "screenshot" in result.content


def test_a_double_click_is_two_presses(tool, ctx, machine):
    granted(tool)
    look(tool, ctx)

    tool.invoke(ctx, {"action": "double_click", "coordinate": [10, 10]})

    assert machine.did.count("left down") == 2


def test_typing_says_it_may_have_been_changed(tool, ctx, machine):
    """Windows 11's Notepad turned `ümlaut` into `umlaut` while this was being
    built. The model has no other way to find that out."""
    granted(tool)

    result = tool.invoke(ctx, {"action": "type", "text": "hello"})

    assert machine.typed == "hello"
    assert "autocorrect" in result.content


def test_a_key_combination_holds_and_releases_in_order(tool, ctx, machine):
    granted(tool)

    tool.invoke(ctx, {"action": "key", "text": "ctrl+shift+s"})

    assert machine.did == ["key 0x11 down", "key 0x10 down",
                           "key 0x53 down", "key 0x53 up",
                           "key 0x10 up", "key 0x11 up"]


def test_zoom_needs_something_to_zoom_into(tool, ctx):
    granted(tool)

    result = tool.invoke(ctx, {"action": "zoom", "region": [0, 0, 10, 10]})

    assert not result.ok
    assert "screenshot before zooming" in result.content


def test_zoom_does_not_move_the_frame_of_reference(tool, ctx, machine):
    """After looking closely at a corner, a coordinate still means what it
    meant in the wide shot — otherwise the model has to track which picture it
    is answering about."""
    granted(tool)
    wide = look(tool, ctx)
    tool.invoke(ctx, {"action": "zoom", "region": [0, 0, 100, 100]})

    tool.invoke(ctx, {"action": "mouse_move", "coordinate": [200, 100]})

    assert machine.at == (round(200 / wide.meta["scale"]),
                          round(100 / wide.meta["scale"]))


def test_an_unknown_action_lists_the_real_ones(tool, ctx):
    granted(tool)

    result = tool.invoke(ctx, {"action": "reboot"})

    assert not result.ok
    assert "screenshot" in result.content and "left_click" in result.content


def test_the_summary_reads_like_a_sentence(tool):
    assert tool.summary({"action": "left_click", "coordinate": [8, 9]}) \
        == "computer: left_click at (8, 9)"
    assert "'hi'" in tool.summary({"action": "type", "text": "hi"})


def test_closing_takes_the_permission_away(tool):
    granted(tool)
    tool.close()

    assert not tool.guard.active
