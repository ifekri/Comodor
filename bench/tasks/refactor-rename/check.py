"""Rename two functions across four files, leaving nothing behind.

The test file is renamed too, so `unchanged` cannot be used here — which is
what makes the second half of the check necessary. A green suite alone is
passed by leaving a one-line alias, and the task explicitly rules that out. So
both halves are required: the suite passes *and* the old names are gone.

`mk_k` being a substring of `mk_k_prefix` is deliberate. A careless rename
turns `mk_k_prefix` into `record_key_prefix`, which passes the "old name is
gone" half and fails the suite — the two checks catch different mistakes.
"""

from bench import judge

CATEGORY = "refactor"
MAX_STEPS = 30
TIMEOUT = 420.0


def check(attempt):
    return judge.all_of(
        judge.tests_pass(attempt.workspace),
        judge.absent(attempt.workspace, "mk_k"),
    )
