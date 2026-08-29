"""Finding the text an edit meant, when it is not quite the text it gave.

`edit_file` takes an exact string. That is the right design — a line number
drifts the moment anything above it changes, and an anchored string either
matches or it does not — but "does not" was the end of the road, and it is the
commonest wasted turn in any coding agent. The model reproduced the block from
memory and got a trailing space wrong, or read a file with CRLF endings and
wrote back LF, and the whole turn is spent discovering that.

So there is a ladder. Exact first, always. Then three transformations, each
tried only when the one above it found nothing:

*Line endings.* CRLF against LF. Invisible, and the default on Windows, which
makes it the single likeliest cause of a mismatch nobody can see.

*Trailing whitespace.* A space at the end of a line survives a copy and does
not survive being read out of a model's context.

*Common indentation.* The block was reproduced flush left, or one level in,
because it was quoted somewhere it had been dedented.

Two rules that are not negotiable.

**Every rung reports itself.** A match found after normalising is announced as
such — `matched after normalising line endings` — because an edit that was
not quite what was asked for and says nothing is a worse failure than one that
does not apply at all.

**Ambiguity fails the rung, it does not get resolved.** If a transformation
turns one intended match into three candidates, that rung finds nothing and the
ladder moves on. Guessing which of three places was meant is how an agent
silently edits the wrong function.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

#: How many near-misses to show when nothing matched at all.
SUGGESTIONS = 3

#: Below this, two blocks are not "nearly the same thing", they are different
#: things that share a keyword. Showing them as candidates wastes a turn.
CLOSE_ENOUGH = 0.6


@dataclass(frozen=True)
class Match:
    """Where the text was found, and what had to be done to find it."""

    start: int
    end: int
    #: Empty when the match was exact. Otherwise, what to tell the user.
    how: str

    @property
    def exact(self) -> bool:
        return not self.how


def find(haystack: str, needle: str, *, all_of_them: bool = False
         ) -> tuple[list[Match], str]:
    """Every place `needle` occurs, and how it had to be read to see them.

    Returns `(matches, note)`. An empty list means no rung found anything;
    `note` is then the reason, ready to be shown.
    """
    if not needle:
        return [], "old_string is empty"

    for transform, how in _LADDER:
        matches = _occurrences(haystack, needle, transform, how)
        if not matches:
            continue
        if len(matches) > 1 and not all_of_them:
            # Not this rung's answer to give. A normalisation that collapses
            # two distinct places into one shape has lost the information that
            # told them apart, and picking either is a coin toss on somebody's
            # source file.
            if how:
                continue
            return matches, ""
        return matches, ""

    return [], ""


def _occurrences(haystack: str, needle: str, transform, how: str) -> list[Match]:
    """Where `needle` sits in `haystack`, once both are read the same way.

    The offsets returned are into the *original* haystack, never the
    transformed one, because that is what is about to be spliced.
    """
    if transform is None:
        return [Match(at, at + len(needle), "")
                for at in _plain(haystack, needle)]

    # Line-wise, so an offset in the transformed text can be carried back to
    # an offset in the original: transformations here never merge or split
    # lines, so line N maps to line N.
    lines = haystack.splitlines(keepends=True)
    starts, cursor = [], 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)

    read = [transform(line) for line in lines]
    wanted = [transform(line) for line in needle.splitlines(keepends=True)]
    if not wanted:
        return []

    found = []
    span = len(wanted)
    for index in range(len(read) - span + 1):
        if read[index:index + span] == wanted:
            start = starts[index]
            last = index + span - 1
            end = starts[last] + len(lines[last])
            found.append(Match(start, end, how))
    return found


def _plain(haystack: str, needle: str) -> list[int]:
    found, at = [], haystack.find(needle)
    while at != -1:
        found.append(at)
        at = haystack.find(needle, at + 1)
    return found


# --------------------------------------------------------------------------- #
# the rungs
# --------------------------------------------------------------------------- #


def _endings(line: str) -> str:
    return line.replace("\r\n", "\n").replace("\r", "\n")


def _trailing(line: str) -> str:
    return _endings(line).rstrip() + ("\n" if line.endswith(("\n", "\r")) else "")


def _dedented(line: str) -> str:
    return _trailing(line).lstrip()


_LADDER = (
    (None, ""),
    (_endings, "matched after normalising line endings"),
    (_trailing, "matched after ignoring trailing whitespace"),
    (_dedented, "matched after ignoring indentation"),
)


# --------------------------------------------------------------------------- #
# when nothing matched
# --------------------------------------------------------------------------- #


def near_misses(haystack: str, needle: str) -> str:
    """The closest few places, so the next attempt can be right.

    A bare "not found" makes the model read the whole file again and guess
    afresh. Showing it the three places that nearly matched, with the closest
    one diffed, usually turns the next call into the correct one.
    """
    lines = haystack.splitlines()
    wanted = needle.splitlines()
    if not wanted or not lines:
        return ""

    span = len(wanted)
    # Character by character, not line by line. Comparing lists of lines makes
    # each line an atom, so `return 2` and `return 22222` are simply unequal
    # and a two-line block that differs in one digit scores 0.5 — under any
    # useful threshold. The whole point here is to find the block that is
    # nearly right, and "nearly" lives inside the line.
    matcher = difflib.SequenceMatcher(autojunk=False)
    matcher.set_seq2("\n".join(_norm(line) for line in wanted))

    scored = []
    for index in range(max(1, len(lines) - span + 1)):
        window = lines[index:index + span]
        matcher.set_seq1("\n".join(_norm(line) for line in window))
        scored.append((matcher.ratio(), index, window))

    scored.sort(key=lambda entry: (-entry[0], entry[1]))
    close = [entry for entry in scored[:SUGGESTIONS] if entry[0] >= CLOSE_ENOUGH]
    if not close:
        return ""

    ratio, index, window = close[0]
    report = [
        f"The closest thing in the file is at line {index + 1} "
        f"({ratio:.0%} similar):",
        "",
        *difflib.unified_diff(wanted, window, lineterm="",
                              fromfile="what you asked for",
                              tofile=f"what is at line {index + 1}"),
    ]
    if len(close) > 1:
        others = ", ".join(str(entry[1] + 1) for entry in close[1:])
        report.append("")
        report.append(f"Other candidates start at line {others}.")
    return "\n".join(report)


def _norm(line: str) -> str:
    """For similarity only. Never used to decide a match."""
    return re.sub(r"\s+", " ", line).strip()
