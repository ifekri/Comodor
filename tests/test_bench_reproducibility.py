"""Benchmark reproducibility is built in, not promised (T157; SC-026, FR-064).

Each attempt runs in a workspace and a COMODOR_HOME of its own, learning is an
explicit written mode (never something the run happens to pick up from disk),
and results are reported as rates across repeated attempts rather than single
booleans. Two attempts with the same inputs get the same measurement inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

from bench import baseline, report, runner
from bench.runner import Outcome, _settings
from bench.task import Attempt, Task, Verdict


def _task(tmp_path) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Task(name="iso", category="fix", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok())


def test_the_learning_mode_is_written_explicitly(tmp_path):
    """On and off are both written; neither is inferred from what is on disk."""
    task = _task(tmp_path)
    for learning in (False, True):
        home = tmp_path / f"home-{learning}"
        home.mkdir()
        _settings(home, task, learning=learning)
        written = json.loads((home / "config.json").read_text(encoding="utf-8"))
        assert written["learning"]["enabled"] is learning


def test_two_identical_settings_are_byte_identical(tmp_path):
    """The same mode, the same inputs: the same measurement inputs."""
    task = _task(tmp_path)
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    _settings(first, task, strategy=baseline.CURRENT)
    _settings(second, task, strategy=baseline.CURRENT)
    assert (first / "config.json").read_bytes() == (second / "config.json").read_bytes()


def test_each_attempt_gets_a_workspace_and_home_of_its_own(monkeypatch, tmp_path):
    """Isolation per attempt: a fresh workspace and a fresh home, every time."""
    task = _task(tmp_path)
    seen: list[tuple[Path, Path]] = []

    def fake_invoke(task, workspace, home, provider, model):
        seen.append((workspace, home))
        return Attempt(workspace=workspace, ok=True, stopped="done",
                       text="done", steps=1)

    monkeypatch.setattr(runner, "_invoke", fake_invoke)
    runner._one(task, "fake", "m", None)
    runner._one(task, "fake", "m", None)

    first, second = seen
    assert first[0] != second[0], "the two attempts shared a workspace"
    assert first[1] != second[1], "the two attempts shared a home"


def test_results_are_rates_not_single_booleans(tmp_path):
    task = _task(tmp_path)
    outcome = Outcome(task=task, verdicts=[Verdict.ok(), Verdict.no("one failed")],
                      attempts=[
                          Attempt(workspace=tmp_path, ok=True, stopped="done",
                                  text="ok", steps=1),
                          Attempt(workspace=tmp_path, ok=False, stopped="done",
                                  text="no", steps=2),
                      ])
    assert outcome.rate == "1/2"

    body = report.as_json([outcome], provider="fake", model="m", tries=2)
    row = body["tasks"][0]
    assert row["result"] == "1/2"
    assert row["passed"] == 1 and row["tries"] == 2
    assert row["correctness"] == 0.5


def test_the_paired_record_carries_the_quality_counts(tmp_path):
    """A token figure is published with its outcome, clarifications and
    corrections beside it (T153; FR-076)."""
    task = _task(tmp_path)
    attempt = Attempt(
        workspace=tmp_path, ok=True, stopped="done", text="done", steps=1,
        input_tokens=100, output_tokens=50, cached_tokens=200, tool_calls=4,
        measurement={"clarifications_raised": 1, "corrections": 1,
                     "validation_outcome": "annotate"},
        clarification={"outcome": "unattended", "decision": "Which?"})
    outcome = Outcome(task=task, verdicts=[Verdict.ok()], attempts=[attempt])

    row = report.as_json([outcome], provider="fake", model="m", tries=1)["tasks"][0]
    assert row["mean_total_tokens"] == 350
    assert row["clarifications"] == 1
    assert row["corrections"] == 1
    assert row["validation"] == {"annotate": 1}


def test_written_tokens_are_carried_and_counted(monkeypatch, tmp_path):
    """Cache-creation tokens are part of the prompt and of the total.

    A provider that bills cache creation reports it separately from input and
    cached; a total that omits it understates what the model read.
    """
    payload = {
        "ok": True, "stopped": "done", "text": "done", "steps": 1,
        "tools": [], "tool_calls": 0,
        "usage": {"input_tokens": 10, "output_tokens": 5, "cached_tokens": 20,
                  "written_tokens": 7, "cost_usd": 0.0},
    }

    class Finished:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Finished())

    task = _task(tmp_path)
    attempt = runner._invoke(task, tmp_path / "ws", tmp_path / "home", "fake", "m")
    assert attempt.written_tokens == 7
    assert attempt.total_tokens == 10 + 20 + 7 + 5

    outcome = Outcome(task=task, verdicts=[Verdict.ok()], attempts=[attempt])
    row = report.as_json([outcome], provider="fake", model="m", tries=1)["tasks"][0]
    assert row["mean_written_tokens"] == 7
