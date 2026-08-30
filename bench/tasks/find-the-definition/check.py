"""Find where a rule is implemented, and prove you understood it.

A reading task, run in plan mode so the write tools are absent rather than
merely refused — a question about code cannot be answered by editing it.

**Both halves of the answer have exactly one correct spelling**, and that is a
change to the task rather than a cleverer way of reading prose. Three versions
of this judge tried the latter:

*Too lenient.* "allowance" anywhere passed "anything over 1000 raw units,
regardless of the allowance" — the opposite of what the code does, stated
confidently, passing because it named the thing it was dismissing.

*Too strict.* Requiring the words in one sentence failed answers that used a
pronoun in the next.

*Too strict again.* A dismissal list containing "total quantity" failed this,
which is correct: "the billable quantity (total quantity minus the plan's free
allowance) exceeds 1,000". The phrase was on the list because it can signal the
wrong rule. Here it is half of the right one.

So the second half is a number now. `25,000` requests on the growth plan, whose
included allowance is `10,000`, leaves `15,000` billable. An answer that has
understood the rule can compute it; one that thinks the tier is decided by raw
quantity will say `25,000`, which is the wrong answer and is visibly the wrong
answer. No word list can be wrong about it.
"""

import re

from bench import judge
from bench.task import Verdict

CATEGORY = "find"
MAX_STEPS = 20
TIMEOUT = 300.0
WRITES = False

#: `def apply_rate` through its last line.
BODY = range(33, 44)

WHERE = re.compile(r"^\W*WHERE\W*:\W*`?\**\s*([\w./\\-]+?\.py)\D{0,4}(\d{1,4})",
                   re.IGNORECASE | re.MULTILINE)

BILLABLE = re.compile(r"^\W*BILLABLE\W*:\W*`?\**\s*([\d,_ ]+)",
                      re.IGNORECASE | re.MULTILINE)

#: 25,000 requests against a growth allowance of 10,000.
ANSWER = 15_000

#: What an answer says when it thinks the tier is decided by raw quantity.
RAW = 25_000


def check(attempt):
    where = WHERE.search(attempt.text)
    if not where:
        return Verdict.no("the answer has no `WHERE:` line, which the task "
                          "asked for")

    path, line = where.group(1).replace("\\", "/"), int(where.group(2))
    if not path.endswith("rates.py"):
        return Verdict.no(f"it named {path}, and the arithmetic is in "
                          f"app/rates.py")
    if line not in BODY:
        return Verdict.no(
            f"line {line} is not inside apply_rate "
            f"({BODY.start}-{BODY.stop - 1})")

    billable = BILLABLE.search(attempt.text)
    if not billable:
        return Verdict.no("the answer has no `BILLABLE:` line")

    digits = re.sub(r"[^\d]", "", billable.group(1))
    if not digits:
        return Verdict.no(f"`BILLABLE: {billable.group(1).strip()}` is not a number")

    counted = int(digits)
    if counted == RAW:
        return Verdict.no(
            f"it answered {counted:,}, which is the raw quantity. The included "
            f"allowance comes off first — the tier is decided on billable units")
    if counted != ANSWER:
        return Verdict.no(f"it answered {counted:,}; the growth plan includes "
                          f"10,000, so 25,000 requests leave {ANSWER:,} billable")

    return judge.untouched(attempt, judge.original(__file__),
                           "app/rates.py", "app/billing.py", "report.py")
