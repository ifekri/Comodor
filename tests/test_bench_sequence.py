"""The six-task same-project sequence (T152; SC-021).

One project, six comparable tasks: the first three are the initial window, the
last three the learned window. The two primary metrics are the mandatory
clarification count and the user correction count; success must not regress. An
incomparable run is invalid, not passing.
"""

from __future__ import annotations

from pathlib import Path

from bench import report, runner
from bench.task import Attempt, SequenceResult, SequenceStep, Task, Verdict, load_task

TASKS = Path(__file__).resolve().parents[1] / "bench" / "tasks"
REPEAT = TASKS / "learning-repeat"


def _steps(count: int = 6) -> list[SequenceStep]:
    return [SequenceStep(prompt=f"add setting K{index + 1}",
                         expect={"path": "items.py", "marker": f"K{index + 1}"})
            for index in range(count)]


def _attempt(workspace: Path, *, clarifications: int = 0, corrections: int = 0,
             success: bool = True) -> Attempt:
    return Attempt(
        workspace=workspace, ok=True, stopped="done", text="done", steps=1,
        measurement={"clarifications_raised": clarifications,
                     "corrections": corrections},
        success=success)


def _result(workspace: Path, attempts: list[Attempt],
            steps: list[SequenceStep] | None = None) -> SequenceResult:
    task = Task(name="s", category="careful", prompt="p", repo=workspace,
                check=lambda a: Verdict.ok())
    return SequenceResult(task=task, steps=steps or _steps(len(attempts)),
                          attempts=attempts)


# --------------------------------------------------------------------------- #
# window aggregation (items 9, 10, 11)
# --------------------------------------------------------------------------- #


def test_the_windows_aggregate_the_first_and_last_three(tmp_path):
    attempts = [_attempt(tmp_path, clarifications=c, corrections=k)
                for c, k in ((1, 1), (1, 1), (1, 1), (0, 1), (0, 0), (0, 0))]
    windows = _result(tmp_path, attempts).windows()

    assert windows["initial"] == {"clarifications": 3, "corrections": 3,
                                  "success": 3, "tasks": 3}
    assert windows["learned"] == {"clarifications": 0, "corrections": 1,
                                  "success": 3, "tasks": 3}


def test_the_metrics_come_from_the_measurement(tmp_path):
    attempt = _attempt(tmp_path, clarifications=2, corrections=1)
    assert attempt.clarifications_raised == 2
    assert attempt.corrections == 1
    assert attempt.validation_outcome == ""


# --------------------------------------------------------------------------- #
# the SC-021 verdict (items 12, 13)
# --------------------------------------------------------------------------- #


def test_both_metrics_falling_and_success_held_passes(tmp_path):
    attempts = [_attempt(tmp_path, clarifications=1, corrections=1) for _ in range(3)] \
        + [_attempt(tmp_path, clarifications=0, corrections=0) for _ in range(3)]
    verdict = load_task(REPEAT).check_sequence(_result(tmp_path, attempts))
    assert verdict.passed, verdict.reason


def test_a_metric_that_does_not_fall_fails(tmp_path):
    attempts = [_attempt(tmp_path, clarifications=1, corrections=1) for _ in range(3)] \
        + [_attempt(tmp_path, clarifications=1, corrections=0) for _ in range(3)]
    verdict = load_task(REPEAT).check_sequence(_result(tmp_path, attempts))
    assert not verdict.passed
    assert "clarifications" in verdict.reason


def test_a_correctness_regression_fails_even_when_both_metrics_fall(tmp_path):
    attempts = [_attempt(tmp_path, clarifications=1, corrections=1, success=True)
                for _ in range(3)] \
        + [_attempt(tmp_path, clarifications=0, corrections=0, success=False)
           for _ in range(3)]
    verdict = load_task(REPEAT).check_sequence(_result(tmp_path, attempts))
    assert not verdict.passed
    assert "regressed" in verdict.reason


