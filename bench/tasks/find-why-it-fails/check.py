"""Diagnose a failing test without fixing it.

The question has exactly one right answer and one attractive wrong one, and
that is the whole design: `get` never records that an entry was used, so
eviction still follows insertion order. `put` — where the eviction code
actually lives, and where the eye goes first — is the wrong answer.

So what is judged is **which method the answer blames**, and nothing else.

Two earlier versions of this check got that wrong in both directions, which is
worth writing down because the fix for one caused the other.

*Too lenient.* Looking for `get` anywhere and a cause phrase anywhere passed
this: "The bug is in `put`. It evicts in insertion order... `get` is fine."

*Too strict.* Requiring them in the same sentence then failed a genuinely
excellent answer, because the model wrote "**Root cause — `Cache.get` is
wrong**" and then continued with a pronoun: "It never records that the key was
accessed." Every human reader knows what "it" is. A judge that does not is
grading prose style, not correctness.

The third version stops guessing at phrasing. An answer that diagnoses
something names the thing it blames next to the words that say it is to blame,
and that is a position, not a vocabulary. Find where the fault is attributed;
see which method is standing there.
"""

import re

from bench import judge
from bench.task import Verdict

CATEGORY = "find"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = False

#: Where an answer says "this is the thing that is wrong".
BLAME = re.compile(
    r"root cause|the cause|the bug|the problem|the issue|the fault|at fault|"
    r"culprit|is wrong|is broken|is the one|does not|doesn't|never |fails to|"
    r"is missing|is incorrect|what actually happens|why it fails",
    re.IGNORECASE)

#: How far either side of that a method name still counts as the subject.
#: Wide enough for "Root cause — `Cache.get` is wrong (cache.py:13-14)", narrow
#: enough that the next paragraph is not swept in.
REACH = 90

METHOD = re.compile(r"\b(get|put)\b", re.IGNORECASE)


def check(attempt):
    still = judge.untouched(attempt, judge.original(__file__),
                            "cache.py", "test_cache.py")
    if not still.passed:
        return still

    text = attempt.text
    if not METHOD.search(text):
        return Verdict.no("the answer names neither `get` nor `put`")

    blamed = _blamed(text)
    if blamed == "get":
        return Verdict.ok()
    if blamed == "put":
        return Verdict.no(
            "the answer blames `put`, where the eviction code is. The eviction "
            "is correct; `get` is what never records that an entry was used")
    return Verdict.no(
        "the answer does not say which method is at fault — the eviction in "
        "`put` is correct, and `get` is what fails to record a read")


def _blamed(text: str) -> str:
    """Which method the answer holds responsible, or an empty string.

    The first place fault is attributed and exactly one of the two methods is
    within reach of it. "Exactly one" matters: a sentence naming both is
    comparing them rather than accusing either.
    """
    for marker in BLAME.finditer(text):
        window = text[max(0, marker.start() - REACH):marker.end() + REACH]
        near = {found.group(1).lower() for found in METHOD.finditer(window)}
        if len(near) == 1:
            return near.pop()
    return ""
