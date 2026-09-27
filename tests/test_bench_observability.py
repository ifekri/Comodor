"""Benchmark observability: a cell must stay auditable after its workspace is gone.

The paired checkpoint used to keep only counts, so a passed attempt — whose
temporary workspace the runner deletes — left no answer, no tools and no
preflight trace to audit. And a killed child was reported as "no answer within
Ns", which reads like a provider verdict when it is only a hard timeout with no
final JSON captured. These pin the evidence and the wording (SC-036, FR-064).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from bench import runner
from bench.task import Attempt, Task, Verdict


def _task(tmp_path, timeout: float = 60.0) -> Task:
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    return Task(name="iso", category="fix", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok(), timeout=timeout)


def _write_pair(path: Path, key: tuple[str, int, str], attempt: Attempt,
                verdict: Verdict) -> None:
    header = {"kind": "paired-header"}
    record = runner._paired_attempt_record(key, attempt, verdict)
    path.write_text(json.dumps(header) + "\n" + json.dumps(record) + "\n",
                    encoding="utf-8")


# --------------------------------------------------------------------------- #
# checkpoint round-trip
# --------------------------------------------------------------------------- #


def test_the_paired_checkpoint_preserves_the_full_attempt(tmp_path):
    attempt = Attempt(
        workspace=tmp_path / "gone", ok=True, stopped="done",
        text="The suite does not pass because postcodes.csv is missing.", steps=5,
        tools=["read_file", "edit_file"], tool_calls=2, elapsed=12.5, error="",
        input_tokens=100, output_tokens=50, cached_tokens=200, written_tokens=7,
        cost_usd=0.0,
        clarification={"outcome": "unattended", "decision": "Which?"},
        measurement={"model_turns": 5, "preflight_calls": 2, "preflight_tokens": 900},
        preflight_traces=[{"tools": ["edit_file"], "withheld": True,
                           "assessment": {"status": "reject"}}],
    )
    path = tmp_path / "paired.checkpoint.jsonl"
    _write_pair(path, ("careful-cannot-be-done", 3, "current"), attempt, Verdict.ok())

    _, saved = runner._read_paired_checkpoint(path)
    restored = saved[("careful-cannot-be-done", 3, "current")][0]

    assert restored.text == attempt.text
    assert restored.tools == attempt.tools
    assert restored.clarification == attempt.clarification
    assert restored.measurement == attempt.measurement
    assert restored.preflight_traces == attempt.preflight_traces
    assert restored.input_tokens == 100
    assert restored.output_tokens == 50
    assert restored.cached_tokens == 200
    assert restored.written_tokens == 7
    assert restored.tool_calls == 2
    assert restored.stopped == "done"
    assert restored.steps == 5
    assert restored.ok is True
    assert restored.error == ""


def test_a_passed_attempt_stays_auditable_after_its_workspace_is_deleted(tmp_path):
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "data.py").write_text("x = 1\n", encoding="utf-8")
    attempt = Attempt(
        workspace=workspace, ok=True, stopped="done",
        text="I could not get the suite green; the dataset is unavailable.", steps=4,
        tools=["read_file", "run_shell"],
        preflight_traces=[{"tools": ["write_file"], "withheld": True,
                           "assessment": {"status": "reject"}}],
    )
    path = tmp_path / "paired.checkpoint.jsonl"
    _write_pair(path, ("careful-cannot-be-done", 1, "current"), attempt, Verdict.ok())

    shutil.rmtree(workspace)
    assert not workspace.exists(), "the workspace should be gone"

    _, saved = runner._read_paired_checkpoint(path)
    restored = saved[("careful-cannot-be-done", 1, "current")][0]
    assert restored.text == attempt.text
    assert restored.tools == attempt.tools
    assert restored.preflight_traces == attempt.preflight_traces


def test_an_older_checkpoint_without_the_new_fields_still_loads(tmp_path):
    """A resume from a pre-observability checkpoint must not crash."""
    path = tmp_path / "paired.checkpoint.jsonl"
    path.write_text(
        json.dumps({"kind": "paired-header"}) + "\n"
        + json.dumps({
            "kind": "paired-attempt", "task": "t", "attempt_index": 1,
            "strategy": "current", "passed": False, "reason": "x",
            "attempt": {"ok": False, "stopped": "timeout", "steps": 0,
                        "elapsed": 1.0, "input_tokens": 0, "output_tokens": 0,
                        "cached_tokens": 0, "written_tokens": 0, "cost_usd": 0.0,
                        "tool_calls": 0, "error": "old", "measurement": {}},
        }) + "\n", encoding="utf-8")

    _, saved = runner._read_paired_checkpoint(path)
    restored = saved[("t", 1, "current")][0]
    assert restored.stopped == "timeout"
    assert restored.text == ""
    assert restored.tools == []
    assert restored.preflight_traces == []


# --------------------------------------------------------------------------- #
# timeout diagnostics
# --------------------------------------------------------------------------- #


def test_a_hard_timeout_is_not_a_provider_error(tmp_path, monkeypatch):
    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="comodor", timeout=420.0, output='{"partial": ', stderr="boom")

    monkeypatch.setattr(runner.subprocess, "run", expire)
    task = _task(tmp_path, timeout=420.0)

    attempt = runner._invoke(task, tmp_path / "ws", tmp_path / "home", "fake", "m")

    assert attempt.stopped == "timeout"
    assert attempt.ok is False
    assert "hard timeout after 420s" in attempt.error
    assert "no final JSON captured" in attempt.error
    assert "partial stdout" in attempt.error and "partial" in attempt.error
    assert "partial stderr" in attempt.error and "boom" in attempt.error
    assert "provider" not in attempt.error.lower()
    assert "transport" not in attempt.error.lower()


def test_a_hard_timeout_without_partial_output_says_so(tmp_path, monkeypatch):
    def expire(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="comodor", timeout=420.0)

    monkeypatch.setattr(runner.subprocess, "run", expire)
    task = _task(tmp_path, timeout=420.0)

    attempt = runner._invoke(task, tmp_path / "ws", tmp_path / "home", "fake", "m")

    assert attempt.stopped == "timeout"
    assert "hard timeout after 420s" in attempt.error
    assert "partial stdout" not in attempt.error
    assert "partial stderr" not in attempt.error
    assert "provider" not in attempt.error.lower()


def test_the_timeout_diagnostic_is_bounded():
    expired = subprocess.TimeoutExpired(cmd="c", timeout=1.0,
                                        output="x" * 5000, stderr="y" * 5000)
    note = runner._timeout_diagnostic(420.0, expired)
    assert len(note) < 3 * runner.TIMEOUT_DIAGNOSTIC_CHARS + 200
