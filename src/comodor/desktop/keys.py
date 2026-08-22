"""Turning the key names a model says into the codes Windows wants.

The model speaks X11 key names - `Return`, `ctrl+s`, `alt+Tab`, `Page_Down` -
because that is the vocabulary the computer-use tool was trained on, and it is
what `xdotool` uses. None of those names mean anything to Windows, which wants
virtual key codes.

Two rules that are easy to get wrong and unpleasant when they are:

**Ordinary characters do not belong here.** Typing `@` by pressing the key at
the position of `@` on a US keyboard produces something else entirely on a
French or German layout. Text goes through `unicode_char`, which names the
character rather than the key. This table is only for the keys that have no
character - Enter, Escape, F7, the arrows - and for deliberate combinations.

**Modifiers are released in reverse.** Holding ctrl, then shift, then pressing
`s`, and releasing them in the order they were pressed, leaves shift down for
whatever comes next. Unwinding backwards is the only order that ends where it
started.
"""

from __future__ import annotations

#: X11-ish name -> Windows virtual key code. Lower-cased on lookup, so the
#: model may write `Return`, `return` or `RETURN`.
NAMED: dict[str, int] = {
    # the ones a model reaches for constantly
    "return": 0x0D, "enter": 0x0D, "kp_enter": 0x0D,
    "tab": 0x09, "escape": 0x1B, "esc": 0x1B,
    "space": 0x20, "backspace": 0x08, "bksp": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23,
    "page_up": 0x21, "pageup": 0x21, "prior": 0x21,
    "page_down": 0x22, "pagedown": 0x22, "next": 0x22,

    # arrows
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,

    # modifiers, when held rather than combined
    "shift": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "menu": 0x12,
    "super": 0x5B, "win": 0x5B, "cmd": 0x5B, "meta": 0x5B,
    "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,

    # the rest of the top row
    "print": 0x2C, "printscreen": 0x2C, "pause": 0x13,

    # punctuation the model sometimes names rather than types
    "minus": 0xBD, "equal": 0xBB, "plus": 0xBB,
    "bracketleft": 0xDB, "bracketright": 0xDD,
    "semicolon": 0xBA, "apostrophe": 0xDE, "quoteright": 0xDE,
    "grave": 0xC0, "backslash": 0xDC,
    "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
}

#: F1 to F24.
NAMED.update({f"f{number}": 0x6F + number for number in range(1, 25)})

#: The number pad, which is a different key from the digit above it.
NAMED.update({f"kp_{digit}": 0x60 + digit for digit in range(10)})
NAMED.update({"kp_add": 0x6B, "kp_subtract": 0x6D, "kp_multiply": 0x6A,
              "kp_divide": 0x6F, "kp_decimal": 0x6E})

#: Keys that need the extended-key flag or Windows reads them as the number-pad
#: key sharing their scan code. Getting this wrong makes an arrow key type a
#: digit when NumLock happens to be on.
EXTENDED = frozenset({
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,   # page/home/end/arrows
    0x2D, 0x2E,                                        # insert, delete
    0x5B, 0x5C,                                        # the Windows keys
    0x6F, 0x0D,                                        # kp divide, kp enter
    0x2C, 0x90,                                        # print screen, numlock
})

#: Punctuation, as the character rather than as a name. A model writing
#: `ctrl++` for zoom-in means the key, not the word `plus`, and refusing it
#: because it is "a character, not a key" would be pedantry about a shortcut
#: half the applications on the machine use. The shifted and unshifted symbols
#: on one key share its code, which is what a combination wants.
SYMBOLS: dict[str, int] = {
    "-": 0xBD, "_": 0xBD,
    "=": 0xBB, "+": 0xBB,
    "[": 0xDB, "{": 0xDB,
    "]": 0xDD, "}": 0xDD,
    ";": 0xBA, ":": 0xBA,
    "'": 0xDE, '"': 0xDE,
    "`": 0xC0, "~": 0xC0,
    "\\": 0xDC, "|": 0xDC,
    ",": 0xBC, "<": 0xBC,
    ".": 0xBE, ">": 0xBE,
    "/": 0xBF, "?": 0xBF,
}

#: What may be held down as part of a combination.
MODIFIERS: dict[str, int] = {
    "shift": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "option": 0x12,
    "super": 0x5B, "win": 0x5B, "cmd": 0x5B, "meta": 0x5B,
}


class UnknownKey(ValueError):
    """A name nothing here recognises, reported with what was expected."""


def parse(combination: str) -> tuple[list[int], int]:
    """`ctrl+shift+s` -> the modifiers to hold, and the key to press.

    Returns them separately because they have to be pressed and released in a
    particular order, and a caller that got one flat list would have to know
    which of them were modifiers to do it.
    """
    text = (combination or "").strip()
    if not text:
        raise UnknownKey("no key was given")

    # `ctrl++` means ctrl with the plus key. Splitting naively loses it.
    parts = _split(text)
    *held, final = parts

    modifiers: list[int] = []
    for name in held:
        code = MODIFIERS.get(name.lower())
        if code is None:
            raise UnknownKey(
                f"{name!r} is not a modifier. Use shift, ctrl, alt or super.")
        if code not in modifiers:
            modifiers.append(code)

    return modifiers, code_for(final)


def code_for(name: str) -> int:
    """One key, by name or by the single character on it."""
    key = (name or "").strip()
    if not key:
        raise UnknownKey("no key was given")

    known = NAMED.get(key.lower())
    if known is not None:
        return known

    if len(key) == 1:
        # A letter or digit is at its ASCII code, which is the one place the
        # virtual key layout and the character agree on every keyboard.
        if key.isascii() and key.isalnum():
            return ord(key.upper())
        symbol = SYMBOLS.get(key)
        if symbol is not None:
            return symbol
        raise UnknownKey(
            f"{key!r} is a character, not a key - use the type action for text")

    raise UnknownKey(
        f"unknown key {name!r}. Names look like Return, Escape, Tab, F5, "
        f"Page_Down, Up, or a combination such as ctrl+s")


def _split(text: str) -> list[str]:
    """Split on `+`, without losing a `+` that is itself the key."""
    parts: list[str] = []
    current = ""
    for index, character in enumerate(text):
        if character == "+" and current and index != len(text) - 1:
            parts.append(current)
            current = ""
        else:
            current += character
    parts.append(current)
    return [part for part in parts if part] or [text]


def is_extended(code: int) -> bool:
    return code in EXTENDED
