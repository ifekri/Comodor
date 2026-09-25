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
from typing import Any

from . import baseline
from .task import Attempt, SequenceResult, Task, Verdict, fresh_copy

#: What a run is given to spend before it is stopped, whatever the task's own
#: step budget says. A ceiling on the bill, not on the work.
COST_CEILING = 1.00

#: The working tree's `src/`, put ahead of everything on the subprocess's path.
#: A benchmark that measures an installed copy is measuring whatever somebody
#: last installed, which is the one thing it must never do.
SOURCE = Path(__file__).resolve().parent.parent / "src"

#: How much of a killed child's partial output a timeout diagnostic keeps.
TIMEOUT_DIAGNOSTIC_CHARS = 800


@dataclass
class Outcome:
    """Every attempt at one task, and what they add up to."""

    task: Task
    verdicts: list[Verdict] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    #: Which context strategy the attempts ran under (see `baseline.py`).
    strategy: str = baseline.CURRENT
    #: Whether the learning engine was on for these attempts. Off is the
    #: measurement default; on is the explicit mode the learning scenarios
    #: use, where the brain starts empty in a home of its own every attempt.
    learning: bool = False
    #: Context optimizations switched off for these attempts, by name.
    without: tuple[str, ...] = ()
    #: Whether this ran a same-project sequence rather than one prompt.
    sequence: bool = False
    #: Sequence runs the harness could not measure (a correction hook that
    #: raised). Kept for the report, excluded from pass/fail aggregation.
    invalid: list[str] = field(default_factory=list)
    #: The scenario these attempts were judged by, as `bench.integrity`
    #: fingerprinted it at the start of a paired run (D12). `None` elsewhere.
    scenario_fingerprint: dict | None = None

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

    def mean(self, name: str) -> float:
        """The per-attempt mean of one numeric attempt field.

        For a sequence, an "attempt" is a whole run of its steps, so this is
        the mean of each run's total — not the mean of its steps, which would
        report a six-turn sequence at a sixth of its cost.
        """
        runs = self.sequence_runs()
        if runs:
            return (sum(sum(getattr(step, name) for step in run.attempts)
                        for run in runs) / len(runs))
        if not self.attempts:
            return 0.0
        return sum(getattr(attempt, name) for attempt in self.attempts) / len(self.attempts)

    @property
    def clarifications(self) -> int:
        """Mandatory clarifications raised across the attempts (SC-021)."""
        return sum(attempt.clarifications_raised for attempt in self.attempts)

    @property
    def corrections(self) -> int:
        """User corrections received across the attempts (SC-021)."""
        return sum(attempt.corrections for attempt in self.attempts)

    @property
    def validations(self) -> dict[str, int]:
        """How each attempt's completion gate concluded, tallied."""
        tally: dict[str, int] = {}
        for attempt in self.attempts:
            state = attempt.validation_outcome
            if state:
                tally[state] = tally.get(state, 0) + 1
        return tally

    def sequence_runs(self) -> list[SequenceResult]:
        """One `SequenceResult` per sequence run (`tries` honours the flag).

        A sequence's attempts are its steps, so averaging them as if each were
        an independent try would report per-step figures. Grouping by run keeps
        the window totals a statement about whole sequences.
        """
        if not self.task.sequence:
            return []
        runs: dict[int, list[Attempt]] = {}
        for attempt in self.attempts:
            runs.setdefault(attempt.sequence_run or 1, []).append(attempt)
        return [SequenceResult(task=self.task, steps=list(self.task.sequence),
                               attempts=grouped)
                for _, grouped in sorted(runs.items())]

    @property
    def sequence_result(self) -> SequenceResult | None:
        """The first sequence run, for the per-step block of the report."""
        runs = self.sequence_runs()
        return runs[0] if runs else None

    def why(self) -> str:
        """The first reason it failed, which is the one worth reading.

        With no valid failure, the first invalid run's reason: a task whose
        every attempt the harness could not measure has to say which hook or
        judge broke, or the published report cannot be acted on.
        """
        for verdict in self.verdicts:
            if not verdict.passed:
                return verdict.reason
        return self.invalid[0] if self.invalid else ""


