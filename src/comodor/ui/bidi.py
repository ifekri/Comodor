"""Right-to-left text, in a left-to-right interface.

A terminal draws whatever it is sent and then runs the Unicode bidirectional
algorithm over each line. That algorithm is good, and it is the reason Persian,
Arabic and Hebrew mostly look right already — the characters arrive in logical
order and the terminal puts them on screen in visual order. Nothing here
reimplements any of that.

What it does is stop the algorithm reaching across boundaries it should not.

A line of this interface is usually one part ours and one part the user's:
``learned`` then a rule they wrote, ``edit`` then a path, a task glyph then a
title. Bidi has no idea which half is which. Given ``edit  گزارش.py``, it sees
one line with a right-to-left run at the end, and the *neutral* characters
between the two halves — spaces, the dot in a filename, a trailing colon — get
resolved against the wrong side. The path comes out with its extension in front
of it, or the time on the right of a tool row jumps to the left, and the user
sees a scrambled line and blames the program that printed it.

The fix is the one Unicode designed for exactly this: wrap each field in an
isolate. ``FSI`` says "work out this run's direction from its own first strong
character, and do not let it interact with anything outside"; ``PDI`` closes
it. The two are zero-width — they cost nothing on screen and nothing in the
width arithmetic the layout depends on.

**Isolate last.** A string that is truncated after being isolated loses its
``PDI``, and an unbalanced isolate leaks into the rest of the line, which is
worse than not isolating at all. Every caller here trims first.

**What this cannot do.** It cannot choose a font. The glyphs are the terminal
emulator's business, and a terminal that has no Arabic-script face will draw
boxes however carefully the text is ordered. `comodor doctor` says which font
to set and where.
"""

from __future__ import annotations

import unicodedata

#: Unicode's isolate marks. Zero width, and understood by every terminal that
#: implements bidi at all.
FSI = "⁨"          # first strong isolate: infer direction from content
PDI = "⁩"          # pop directional isolate

#: The bidi classes that make a character "strongly" one direction or the
#: other. Everything else — digits, spaces, punctuation — takes its direction
#: from whatever is around it, which is the whole problem.
_RTL = frozenset({"R", "AL"})
_LTR = frozenset({"L"})


def direction(text: str) -> str:
    """``rtl``, ``ltr``, or ``neutral`` — from the first strong character.

    First strong, not majority: that is the rule the bidi algorithm itself
    uses to decide a paragraph's direction, so anything else here would
    disagree with what the terminal is about to do.
    """
    for character in text:
        category = unicodedata.bidirectional(character)
        if category in _RTL:
            return "rtl"
        if category in _LTR:
            return "ltr"
    return "neutral"


def is_rtl(text: str) -> bool:
    return direction(text) == "rtl"


def has_rtl(text: str) -> bool:
    """Is there any right-to-left character in here at all?

    Cheaper than it looks, and the answer decides whether a line needs
    isolating: a line of pure ASCII cannot be reordered, so wrapping it costs
    two codepoints for nothing.
    """
    return any(unicodedata.bidirectional(character) in _RTL for character in text)


def isolate(text: str) -> str:
    """Fence a field off from the rest of its line.

    Only when there is something to fence. Adding the marks to every string in
    the interface would double the codepoints in a transcript to protect the
    one line in a thousand that needs it, and would make every snapshot test
    unreadable.
    """
    if not text or not has_rtl(text):
        return text
    return f"{FSI}{text}{PDI}"


def strip(text: str) -> str:
    """Remove the marks again — for widths, comparisons, and tests."""
    return text.replace(FSI, "").replace(PDI, "")
