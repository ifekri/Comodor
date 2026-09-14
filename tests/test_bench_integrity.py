"""Scenario fingerprints catch a weakened benchmark (T013, T154; SC-026, FR-077).

The check has to fail for every way a suite can be made easier: a shortened
prompt, a softened judge, a raised budget, a changed starting repository, a
deleted scenario, and a scenario added without being recorded. A lower token
figure obtained by any of these is not a result.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bench import integrity

REAL_TASKS = Path(__file__).resolve().parents[1] / "bench" / "tasks"


@pytest.fixture
def suite(tmp_path):
    """A copy of two real scenarios, recorded, so edits are against a record."""
    root = tmp_path / "tasks"
    root.mkdir()
    for name in ("careful-unknowable", "fix-off-by-one"):
        shutil.copytree(REAL_TASKS / name, root / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    record = root / "FINGERPRINTS.json"
    integrity.record(root, record)
    return root, record


def test_an_untouched_suite_is_clean(suite):
    root, record = suite
    assert integrity.check(root, record).clean


def test_the_committed_record_matches_the_committed_scenarios():
    drift = integrity.check()
    assert drift.clean, drift.describe()


def test_a_shortened_prompt_is_drift(suite):
    root, record = suite
    prompt = root / "careful-unknowable" / "task.md"
    prompt.write_text(prompt.read_text(encoding="utf-8").splitlines()[0] + "\n",
                      encoding="utf-8")
    drift = integrity.check(root, record)
    assert drift.changed == {"careful-unknowable": ["task.md"]}


def test_a_softened_judge_is_drift(suite):
    root, record = suite
    judge = root / "fix-off-by-one" / "check.py"
    judge.write_text(judge.read_text(encoding="utf-8").replace(
        "def check(", "def check(  # softened\n    attempt=None):\n    pass\n\ndef _old("),
        encoding="utf-8")
    drift = integrity.check(root, record)
    assert "check.py" in drift.changed["fix-off-by-one"]


def test_a_raised_budget_is_named(suite):
    root, record = suite
    judge = root / "careful-unknowable" / "check.py"
    judge.write_text(judge.read_text(encoding="utf-8").replace("MAX_STEPS = 25",
                                                               "MAX_STEPS = 60"),
                     encoding="utf-8")
    drift = integrity.check(root, record)
    what = drift.changed["careful-unknowable"]
    assert any(entry.startswith("budgets: MAX_STEPS '25'") for entry in what), what


def test_a_changed_starting_repository_is_drift(suite):
    root, record = suite
    repo = root / "fix-off-by-one" / "repo"
    target = next(path for path in repo.rglob("*.py"))
    target.write_text(target.read_text(encoding="utf-8") + "\n# hint\n", encoding="utf-8")
    drift = integrity.check(root, record)
    assert any(entry.startswith("repo/") and "edited" in entry
               for entry in drift.changed["fix-off-by-one"])


def test_a_deleted_test_file_in_the_repository_is_drift(suite):
    root, record = suite
    repo = root / "fix-off-by-one" / "repo"
    victim = next(path for path in repo.rglob("test_*.py"))
    victim.unlink()
    drift = integrity.check(root, record)
    assert any("removed" in entry for entry in drift.changed["fix-off-by-one"])


def test_a_deleted_scenario_is_drift(suite):
    root, record = suite
    shutil.rmtree(root / "careful-unknowable")
    drift = integrity.check(root, record)
    assert drift.missing == ["careful-unknowable"]
    assert "deleted" in drift.describe()


def test_an_unrecorded_scenario_is_drift(suite):
    root, record = suite
    shutil.copytree(root / "fix-off-by-one", root / "fix-off-by-two")
    drift = integrity.check(root, record)
    assert drift.unrecorded == ["fix-off-by-two"]


def test_pycache_is_not_part_of_a_fingerprint(suite):
    root, record = suite
    cache = root / "fix-off-by-one" / "repo" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\x00")
    assert integrity.check(root, record).clean


def test_a_missing_record_reports_every_scenario_as_unrecorded(suite):
    root, record = suite
    record.unlink()
    drift = integrity.check(root, record)
    assert drift.unrecorded == ["careful-unknowable", "fix-off-by-one"]


def test_the_command_line_exits_nonzero_on_drift(suite, monkeypatch, capsys):
    root, record = suite
    monkeypatch.setattr(integrity, "TASKS", root)
    monkeypatch.setattr(integrity, "RECORD", record)
    assert integrity.main(["check"]) == 0
    shutil.rmtree(root / "careful-unknowable")
    assert integrity.main(["check"]) == 1
    assert "careful-unknowable" in capsys.readouterr().err


def test_the_runtime_never_imports_the_benchmark_helpers():
    """`bench/integrity.py` and `bench/baseline.py` are harness only."""
    source = Path(__file__).resolve().parents[1] / "src" / "comodor"
    offenders = []
    for path in source.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "bench.integrity" in text or "bench.baseline" in text \
                or "from bench" in text or "import bench" in text:
            offenders.append(path.relative_to(source).as_posix())
    assert offenders == []
