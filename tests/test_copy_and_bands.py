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


# --------------------------------------------------------------------------- #
# the names
# --------------------------------------------------------------------------- #


def test_both_speakers_are_named():
    assert "You" in painted(Entry("user", "why?"))
    assert "Comodor" in painted(Entry("assistant", "because."))


def test_the_names_work_without_any_colour():
    """The band is the fast answer and the name is the reliable one. A theme
    with no colour has no bands at all, so without the names a `--no-color`
    transcript is a wall with no speaker in it anywhere."""
    user = painted(Entry("user", "why?"), name="mono")
    assistant = painted(Entry("assistant", "because."), name="mono")

    assert "48;2;" not in user and "48;2;" not in assistant
    assert "You" in user and "Comodor" not in user
    assert "Comodor" in assistant and "You" not in assistant


def test_naming_the_question_costs_it_no_row():
    """A one-line question with a label over it is two rows to say one thing,
    and a conversation is mostly one-line questions."""
    plain = [row for row in rows(painted(Entry("user", "why?"))) if row.strip()]

    assert len(plain) == 1
    assert "You" in plain[0] and "why?" in plain[0]


def test_the_answer_is_named_above_its_own_prose():
    """An answer opens with a heading or a list as often as with a sentence.
    Prefixing its first line would put the label inside the Markdown and lose
    it the moment it does."""
    drawn = [row for row in rows(painted(Entry("assistant", "# Title\n\nbody")))
             if row.strip()]

    assert drawn[0].strip() == "Comodor"


def test_the_surfaces_are_asked_for_by_role_not_by_colour():
    """`surface_user` and `surface_assistant` are what a widget names. Which
    field of which palette answers is the theme's business, and swapping a
    palette must not need an edit here."""
    theme = theme_module.load("cyan")

    assert theme.palette_colour("surface_user") == theme.palette.user_bg
    assert theme.palette_colour("surface_assistant") == theme.palette.assistant_bg
    assert _rgb(theme.palette_colour("surface_user")) in painted(
        Entry("user", "why?"), name="cyan")


def test_one_surface_per_message_not_per_paragraph():
    """Three paragraphs in one answer is one block with one background, and
    the blank rows between them are painted too — otherwise a long answer
    comes out looking like three separate ones."""
    out = painted(Entry("assistant", "one\n\ntwo\n\nthree"), name="cyan", width=60)
    theme = theme_module.load("cyan")
    coloured = [row for row in out.splitlines()
                if _rgb(theme.palette.assistant_bg) in row]

    assert len(coloured) >= 6, "the gaps inside the answer were left bare"
    assert _rgb(theme.palette.user_bg) not in out


# --------------------------------------------------------------------------- #
# what a tool call did
# --------------------------------------------------------------------------- #


def a_tool(ok=True, running=False, name="ember"):
    return painted(Entry("tool", "edit_file", meta={
        "summary": "edit src/app.py", "ok": ok, "running": running,
        "elapsed": 0.0 if running else 0.2,
    }), name=name)


def test_a_tool_call_says_what_it_did_without_colour():
    """Colour said this already, and said it to nobody running `--no-color`,
    nobody colour-blind on the red/green axis, and nobody reading a copied
    transcript."""
    assert "✓" in a_tool(ok=True)
    assert "×" in a_tool(ok=False)
    assert "●" in a_tool(running=True)


def test_the_marks_have_an_ascii_form():
    """`--ascii` is for terminals that render these as boxes. A state nobody
    can read is not a state."""
    theme = theme_module.load("ember", ascii_borders=True)
    glyphs = theme.glyphs

    assert (glyphs.ok, glyphs.running, glyphs.queued, glyphs.failed) == (
        "[OK]", "[..]", "[--]", "[!!]")
    for glyph in (glyphs.ok, glyphs.running, glyphs.queued, glyphs.failed):
        assert glyph.isascii()


def test_the_mark_is_not_a_font_that_has_to_be_installed():
    """Nerd-Font glyphs sit in a private use area. A terminal without the font
    draws a box, which is worse than the plain character it replaced."""
    theme = theme_module.load("ember")
    for glyph in (theme.glyphs.ok, theme.glyphs.running,
                  theme.glyphs.queued, theme.glyphs.failed):
        assert len(glyph) == 1
        assert not (0xE000 <= ord(glyph) <= 0xF8FF), f"{glyph!r} needs a font"


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
