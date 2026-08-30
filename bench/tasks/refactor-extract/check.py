"""Three functions with the same shape copied three times.

Judged by counting exact fragments rather than by an opinion about how tidy the
result is. Each of the three pieces of scaffolding — the rule under the header,
the wrapping loop, the footer — must appear at most once in the file.

"At most" rather than "exactly" on purpose: rewriting the loop as
`textwrap.wrap` makes it appear zero times, and that is a better answer, not a
failing one. What is not allowed is three.

The suite is the other half. A file that has been tidied into something that no
longer produces the same messages has not refactored anything.
"""

from bench import judge
from bench.task import Verdict

CATEGORY = "refactor"
MAX_STEPS = 30
TIMEOUT = 420.0

#: Copied verbatim into all three functions today.
REPEATED = (
    '"=" * min(len(header), WIDTH)',
    'f"Questions? {SUPPORT}"',
    "range(0, len(body), WIDTH)",
)


def check(attempt):
    green = judge.tests_pass(attempt.workspace)
    if not green.passed:
        return green

    source = (attempt.workspace / "notify.py").read_text(
        encoding="utf-8", errors="replace")

    for fragment in REPEATED:
        seen = source.count(fragment)
        if seen > 1:
            return Verdict.no(f"{fragment} still appears {seen} times")

    return Verdict.ok()
