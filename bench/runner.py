"""Running one task, several times, without touching anything of the user's.

Everything here is about isolation. A benchmark that shares state with the
machine it runs on measures the machine, and a benchmark whose runs share state
with each other measures the order they ran in.

Four things are separated, and each was a way to get a wrong number:

*The workspace.* A fresh copy of the task's ``repo/`` per attempt, in a
temporary directory that is kept when the attempt fails so the failure can be
looked at.

*The configuration and the brain.* ``COMODOR_HOME`` points into the temporary
directory, so nothing reads or writes the config, the lessons or the session
history of whoever is running this.

*The learning engine.* Switched off. It is the feature that makes Comodor
better on the second run than the first, which is exactly what a reproducible
measurement cannot have.

*The clock.* A hard timeout per attempt, enforced by killing the process. An
agent that has wedged must be reported as a failure at a known cost, not waited
on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .task import Attempt, Task, Verdict

#: What a run is given to spend before it is stopped, whatever the task's own
#: step budget says. A ceiling on the bill, not on the work.
COST_CEILING = 1.00

#: The working tree's `src/`, put ahead of everything on the subprocess's path.
#: A benchmark that measures an installed copy is measuring whatever somebody
#: last installed, which is the one thing it must never do.
SOURCE = Path(__file__).resolve().parent.parent / "src"


@dataclass
class Outcome:
    """Every attempt at one task, and what they add up to."""

    task: Task
    verdicts: list[Verdict] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for verdict in self.verdicts if verdict.passed)

    @property
    def tries(self) -> int:
        return len(self.verdicts)

    @property
    def rate(self) -> str:
        return f"{self.passed}/{self.tries}"

    @property
    def cost(self) -> float:
        return sum(attempt.cost_usd for attempt in self.attempts)

    @property
    def seconds(self) -> float:
        return sum(attempt.elapsed for attempt in self.attempts)

    @property
    def steps(self) -> float:
        if not self.attempts:
            return 0.0
        return sum(attempt.steps for attempt in self.attempts) / len(self.attempts)

    def why(self) -> str:
        """The first reason it failed, which is the one worth reading."""
        for verdict in self.verdicts:
            if not verdict.passed:
                return verdict.reason
        return ""


def run_task(task: Task, *, provider: str, model: str, tries: int = 3,
             keep: Path | None = None, say=print) -> Outcome:
    outcome = Outcome(task=task)
    for attempt_number in range(1, tries + 1):
        attempt, verdict, workspace = _one(task, provider, model, keep)
        outcome.attempts.append(attempt)
        outcome.verdicts.append(verdict)
        if not verdict.passed:
            outcome.kept.append(str(workspace))
        mark = "pass" if verdict.passed else "FAIL"
        say(f"    {attempt_number}/{tries}  {mark}  "
            f"{attempt.steps} steps  {attempt.elapsed:.0f}s  "
            f"${attempt.cost_usd:.3f}"
            + (f"  — {verdict.reason}" if not verdict.passed else ""))
    return outcome


def _one(task: Task, provider: str, model: str,
         keep: Path | None) -> tuple[Attempt, Verdict, Path]:
    root = Path(tempfile.mkdtemp(prefix=f"comodor-bench-{task.name}-"))
    workspace = root / "work"
    home = root / "home"
    shutil.copytree(task.repo, workspace)
    home.mkdir()
    _settings(home, task)

    attempt = _invoke(task, workspace, home, provider, model)

    try:
        verdict = task.check(attempt)
    except Exception as problem:
        # A judge that throws is a broken judge, and reporting that as a failed
        # task would blame the agent for it.
        verdict = Verdict.no(f"the judge raised {type(problem).__name__}: {problem}")

    if verdict.passed:
        shutil.rmtree(root, ignore_errors=True)
    elif keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        moved = keep / f"{task.name}-{int(time.time())}"
        shutil.move(str(root), str(moved))
        return attempt, verdict, moved
    return attempt, verdict, root


def _settings(home: Path, task: Task) -> None:
    """The config this attempt runs under, written into its own empty home.

    Three of these are what make the number mean something.

    `learning.enabled` is off: the brain is the feature that makes the second
    run better than the first, and a measurement cannot have that.

    `max_cost_usd` is a real ceiling. A task that goes wrong on a metered model
    goes wrong at a known price rather than an open-ended one.

    `mode` follows the task: a `find` task runs in plan mode, where the write
    tools are not merely refused but absent, so it cannot be passed by
    rewriting the thing it was asked to look at.
    """
    settings = {
        "agent": {
            "mode": "act" if task.writes else "plan",
            "max_steps": task.max_steps,
            "max_seconds": task.timeout,
            "max_cost_usd": COST_CEILING,
        },
        "learning": {"enabled": False},
    }
    (home / "config.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8")


def _invoke(task: Task, workspace: Path, home: Path,
            provider: str, model: str) -> Attempt:
    """One `comodor run`, in its own process with its own everything."""
    environment = dict(os.environ)
    environment.update({
        "COMODOR_HOME": str(home),
        "COMODOR_PROVIDER": provider,
        "COMODOR_MODEL": model,
        # The tree, not whatever happens to be installed. Without this the
        # benchmark silently measured a copy in site-packages from a fortnight
        # earlier — a number about code nobody was working on, and nothing
        # about it looked wrong.
        "PYTHONPATH": os.pathsep.join(
            [str(SOURCE)] + ([os.environ["PYTHONPATH"]]
                             if os.environ.get("PYTHONPATH") else [])),
        # Rich would otherwise decide from a pipe that it is talking to a
        # terminal of unknown width and wrap the JSON.
        "COLUMNS": "200",
        "NO_COLOR": "1",
    })

    command = [sys.executable, "-m", "comodor", "run", task.prompt, "--json",
               "--max-steps", str(task.max_steps)]
    if task.writes:
        command.append("--yes")

    started = time.monotonic()
    try:
        finished = subprocess.run(
            command, cwd=workspace, env=environment, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=task.timeout,
        )
    except subprocess.TimeoutExpired:
        return Attempt(workspace=workspace, ok=False, stopped="timeout", text="",
                       steps=0, elapsed=time.monotonic() - started,
                       error=f"no answer within {task.timeout:.0f}s")

    elapsed = time.monotonic() - started
    report = _parse(finished.stdout)
    if report is None:
        return Attempt(workspace=workspace, ok=False, stopped="unreadable",
                       text=finished.stdout[-2000:], steps=0, elapsed=elapsed,
                       error=(finished.stderr or "no JSON on stdout")[-2000:])

    usage = report.get("usage") or {}
    return Attempt(
        workspace=workspace,
        ok=bool(report.get("ok")),
        stopped=str(report.get("stopped", "")),
        text=str(report.get("text", "")),
        steps=int(report.get("steps", 0)),
        tools=[str(name) for name in report.get("tools", [])],
        cost_usd=float(usage.get("cost_usd", 0.0)),
        elapsed=elapsed,
        error=str(report.get("error", "")),
    )


def _parse(stdout: str) -> dict | None:
    """The JSON document, even when something printed before it.

    A warning on stdout from a library the agent imported would otherwise turn
    a completed task into an unreadable one, which reads in the report as the
    agent's failure rather than a stray line.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except ValueError:
            start = text.find("{", start + 1)
    return None
