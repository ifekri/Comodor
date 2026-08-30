"""Find where a rule is actually implemented, across four files.

A reading task, run in plan mode so the write tools are absent rather than
merely refused — a question about code cannot be answered by editing it.

What is judged is the pair every useful answer to this question contains: the
file, and a line inside the function that does the work. The line is accepted
anywhere in `apply_rate` rather than on one exact row, because "the function
at rates.py:33" and "the branch at rates.py:43" are both right and arguing
about which is more right would be the judge having an opinion.
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


def check(attempt):
    named = judge.says(attempt, "rates.py", "apply_rate")
    if not named.passed:
        return named

    lines = {int(number) for number in re.findall(r"\b(\d{1,4})\b", attempt.text)}
    if not lines & set(BODY):
        return Verdict.no(
            f"no line number inside apply_rate ({BODY.start}-{BODY.stop - 1}) "
            f"appears in the answer")

    # The tier is chosen by billable units past the allowance, not by the raw
    # quantity — the distinction the question asks about.
    if not any(word in attempt.text.lower()
               for word in ("billable", "allowance", "included", "free")):
        return Verdict.no("the answer never says the tier is decided after the "
                          "included allowance is taken off")

    return judge.untouched(attempt, judge.original(__file__),
                           "app/rates.py", "app/billing.py", "report.py")