def run_task(task: Task, *, provider: str, model: str, tries: int = 3,
             keep: Path | None = None, say=print,
             strategy: str = baseline.CURRENT, learning: bool = False,
             without: tuple[str, ...] = ()) -> Outcome:
    if task.sequence:
        outcome = Outcome(task=task, strategy=strategy)
        outcome.learning = learning
        outcome.without = tuple(without)
        outcome.sequence = True
        for attempt_number in range(1, tries + 1):
            say(f"  sequence run {attempt_number}/{tries}")
            attempts, verdict, kept = _run_sequence_once(
                task, provider=provider, model=model, keep=keep, say=say,
                strategy=strategy, learning=learning, without=without)
            if verdict.invalid:
                # A harness failure is not agent quality: its steps are not
                # scored, so they never reach the token, cost or clarification
                # aggregates (SC-021). The transcript is kept by the runner.
                outcome.invalid.append(verdict.reason)
                continue
            for step_attempt in attempts:
                step_attempt.sequence_run = attempt_number
            outcome.attempts.extend(attempts)
            outcome.verdicts.append(verdict)
            if not verdict.passed:
                outcome.kept.append(kept)
        return outcome
    outcome = Outcome(task=task, strategy=strategy)
    outcome.learning = learning
    outcome.without = tuple(without)
    for attempt_number in range(1, tries + 1):
        attempt, verdict, workspace = _one(task, provider, model, keep, strategy,
                                           learning, without)
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


def run_paired(tasks: list[Task], *, provider: str, model: str, tries: int = 3,
               keep: Path | None = None, say=print, learning: bool = False,
               checkpoint: Path | None = None
               ) -> tuple[list[Outcome], list[Outcome]]:
    """Both strategies, paired within each `(task, try)` block, counterbalanced.

    Running all of `current` and then all of `naive` confounds the strategy
    with the hour it ran: provider load, cache warmth and the model's own drift
    all move between two long runs. Each block runs both strategies close
    together, and which goes first alternates across blocks, so a pair differs
    by the strategy and little else. Returns `(current, naive)` — the same two
    lists the sequential mode produced, from a fairer experiment.

    The scenarios are fingerprinted once, here, at the start: the same header
    binds the checkpoint and is carried on both arms of every task, so the
    published result names the scenarios the attempts were actually judged by.
    """
    if any(task.sequence for task in tasks):
        raise ValueError("the paired experiment does not take sequence tasks")

    header = _paired_header(provider, model, tries, tasks)
    done: dict[tuple[str, int, str], tuple[Attempt, Verdict, str]] = {}
    if checkpoint is not None:
        saved_header, saved = _read_paired_checkpoint(checkpoint)
        if saved_header is None:
            _write_checkpoint(checkpoint, header)
        else:
            _verify_paired_checkpoint(saved_header, header)
            done = saved

    current = [Outcome(task=task, strategy=baseline.CURRENT) for task in tasks]
    naive = [Outcome(task=task, strategy=baseline.NAIVE) for task in tasks]
    for outcome in (*current, *naive):
        outcome.learning = learning
        outcome.scenario_fingerprint = header["fingerprints"].get(outcome.task.name)

    block = 0
    for index, task in enumerate(tasks):
        for attempt_number in range(1, tries + 1):
            order = (baseline.CURRENT, baseline.NAIVE) if block % 2 == 0 \
                else (baseline.NAIVE, baseline.CURRENT)
            say(f"[block {block + 1}] {task.name} try {attempt_number}: "
                f"{' -> '.join(order)}")
            for strategy in order:
                key = (task.name, attempt_number, strategy)
                if key in done:
                    attempt, verdict, workspace = done[key]
                else:
                    attempt, verdict, workspace = _one(
                        task, provider, model, keep, strategy, learning, ())
                    if checkpoint is not None:
                        _write_checkpoint(checkpoint,
                                          _paired_attempt_record(key, attempt, verdict))
                target = current[index] if strategy == baseline.CURRENT else naive[index]
                target.attempts.append(attempt)
                target.verdicts.append(verdict)
                if not verdict.passed:
                    target.kept.append(str(workspace))
                mark = "pass" if verdict.passed else "FAIL"
                say(f"    {strategy:<7} {mark}  {attempt.steps} steps  "
                    f"{attempt.elapsed:.0f}s  ${attempt.cost_usd:.3f}"
                    + (f"  — {verdict.reason}" if not verdict.passed else ""))
            block += 1
    return current, naive


