"""Noticing when an answer says the tests pass and nothing ran them.

The one thing a programmer will not forgive is a tool that reports work it did
not do. Slowness is forgiven; a wrong diff is forgiven, because they can see
it. "The tests pass now" when nothing was run is different in kind — every
other claim the tool makes is worth less afterwards.

The system prompt already says not to. This is what happens when it does
anyway: a notice, next to the answer, saying nothing was run. Not a block, and
not an accusation — the user is simply told which of the two situations they
are in, which is the thing they cannot see for themselves.

**The bar for firing is deliberately high**, because a warning that is
sometimes wrong teaches people to ignore the warning. All four have to hold:

1. Files were changed this turn. With nothing changed there is nothing to
   verify and the sentence is almost certainly about something else.
2. No command was run. If anything was, the user can see what it said.
3. The answer states plainly that a suite or a build passes — matched against a
   short list of assertions, not a keyword.
4. The sentence it appears in is not hedged, negated, or an instruction. "Make
   sure the tests pass", "the tests do not pass yet" and "if the tests pass"
   are all the opposite of the claim being looked for.
"""

from __future__ import annotations

import re

#: Tools that could have produced evidence. Anything here means the user has
#: output of their own to read and needs nothing from us.
COMMANDS = frozenset({"run_shell", "run_python"})

#: Tools that change the project, so that there is something to verify.
WRITES = frozenset({"write_file", "edit_file"})

#: Plain assertions that a suite or a build is good. Every one of these is a
#: statement about a thing that was run, which is what makes the absence of a
#: command meaningful.
ASSERTIONS = (
    "tests pass", "tests now pass", "tests are passing", "tests all pass",
    "test suite passes", "the suite passes", "suite is green",
    "suite now passes", "everything passes", "all green",
    "build succeeds", "build passes", "builds successfully",
    "builds cleanly", "compiles cleanly",
)

#: In the same sentence, any of these means it is not a claim about what
#: happened. A hedge, a negation, or an instruction to the reader.
NOT_A_CLAIM = (
    "not ", "n't", "fail", "unable", "cannot", "can not", "still ",
    "if ", "once ", "after ", "when ", "should ", "would ", "will ",
    "make sure", "ensure", "check that", "verify that", "please ",
    "so that", "to confirm", "expect", "assume", "presumably", "likely",
)

_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]?")


def unverified(answer: str, tools_used: list[str]) -> str:
    """The notice to show, or an empty string.

    `tools_used` is every tool name from this turn, in order.
    """
    if not answer:
        return ""
    if any(name in COMMANDS for name in tools_used):
        return ""
    if not any(name in WRITES for name in tools_used):
        return ""

    claim = _find(answer)
    if not claim:
        return ""

    return (f"Nothing was run this turn, so “{claim}” has not been "
            f"checked. Ask it to run the tests, or run them yourself.")


def _find(answer: str) -> str:
    """The first plain assertion in the answer, as it was written."""
    for sentence in _SENTENCE.findall(answer):
        lowered = sentence.lower()
        if not any(phrase in lowered for phrase in ASSERTIONS):
            continue
        if any(word in lowered for word in NOT_A_CLAIM):
            continue
        trimmed = sentence.strip().rstrip(".!?")
        return trimmed if len(trimmed) <= 90 else trimmed[:87] + "…"
    return ""
