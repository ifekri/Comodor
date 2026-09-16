"""Scenario fingerprints, so a weakened benchmark cannot pass as a better agent.

A benchmark measures the agent only while the tasks stay the same. Shorten a
prompt, soften a judge, drop the hardest case, raise a step budget — and the
number goes up with nothing about the agent having changed. None of those
edits looks like cheating in a diff; each looks like tidying.

So every scenario is fingerprinted — the prompt, the judge, the starting
repository, and the budgets the judge declares — and the fingerprints are
committed beside the tasks. `check` compares the tasks on disk against the
record and names every difference. A run against a drifted suite is not a
result about the agent, and `python -m bench` refuses to produce one.

This is benchmark infrastructure. Nothing under `src/comodor/` imports it,
and nothing here imports the runtime: it reads files and hashes bytes.

    python -m bench.integrity record      # write FINGERPRINTS.json
    python -m bench.integrity check       # exit 1 and say what moved
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
RECORD = TASKS / "FINGERPRINTS.json"

#: Never part of a fingerprint: left behind by running the tests, not by
#: writing the task.
NOISE = {"__pycache__", ".pytest_cache", ".comodor", ".git", ".ruff_cache"}

#: The parts of a scenario that decide what it measures. The budgets are
#: inside `check.py`, so hashing the judge covers them; they are also read
#: out separately so a report can say *which* budget moved.
PARTS = ("task.md", "check.py", "repo", "hidden")


def _sha(data: bytes) -> str:
    """A content hash that does not depend on the checkout's line endings.

    The repository stores LF, but a working tree on Windows can hand a file
    back with CRLF before the next checkout normalises it. Line endings are not
    part of what a scenario measures, so they are normalised here — otherwise
    the same scenario would fingerprint differently on two platforms and the
    committed record would only be true on the machine that wrote it.
    """
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _tree(root: Path) -> dict[str, str]:
    """Every file under `root`, by posix path, as a content hash."""
    found: dict[str, str] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in NOISE for part in relative.parts):
            continue
        found[relative.as_posix()] = _sha(path.read_bytes())
    return found


def _budgets(check_file: Path) -> dict[str, object]:
    """The judge's declared budgets, read as text rather than imported.

    Importing would execute the judge; a fingerprint must not run anything.
    The constants are simple assignments at module level, which is all this
    reads.
    """
    budgets: dict[str, object] = {}
    try:
        text = check_file.read_text(encoding="utf-8")
    except OSError:
        return budgets
    for line in text.splitlines():
        stripped = line.strip()
        for name in ("MAX_STEPS", "TIMEOUT", "WRITES", "CATEGORY"):
            if stripped.startswith((f"{name} ", f"{name}=")):
                _, _, value = stripped.partition("=")
                budgets[name] = value.strip().strip('"').strip("'")
    return budgets


def fingerprint(directory: Path) -> dict[str, object]:
    """One scenario's fingerprint: enough to detect any change to what it measures."""
    record: dict[str, object] = {}
    for part in ("task.md", "check.py"):
        path = directory / part
        record[part] = _sha(path.read_bytes()) if path.is_file() else None
    record["repo"] = _tree(directory / "repo")
    record["hidden"] = _tree(directory / "hidden")
    record["budgets"] = _budgets(directory / "check.py")
    return record


def fingerprint_all(root: Path = TASKS) -> dict[str, dict[str, object]]:
    return {
        directory.name: fingerprint(directory)
        for directory in sorted(root.iterdir())
        if directory.is_dir() and not directory.name.startswith("_")
    }


def record(root: Path = TASKS, target: Path = RECORD) -> Path:
    """Write the fingerprints of every scenario on disk."""
    # LF on every platform: the record is committed, and a file that differs
    # by line endings between Windows and Linux would drift on its own.
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(fingerprint_all(root), indent=2, sort_keys=True) + "\n")
    return target


@dataclass
class Drift:
    """What differs between the record and the tasks on disk."""

    missing: list[str] = field(default_factory=list)      # recorded, gone from disk
    unrecorded: list[str] = field(default_factory=list)   # on disk, not recorded
    changed: dict[str, list[str]] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not (self.missing or self.unrecorded or self.changed)

    def describe(self) -> str:
        lines: list[str] = []
        for name in self.missing:
            lines.append(f"{name}: scenario deleted (it is still in the record)")
        for name in self.unrecorded:
            lines.append(f"{name}: scenario not in the record — run "
                         f"`python -m bench.integrity record` after review")
        for name, what in self.changed.items():
            lines.append(f"{name}: changed — {', '.join(what)}")
        return "\n".join(lines)


def _compare(before: dict[str, object], after: dict[str, object]) -> list[str]:
    what: list[str] = []
    for part in ("task.md", "check.py"):
        if before.get(part) != after.get(part):
            what.append(part)
    for tree in ("repo", "hidden"):
        was = before.get(tree) or {}
        now = after.get(tree) or {}
        if was != now:
            added = sorted(set(now) - set(was))
            gone = sorted(set(was) - set(now))
            edited = sorted(name for name in set(was) & set(now) if was[name] != now[name])
            detail = []
            if added:
                detail.append(f"added {', '.join(added)}")
            if gone:
                detail.append(f"removed {', '.join(gone)}")
            if edited:
                detail.append(f"edited {', '.join(edited)}")
            what.append(f"{tree}/ ({'; '.join(detail)})")
    was_budgets = before.get("budgets") or {}
    now_budgets = after.get("budgets") or {}
    if was_budgets != now_budgets:
        moved = sorted(set(was_budgets) | set(now_budgets))
        what.append("budgets: " + ", ".join(
            f"{name} {was_budgets.get(name)!r}→{now_budgets.get(name)!r}"
            for name in moved if was_budgets.get(name) != now_budgets.get(name)))
    return what


def check(root: Path = TASKS, target: Path = RECORD) -> Drift:
    """Compare the tasks on disk with the record. Never raises on drift."""
    drift = Drift()
    try:
        recorded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recorded = {}
    current = fingerprint_all(root)
    drift.missing = sorted(set(recorded) - set(current))
    drift.unrecorded = sorted(set(current) - set(recorded))
    for name in sorted(set(recorded) & set(current)):
        what = _compare(recorded[name], current[name])
        if what:
            drift.changed[name] = what
    return drift


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "check"
    if command == "record":
        written = record(TASKS, RECORD)
        print(f"recorded {len(fingerprint_all(TASKS))} scenarios in {written}")
        return 0
    if command == "check":
        drift = check(TASKS, RECORD)
        if drift.clean:
            print("benchmark scenarios match their record")
            return 0
        print("benchmark scenarios have drifted from their record:\n"
              + drift.describe(), file=sys.stderr)
        return 1
    print("usage: python -m bench.integrity [record|check]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
