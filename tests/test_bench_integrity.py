"""Scenario fingerprints catch a weakened benchmark (T013, T154; SC-026, FR-077).

The check has to fail for every way a suite can be made easier: a shortened
prompt, a softened judge, a raised budget, a changed starting repository, a
deleted scenario, and a scenario added without being recorded. A lower token
figure obtained by any of these is not a result.
"""

from __future__ import annotations

import shutil
import subprocess
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


def test_a_fingerprint_does_not_depend_on_line_endings(tmp_path):
    """The record is committed once and read on every platform.

    A working tree on Windows can hand a file back with CRLF before the next
    checkout normalises it, and the repository stores LF. If line endings were
    part of the hash, the same scenario would fingerprint differently on two
    platforms and the committed record would only be true where it was written.
    """
    scenario = tmp_path / "s"
    (scenario / "repo").mkdir(parents=True)
    (scenario / "task.md").write_bytes(b"do the thing\r\non two lines\r\n")
    (scenario / "check.py").write_bytes(b"CATEGORY = 'fix'\r\n")
    (scenario / "repo" / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")
    with_crlf = integrity.fingerprint(scenario)

    (scenario / "task.md").write_bytes(b"do the thing\non two lines\n")
    (scenario / "check.py").write_bytes(b"CATEGORY = 'fix'\n")
    (scenario / "repo" / "a.py").write_bytes(b"x = 1\ny = 2\n")
    with_lf = integrity.fingerprint(scenario)

    assert with_crlf == with_lf


# --------------------------------------------------------------------------- #
# history: fingerprint_at and digest (T208; SC-012, D11)
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path):
    """A throwaway repository with two real scenarios under `bench/tasks`."""
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    tasks = repo / "bench" / "tasks"
    tasks.mkdir(parents=True)
    for name in ("careful-unknowable", "fix-off-by-one"):
        shutil.copytree(REAL_TASKS / name, tasks / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "bench" / "runner.py").write_text("# harness\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    first = _commit_all(repo, "first")
    return repo, tasks, first


def test_fingerprint_at_a_commit_equals_fingerprint_all_of_that_tree(history):
    repo, tasks, first = history
    assert integrity.fingerprint_at(first, repo=repo) == integrity.fingerprint_all(tasks)


def test_fingerprint_at_reads_the_commit_not_the_working_tree(history):
    repo, tasks, first = history
    before = integrity.fingerprint_all(tasks)
    (tasks / "fix-off-by-one" / "task.md").write_text("an uncommitted edit\n", encoding="utf-8")
    assert integrity.fingerprint_at(first, repo=repo) == before


def test_fingerprint_at_an_unresolvable_commit_raises(history):
    repo, _, _ = history
    for commit in ("0" * 40, "no-such-ref", "", "--help"):
        with pytest.raises(ValueError):
            integrity.fingerprint_at(commit, repo=repo)


def test_a_digest_does_not_depend_on_key_order():
    one = {"task.md": "a", "check.py": "b", "repo": {"x.py": "1", "y.py": "2"},
           "hidden": {}, "budgets": {"MAX_STEPS": "25", "CATEGORY": "careful"}}
    other = {"budgets": {"CATEGORY": "careful", "MAX_STEPS": "25"}, "hidden": {},
             "repo": {"y.py": "2", "x.py": "1"}, "check.py": "b", "task.md": "a"}
    assert one == other
    assert integrity.digest(one) == integrity.digest(other)
    assert len(integrity.digest(one)) == 64


@pytest.mark.parametrize("edit", ["task.md", "check.py", "repo", "hidden", "budget"])
def test_a_digest_moves_with_every_part_of_a_scenario(history, edit):
    repo, tasks, first = history
    scenario = tasks / "careful-unknowable"
    if edit == "task.md":
        (scenario / "task.md").write_text("a different prompt\n", encoding="utf-8")
    elif edit == "check.py":
        judge = scenario / "check.py"
        judge.write_text(judge.read_text(encoding="utf-8") + "\n# softened\n", encoding="utf-8")
    elif edit == "repo":
        (scenario / "repo" / "added.py").write_text("x = 1\n", encoding="utf-8")
    elif edit == "hidden":
        (scenario / "hidden").mkdir(exist_ok=True)
        (scenario / "hidden" / "answer.txt").write_text("secret\n", encoding="utf-8")
    else:
        judge = scenario / "check.py"
        judge.write_text(judge.read_text(encoding="utf-8").replace("MAX_STEPS = 25",
                                                                   "MAX_STEPS = 60"),
                         encoding="utf-8")
    second = _commit_all(repo, f"change {edit}")
    before = integrity.fingerprint_at(first, repo=repo)
    after = integrity.fingerprint_at(second, repo=repo)
    assert integrity.digest(before["careful-unknowable"]) \
        != integrity.digest(after["careful-unknowable"])
    assert integrity.digest(before["fix-off-by-one"]) \
        == integrity.digest(after["fix-off-by-one"])


def test_a_harness_only_commit_leaves_every_scenario_digest_unchanged(history):
    repo, _, first = history
    (repo / "bench" / "runner.py").write_text("# harness, rewritten\n", encoding="utf-8")
    (repo / "bench" / "report.py").write_text("# new reporting\n", encoding="utf-8")
    second = _commit_all(repo, "harness only")
    before = integrity.fingerprint_at(first, repo=repo)
    after = integrity.fingerprint_at(second, repo=repo)
    assert {name: integrity.digest(fp) for name, fp in before.items()} \
        == {name: integrity.digest(fp) for name, fp in after.items()}
