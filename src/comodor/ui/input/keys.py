"""Decoding a terminal input stream.

Rich renders; it does not read input. This module is the other half: a state
machine that turns the raw character stream into key, mouse, paste and focus
events.

It is written as a pure decoder — text in, events out, no I/O — so the whole
protocol layer is testable without a terminal, which matters because the
sequences involved differ between terminals and are miserable to debug live.

The escape-sequence handling deals with the fact that a lone ``Esc`` and the
start of ``Esc [ A`` (an arrow key) look identical until more bytes arrive. The
decoder holds an incomplete sequence in its buffer; the reader that feeds it
resolves the ambiguity with a short timeout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Union

# --------------------------------------------------------------------------- #
# events
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class KeyEvent:
    key: str                     # "char", "up", "enter", "f2", …
    char: str = ""               # the character, when key == "char"
    ctrl: bool = False
    alt: bool = False
    shift: bool = False

    def matches(self, spec: str) -> bool:
        """``event.matches("ctrl+c")`` / ``event.matches("f2")``."""
        parts = [part.strip().lower() for part in spec.split("+")]
        want_ctrl = "ctrl" in parts
        want_alt = "alt" in parts
        want_shift = "shift" in parts
        name = parts[-1]
        if self.ctrl != want_ctrl or self.alt != want_alt:
            return False
        if want_shift and not self.shift:
            return False
        return self.key == name or (self.key == "char" and self.char.lower() == name)

    def __str__(self) -> str:
        prefix = ("ctrl+" if self.ctrl else "") + ("alt+" if self.alt else "")
        return prefix + (self.char if self.key == "char" else self.key)


@dataclass(slots=True)
class MouseEvent:
    x: int                       # 0-based column
    y: int                       # 0-based row
    action: str                  # press | release | move | scroll_up | scroll_down
    button: int = 0


@dataclass(slots=True)
class PasteEvent:
    text: str


@dataclass(slots=True)
class ResizeEvent:
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class FocusEvent:
    focused: bool = True


InputEvent = Union[KeyEvent, MouseEvent, PasteEvent, ResizeEvent, FocusEvent]

# --------------------------------------------------------------------------- #
# tables
# --------------------------------------------------------------------------- #

# Final sequences, matched exactly.
_SEQUENCES: dict[str, KeyEvent] = {
    "[A": KeyEvent("up"), "[B": KeyEvent("down"),
    "[C": KeyEvent("right"), "[D": KeyEvent("left"),
    "[H": KeyEvent("home"), "[F": KeyEvent("end"),
    "OA": KeyEvent("up"), "OB": KeyEvent("down"),
    "OC": KeyEvent("right"), "OD": KeyEvent("left"),
    "OH": KeyEvent("home"), "OF": KeyEvent("end"),
    "[Z": KeyEvent("tab", shift=True),
    "[1~": KeyEvent("home"), "[2~": KeyEvent("insert"), "[3~": KeyEvent("delete"),
    "[4~": KeyEvent("end"), "[5~": KeyEvent("pgup"), "[6~": KeyEvent("pgdn"),
    "[7~": KeyEvent("home"), "[8~": KeyEvent("end"),
    "OP": KeyEvent("f1"), "OQ": KeyEvent("f2"), "OR": KeyEvent("f3"), "OS": KeyEvent("f4"),
    "[11~": KeyEvent("f1"), "[12~": KeyEvent("f2"), "[13~": KeyEvent("f3"),
    "[14~": KeyEvent("f4"), "[15~": KeyEvent("f5"), "[17~": KeyEvent("f6"),
    "[18~": KeyEvent("f7"), "[19~": KeyEvent("f8"), "[20~": KeyEvent("f9"),
    "[21~": KeyEvent("f10"), "[23~": KeyEvent("f11"), "[24~": KeyEvent("f12"),
    "[I": FocusEvent(True), "[O": FocusEvent(False),   # focus in / out
}

# Modified keys: CSI 1 ; <mod> <final>, e.g. Ctrl+Right is "[1;5C".
_MODIFIED = re.compile(r"^\[(\d*);(\d+)([A-Z~])$")
_MODIFIER_BITS = {1: "shift", 2: "alt", 4: "ctrl"}
_FINALS = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end"}
_TILDE_CODES = {"2": "insert", "3": "delete", "5": "pgup", "6": "pgdn",
                "15": "f5", "17": "f6", "18": "f7", "19": "f8", "20": "f9",
                "21": "f10", "23": "f11", "24": "f12"}

# SGR mouse: CSI < button ; col ; row (M press | m release)
_SGR_MOUSE = re.compile(r"^\[<(\d+);(\d+);(\d+)([Mm])$")

PASTE_START = "[200~"
PASTE_END = "[201~"

# Control characters that are not part of an escape sequence.
_CONTROL: dict[str, KeyEvent] = {
    "\r": KeyEvent("enter"),
    "\n": KeyEvent("enter"),
    "\t": KeyEvent("tab"),
    "\x7f": KeyEvent("backspace"),
    "\x08": KeyEvent("backspace"),
    "\x00": KeyEvent("char", char=" ", ctrl=True),
}


def _control_letter(char: str) -> KeyEvent:
    """``\\x03`` -> Ctrl+C."""
    return KeyEvent("char", char=chr(ord(char) + 96), ctrl=True)


# --------------------------------------------------------------------------- #
# the decoder
# --------------------------------------------------------------------------- #


@dataclass
class KeyDecoder:
    """Feed it characters; take events out."""

    buffer: str = ""
    pasting: bool = False
    paste_buffer: list[str] = field(default_factory=list)

    def feed(self, data: str) -> list[InputEvent]:
        self.buffer += data
        events: list[InputEvent] = []
        while self.buffer:
            event, consumed = self._step()
            if consumed == 0:
                break                      # incomplete sequence; wait for more
            self.buffer = self.buffer[consumed:]
            if event is not None:
                events.append(event)
        return events

    def flush(self) -> list[InputEvent]:
        """Resolve a pending ambiguous sequence — used when input goes quiet.

        A bare ``Esc`` sits in the buffer looking like the start of an arrow
        key. When no more bytes arrive, it was a real Escape.
        """
        if not self.buffer:
            return []
        if self.buffer == "\x1b":
            self.buffer = ""
            return [KeyEvent("escape")]
        events = self.feed("")
        if not events and self.buffer:
            # Unrecognised leftovers would otherwise wedge the decoder.
            self.buffer = ""
        return events

    # -- one token -------------------------------------------------------- #

    def _step(self) -> tuple[InputEvent | None, int]:
        char = self.buffer[0]

        if self.pasting:
            return self._step_paste()

        if char != "\x1b":
            return self._plain(char), 1

        if len(self.buffer) == 1:
            return None, 0                 # could still become a sequence

        second = self.buffer[1]
        if second not in "[O":
            # Esc followed by a normal key is Alt+key.
            event = self._plain(second)
            if isinstance(event, KeyEvent):
                event.alt = True
            return event, 2

        return self._escape_sequence()

    def _plain(self, char: str) -> InputEvent:
        if char in _CONTROL:
            # A copy, never the table entry itself: the caller may set `alt` on
            # what it gets back, and mutating the shared entry would make every
            # later Enter look like Alt+Enter.
            return _copy(_CONTROL[char])
        if char == "\x1b":
            return KeyEvent("escape")
        if len(char) == 1 and ord(char) < 32:
            return _control_letter(char)
        return KeyEvent("char", char=char)

    def _escape_sequence(self) -> tuple[InputEvent | None, int]:
        # Scan for the terminating byte of a CSI/SS3 sequence.
        for index in range(1, min(len(self.buffer), 32)):
            candidate = self.buffer[1:index + 1]
            if not _is_terminated(candidate):
                continue

            if candidate == PASTE_START:
                self.pasting = True
                self.paste_buffer = []
                return None, index + 1
            if candidate in _SEQUENCES:
                event = _SEQUENCES[candidate]
                # Table entries are shared; hand out copies so a caller setting
                # `alt` cannot corrupt the table for every later keypress.
                return _copy(event), index + 1

            mouse = _SGR_MOUSE.match(candidate)
            if mouse:
                return _decode_mouse(mouse), index + 1

            modified = _MODIFIED.match(candidate)
            if modified:
                return _decode_modified(modified), index + 1

            return None, index + 1          # known-shaped but unhandled
        if len(self.buffer) > 32:
            return None, 1                  # garbage; drop one byte and resync
        return None, 0

    def _step_paste(self) -> tuple[InputEvent | None, int]:
        end = self.buffer.find("\x1b" + PASTE_END)
        if end == -1:
            # Keep everything that cannot be the start of the end marker.
            safe = max(0, len(self.buffer) - len(PASTE_END) - 1)
            if safe <= 0:
                return None, 0
            self.paste_buffer.append(self.buffer[:safe])
            return None, safe
        self.paste_buffer.append(self.buffer[:end])
        self.pasting = False
        text = "".join(self.paste_buffer)
        self.paste_buffer = []
        return PasteEvent(text), end + len(PASTE_END) + 1


def _copy(event: InputEvent) -> InputEvent:
    if isinstance(event, KeyEvent):
        return KeyEvent(event.key, event.char, event.ctrl, event.alt, event.shift)
    if isinstance(event, FocusEvent):
        return FocusEvent(event.focused)
    return event


def _is_terminated(candidate: str) -> bool:
    if not candidate:
        return False
    last = candidate[-1]
    if candidate[0] == "O":
        return len(candidate) >= 2
    if candidate[0] == "[":
        return last.isalpha() or last == "~"
    return True


def _decode_mouse(match: re.Match[str]) -> MouseEvent:
    code = int(match.group(1))
    column = int(match.group(2)) - 1        # SGR is 1-based
    row = int(match.group(3)) - 1
    pressed = match.group(4) == "M"

    if code & 64:                           # wheel
        return MouseEvent(column, row, "scroll_up" if (code & 3) == 0 else "scroll_down")
    if code & 32:                           # drag / motion
        return MouseEvent(column, row, "move", code & 3)
    return MouseEvent(column, row, "press" if pressed else "release", code & 3)


def _decode_modified(match: re.Match[str]) -> KeyEvent | None:
    code, modifier, final = match.group(1), int(match.group(2)), match.group(3)
    name = _FINALS.get(final) if final != "~" else _TILDE_CODES.get(code or "")
    if name is None:
        return None
    bits = modifier - 1
    return KeyEvent(
        name,
        shift=bool(bits & 1),
        alt=bool(bits & 2),
        ctrl=bool(bits & 4),
    )


# --------------------------------------------------------------------------- #
# Windows console key codes
# --------------------------------------------------------------------------- #

# When VT input cannot be enabled, msvcrt hands back a two-byte code instead.
WINDOWS_SPECIAL: dict[str, KeyEvent] = {
    "H": KeyEvent("up"), "P": KeyEvent("down"),
    "K": KeyEvent("left"), "M": KeyEvent("right"),
    "G": KeyEvent("home"), "O": KeyEvent("end"),
    "I": KeyEvent("pgup"), "Q": KeyEvent("pgdn"),
    "R": KeyEvent("insert"), "S": KeyEvent("delete"),
    ";": KeyEvent("f1"), "<": KeyEvent("f2"), "=": KeyEvent("f3"), ">": KeyEvent("f4"),
    "?": KeyEvent("f5"), "@": KeyEvent("f6"), "A": KeyEvent("f7"), "B": KeyEvent("f8"),
    "C": KeyEvent("f9"), "D": KeyEvent("f10"), "\x85": KeyEvent("f11"),
    "\x86": KeyEvent("f12"),
    # Ctrl+arrows
    "\x8d": KeyEvent("up", ctrl=True), "\x91": KeyEvent("down", ctrl=True),
    "s": KeyEvent("left", ctrl=True), "t": KeyEvent("right", ctrl=True),
}