def test_an_incomparable_sequence_is_invalid(tmp_path):
    steps = _steps(6)
    steps[3] = SequenceStep(prompt="something else",
                            expect={"path": "other.py", "marker": "K4"})
    attempts = [_attempt(tmp_path) for _ in range(6)]
    result = _result(tmp_path, attempts, steps)

    assert not result.comparable
    verdict = load_task(REPEAT).check_sequence(result)
    assert not verdict.passed
    assert "not comparable" in verdict.reason


# --------------------------------------------------------------------------- #
# the runner: one project, one brain, fresh conversations (items 7, 8)
# --------------------------------------------------------------------------- #


def _sequence_task(tmp_path: Path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "items.py").write_text("SETTINGS = {}\n", encoding="utf-8")
    steps = tuple(SequenceStep(prompt=f"add setting K{index + 1}",
                               expect={"path": "items.py",
                                       "marker": f"K{index + 1}"})
                  for index in range(6))
    return Task(name="seq", category="careful", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok(), sequence=steps,
                check_sequence=lambda result: Verdict.ok())


def test_the_sequence_uses_one_project_and_one_brain(monkeypatch, tmp_path):
    task = _sequence_task(tmp_path)
    seen: list[dict] = []

    def fake_invoke(task, workspace, home, provider, model, prompt="",
                    interaction=()):
        seen.append({"workspace": workspace, "home": home, "prompt": prompt})
        return _attempt(workspace)

    monkeypatch.setattr(runner, "_invoke", fake_invoke)
    outcome = runner.run_task(task, provider="fake", model="m", tries=1,
                              say=lambda *a, **k: None)

    assert len(seen) == 6, "every step is its own turn"
    assert len({entry["workspace"] for entry in seen}) == 1, "one workspace"
    assert len({entry["home"] for entry in seen}) == 1, "one brain"
    assert [entry["prompt"] for entry in seen] == [step.prompt
                                                   for step in task.sequence]
    assert outcome.attempts and outcome.sequence


def test_a_sequence_run_writes_the_learning_mode_once(monkeypatch, tmp_path):
    """The brain is the same across steps; only transient state is fresh."""
    import json

    task = _sequence_task(tmp_path)
    homes: list[Path] = []
    written: list[dict] = []

    def fake_invoke(task, workspace, home, provider, model, prompt="",
                    interaction=()):
        homes.append(home)
        written.append(json.loads((home / "config.json").read_text(encoding="utf-8")))
        return _attempt(workspace)

    monkeypatch.setattr(runner, "_invoke", fake_invoke)
    runner.run_task(task, provider="fake", model="m", tries=1,
                    learning=True, say=lambda *a, **k: None)

    assert written and all(config["learning"]["enabled"] is True
                           for config in written)
    assert len(set(homes)) == 1


# --------------------------------------------------------------------------- #
# the report carries the sequence record
# --------------------------------------------------------------------------- #


def test_the_report_includes_the_sequence_record(tmp_path):
    attempts = [_attempt(tmp_path, clarifications=1, corrections=1) for _ in range(3)] \
        + [_attempt(tmp_path, clarifications=0, corrections=0) for _ in range(3)]
    task = Task(name="learning-repeat", category="careful", prompt="p",
                repo=tmp_path, check=lambda a: Verdict.ok(),
                sequence=tuple(_steps(6)),
                check_sequence=lambda result: Verdict.ok())
    outcome = runner.Outcome(task=task, verdicts=[Verdict.ok()], attempts=attempts)

    body = report.as_json([outcome], provider="fake", model="m", tries=1)
    record = body["tasks"][0]["sequence"]

    assert record["comparable"] is True
    assert record["windows"]["initial"]["clarifications"] == 3
    assert record["windows"]["learned"]["clarifications"] == 0
    assert record["verdict"] == "pass"
    assert len(record["steps"]) == 6
    assert record["steps"][0]["clarifications"] == 1


