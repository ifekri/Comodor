"""Two boundaries written `>` where the spec beside them says "at or above".

Both bugs are one character and neither is visible in the failure message —
`54.95 != 50.0` says a number is wrong, not which comparison produced it. It is
passed by reading the constant, its comment and the branch together, which is
the ordinary work of fixing somebody else's code.
"""

from bench import judge

CATEGORY = "fix"
MAX_STEPS = 20
TIMEOUT = 300.0


def check(attempt):
    return judge.all_of(
        judge.unchanged(attempt, judge.original(__file__), "test_pricing.py"),
        judge.tests_pass(attempt.workspace),
    )
