"""The assertions the judges are built from.

Every one of these is something a person could check by hand and get the same
answer. That is the whole standard: if a check here needed judgement, it would
belong to a model, and a model's judgement is not reproducible.

The one that matters most is :func:`unchanged`. A task that says "make the test
pass" is passed trivially by deleting the test, and an agent that does it is
not cheating — it is doing what a badly written judge rewarded. So every task
whose goal is a green suite also pins the test file.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from .task import Verdict

#: Long enough for a small suite on a cold interpreter, short enough that a
#: hanging test is reported rather than waited on.
PATIENCE = 120.0


def tests_pass(workspace: Path, target: str = "") -> Verdict:
    """Run pytest in the workspace and read the exit code."""
    command = [sys.executable, "-m", "pytest", "-q"]
    if target:
        command.append(target)
    try:
        finished = subprocess.run(command, cwd=workspace, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace",
                                  timeout=PATIENCE)
    except subprocess.TimeoutExpired:
        return Verdict.no(f"the suite did not finish within {PATIENCE:.0f}s")
    if finished.returncode == 0:
        return Verdict.ok()
    tail = (finished.stdout or finished.stderr).strip().splitlines()
    return Verdict.no("the suite still fails: "
                      + " ".join(tail[-3:])[:300])


def hidden_tests(attempt, check_file: str) -> Verdict:
    """Copy the task's held-back tests in, then run only those.

    They are run on their own rather than with the rest of the suite so the
    reason for a failure is unambiguous: the spec was not met, not that
    something else in the workspace is red.
    """
    source = Path(check_file).resolve().parent / "hidden"
    if not source.is_dir():
        return Verdict.no("this task declares hidden tests and has none")

    names = []
    for path in sorted(source.glob("test_*.py")):
        (attempt.workspace / path.name).write_bytes(path.read_bytes())
        names.append(path.name)
    if not names:
        return Verdict.no("the hidden directory holds no tests")

    for name in names:
        verdict = tests_pass(attempt.workspace, name)
        if not verdict.passed:
            return verdict
    return Verdict.ok()


def unchanged(attempt, original: Path, *names: str) -> Verdict:
    """These files must be exactly as they started.

    The guard against passing a task by removing the thing that judges it.
    """
    for name in names:
        was = (original / name).read_bytes()
        try:
            now = (attempt.workspace / name).read_bytes()
        except OSError:
            return Verdict.no(f"{name} was deleted")
        if was != now:
            return Verdict.no(f"{name} was modified — it is what the task "
                              f"is judged against, not part of the work")
    return Verdict.ok()


def untouched(attempt, original: Path, *names: str) -> Verdict:
    """These files were not part of the task and must be left alone."""
    changed = set(attempt.touched(original))
    strayed = [name for name in names if name in changed]
    if strayed:
        return Verdict.no(f"changed {', '.join(strayed)}, which the task did "
                          f"not ask about")
    return Verdict.ok()


def parses(workspace: Path, *names: str) -> Verdict:
    """Every named Python file is still syntactically valid."""
    for name in names:
        path = workspace / name
        try:
            ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as broken:
            return Verdict.no(f"{name} does not parse: line {broken.lineno}, "
                              f"{broken.msg}")
        except OSError:
            return Verdict.no(f"{name} is gone")
    return Verdict.ok()


def absent(workspace: Path, needle: str, suffix: str = ".py") -> Verdict:
    """`needle` appears in no file of that kind. Used by the rename tasks."""
    for path in sorted(workspace.rglob(f"*{suffix}")):
        if any(part in {"__pycache__", ".comodor"} for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle in text:
            line = next((number for number, row
                         in enumerate(text.splitlines(), start=1)
                         if needle in row), 0)
            return Verdict.no(f"{needle!r} is still in "
                              f"{path.relative_to(workspace).as_posix()}:{line}")
    return Verdict.ok()


def says(attempt, *needles: str) -> Verdict:
    """The answer mentions each of these, case-insensitively.

    Used only where the wording genuinely is the deliverable — a `find` task
    whose whole output is a file and a line. Never as a proxy for work done.
    """
    lowered = attempt.text.lower()
    missing = [needle for needle in needles if needle.lower() not in lowered]
    if missing:
        return Verdict.no(f"the answer never mentions {', '.join(missing)}")
    return Verdict.ok()


def all_of(*verdicts: Verdict) -> Verdict:
    """Every check, reporting the first that failed."""
    for verdict in verdicts:
        if not verdict.passed:
            return verdict
    return Verdict.ok()


def original(check_file: str) -> Path:
    """The pristine `repo/` beside a `check.py`, for before-and-after work."""
    return Path(check_file).resolve().parent / "repo"
