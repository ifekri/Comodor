"""Build a retry decorator from a written spec.

Nine bullet points, none of them hard on its own, and the whole of the task is
honouring all nine rather than the three that come to mind first. The two that
are usually missed are the same two every time: a non-matching exception must
come out unwrapped, and the decorated function must keep its own name.

The tests are held back deliberately. Given them, this is "make these pass";
withheld, it is "build what was described", which is the job.
"""

from bench import judge

CATEGORY = "feature"
MAX_STEPS = 30
TIMEOUT = 480.0


def check(attempt):
    return judge.all_of(
        # It has to still be valid Python before anything is imported, or the
        # failure below reads as a wrong implementation rather than a broken
        # file.
        judge.parses(attempt.workspace, "retry.py"),
        judge.unchanged(attempt, judge.original(__file__), "test_retry.py"),
        judge.tests_pass(attempt.workspace, "test_retry.py"),
        judge.hidden_tests(attempt, __file__),
    )
