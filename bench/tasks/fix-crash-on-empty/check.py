"""An empty run crashes the summary — and the obvious fix breaks another test.

The point of this one is that the first idea is wrong. Guarding `mean` makes
the failing test pass and turns `test_the_two_pieces_agree_with_the_summary`
red, so passing it requires running the suite after the change rather than
assuming. That is the habit being measured.
"""

from bench import judge

CATEGORY = "fix"
MAX_STEPS = 20
TIMEOUT = 300.0


def check(attempt):
    return judge.all_of(
        judge.unchanged(attempt, judge.original(__file__), "test_stats.py"),
        judge.tests_pass(attempt.workspace),
    )
