"""A remainder needs a page. Integer division says it does not.

The commonest real bug there is, and the reason it is first: it is found by
reading the failure rather than by knowing anything, so a model that cannot
pass it is not reading what its own tools returned.
"""

from bench import judge

CATEGORY = "fix"
MAX_STEPS = 20
TIMEOUT = 300.0


def check(attempt):
    return judge.all_of(
        # Before the suite, because a green suite with a rewritten test file is
        # the failure this task is most likely to be passed by.
        judge.unchanged(attempt, judge.original(__file__), "test_pagination.py"),
        judge.tests_pass(attempt.workspace),
    )
