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
import shutil
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
    #: The paired-report figures (spec 002, SC-036): what the model read,
    #: what it wrote, what the provider served from cache, and how many
    #: tool calls the turn made. Zero when the run reported nothing.
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    tool_calls: int = 0
    #: The structured clarification outcome, when the turn stopped needing a
    #: decision (`stopped: "clarification_required"`). Carries
    #: `clarification.outcome` (cancelled | expired | unattended) and the
    #: decisions that stayed open (spec 002, T148; FR-123).
    clarification: dict[str, Any] = field(default_factory=dict)
    #: The turn's measurement record: counts only (FR-072, FR-074), as the
    #: headless JSON reports it. `clarifications_raised`, `corrections` and
    #: `validation_outcome` feed the paired report (T153).
    measurement: dict[str, Any] = field(default_factory=dict)
    #: For a sequence step, whether the step produced what it had to (its
    #: `expect`). Checked while the workspace exists; the report reads this
    #: rather than the removed workspace.
    success: bool = False

    @property
    def outcome(self) -> str:
        """The clarification outcome, or the turn's own stop reason."""
        return str(self.clarification.get("outcome") or self.stopped)

    @property
    def clarifications_raised(self) -> int:
        return int(self.measurement.get("clarifications_raised", 0) or 0)

    @property
    def corrections(self) -> int:
        return int(self.measurement.get("corrections", 0) or 0)

    @property
    def validation_outcome(self) -> str:
        return str(self.measurement.get("validation_outcome", "") or "")

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.cached_tokens + self.output_tokens

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
class SequenceStep:
    """One task in a same-project sequence.

    A sequence runs several prompts against one workspace and one home, so the
    durable brain carries forward while each turn's conversation is fresh.
    `expect` says what the step must have produced (`path` holding `marker`),
    and `interaction` is what a person does with any form this step raises.
    """

    prompt: str
    interaction: tuple[Any, ...] = ()
    expect: dict[str, str] = field(default_factory=dict)


@dataclass
class SequenceResult:
    """What a run of a sequence produced, with the window comparison."""

    task: "Task"
    steps: list[SequenceStep]
    attempts: list[Attempt]

    @property
    def comparable(self) -> bool:
        """Whether the six inputs are the same shape, so the run is valid.

        Same number of steps and attempts, every step asking for work on the
        same artifact, and every step with a prompt and something to check. An
        incomparable sequence is not a pass or a fail — it is not a
        measurement (SC-021).
        """
        if len(self.steps) != len(self.attempts) or len(self.steps) < 2:
            return False
        paths = {step.expect.get("path", "") for step in self.steps}
        return len(paths) == 1 and all(
            step.prompt.strip() and step.expect.get("path")
            and step.expect.get("marker") for step in self.steps)

    def _aggregate(self, attempts: list[Attempt]) -> dict[str, int]:
        """The SC-021 totals for one window: the two primary metrics and success."""
        return {
            "clarifications": sum(attempt.clarifications_raised for attempt in attempts),
            "corrections": sum(attempt.corrections for attempt in attempts),
            "success": sum(1 for attempt in attempts if attempt.success),
            "tasks": len(attempts),
        }

    def windows(self) -> dict[str, dict[str, int]]:
        """The initial (first half) and learned (second half) aggregates."""
        half = len(self.attempts) // 2
        return {
            "initial": self._aggregate(self.attempts[:half]),
            "learned": self._aggregate(self.attempts[half:]),
        }


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
    #: What a person would do with each clarification form, in order, for the
    #: headless run: `"answer"` (an object may carry a `value`), `"cancel"`,
    #: `"expire"` or `"unattended"`. Empty means the old behaviour — nobody is
    #: there, so every form is unattended (spec 002, T149/T150).
    interaction: tuple[Any, ...] = ()
    #: A same-project sequence (T152). Non-empty means this task runs its
    #: steps against one workspace and one home rather than a single prompt.
    sequence: tuple[SequenceStep, ...] = ()
    #: The sequence's judge, given the whole `SequenceResult`.
    check_sequence: Callable[[SequenceResult], Verdict] | None = None
    #: The user side of a correction, given `(index, attempt, workspace)`,
    #: called after a step. It performs the edit a person would have made and
    #: returns whether one happened; the next step's learning detects it
    #: through the real correction path.
    correct: Callable[[int, Attempt, Path], bool] | None = None

    @property
    def sort_key(self) -> tuple[int, str]:
        order = CATEGORIES.index(self.category) if self.category in CATEGORIES \
            else len(CATEGORIES)
        return (order, self.name)


