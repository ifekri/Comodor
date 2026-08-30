"""Diagnose a failing test without fixing it.

The question has one right answer and one attractive wrong one, and that is the
whole design: `get` never records that an entry was used, so eviction still
follows insertion order. `put` — where the eviction code actually lives, and
where the eye goes first — is the wrong answer.

**The task now asks for the verdict on its own line**, and this reads that line.
That is a change to the task, not a cleverer way of reading prose, and it was
made after four attempts at the latter. Each one was wrong in one direction:

*Too lenient.* `get` anywhere and a cause phrase anywhere passed "The bug is in
`put`… `get` is fine."

*Too strict.* Requiring them in one sentence failed an excellent answer that
named `Cache.get` in a heading and continued with "It never records…".

*Too strict again.* Looking for the method nearest a blame phrase failed
"**The failing method is `Cache.get`**" — because "failing method is" was not
one of the phrases I had thought of.

Four heuristics, three of them wrong, each wrong in a way that looked exactly
like a real result. The lesson is not that the fourth word list would have been
the good one. It is that grading prose is not something a program does well,
and a benchmark that needs it should change the question instead — a task whose
answer is checkable is worth more than a judge that is nearly right.

The prose still has to be there. The rest of the check reads it for the cause,
loosely, because that half is genuinely secondary: the method named is the
finding, and the explanation is how it is shown.
"""

import re

from bench import judge
from bench.task import Verdict

CATEGORY = "find"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = False

#: The line the task asks for. Tolerant of the ways a model dresses it —
#: bold, backticks, a `Cache.` prefix, parentheses — because none of that is
#: what is being measured.
VERDICT = re.compile(r"^\W*METHOD\W*:\W*`?\**\s*(?:cache\.)?(\w+)",
                     re.IGNORECASE | re.MULTILINE)

#: Said by an answer that has understood *why*, in any of the ways it is put.
CAUSES = (
    "recently used", "access order", "order", "move", "reorder", "re-order",
    "does not update", "never updates", "doesn't update", "no record",
    "does not record", "never records", "doesn't record", "unchanged",
    "no effect", "does not mark", "never marks",
)


def check(attempt):
    still = judge.untouched(attempt, judge.original(__file__),
                            "cache.py", "test_cache.py")
    if not still.passed:
        return still

    found = VERDICT.search(attempt.text)
    if not found:
        return Verdict.no(
            "the answer has no `METHOD:` line, which the task asked for")

    named = found.group(1).lower()
    if named == "put":
        return Verdict.no(
            "it named `put`, where the eviction code is. The eviction is "
            "correct; `get` is what never records that an entry was used")
    if named != "get":
        return Verdict.no(f"it named `{named}`, which is not the method at fault")

    if not any(cause in attempt.text.lower() for cause in CAUSES):
        return Verdict.no(
            "it named the right method and did not say what is wrong with it")

    return Verdict.ok()
