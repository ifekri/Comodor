"""Diagnose a failing test without fixing it.

Two things are being measured at once, and the second is the interesting one.

*Did it find the cause?* `get` never records that an entry was used, so the
eviction order is insertion order and a read changes nothing. Naming `put` —
which is where the eviction code lives, and where the eye goes first — is the
wrong answer, and a confident, well-argued version of it is the likeliest
wrong answer there is.

*Did it do as it was told?* The instruction was to explain, not fix. An agent
that fixes it anyway has not failed at programming; it has failed at doing what
was asked, which is the more expensive habit. Plan mode makes that impossible
here, and the check is kept so the task still means something if that changes.

**The cause has to be attributed to `get`, not merely mentioned near it.** An
earlier version of this judge looked for the word `get` anywhere and a cause
phrase anywhere, and passed this:

    The bug is in `put`. It evicts with next(iter(...)), which is insertion
    order, so it drops the oldest inserted entry. `get` is fine.

— which is confident, plausible, and wrong. A judge that passes a wrong answer
is the same bug as one that fails a right one, and both produce a number
indistinguishable from a real one. So the two have to meet in the same
sentence.
"""

import re

from bench import judge
from bench.task import Verdict

CATEGORY = "find"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = False

#: The cause, in any of the ways somebody would put it: reading does not mark
#: the entry as used, so eviction still follows insertion order.
CAUSES = (
    "most recently used", "recently used", "move", "reorder", "re-order",
    "insertion order", "order of insertion", "does not update",
    "never updates", "doesn't update", "no record", "does not record",
    "never records", "doesn't record", "does not touch", "never marks",
    "does not mark", "unchanged", "no effect",
)

_SENTENCE = re.compile(r"[^.!?\n]+")


def check(attempt):
    still = judge.untouched(attempt, judge.original(__file__),
                            "cache.py", "test_cache.py")
    if not still.passed:
        return still

    text = attempt.text.lower()
    if "get" not in text:
        return Verdict.no("the answer never names `get`")

    for sentence in _SENTENCE.findall(text):
        if "get" in sentence and any(cause in sentence for cause in CAUSES):
            return Verdict.ok()

    return Verdict.no(
        "the answer never says that `get` is what fails to update the order — "
        "naming `put`, where the eviction code is, is the wrong answer")
