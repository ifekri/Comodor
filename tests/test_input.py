"""Terminal input decoding and the prompt editor.

The decoder is pure — text in, events out — so the escape sequences real
terminals emit can be replayed exactly, without a terminal.
"""

from __future__ import annotations

import os

import pytest

from comodor.config import Config, ProviderConfig
from comodor.ui.input.keys import (
    FocusEvent,
    KeyDecoder,
    KeyEvent,
    MouseEvent,
    PasteEvent,
)
from comodor.ui.widgets.prompt import Editor, completions


def decode(sequence: str) -> list:
    return KeyDecoder().feed(sequence)


def keys(sequence: str) -> list[str]:
    return [str(event) for event in decode(sequence) if isinstance(event, KeyEvent)]


# --------------------------------------------------------------------------- #
# key decoding
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sequence,expected", [
    ("abc", ["a", "b", "c"]),
    ("\x1b[A\x1b[B\x1b[C\x1b[D", ["up", "down", "right", "left"]),
    ("\x1bOA\x1bOB", ["up", "down"]),                   # application cursor mode
    ("\r", ["enter"]),
    ("\t", ["tab"]),
    ("\x7f", ["backspace"]),
    ("\x03", ["ctrl+c"]),
    ("\x1b[3~", ["delete"]),
    ("\x1b[5~\x1b[6~", ["pgup", "pgdn"]),
    ("\x1b[H\x1b[F", ["home", "end"]),
    ("\x1bOQ", ["f2"]),
    ("\x1b[21~", ["f10"]),
    ("\x1bb", ["alt+b"]),
])
def test_sequences_decode_to_the_right_keys(sequence, expected):
    assert keys(sequence) == expected


def test_modifier_bits_are_decoded():
    event = decode("\x1b[1;5D")[0]
    assert event.key == "left" and event.ctrl and not event.alt

    event = decode("\x1b[1;2C")[0]
    assert event.key == "right" and event.shift


def test_an_incomplete_sequence_waits_for_the_rest():
    decoder = KeyDecoder()
    assert decoder.feed("\x1b[") == []
    assert [str(event) for event in decoder.feed("A")] == ["up"]


def test_a_lone_escape_resolves_when_input_goes_quiet():
    decoder = KeyDecoder()
    assert decoder.feed("\x1b") == []
    assert [str(event) for event in decoder.flush()] == ["escape"]


def test_utf8_text_arrives_intact():
    assert keys("héllo 日本") == ["h", "é", "l", "l", "o", " ", "日", "本"]


def test_modifiers_do_not_leak_into_later_keypresses():
    """Alt+Enter must not leave every later Enter looking alt-pressed.

    Enter is the send key and Alt+Enter inserts a newline, so a leaked flag
    here would stop the agent ever receiving a message.
    """
    decoder = KeyDecoder()
    alt_enter = decoder.feed("\x1b\r")[0]
    plain_enter = decoder.feed("\r")[0]

    assert alt_enter.key == "enter" and alt_enter.alt
    assert plain_enter.key == "enter" and not plain_enter.alt


def test_arrow_table_entries_are_not_mutated_either():
    decoder = KeyDecoder()
    decoder.feed("\x1b[1;3A")               # alt+up
    assert decoder.feed("\x1b[A")[0].alt is False


# --------------------------------------------------------------------------- #
# mouse and paste
# --------------------------------------------------------------------------- #


def test_sgr_mouse_press_is_decoded_to_zero_based_coordinates():
    event = decode("\x1b[<0;12;34M")[0]
    assert isinstance(event, MouseEvent)
    assert (event.x, event.y, event.action) == (11, 33, "press")


def test_scroll_wheel_events():
    assert decode("\x1b[<64;5;5M")[0].action == "scroll_up"
    assert decode("\x1b[<65;5;5M")[0].action == "scroll_down"


def test_bracketed_paste_arrives_as_one_event():
    events = decode("\x1b[200~line one\nline two\x1b[201~")
    assert len(events) == 1
    assert isinstance(events[0], PasteEvent)
    assert events[0].text == "line one\nline two"


def test_paste_split_across_reads_is_reassembled():
    decoder = KeyDecoder()
    decoder.feed("\x1b[200~hello ")
    decoder.feed("brave ")
    events = decoder.feed("world\x1b[201~")
    assert [event.text for event in events if isinstance(event, PasteEvent)] == \
        ["hello brave world"]


def test_focus_events_are_recognised():
    assert isinstance(decode("\x1b[I")[0], FocusEvent)
    assert decode("\x1b[O")[0].focused is False


def test_garbage_does_not_wedge_the_decoder():
    decoder = KeyDecoder()
    decoder.feed("\x1b[" + "9" * 40)
    assert [str(event) for event in decoder.feed("\x1b[A")
            if isinstance(event, KeyEvent)] == ["up"]


