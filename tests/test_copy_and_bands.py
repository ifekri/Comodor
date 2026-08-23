"""Getting text out, and telling the two speakers apart.

Two complaints, both about the terminal being a wall: text could not be copied
out of it, and a long conversation in one colour gave the eye nothing to work
with.

The copy tests are mostly about encoding, because that is where a copy command
fails in the way that matters — silently, producing something that looks like a
copy and is not.
"""

from __future__ import annotations

import io
import re
import sys

import pytest
from rich.console import Console

from comodor.ui import clipboard
from comodor.ui import theme as theme_module
from comodor.ui.widgets.chat import Entry, render_entry

PERSIAN = "سلام دنیا"
MIXED = f"Comodor — {PERSIAN} — 42"


def painted(entry: Entry, name: str = "ember", width: int = 60) -> str:
    theme = theme_module.load(name)
    buffer = io.StringIO()
    Console(file=buffer, width=width, force_terminal=True,
            color_system="truecolor", legacy_windows=False,
            theme=theme.rich_theme()).print(render_entry(entry, theme, width))
    return buffer.getvalue()


def rows(text: str) -> list[str]:
    return [re.sub("\x1b" + r"\[[0-9;:?]*[a-zA-Z]", "", row)
            for row in text.splitlines()]


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


# --------------------------------------------------------------------------- #
# the bands
# --------------------------------------------------------------------------- #


def test_the_two_speakers_get_different_backgrounds():
    """A long conversation in one colour is a wall — the eye has to read the
    caret to work out who is speaking, on every turn."""
    user = painted(Entry("user", "why?"))
    assistant = painted(Entry("assistant", "because."))

    theme = theme_module.load("ember")
    assert _rgb(theme.palette.user_bg) in user
    assert _rgb(theme.palette.assistant_bg) in assistant
    assert _rgb(theme.palette.user_bg) not in assistant


def _rgb(colour: str) -> str:
    value = colour.lstrip("#")
    return (f"48;2;{int(value[0:2], 16)};{int(value[2:4], 16)};"
            f"{int(value[4:6], 16)}")


def test_the_band_reaches_both_margins():
    """A background on the text alone covers the characters and stops, so a
    paragraph of uneven lines comes out looking torn."""
    lines = rows(painted(Entry("user", "short"), width=60))
    body = [line for line in lines if "short" in line][0]

    assert len(body) >= 58, f"the band stopped early: {len(body)} of 60"


def test_a_blank_line_inside_a_paragraph_is_painted_too():
    painted_out = painted(Entry("assistant", "one\n\ntwo"), width=60)
    coloured = [row for row in painted_out.splitlines() if "48;2;" in row]

    assert len(coloured) >= 3, "the gap between the paragraphs was left bare"


def test_a_colourless_theme_gets_no_bands():
    """A theme whose whole premise is no colour does not want two."""
    out = painted(Entry("user", "why?"), name="mono")

    assert "48;2;" not in out and "48;5;" not in out
    assert "why?" in rows(out)[0]


def test_the_bands_cost_no_vertical_space():
    """A row above and below looked better and cost two rows of terminal for
    every turn — on a twenty-row window that is half a four-turn exchange."""
    plain = rows(painted(Entry("user", "one line")))

    assert len([row for row in plain if row.strip()]) == 1


def test_right_to_left_text_stays_at_the_right_margin():
    lines = rows(painted(Entry("user", PERSIAN)))
    body = [line for line in lines if PERSIAN in line][0]

    assert len(body) - len(body.rstrip()) <= 2, "it was pushed off the margin"
    assert body.startswith("  "), "it was left-aligned"


@pytest.mark.parametrize("name", ["ember", "midnight", "matrix", "paper", "ink"])
def test_every_colour_theme_has_a_pair(name):
    palette = theme_module.load(name).palette

    assert palette.user_bg != "default"
    assert palette.assistant_bg != "default"
    assert palette.user_bg != palette.assistant_bg
