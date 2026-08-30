"""`plan` matching `planet`: a substring test where a word test was meant.

Harder than the other `fix` tasks in one specific way. The failing assertion is
in `search.py` but the machinery for splitting text into words already exists
in `tokens.py`, and the good fix uses it rather than writing a second regex.
Both pass this check — it judges behaviour, not taste — but the task is here
because it is the shape where an agent that never looks at the neighbouring
file writes the third copy of something.

The tie in `test_ranking_puts_the_best_first` is deliberate: `cost` does not
match `costs` once whole words are required, so both surviving documents score
one half and the original order decides. A fix that reaches for stemming breaks
it, and should.
"""

from bench import judge

CATEGORY = "fix"
MAX_STEPS = 25
TIMEOUT = 360.0


def check(attempt):
    return judge.all_of(
        judge.unchanged(attempt, judge.original(__file__), "test_search.py"),
        judge.tests_pass(attempt.workspace),
    )
