"""Add a `--json` flag to a small command-line tool.

Judged by running the program, which is the only check that cannot be satisfied
by code that merely looks right. Three things are asked for and the third is
the one usually dropped: the plain output must be unchanged, and stdout must
stay clean on the error path so a caller can pipe it into a parser.
"""

import json
import subprocess
import sys

from bench import judge
from bench.task import Verdict

CATEGORY = "feature"
MAX_STEPS = 25
TIMEOUT = 420.0

PLAIN = "sample.txt: 6 words, 4 lines, 29 characters"


def run(workspace, *arguments):
    return subprocess.run(
        [sys.executable, "wordcount.py", *arguments], cwd=workspace,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60)


def check(attempt):
    first = judge.all_of(
        judge.parses(attempt.workspace, "wordcount.py"),
        # Before the counts are compared, because an agent that rewrote the
        # sample while trying things out produces numbers that disagree for a
        # reason nothing else here would explain. Saying "the sample changed"
        # is a finding; "expected 6, got 10" would send somebody hunting
        # through a correct implementation.
        judge.unchanged(attempt, judge.original(__file__), "sample.txt"),
    )
    if not first.passed:
        return first

    with_flag = run(attempt.workspace, "--json", "sample.txt")
    if with_flag.returncode != 0:
        return Verdict.no(f"`--json sample.txt` exited {with_flag.returncode}: "
                          f"{with_flag.stderr.strip()[:200]}")

    try:
        report = json.loads(with_flag.stdout)
    except ValueError:
        return Verdict.no("stdout was not one JSON object: "
                          f"{with_flag.stdout.strip()[:200]!r}")

    wanted = {"path": "sample.txt", "words": 6, "lines": 4, "characters": 29}
    if report != wanted:
        return Verdict.no(f"expected {wanted}, got {report}")

    plain = run(attempt.workspace, "sample.txt")
    if plain.stdout.strip() != PLAIN:
        return Verdict.no(f"the plain output changed: "
                          f"{plain.stdout.strip()[:200]!r}")

    missing = run(attempt.workspace, "--json", "nothing-here.txt")
    if missing.returncode != 1:
        return Verdict.no(f"a missing file exited {missing.returncode}, not 1")
    if missing.stdout.strip():
        return Verdict.no("stdout was written on the error path: "
                          f"{missing.stdout.strip()[:200]!r}")
    if not missing.stderr.strip():
        return Verdict.no("a missing file said nothing on stderr")

    return judge.Verdict.ok()