def test_key_matching():
    assert KeyEvent("char", char="c", ctrl=True).matches("ctrl+c")
    assert not KeyEvent("char", char="c").matches("ctrl+c")
    assert KeyEvent("f2").matches("f2")
    assert KeyEvent("tab", shift=True).matches("shift+tab")


# --------------------------------------------------------------------------- #
# the editor
# --------------------------------------------------------------------------- #


def test_typing_and_deleting():
    editor = Editor()
    editor.insert("hello")
    editor.backspace()
    assert editor.text == "hell"
    editor.insert(" there")
    editor.home()
    editor.delete()
    assert editor.text == "ell there"


def test_word_motion_and_deletion():
    editor = Editor(text="the quick brown fox")
    editor.cursor = len(editor.text)
    editor.word_left()
    assert editor.cursor == 16
    editor.delete_word()                      # removes the word before the cursor
    assert editor.text == "the quick fox"


def test_multiline_navigation_preserves_the_column():
    editor = Editor(text="first line\nshort\nthird line here")
    editor.cursor = len("first line\nshort\nthird")
    editor.up()
    assert editor.cursor == len("first line\nshort")     # clamped to a short line
    editor.up()
    assert editor.text[:editor.cursor].count("\n") == 0


def test_history_is_browsable():
    editor = Editor()
    editor.remember("first command")
    editor.remember("second command")
    editor.insert("draft")

    editor.previous()
    assert editor.text == "second command"
    editor.previous()
    assert editor.text == "first command"
    editor.next()
    editor.next()
    assert editor.text == "draft", "leaving history restores what was being typed"


def test_wrapping_measures_display_width_not_characters():
    editor = Editor(text="日本語のテキスト")       # two cells per character
    rows = editor.wrapped(width=8)
    assert len(rows) > 1
    for text, _ in rows:
        from rich.cells import cell_len

        assert cell_len(text) <= 8


def test_cursor_position_accounts_for_wide_characters():
    editor = Editor(text="日本abc")
    editor.cursor = 3                                  # after 日本a
    _, column = editor.cursor_position(width=40)
    assert column == 5                                  # 2 + 2 + 1 cells


def test_slash_completions_match_a_prefix():
    commands = [("/help", "h"), ("/model", "m"), ("/memory", "mm")]
    assert [name for name, _ in completions("/me", commands)] == ["/memory"]
    assert [name for name, _ in completions("/m", commands)] == ["/model", "/memory"]
    assert completions("/model gpt", commands) == []    # past the command word
    assert completions("not a command", commands) == []


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #


def test_secrets_never_appear_in_the_public_config():
    config = Config()
    config.providers["x"] = ProviderConfig(name="x", api_key="sk-secret-value",
                                           base_url="https://example.invalid")
    public = config.to_public_dict()

    assert public["providers"]["x"]["api_key"] == "***"
    assert "sk-secret-value" not in str(public)
    assert "paths" not in public


def test_a_local_provider_is_ready_without_a_key():
    local = ProviderConfig(name="ollama", base_url="http://localhost:11434/v1")
    hosted = ProviderConfig(name="openai", base_url="https://api.openai.com/v1")

    assert local.ready
    assert not hosted.ready
    hosted.api_key = "sk-x"
    assert hosted.ready


# --------------------------------------------------------------------------- #
# the terminal itself
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(os.name == "nt", reason="POSIX line discipline")
def test_reading_keys_raw_leaves_the_output_translation_alone():
    """Raw input must not switch off output post-processing.

    The line discipline belongs to the terminal device, not to one descriptor,
    so clearing OPOST in order to read keys also stops a newline being turned
    into carriage-return-newline on the way *out*.

    That is not cosmetic here. Every frame this interface draws is exactly as
    wide as the terminal, which leaves the cursor in the deferred-wrap state at
    the end of each row; terminals disagree about what a bare line feed does
    from there, and several of them perform the pending wrap as well as the
    feed. The picture comes out twice as tall as the screen with a blank row
    between every drawn row, and the top half of it — the panel borders and
    titles — scrolls away before anyone sees it.

    It never showed up on Windows, which does not use this code path at all.
    """
    import pty
    import termios

    from comodor.ui.input.reader import TerminalInput

    primary, secondary = pty.openpty()
    try:
        stream = os.fdopen(secondary, "r")
        before = termios.tcgetattr(secondary)

        with TerminalInput(stream=stream, mouse=False, paste=False):
            during = termios.tcgetattr(secondary)
            assert during[1] & termios.OPOST, "OPOST was cleared"
            assert during[1] & termios.ONLCR, "ONLCR was cleared"
            # Still raw enough to read a keystroke the moment it arrives.
            assert not during[3] & termios.ICANON
            assert not during[3] & termios.ECHO

        assert termios.tcgetattr(secondary) == before
    finally:
        os.close(primary)
