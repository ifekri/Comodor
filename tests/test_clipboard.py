"""Getting text out of a terminal.

The copy tests are mostly about encoding, because that is where a copy command
fails in the way that matters — silently, producing something that looks like a
copy and is not.
"""

from __future__ import annotations

import sys

import pytest

from comodor.terminal import clipboard
from comodor.terminal import theme as theme_module

PERSIAN = "سلام دنیا"
MIXED = f"Comodor — {PERSIAN} — 42"


# --------------------------------------------------------------------------- #
# the clipboard
# --------------------------------------------------------------------------- #


def test_windows_gets_utf16_because_clip_exe_reads_utf8_as_the_code_page():
    """`clip.exe` handed UTF-8 does not fail — it copies mojibake. Measured:
    `سلام` came back as `╪│┘ä╪º┘à`. A silent corruption is the worst kind of
    bug to have in a copy command."""
    encoded = clipboard._encode(MIXED, ("clip.exe",))

    assert encoded.decode("utf-16-le") == MIXED


def test_no_byte_order_mark_reaches_the_clipboard():
    """With one, clip.exe decodes correctly and keeps the mark as content, so
    every paste begins with an invisible U+FEFF — which a code editor will
    happily write to the top of a file. Measured both ways: it detects the
    encoding without needing the mark."""
    encoded = clipboard._encode(MIXED, ("clip.exe",))

    assert not encoded.startswith(b"\xff\xfe")
    assert encoded.decode("utf-16-le")[0] != "﻿"


@pytest.mark.parametrize("tool", [("pbcopy",), ("wl-copy",), ("xclip",)])
def test_everything_else_gets_utf8(tool):
    assert clipboard._encode(MIXED, tool).decode("utf-8") == MIXED


def test_copying_nothing_is_not_an_error():
    assert clipboard.copy("") == "nothing to copy"


def test_it_says_what_would_work_when_nothing_does(monkeypatch):
    """A copy command that fails silently is worse than one that is absent."""
    monkeypatch.setattr(clipboard, "_tool_for_platform", lambda: None)
    monkeypatch.setattr(clipboard, "_osc52", lambda text: False)

    with pytest.raises(clipboard.Unavailable, match="/mouse"):
        clipboard.copy("something")


def test_an_unknown_terminal_is_assumed_not_to_take_osc52(monkeypatch):
    """The sequence has no reply, so a terminal that ignores it is
    indistinguishable from one that acted. Reporting a copy that did not happen
    is worse than saying it could not be done."""
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    for name in ("WT_SESSION", "TERM_PROGRAM", "TERM"):
        monkeypatch.delenv(name, raising=False)

    assert clipboard._terminal_may_accept_osc52() is False


def test_a_known_terminal_is(monkeypatch):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")

    assert clipboard._terminal_may_accept_osc52() is True


def test_osc52_is_wrapped_inside_tmux(monkeypatch, capsys):
    """Unwrapped, tmux eats the sequence rather than passing it to the terminal
    that could act on it."""
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,123,0")

    clipboard._osc52("hello")

    assert "\x1bPtmux;" in capsys.readouterr().out


@pytest.mark.parametrize("name", ["ember", "midnight", "matrix", "paper", "ink"])
def test_every_colour_theme_has_a_pair(name):
    palette = theme_module.load(name).palette

    assert palette.user_bg != "default"
    assert palette.assistant_bg != "default"
    assert palette.user_bg != palette.assistant_bg
