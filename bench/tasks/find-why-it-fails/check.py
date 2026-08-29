"""Diagnose a failing test without fixing it.

Two things are being measured at once, and the second is the interesting one.

*Did it find the cause?* `get` never records that an entry was used, so the
eviction order is insertion order and a read changes nothing. Naming `put` —
which is where the eviction code lives and where the eye goes first — is the
wrong answer, and a common one.

*Did it do as it was told?* The instruction was to explain, not fix. An agent
that fixes it anyway has not failed at programming; it has failed at doing what
was asked, which is the more expensive habit. Plan mode makes that impossible
here, and the check is kept so the task still means something if that changes.
"""

from bench import judge
from bench.task import Verdict

CATEGORY = "find"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = False


def check(attempt):
    still = judge.untouched(attempt, judge.original(__file__),
                            "cache.py", "test_cache.py")
    if not still.passed:
        return still

    text = attempt.text.lower()

    if "get" not in text:
        return Verdict.no("the answer never names `get`")

    # The cause: reading does not mark the entry as used, so eviction follows
    # insertion order. Any of these phrasings is the same finding.
    causes = ("most recently used", "recently used", "move", "reorder",
              "insertion order", "does not update", "never updates",
              "no record", "does not record", "order of insertion")
    if not any(phrase in text for phrase in causes):
        return Verdict.no("the answer does not say that reading fails to "
                          "update the order")

    return Verdict.ok()
