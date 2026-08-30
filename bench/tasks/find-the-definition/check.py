"""Find where a rule is actually implemented, across four files.

A reading task, run in plan mode so the write tools are absent rather than
merely refused — a question about code cannot be answered by editing it.

Three things are judged, and the third is the one that took two attempts to get
right.

*The file and the function.* `apply_rate` in `app/rates.py`, not `included`
next to it and not `invoice_lines` upstream.

*A line inside that function.* Accepted anywhere in its body rather than on one
exact row: "the function at rates.py:33" and "the branch at rates.py:43" are
both right, and arguing about which is more right would be the judge having an
opinion.

*What actually decides the tier.* The allowance comes off first — the reduced
price applies past a thousand **billable** units, not a thousand raw ones. This
is the half of the question that separates having read the function from having
found it.

The first version of this check looked for the word "allowance" anywhere in the
answer, which passed:

    Anything over 1000 raw units of the meter gets the reduced price,
    regardless of the allowance.

— the wrong rule, stated confidently, passing because it named the thing it was
dismissing. So the subtraction and the allowance have to appear in the same
sentence, and that sentence must not be waving it away.
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

#: The free part, however it is named.
ALLOWANCE = ("allowance", "included", "free", "billable")

#: Taking it off, however it is put.
SUBTRACTED = ("minus", "after", "past", "beyond", "subtract", "deduct",
              "excess", "over and above", "on top of", "billable", "-",
              "remaining", "left")

#: Waving it away, which is the wrong answer wearing the right words.
DISMISSED = ("regardless", "ignoring", "irrespective", "raw ", "whether or not",
             "does not matter", "doesn't matter", "no matter", "total quantity")

#: Where the answer talks about the threshold itself.
THRESHOLD = re.compile(r"\b(?:1[,_ ]?000|thousand|1000)\b", re.IGNORECASE)

#: How far either side of the threshold still counts as talking about it.
#: A paragraph, not a sentence: an answer that names the allowance and then
#: continues with a pronoun is an answer, and a rule that cannot follow "it"
#: is grading prose rather than correctness. That mistake was made twice in
#: this suite before it was written down.
REACH = 220


def check(attempt):
    named = judge.says(attempt, "rates.py", "apply_rate")
    if not named.passed:
        return named

    lines = {int(number) for number in re.findall(r"\b(\d{1,4})\b", attempt.text)}
    if not lines & set(BODY):
        return Verdict.no(
            f"no line number inside apply_rate ({BODY.start}-{BODY.stop - 1}) "
            f"appears in the answer")

    explained = False
    lowered = attempt.text.lower()
    for found in THRESHOLD.finditer(lowered):
        window = lowered[max(0, found.start() - REACH):found.end() + REACH]
        if any(word in window for word in DISMISSED):
            continue
        if (any(word in window for word in ALLOWANCE)
                and any(word in window for word in SUBTRACTED)):
            explained = True
            break

    if not explained:
        return Verdict.no(
            "the answer does not say that the tier is decided after the "
            "included allowance comes off — the reduced price applies past a "
            "thousand billable units, not a thousand raw ones")

    return judge.untouched(attempt, judge.original(__file__),
                           "app/rates.py", "app/billing.py", "report.py")