def _paired_header(provider: str, model: str, tries: int, tasks: list[Task]) -> dict:
    from . import integrity

    fingerprints = integrity.fingerprint_all()
    return {
        "kind": "paired-header",
        "provider": provider,
        "model": model,
        "tries": tries,
        "cohort": [task.name for task in tasks],
        "strategies": list(baseline.STRATEGIES),
        "scheme": "counterbalanced: (task, try) blocks, current-first on even blocks",
        "fingerprints": {task.name: fingerprints.get(task.name) for task in tasks},
    }


def _verify_paired_checkpoint(header: dict, expected: dict) -> None:
    for key in ("provider", "model", "tries", "cohort", "strategies", "scheme"):
        if header.get(key) != expected[key]:
            raise ValueError(
                f"checkpoint {key} does not match this run; refusing to mix "
                f"two experiments")
    if header.get("fingerprints") != expected["fingerprints"]:
        raise ValueError(
            "scenario fingerprints changed since the checkpoint; refusing to "
            "resume a different benchmark")


def _paired_attempt_record(key: tuple[str, int, str], attempt: Attempt,
                           verdict: Verdict) -> dict:
    """One paired cell's full, sanitized evidence, for auditing after the run.

    Everything needed to audit the cell once its temporary workspace is gone:
    the answer, the tools, the clarification, the measurement and the preflight
    trace, plus the token counts. The structures are the agent's own
    already-sanitized output — no prompt body, no file content, no secret is
    added here.
    """
    task, attempt_index, strategy = key
    return {
        "kind": "paired-attempt",
        "task": task,
        "attempt_index": attempt_index,
        "strategy": strategy,
        "passed": bool(verdict.passed),
        "reason": verdict.reason,
        "attempt": {
            "ok": attempt.ok,
            "stopped": attempt.stopped,
            "text": attempt.text,
            "steps": attempt.steps,
            "tools": list(attempt.tools),
            "tool_calls": attempt.tool_calls,
            "elapsed": attempt.elapsed,
            "error": attempt.error,
            "clarification": attempt.clarification,
            "measurement": attempt.measurement,
            "preflight_traces": list(attempt.preflight_traces),
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "cached_tokens": attempt.cached_tokens,
            "written_tokens": attempt.written_tokens,
            "cost_usd": attempt.cost_usd,
        },
    }