def _step_fake(calls):
    """A stand-in for the per-step `comodor run`, so no process starts."""
    def fake(task, workspace, home, provider, model, prompt="", interaction=()):
        calls.append(prompt)
        return Attempt(workspace=workspace, ok=True, stopped="done", text="",
                       steps=1, input_tokens=100, output_tokens=10, cached_tokens=50)
    return fake


def test_a_sequence_honours_the_requested_tries(monkeypatch, tmp_path):
    """`--tries 3` means three whole sequences, not one."""
    task = _sequence_task(tmp_path)
    calls: list = []
    monkeypatch.setattr(runner, "_invoke", _step_fake(calls))
    outcome = runner.run_task(task, provider="fake", model="m", tries=3,
                              say=lambda *a, **k: None)

    assert len(calls) == 18, "three runs of six steps"
    assert len(outcome.verdicts) == 3
    assert len(outcome.sequence_runs()) == 3
    assert [run.attempts[0].sequence_run for run in outcome.sequence_runs()] == [1, 2, 3]


def test_sequence_totals_are_per_run_not_per_step(monkeypatch, tmp_path):
    task = _sequence_task(tmp_path)
    monkeypatch.setattr(runner, "_invoke", _step_fake([]))
    outcome = runner.run_task(task, provider="fake", model="m", tries=2,
                              say=lambda *a, **k: None)

    row = report.as_json([outcome], provider="fake", model="m", tries=2)["tasks"][0]
    # Each step totals 160 tokens (100+50+10); a run of six steps is 960.
    assert row["mean_total_tokens"] == 960
    assert row["sequence"]["runs"] == 2


def test_a_sequence_step_reports_artifact_success_not_exit(monkeypatch, tmp_path):
    """The step's success is whether it produced its artifact, not that the
    process exited cleanly."""
    repo = tmp_path / "repo2"
    repo.mkdir()
    steps = tuple(SequenceStep(prompt=f"add setting K{index + 1}",
                               expect={"path": "items.py",
                                       "marker": f"K{index + 1}"})
                  for index in range(6))
    task = Task(name="seq-artifact", category="careful", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok(), sequence=steps,
                check_sequence=lambda result: Verdict.ok())
    monkeypatch.setattr(runner, "_invoke", _step_fake([]))
    outcome = runner.run_task(task, provider="fake", model="m", tries=1,
                              say=lambda *a, **k: None)
    row = report.as_json([outcome], provider="fake", model="m", tries=1)["tasks"][0]
    assert row["sequence"]["steps"][0]["success"] is False


def test_a_sequence_mean_is_per_run(monkeypatch, tmp_path):
    """A six-step sequence is a whole attempt, not six of them."""
    task = _sequence_task(tmp_path)
    monkeypatch.setattr(runner, "_invoke", _step_fake([]))
    outcome = runner.run_task(task, provider="fake", model="m", tries=2,
                              say=lambda *a, **k: None)

    assert outcome.mean("total_tokens") == 960


def test_a_mixed_sequence_verdict_is_the_first_runs():
    """The per-step block describes the first run; the aggregate is at the task
    level, so a partly-passing sequence is not labelled `pass`."""
    from bench.runner import Outcome
    from bench.task import SequenceStep, Verdict

    steps = [SequenceStep(prompt="add", expect={"path": "items.py", "marker": "K"})]
    task = Task(name="s", category="careful", prompt="p", repo=Path("."),
                check=lambda a: Verdict.ok(), sequence=tuple(steps),
                check_sequence=lambda r: Verdict.ok())
    attempt = Attempt(workspace=Path("."), ok=True, stopped="done", text="",
                      steps=1, sequence_run=1)
    outcome = Outcome(task=task, verdicts=[Verdict.no("the first run failed"),
                                           Verdict.ok()], attempts=[attempt])
    record = report._sequence_record(outcome.sequence_result, outcome, runs=2)

    assert record["verdict"] == "fail"
    assert record["passed_runs"] == 1
    assert record["runs"] == 2
