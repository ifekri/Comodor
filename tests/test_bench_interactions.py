"""Interactive benchmarks, and the data they carry into the report (T149/T150).

The runner automates the *user side* of a clarification — answer, cancel,
expire, unattended — while the product still raises the form, runs the
lifecycle and produces the outcome. These tests prove the harness contract and
the judge honesty; the end-to-end lifecycle is proven against the real headless
run in `tests/test_headless.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench import integrity, runner
from bench.task import Attempt, Task, Verdict, load_task, load_tasks

TASKS = Path(__file__).resolve().parents[1] / "bench" / "tasks"

CANCELLED = TASKS / "careful-cancelled"
EXPIRED = TASKS / "careful-expired"


def an_attempt(workspace: Path, **fields) -> Attempt:
    defaults = {"ok": False, "stopped": "clarification_required", "text": "",
                "steps": 3, "tools": ["read_file", "ask"],
                "clarification": {"outcome": "cancelled"}}
    defaults.update(fields)
    return Attempt(workspace=workspace, **defaults)


@pytest.fixture
def copy_of(tmp_path):
    from bench.task import fresh_copy

    def make(name: str) -> Path:
        workspace = tmp_path / name
        fresh_copy(TASKS / name / "repo", workspace)
        return workspace
    return make


# --------------------------------------------------------------------------- #
# the cancellation judge (T149)
# --------------------------------------------------------------------------- #


def test_a_dismissal_passes_the_cancellation_task(copy_of):
    verdict = load_task(CANCELLED).check(an_attempt(copy_of("careful-cancelled")))
    assert verdict.passed, verdict.reason


def test_a_chosen_target_fails_the_cancellation_task(copy_of):
    workspace = copy_of("careful-cancelled")
    (workspace / "release.py").write_text(
        'TARGET = "production"\n', encoding="utf-8")
    verdict = load_task(CANCELLED).check(an_attempt(workspace))
    assert not verdict.passed
    assert "production" in verdict.reason


def test_a_cancelled_turn_is_refused_as_a_dismissal(copy_of):
    """`stopped = "cancelled"` is the whole run stopping, never a dismissed
    question (contracts §C5)."""
    verdict = load_task(CANCELLED).check(an_attempt(
        copy_of("careful-cancelled"), stopped="cancelled"))
    assert not verdict.passed
    assert "cancelled" in verdict.reason


def test_re_asking_a_cancelled_decision_fails(copy_of):
    verdict = load_task(CANCELLED).check(an_attempt(
        copy_of("careful-cancelled"), tools=["ask", "read_file", "ask"]))
    assert not verdict.passed
    assert "again" in verdict.reason


def test_an_expiry_is_not_a_cancellation(copy_of):
    verdict = load_task(CANCELLED).check(an_attempt(
        copy_of("careful-cancelled"), clarification={"outcome": "expired"}))
    assert not verdict.passed
    assert "cancelled" in verdict.reason


# --------------------------------------------------------------------------- #
# the expiry judge (T150)
# --------------------------------------------------------------------------- #


def test_an_expiry_passes_the_expiry_task(copy_of):
    verdict = load_task(EXPIRED).check(an_attempt(
        copy_of("careful-expired"), clarification={"outcome": "expired"}))
    assert verdict.passed, verdict.reason


def test_a_dismissal_is_not_an_expiry(copy_of):
    verdict = load_task(EXPIRED).check(an_attempt(
        copy_of("careful-expired"), clarification={"outcome": "cancelled"}))
    assert not verdict.passed
    assert "expired" in verdict.reason


def test_a_guessed_target_fails_the_expiry_task(copy_of):
    workspace = copy_of("careful-expired")
    (workspace / "release.py").write_text('TARGET = "staging"\n', encoding="utf-8")
    verdict = load_task(EXPIRED).check(an_attempt(
        workspace, clarification={"outcome": "expired"}))
    assert not verdict.passed
    assert "staging" in verdict.reason


def test_the_two_scenarios_declare_their_interaction():
    assert load_task(CANCELLED).interaction == ("cancel",)
    assert load_task(EXPIRED).interaction == ("expire",)


# --------------------------------------------------------------------------- #
# the lifecycle reaches the attempt and the report (item 5, T153)
# --------------------------------------------------------------------------- #


def test_the_runner_carries_the_clarification_into_the_attempt(monkeypatch, tmp_path):
    payload = {
        "ok": False, "stopped": "clarification_required", "text": "needs a decision",
        "steps": 2, "tools": ["read_file", "ask"], "tool_calls": 1,
        "clarification": {"kind": "clarification_required", "decision": "Which?",
                          "outcome": "expired"},
        "measurement": {"clarifications_raised": 1, "corrections": 0,
                        "validation_outcome": "clarification_required"},
    }

    class Finished:
        returncode = 0
        stdout = json.dumps(payload)
        stderr = ""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Finished())

    repo = tmp_path / "repo"
    repo.mkdir()
    task = Task(name="t", category="careful", prompt="p", repo=repo,
                check=lambda attempt: Verdict.ok(), interaction=("expire",))
    attempt = runner._invoke(task, tmp_path / "ws", tmp_path / "home", "fake", "m")

    assert attempt.stopped == "clarification_required"
    assert attempt.outcome == "expired"
    assert attempt.clarifications_raised == 1
    assert attempt.validation_outcome == "clarification_required"


# --------------------------------------------------------------------------- #
# fingerprints cover the interaction/sequence semantics (item 14)
# --------------------------------------------------------------------------- #


def test_the_fingerprint_changes_when_an_interaction_changes(tmp_path):
    scenario = tmp_path / "s"
    (scenario / "repo").mkdir(parents=True)
    (scenario / "task.md").write_text("do it\n", encoding="utf-8")
    (scenario / "check.py").write_text(
        "CATEGORY = 'careful'\nINTERACTION = ('cancel',)\n"
        "def check(attempt):\n    return None\n", encoding="utf-8")

    before = integrity.fingerprint(scenario)
    (scenario / "check.py").write_text(
        "CATEGORY = 'careful'\nINTERACTION = ('expire',)\n"
        "def check(attempt):\n    return None\n", encoding="utf-8")
    after = integrity.fingerprint(scenario)

    assert before["check.py"] != after["check.py"], (
        "changing the interaction must change the fingerprint")


def test_the_fingerprint_changes_when_a_sequence_changes(tmp_path):
    scenario = tmp_path / "s"
    (scenario / "repo").mkdir(parents=True)
    (scenario / "task.md").write_text("do it\n", encoding="utf-8")
    body = ("CATEGORY = 'careful'\n"
            "SEQUENCE = [{'prompt': %r, 'expect': {'path': 'x.py', "
            "'marker': 'K'}}]\n"
            "def check_sequence(result):\n    return None\n")
    (scenario / "check.py").write_text(body % "add one", encoding="utf-8")
    before = integrity.fingerprint(scenario)
    (scenario / "check.py").write_text(body % "add a different one", encoding="utf-8")
    after = integrity.fingerprint(scenario)
    assert before["check.py"] != after["check.py"]


# --------------------------------------------------------------------------- #
# ordinary tasks are untouched by the new contract (item 15)
# --------------------------------------------------------------------------- #


def test_existing_tasks_declare_no_interaction_or_sequence():
    legacy = {
        "fix-across-two-files", "fix-crash-on-empty", "fix-off-by-one",
        "fix-wrong-branch", "feature-cli-flag", "feature-retry-decorator",
        "find-the-definition", "find-why-it-fails", "refactor-extract",
        "refactor-rename", "careful-cannot-be-done",
        "careful-only-what-was-asked", "careful-unknowable",
        "careful-repo-settles-it", "careful-unattended",
        "refactor-many-files",
    }
    tasks = {task.name: task for task in load_tasks(TASKS)}
    for name in legacy:
        task = tasks[name]
        assert task.interaction == (), name
        assert task.sequence == (), name
        assert task.check_sequence is None, name
