"""Driving the machine: the parts that can be checked without one.

The capture and the input need a real screen and a real mouse, so they live in
`test_real_desktop.py` behind a skip. What is here is everything that decides
*whether* and *where* — the arithmetic that turns a model's coordinate into a
place on the screen, the key names, and the guard, which is the file that makes
the rest of it safe to have.

The guard tests are written as the situations they exist for rather than as
method calls: a grant that ran out, a password manager in front, a hand pulling
the mouse away.
"""

from __future__ import annotations

import time

import pytest

from comodor.desktop import keys, screen
from comodor.desktop.guard import Grant, Guard, Refused, Stopped

# --------------------------------------------------------------------------- #
# how large a screenshot should be
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width, height", [
    (1920, 1080),        # the ordinary laptop
    (3840, 1080),        # the ultrawide this was built against
    (2560, 1440),
    (1366, 768),
    (3840, 2160),        # 4k
    (1080, 1920),        # rotated
])
def test_every_screen_fits_inside_the_model_limits(width, height):
    """Both limits, on every shape. Either one exceeded is a refused request."""
    wide, high, scale = screen.fit(width, height)

    assert max(wide, high) <= screen.LONG_EDGE
    assert screen.tokens_for(wide, high) <= screen.DEFAULT_TOKENS
    assert 0 < scale <= 1.0


def test_a_bigger_budget_buys_a_bigger_picture():
    small = screen.fit(3840, 1080, 700)
    large = screen.fit(3840, 1080, 4000)

    assert large[0] > small[0]
    assert screen.tokens_for(*large[:2]) > screen.tokens_for(*small[:2])


def test_the_budget_cannot_be_pushed_past_what_the_model_takes():
    """A number out of a config file is not a reason to send a refused image."""
    wide, high, _ = screen.fit(3840, 2160, budget=99_999)

    assert screen.tokens_for(wide, high) <= screen.MAX_TOKENS
    assert max(wide, high) <= screen.LONG_EDGE


def test_a_small_screen_is_not_enlarged():
    """Scaling up invents detail and costs tokens for it."""
    wide, high, scale = screen.fit(800, 600, 4000)

    assert (wide, high) == (800, 600)
    assert scale == 1.0


def test_an_ultrawide_is_not_squeezed_to_a_strip():
    """1280 wide is the usual advice and it makes this screen unreadable: a
    three-times reduction, and the model guesses at text instead of reading
    it. Measured on the real thing — legible at 2068, not at 1280."""
    wide, _, _ = screen.fit(3840, 1080)

    assert wide > 1600


# --------------------------------------------------------------------------- #
# the coordinate, which everything turns on
# --------------------------------------------------------------------------- #


def shot(scale: float = 0.5, origin: tuple[int, int] = (0, 0),
         size: tuple[int, int] = (1920, 1080)) -> screen.Shot:
    return screen.Shot(data=b"", width=round(size[0] * scale),
                       height=round(size[1] * scale), scale=scale,
                       origin=origin, region=size)


def test_a_coordinate_the_model_gives_lands_on_the_screen():
    picture = shot(scale=0.5)

    assert picture.to_screen(0, 0) == (0, 0)
    assert picture.to_screen(480, 270) == (960, 540)


def test_a_crop_remembers_where_it_came_from():
    """The model is shown a rectangle and never told where on the desk it was.
    Forgetting the origin puts every click in a zoomed view at the wrong place
    by exactly the offset of the crop."""
    picture = shot(scale=1.0, origin=(1200, 400), size=(500, 300))

    assert picture.to_screen(0, 0) == (1200, 400)
    assert picture.to_screen(250, 150) == (1450, 550)


def test_the_conversion_survives_a_round_trip():
    picture = shot(scale=0.539, origin=(0, 0), size=(3840, 1080))

    for x, y in ((0, 0), (1920, 540), (3839, 1079)):
        back = picture.to_screen(*picture.to_image(x, y))
        assert abs(back[0] - x) <= 2 and abs(back[1] - y) <= 2


def test_a_second_monitor_has_a_negative_origin():
    """A display to the left of the primary one starts at a negative x, and a
    conversion that assumes zero puts everything on the wrong screen."""
    picture = shot(scale=0.5, origin=(-1920, 0), size=(1920, 1080))

    assert picture.to_screen(0, 0) == (-1920, 0)
    assert picture.to_screen(960, 540) == (0, 1080)


# --------------------------------------------------------------------------- #
# key names
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name, expected", [
    ("Return", 0x0D), ("return", 0x0D), ("RETURN", 0x0D),
    ("Escape", 0x1B), ("Tab", 0x09), ("F5", 0x74),
    ("Page_Down", 0x22), ("pagedown", 0x22),
    ("Up", 0x26), ("a", 0x41), ("A", 0x41), ("7", 0x37),
])
def test_the_names_a_model_uses_are_understood(name, expected):
    """X11 names, because that is the vocabulary the computer-use tool speaks."""
    assert keys.code_for(name) == expected


def test_a_combination_separates_what_is_held_from_what_is_pressed():
    held, pressed = keys.parse("ctrl+shift+s")

    assert held == [0x11, 0x10]
    assert pressed == 0x53


