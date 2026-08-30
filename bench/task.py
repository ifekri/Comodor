"""What a task is, and how one is loaded from disk.

A task is three files in a directory:

``task.md``     the prompt, verbatim and nothing else — so a reader can see
                exactly what the agent was given rather than a paraphrase of it
``repo/``       the starting state, copied fresh for every attempt
``check.py``    the judgement, and the budget it is judged under

Keeping the prompt in a file of its own is the point of the split. A benchmark
whose prompts are buried in Python is one nobody audits, and a prompt nobody
audits is where a benchmark quietly starts measuring how well the task was
written rather than how well the agent did.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: Categories, in the order a report lists them. `careful` is last because it
#: is the one that measures restraint rather than output, and it reads better
#: after the four that measure work.
CATEGORIES = ("fix", "feature", "find", "refactor", "careful")


@dataclass(frozen=True)
class Verdict:
    """What a judge decided, and why.

    The reason is not optional and is not decoration: a failing task whose
    report says only `False` tells you the number moved and nothing about what
    to do next, which is the state this whole exercise exists to get out of.
    """

    passed: bool
    reason: str

    @classmethod
    def ok(cls, reason: str = "") -> Verdict:
        return cls(True, reason or "passed")

    @classmethod
    def no(cls, reason: str) -> Verdict:
        return cls(False, reason)


@dataclass
class Attempt:
    """One run of one task: what the agent reported, and where it worked."""

    workspace: Path
    ok: bool
    stopped: str
    text: str
    steps: int
    tools: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    elapsed: float = 0.0
    error: str = ""

    def used(self, name: str) -> bool:
        return name in self.tools

    def touched(self, original: Path) -> list[str]:
        """Every path that differs from the repository it started as.

        Judged from the filesystem rather than from the agent's own account of
        itself, because "did not touch anything it was not asked to" is
        precisely the claim that cannot be taken on trust.
        """
        return sorted(_differences(original, self.workspace))


@dataclass
class Task:
    """One benchmark task, loaded from its directory."""

    name: str
    category: str
    prompt: str
    repo: Path
    check: Callable[[Attempt], Verdict]
    max_steps: int = 30
    timeout: float = 600.0
    #: Whether the agent is allowed to change anything. `find` tasks run with
    #: writes refused, so a task about reading cannot be passed by rewriting
    #: the thing it was asked about.
    writes: bool = True

    @property
    def sort_key(self) -> tuple[int, str]:
        order = CATEGORIES.index(self.category) if self.category in CATEGORIES \
            else len(CATEGORIES)
        return (order, self.name)


class TaskError(Exception):
    """A task directory that cannot be loaded. Never silently skipped."""


def load_task(directory: Path) -> Task:
    prompt_file = directory / "task.md"
    check_file = directory / "check.py"
    repo = directory / "repo"

    for needed in (prompt_file, check_file, repo):
        if not needed.exists():
            raise TaskError(f"{directory.name}: {needed.name} is missing")

    prompt = prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise TaskError(f"{directory.name}: task.md is empty")

    module = _import(check_file, f"bench_task_{directory.name.replace('-', '_')}")
    judge = getattr(module, "check", None)
    if not callable(judge):
        raise TaskError(f"{directory.name}: check.py defines no check(attempt)")

    category = str(getattr(module, "CATEGORY", "")).strip()
    if category not in CATEGORIES:
        raise TaskError(f"{directory.name}: CATEGORY must be one of "
                        f"{', '.join(CATEGORIES)}, not {category!r}")

    return Task(
        name=directory.name,
        category=category,
        prompt=prompt,
        repo=repo,
        check=judge,
        max_steps=int(getattr(module, "MAX_STEPS", 30)),
        timeout=float(getattr(module, "TIMEOUT", 600.0)),
        writes=bool(getattr(module, "WRITES", True)),
    )


def load_tasks(root: Path, only: list[str] | None = None) -> list[Task]:
    """Every task under ``root``, in report order.

    A directory that will not load raises rather than being passed over. A
    benchmark that quietly runs eleven of twelve tasks reports a number for a
    suite that does not exist.
    """
    found: list[Task] = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.name.startswith("_"):
            continue
        if only and directory.name not in only and \
                not any(directory.name.startswith(f"{pick}") for pick in only):
            continue
        found.append(load_task(directory))
    return sorted(found, key=lambda task: task.sort_key)


# --------------------------------------------------------------------------- #
# helpers the judges use
# --------------------------------------------------------------------------- #


def _import(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TaskError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: Never counted as a change. These are made by running the tests, not by the
#: agent, and a task that fails because pytest left a cache behind is measuring
#: pytest.
NOISE = {"__pycache__", ".pytest_cache", ".comodor", ".git", ".ruff_cache"}


def _files(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in NOISE for part in relative.parts):
            continue
        try:
            found[relative.as_posix()] = path.read_bytes()
        except OSError:
            continue
    return found


def _differences(before: Path, after: Path) -> set[str]:
    was, now = _files(before), _files(after)
    changed = {name for name in was.keys() & now.keys() if was[name] != now[name]}
    return changed | (was.keys() ^ now.keys())