class TaskError(Exception):
    """A task directory that cannot be loaded. Never silently skipped."""


def _interactions(value: Any) -> tuple[Any, ...]:
    """A scenario's scripted interactions, normalised to a tuple.

    A single action string is one interaction; a list or tuple is used as
    written. Each entry must be a string or an object with an `action`, so a
    typo is caught when the task loads rather than mid-run.
    """
    if not value:
        return ()
    entries = (value,) if isinstance(value, str) else tuple(value)
    for entry in entries:
        if isinstance(entry, str):
            continue
        if isinstance(entry, dict) and entry.get("action"):
            continue
        raise TaskError(f"INTERACTION entry {entry!r} is not an action")
    return entries


def _sequence(value: Any) -> tuple[SequenceStep, ...]:
    """A scenario's same-project sequence, validated when the task loads."""
    if not value:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TaskError("SEQUENCE must be a list of steps")
    steps: list[SequenceStep] = []
    for entry in value:
        if not isinstance(entry, dict) or not str(entry.get("prompt", "")).strip():
            raise TaskError(f"SEQUENCE step {entry!r} needs a prompt")
        expect = entry.get("expect") or {}
        steps.append(SequenceStep(
            prompt=str(entry["prompt"]),
            interaction=_interactions(entry.get("interaction", ())),
            expect={str(key): str(val) for key, val in dict(expect).items()},
        ))
    return tuple(steps)


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
    sequence = _sequence(getattr(module, "SEQUENCE", ()))
    check_sequence = getattr(module, "check_sequence", None)

    if sequence:
        if not callable(check_sequence):
            raise TaskError(f"{directory.name}: a SEQUENCE needs a "
                            f"check_sequence(result)")
    elif not callable(judge):
        raise TaskError(f"{directory.name}: check.py defines no check(attempt)")

    category = str(getattr(module, "CATEGORY", "")).strip()
    if category not in CATEGORIES:
        raise TaskError(f"{directory.name}: CATEGORY must be one of "
                        f"{', '.join(CATEGORIES)}, not {category!r}")

    correct = getattr(module, "correct", None)
    return Task(
        name=directory.name,
        category=category,
        prompt=prompt,
        repo=repo,
        check=judge if callable(judge) else _no_single_check,
        max_steps=int(getattr(module, "MAX_STEPS", 30)),
        timeout=float(getattr(module, "TIMEOUT", 600.0)),
        writes=bool(getattr(module, "WRITES", True)),
        interaction=_interactions(getattr(module, "INTERACTION", ())),
        sequence=sequence,
        check_sequence=check_sequence if callable(check_sequence) else None,
        correct=correct if callable(correct) else None,
    )


def _no_single_check(attempt: Attempt) -> Verdict:
    return Verdict.no("this is a sequence task; judge it with check_sequence")


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


def fresh_copy(repo: Path, workspace: Path) -> Path:
    """A task's starting state, without anything a previous run left in it.

    `NOISE` was only ever consulted when *comparing* two trees, so the copy
    itself carried whatever was on disk — and running the suite in a task
    repository leaves `__pycache__` in it. The attempt then started from a
    state that depended on what somebody had run there recently: stale
    bytecode for a module the task is about, which pytest may or may not
    decide to reuse. It showed up as one intermittent failure per run, in a
    different test each time.

    The starting state has to be the files in git and nothing else, or the
    benchmark is measuring the developer's disk.
    """
    shutil.copytree(repo, workspace,
                    ignore=shutil.ignore_patterns(*NOISE))
    return workspace


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