def test_a_plus_can_itself_be_the_key():
    """`ctrl++` is zoom-in in half the applications there are, and splitting
    naively loses the key entirely."""
    held, pressed = keys.parse("ctrl++")

    assert held == [0x11]
    assert pressed == keys.code_for("plus")


def test_a_character_is_not_a_key():
    """Pressing the key where `@` sits on a US keyboard types something else on
    a French one. Text goes through the type action, which names characters."""
    with pytest.raises(keys.UnknownKey, match="type action"):
        keys.code_for("@")


def test_an_unknown_name_says_what_would_have_worked():
    with pytest.raises(keys.UnknownKey, match="Return"):
        keys.code_for("PressTheGreenOne")


def test_arrows_are_marked_extended():
    """Without the extended flag Windows reads them as the number-pad keys that
    share their scan codes, and an arrow types a digit when NumLock is on."""
    assert keys.is_extended(keys.code_for("Up"))
    assert keys.is_extended(keys.code_for("Delete"))
    assert not keys.is_extended(keys.code_for("a"))


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #

CORNERS = [(0, 0, 1920, 1080)]


def ask(guard: Guard, *, pointer=(500, 500), foreground="Untitled - Notepad",
        locked=False):
    guard.check(pointer=pointer, corners=CORNERS, foreground=foreground,
                locked=locked)


def test_nothing_happens_without_a_grant():
    guard = Guard()

    with pytest.raises(Refused, match="not been allowed"):
        ask(guard)


def test_a_grant_lets_it_through():
    guard = Guard()
    guard.allow(60)

    ask(guard)          # no exception


def test_a_grant_runs_out():
    """The clock is the point. A permission that lasts until the process exits
    is a permission nobody remembers giving."""
    guard = Guard()
    guard.allow(0.05)
    ask(guard)

    time.sleep(0.08)

    with pytest.raises(Refused, match="ran out"):
        ask(guard)


def test_a_scoped_grant_covers_only_what_it_named():
    guard = Guard()
    guard.allow(60, scope="Notepad")

    ask(guard, foreground="Untitled - Notepad")

    with pytest.raises(Refused, match="allowed"):
        ask(guard, foreground="Mail — Inbox")


def test_a_scope_survives_the_document_changing():
    """A window title changes with what is open in it. A grant for Word should
    not evaporate when the user opens a different file."""
    guard = Guard()
    guard.allow(60, scope="Word")

    ask(guard, foreground="report.docx - Word")
    ask(guard, foreground="notes.docx - Word")


@pytest.mark.parametrize("title", [
    "1Password", "Bitwarden - Vault", "KeePassXC", "Windows Security",
    "User Account Control", "Sign in to your account",
    "Ledger Live", "MetaMask", "Enter your password",
])
def test_some_windows_are_never_driven(title):
    """Whatever was granted. These are refused by what they are, not by policy
    somebody has to remember to set."""
    guard = Guard()
    guard.allow(600)

    with pytest.raises(Refused):
        ask(guard, foreground=title)


def test_it_will_not_drive_comodor_itself():
    """An agent clicking into the terminal it is driven from types into its own
    prompt."""
    guard = Guard()
    guard.allow(600)

    with pytest.raises(Refused, match="own window"):
        ask(guard, foreground="Comodor — main")


def test_nothing_happens_behind_a_lock_screen():
    guard = Guard()
    guard.allow(600)

    with pytest.raises(Refused, match="locked"):
        ask(guard, locked=True)


# -- the stop --------------------------------------------------------------- #


def test_the_mouse_in_a_corner_stops_everything():
    """The one gesture that works while the agent is holding the pointer, and
    the one a person actually makes when their screen starts moving on its own."""
    guard = Guard()
    guard.allow(600)
    guard.note_pointer((900, 500))

    with pytest.raises(Stopped, match="corner"):
        ask(guard, pointer=(2, 3))

    assert not guard.active, "the grant is gone, not just this action refused"


def test_the_agent_may_click_in_a_corner_itself():
    """Otherwise an agent clicking the Start button stops itself, and the stop
    becomes something users learn to work around."""
    guard = Guard()
    guard.allow(600)
    guard.note_pointer((4, 1076))       # it put the mouse there on purpose

    ask(guard, pointer=(4, 1076))


def test_a_nudge_is_not_a_stop():
    """People move a mouse a little without meaning anything by it."""
    guard = Guard()
    guard.allow(600)
    guard.note_pointer((900, 500))

    ask(guard, pointer=(915, 508))


@pytest.mark.parametrize("corner", [(2, 2), (1917, 3), (5, 1075), (1916, 1078)])
def test_every_corner_stops_it(corner):
    guard = Guard()
    guard.allow(600)
    guard.note_pointer((900, 500))

    with pytest.raises(Stopped):
        ask(guard, pointer=corner)


def test_revoking_says_why_afterwards():
    guard = Guard()
    guard.allow(600)
    guard.revoke("you asked it to stop")

    with pytest.raises(Refused, match="asked it to stop"):
        ask(guard)


def test_the_status_reads_like_something_a_person_would_say():
    guard = Guard()
    guard.allow(90, scope="Notepad")

    assert "1m" in guard.status()
    assert "Notepad" in guard.status()

    guard.revoke("you moved the mouse to a corner")
    assert guard.status() == "you moved the mouse to a corner"


def test_a_grant_describes_itself_without_a_scope():
    assert "anywhere on screen" in Grant(seconds=30).describe()