def _read_paired_checkpoint(path: Path) -> tuple[
        dict | None, dict[tuple[str, int, str], tuple[Attempt, Verdict, str]]]:
    """The header and every complete paired attempt. A torn last line is dropped."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, {}
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None, {}
    try:
        header = json.loads(lines[0])
    except ValueError:
        return None, {}
    if header.get("kind") != "paired-header":
        return None, {}
    saved: dict[tuple[str, int, str], tuple[Attempt, Verdict, str]] = {}
    for line in lines[1:]:
        try:
            record = json.loads(line)
        except ValueError:
            break                       # an interrupted write: keep what is whole
        if record.get("kind") != "paired-attempt":
            continue
        values = record["attempt"]
        attempt = Attempt(
            workspace=Path("."), ok=bool(values["ok"]), stopped=str(values["stopped"]),
            text=str(values.get("text", "")), steps=int(values["steps"]),
            tools=[str(name) for name in values.get("tools", [])],
            cost_usd=float(values["cost_usd"]),
            elapsed=float(values["elapsed"]), error=str(values.get("error", "")),
            input_tokens=int(values["input_tokens"]),
            output_tokens=int(values["output_tokens"]),
            cached_tokens=int(values["cached_tokens"]),
            written_tokens=int(values.get("written_tokens", 0)),
            tool_calls=int(values.get("tool_calls", 0)),
            clarification=dict(values.get("clarification") or {}),
            measurement=dict(values.get("measurement") or {}),
            preflight_traces=list(values.get("preflight_traces") or []),
        )
        verdict = Verdict.ok() if record["passed"] else Verdict.no(str(record.get("reason", "")))
        saved[(str(record["task"]), int(record["attempt_index"]),
               str(record["strategy"]))] = (attempt, verdict, "")
    return header, saved


def _run_sequence_once(task: Task, *, provider: str, model: str,
                       keep: Path | None, say, strategy: str,
                       learning: bool, without: tuple[str, ...]
                       ) -> tuple[list[Attempt], Verdict, str]:
    """Run every step of a same-project sequence in one workspace and home.

    The workspace is copied once and the home is created once, so the durable
    brain carries from the first task to the sixth while each `comodor run`
    process brings a fresh conversation. A step's scripted correction is
    applied to the workspace *after* it, so the next step's own correction
    detector — the real learning path — notices it. Nothing is written into the
    brain directly.
    """
    attempts: list[Attempt] = []
    root = Path(tempfile.mkdtemp(prefix=f"comodor-bench-{task.name}-"))
    workspace = root / "work"
    home = root / "home"
    fresh_copy(task.repo, workspace)
    home.mkdir()
    # `learning` is the explicit mode the sequence asks for; the brain starts
    # empty in this home and accumulates only what the six steps teach it.
    _settings(home, task, strategy, learning, without)

    broken = ""
    for index, step in enumerate(task.sequence):
        attempt = _invoke(task, workspace, home, provider, model,
                          prompt=step.prompt, interaction=step.interaction)
        attempt.success = _step_met(workspace, step.expect)
        attempts.append(attempt)
        say(f"    {index + 1}/{len(task.sequence)}  "
            f"{'pass' if attempt.ok else 'FAIL'}  {attempt.steps} steps  "
            f"{attempt.elapsed:.0f}s  "
            f"clarif={attempt.clarifications_raised} "
            f"corr={attempt.corrections}"
            + (f"  — {attempt.error}" if attempt.error else ""))
        if task.correct is not None and index < len(task.sequence) - 1:
            try:
                if task.correct(index, attempt, workspace):
                    say(f"         (a correction was made after step {index + 1})")
            except Exception as problem:              # noqa: BLE001 - harness
                # The simulated correction never happened, so the premise of
                # the steps that follow is gone. Not an ordinary agent failure:
                # the run is invalid and is not counted as a pass or a fail.
                broken = (f"the correction hook failed after step {index + 1}: "
                          f"{type(problem).__name__}: {problem}")
                say(f"         (invalid run — {broken})")
                break

    result = SequenceResult(task=task, steps=list(task.sequence),
                            attempts=list(attempts), invalid_reason=broken)
    if broken:
        verdict = Verdict.invalid_run(f"invalid run — {broken}")
    else:
        try:
            verdict = task.check_sequence(result)
        except Exception as problem:
            # A judge that cannot inspect its own fixture is a broken
            # experiment, not an agent failure: the run is invalid.
            verdict = Verdict.invalid_run(
                f"invalid run — the judge raised {type(problem).__name__}: {problem}")
    say(f"    sequence  {'pass' if verdict.passed else 'FAIL'}  — {verdict.reason}")

    if verdict.passed:
        shutil.rmtree(root, ignore_errors=True)
        return attempts, verdict, ""
    _keep_sequence(root, task, result, verdict)
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        moved = keep / f"{task.name}-{int(time.time())}"
        shutil.move(str(root), str(moved))
        return attempts, verdict, str(moved)
    return attempts, verdict, str(root)


def _step_met(workspace: Path, expect: dict[str, str]) -> bool:
    """Whether a sequence step produced the artifact its `expect` names."""
    path = str(expect.get("path") or "")
    marker = str(expect.get("marker") or "")
    if not path or not marker:
        return False
    try:
        text = (workspace / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return marker in text


def _keep_sequence(root: Path, task: Task, result: SequenceResult,
                   verdict: Verdict) -> None:
    """The per-step transcript beside a failed sequence's workspace."""
    try:
        (root / "sequence.json").write_text(json.dumps({
            "task": task.name,
            "verdict": verdict.reason,
            "windows": result.windows(),
            "comparable": result.comparable,
            "invalid_reason": result.invalid_reason,
            "steps": [
                {"prompt": step.prompt,
                 "stopped": attempt.stopped,
                 "outcome": attempt.outcome,
                 "tools": attempt.tools,
                 "answer": attempt.text,
                 "clarifications": attempt.clarifications_raised,
                 "corrections": attempt.corrections,
                 "error": attempt.error}
                # An invalid run can stop before every step has an attempt;
                # the steps that did run are still worth keeping.
                for step, attempt in zip(result.steps, result.attempts, strict=False)
            ],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _one(task: Task, provider: str, model: str,
         keep: Path | None, strategy: str = baseline.CURRENT,
         learning: bool = False,
         without: tuple[str, ...] = ()) -> tuple[Attempt, Verdict, Path]:
    root = Path(tempfile.mkdtemp(prefix=f"comodor-bench-{task.name}-"))
    workspace = root / "work"
    home = root / "home"
    fresh_copy(task.repo, workspace)
    home.mkdir()
    _settings(home, task, strategy, learning, without)

    attempt = _invoke(task, workspace, home, provider, model)

    try:
        verdict = task.check(attempt)
    except Exception as problem:
        # A judge that throws is a broken judge, and reporting that as a failed
        # task would blame the agent for it.
        verdict = Verdict.no(f"the judge raised {type(problem).__name__}: {problem}")

    if verdict.passed:
        shutil.rmtree(root, ignore_errors=True)
        return attempt, verdict, root

    # What it said, beside what it did. A judge that reads prose can be wrong,
    # and this session proved it twice — once failing a correct answer, once
    # passing a wrong one. Neither was visible from the verdict alone, and the
    # answer that produced it was gone by the time anyone looked. A failure
    # nobody can read is a failure nobody can check.
    _keep_the_answer(root, task, attempt, verdict)

    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        moved = keep / f"{task.name}-{int(time.time())}"
        shutil.move(str(root), str(moved))
        return attempt, verdict, moved
    return attempt, verdict, root


def _keep_the_answer(root: Path, task: Task, attempt: Attempt,
                     verdict: Verdict) -> None:
    """Write the transcript of a failed attempt next to its workspace."""
    try:
        (root / "attempt.json").write_text(json.dumps({
            "task": task.name,
            "category": task.category,
            "prompt": task.prompt,
            "verdict": verdict.reason,
            "stopped": attempt.stopped,
            "steps": attempt.steps,
            "tools": attempt.tools,
            "error": attempt.error,
            "answer": attempt.text,
            "preflight_traces": attempt.preflight_traces,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _settings(home: Path, task: Task, strategy: str = baseline.CURRENT,
              learning: bool = False, without: tuple[str, ...] = ()) -> None:
    """The config this attempt runs under, written into its own empty home.

    Three of these are what make the number mean something.

    `learning.enabled` is an explicit mode, off unless asked for: the brain
    is the feature that makes the second run better than the first, and a
    measurement of the agent cannot have that. A scenario that measures the
    brain itself asks for it on — and still gets an empty brain in a home of
    its own, so what it learns is what the attempt taught it and nothing
    from the machine it runs on. Either way the mode is written into the
    attempt's config, never inferred from what happens to be on disk.

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
            # The context strategy under measurement. The budgets above are
            # the same for every strategy; only how the conversation is
            # assembled differs — see `baseline.py`.
            **baseline.settings(strategy, without),
        },
        "learning": {"enabled": bool(learning)},
    }
    (home / "config.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8")


def _bounded_output(value: Any) -> str:
    """A bounded, single-line excerpt of a child's partial output, or ""."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = " ".join(str(value).split())
    if not text:
        return ""
    if len(text) <= TIMEOUT_DIAGNOSTIC_CHARS:
        return text
    return text[: TIMEOUT_DIAGNOSTIC_CHARS - 1] + "…"


def _timeout_diagnostic(timeout: float,
                        expired: subprocess.TimeoutExpired) -> str:
    """An explicit, bounded note about a child killed at the deadline.

    A bare `TimeoutExpired` is not evidence of a provider failure. The parent
    killed the child and no final JSON was captured; any partial stdout/stderr
    is kept, and the absence of output is stated as absence — never as proof
    that the model did nothing.
    """
    note = f"hard timeout after {timeout:.0f}s; no final JSON captured"
    stdout = _bounded_output(getattr(expired, "stdout", None))
    stderr = _bounded_output(getattr(expired, "stderr", None))
    if stdout:
        note += f"; partial stdout: {stdout}"
    if stderr:
        note += f"; partial stderr: {stderr}"
    return note


def _invoke(task: Task, workspace: Path, home: Path,
            provider: str, model: str, prompt: str = "",
            interaction: tuple[Any, ...] = ()) -> Attempt:
    """One `comodor run`, in its own process with its own everything.

    `prompt` and `interaction` default to the task's own; a sequence passes
    the step's instead, against the same workspace and home.
    """
    prompt = prompt or task.prompt
    interaction = interaction or task.interaction
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

    command = [sys.executable, "-m", "comodor", "run", prompt, "--json",
               "--max-steps", str(task.max_steps)]
    if task.writes:
        command.append("--yes")
    if interaction:
        # What a person would do with each form. The scripted run drives the
        # real ask tool, ledger and loop; only the user side is automated.
        command += ["--interactions", json.dumps(list(interaction))]

    started = time.monotonic()
    try:
        finished = subprocess.run(
            command, cwd=workspace, env=environment, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=task.timeout,
        )
    except subprocess.TimeoutExpired as expired:
        # A hard timeout, not a provider verdict: the child was killed at the
        # deadline and produced no final JSON. Keep whatever partial output
        # arrived, and say plainly that nothing was captured — absence of
        # output is not evidence that the model made no progress.
        return Attempt(workspace=workspace, ok=False, stopped="timeout", text="",
                       steps=0, elapsed=time.monotonic() - started,
                       error=_timeout_diagnostic(task.timeout, expired))

    elapsed = time.monotonic() - started
    report = _parse(finished.stdout)
    if report is None:
        return Attempt(workspace=workspace, ok=False, stopped="unreadable",
                       text=finished.stdout[-2000:], steps=0, elapsed=elapsed,
                       error=(finished.stderr or "no JSON on stdout")[-2000:])

    usage = report.get("usage") or {}
    clarification = report.get("clarification")
    measurement = report.get("measurement")
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
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cached_tokens=int(usage.get("cached_tokens", 0) or 0),
        written_tokens=int(usage.get("written_tokens", 0) or 0),
        tool_calls=int(report.get("tool_calls", 0) or 0),
        clarification=clarification if isinstance(clarification, dict) else {},
        measurement=measurement if isinstance(measurement, dict) else {},
        preflight_traces=list(report.get("preflight_traces") or []),
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


# --------------------------------------------------------------------------- #
# the blocked single-optimization experiment (T096)
# --------------------------------------------------------------------------- #
#
# Running CURRENT in full, then each ablation in full, confounds the switch
# with the time it ran: the provider's cache warmth, its load and the model's
# own drift all move between two 48-attempt runs, and the difference read as
# the switch's effect is mostly the difference between two hours. The
# experiment below runs every configuration **in the same (task, try) block**,
# in a counterbalanced order, so a pair differs by the switch and little else.

@dataclass
class BlockedAttempt:
    """One attempt in the blocked experiment, with where it sat in its block."""

    block: int
    task: str
    attempt_index: int          # 1..tries, the pairing identity within the task
    config: str                 # a name from `baseline.CONFIGURATIONS`
    position: int               # 0..n-1, the order it ran within the block
    attempt: Attempt
    passed: bool = False


@dataclass
class BlockedRun:
    """Every attempt of one blocked experiment, and how to regroup them."""

    provider: str
    model: str
    tries: int
    cohort: list[str]
    configurations: tuple[str, ...] = baseline.CONFIGURATIONS
    attempts: list[BlockedAttempt] = field(default_factory=list)
    #: Set once the run begins, so a stored report records the scheme.
    scheme: str = "counterbalanced: position = (config_index + block_index) % n"

    def blocks(self) -> dict[tuple[str, int], dict[str, BlockedAttempt]]:
        """Attempts grouped by `(task, attempt_index)`, then by configuration."""
        grouped: dict[tuple[str, int], dict[str, BlockedAttempt]] = {}
        for entry in self.attempts:
            grouped.setdefault((entry.task, entry.attempt_index), {})[entry.config] = entry
        return grouped

    @property
    def planned_attempts(self) -> int:
        return len(self.cohort) * self.tries * len(self.configurations)


def run_blocked(tasks: list[Task], *, provider: str, model: str, tries: int = 3,
                keep: Path | None = None, say=print, learning: bool = False,
                checkpoint: Path | None = None) -> BlockedRun:
    """Run every configuration in every `(task, try)` block, counterbalanced.

    Each attempt is a fresh process, workspace and home — the same isolation
    the ordinary runner gives — so a block is seven independent attempts that
    differ only by the switch. Sequence tasks are refused: the experiment's
    unit is a single turn, and a six-turn sequence does not have one.

    `checkpoint` is a JSONL file appended after every attempt, so a run of
    hundreds of paid calls does not repeat its completed blocks after an
    interruption. The first line is a header naming the cohort, configurations
    and scenario fingerprints; a resume whose header or fingerprints no longer
    match is refused rather than silently mixed.
    """
    if any(task.sequence for task in tasks):
        raise ValueError("the blocked experiment does not take sequence tasks")

    run = BlockedRun(provider=provider, model=model, tries=tries,
                     cohort=[task.name for task in tasks])
    done: dict[tuple[int, str], BlockedAttempt] = {}
    if checkpoint is not None:
        header, entries = _read_checkpoint(checkpoint)
        if header is None:
            _write_checkpoint(checkpoint, _header_record(run))
        else:
            _verify_checkpoint(header, run)
            for entry in entries:
                done[(entry.block, entry.config)] = entry
                run.attempts.append(entry)
            say(f"resuming from {checkpoint}: {len(done)} attempt(s) already "
                f"recorded")

    size = len(run.configurations)
    block = 0
    for task in tasks:
        for attempt_index in range(1, tries + 1):
            order = baseline.block_order(block, run.configurations)
            order_text = " -> ".join(run.configurations[index] for index in order)
            say(f"[block {block + 1}/{run.planned_attempts // size}] {task.name} "
                f"try {attempt_index}: {order_text}")
            for config_index in order:
                config = run.configurations[config_index]
                position = (config_index + block) % size
                if (block, config) in done:
                    say(f"    pos {position}  {config:<20} already recorded")
                    continue
                attempt, verdict, workspace = _one(
                    task, provider, model, keep, baseline.CURRENT, learning,
                    baseline.switch_of(config))
                entry = BlockedAttempt(
                    block=block, task=task.name, attempt_index=attempt_index,
                    config=config, position=position, attempt=attempt,
                    passed=verdict.passed)
                run.attempts.append(entry)
                if checkpoint is not None:
                    _write_checkpoint(checkpoint, _attempt_record(entry))
                say(f"    pos {position}  {config:<20} "
                    f"{'pass' if verdict.passed else 'FAIL'}  "
                    f"{attempt.steps} steps  {attempt.elapsed:.0f}s  "
                    f"in={attempt.input_tokens} cached={attempt.cached_tokens} "
                    f"out={attempt.output_tokens}"
                    + (f"  — {verdict.reason}" if not verdict.passed else ""))
            block += 1
    # Canonical order, so a resumed run is byte-for-byte the run it resumes.
    run.attempts.sort(key=lambda entry: (entry.block, entry.position))
    return run


#: The fields of an attempt the checkpoint keeps: everything the paired metrics
#: read, and nothing that is not reproducible (no prompt body, no file content).
def _header_record(run: BlockedRun) -> dict:
    from . import integrity

    fingerprints = integrity.fingerprint_all()
    return {
        "kind": "header",
        "provider": run.provider,
        "model": run.model,
        "tries": run.tries,
        "cohort": list(run.cohort),
        "configurations": list(run.configurations),
        "scheme": run.scheme,
        "fingerprints": {name: fingerprints.get(name) for name in run.cohort},
    }


def _verify_checkpoint(header: dict, run: BlockedRun) -> None:
    expected = _header_record(run)
    for key in ("provider", "model", "tries", "cohort", "configurations", "scheme"):
        if header.get(key) != expected[key]:
            raise ValueError(
                f"checkpoint {key} does not match this run; refusing to mix "
                f"two experiments")
    if header.get("fingerprints") != expected["fingerprints"]:
        raise ValueError(
            "scenario fingerprints changed since the checkpoint; refusing to "
            "resume a different benchmark")


def _attempt_record(entry: BlockedAttempt) -> dict:
    attempt = entry.attempt
    return {
        "kind": "attempt",
        "block": entry.block,
        "task": entry.task,
        "attempt_index": entry.attempt_index,
        "config": entry.config,
        "position": entry.position,
        "passed": entry.passed,
        "attempt": {
            "ok": attempt.ok,
            "stopped": attempt.stopped,
            "steps": attempt.steps,
            "elapsed": attempt.elapsed,
            "input_tokens": attempt.input_tokens,
            "output_tokens": attempt.output_tokens,
            "cached_tokens": attempt.cached_tokens,
            "written_tokens": attempt.written_tokens,
            "cost_usd": attempt.cost_usd,
            "tool_calls": attempt.tool_calls,
            "error": attempt.error,
            "measurement": attempt.measurement,
        },
    }


def _entry_from_record(record: dict) -> BlockedAttempt:
    saved = record["attempt"]
    attempt = Attempt(
        workspace=Path("."), ok=bool(saved["ok"]), stopped=str(saved["stopped"]),
        text="", steps=int(saved["steps"]), cost_usd=float(saved["cost_usd"]),
        elapsed=float(saved["elapsed"]), error=str(saved.get("error", "")),
        input_tokens=int(saved["input_tokens"]),
        output_tokens=int(saved["output_tokens"]),
        cached_tokens=int(saved["cached_tokens"]),
        written_tokens=int(saved.get("written_tokens", 0)),
        tool_calls=int(saved.get("tool_calls", 0)),
        measurement=dict(saved.get("measurement") or {}),
    )
    return BlockedAttempt(
        block=int(record["block"]), task=str(record["task"]),
        attempt_index=int(record["attempt_index"]), config=str(record["config"]),
        position=int(record["position"]), attempt=attempt,
        passed=bool(record["passed"]))


def _write_checkpoint(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_checkpoint(path: Path) -> tuple[dict | None, list[BlockedAttempt]]:
    """The header and every complete attempt line. A torn last line is dropped."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None, []
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None, []
    try:
        header = json.loads(lines[0])
    except ValueError:
        return None, []
    if header.get("kind") != "header":
        return None, []
    entries: list[BlockedAttempt] = []
    for line in lines[1:]:
        try:
            record = json.loads(line)
        except ValueError:
            break                       # an interrupted write: keep what is whole
        if record.get("kind") == "attempt":
            entries.append(_entry_from_record(record))
    return header, entries
