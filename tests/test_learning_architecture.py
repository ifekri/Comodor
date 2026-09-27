"""Structural conventions learned from the repository (T108; FR-107).

A `layout.*` rule is counted from more than one place — a package directory
and its files, a tests directory and what it holds — never inferred from a
single file. Its fingerprint covers the directory structure by name, so
moving what it describes marks it stale; editing a file inside does not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from comodor.learning import BrainStore
from comodor.learning import rules as rules_module
from comodor.learning.memory import stale_by_fingerprint
from comodor.learning.signals import SignalDetector


def _project(root: Path) -> Path:
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_b.py").write_text("def test_b():\n    pass\n", encoding="utf-8")
    (root / "packages" / "one").mkdir(parents=True)
    (root / "packages" / "one" / "package.json").write_text("{}", encoding="utf-8")
    (root / "packages" / "two").mkdir()
    (root / "packages" / "two" / "package.json").write_text("{}", encoding="utf-8")
    (root / "apps" / "app").mkdir(parents=True)
    return root


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


def _scan(store, root):
    detector = SignalDetector(store, checkpoints=None, scope="project:p")
    return detector.scan_project(root)


def test_a_structure_seen_in_more_than_one_place_becomes_a_rule(brain, tmp_path):
    root = _project(tmp_path / "project")
    _scan(brain, root)
    layout = [rule for rule in brain.all_rules() if rule.key.startswith("layout.")]
    assert layout, "a repository with a real structure yields layout rules"
    src = next(rule for rule in layout if rule.key == "layout.src")
    assert src.provenance == "counted_convention"
    assert src.fingerprint == rules_module.structure_fingerprint(root)


def test_a_structure_inferred_from_a_single_file_is_not_a_rule(brain, tmp_path):
    root = tmp_path / "tiny"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_only.py").write_text("def test():\n    pass\n", encoding="utf-8")
    _scan(brain, root)
    assert [rule.key for rule in brain.all_rules() if rule.key.startswith("layout.")] == []


def test_moving_the_structure_marks_the_rule_stale(brain, tmp_path):
    root = _project(tmp_path / "project")
    _scan(brain, root)
    src = next(rule for rule in brain.all_rules() if rule.key == "layout.src")
    assert src.lifecycle == "active"

    (root / "src").rename(root / "lib")
    marked = stale_by_fingerprint(brain, root, ["project:p"])
    assert any(item["id"] == src.id for item in marked)
    moved = next(rule for rule in brain.all_rules() if rule.id == src.id)
    assert moved.lifecycle == "stale"
    assert moved not in brain.confident_rules(["project:p"])


def test_editing_a_file_inside_the_structure_does_not_mark_it_stale(brain, tmp_path):
    root = _project(tmp_path / "project")
    _scan(brain, root)
    before = {rule.key: rule.fingerprint for rule in brain.all_rules()
              if rule.key.startswith("layout.")}
    (root / "src" / "pkg" / "__init__.py").write_text("# a comment\n", encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, ["project:p"], tables=("rules",))
    assert marked == [], "an edit inside a directory is not a move of it"
    after = {rule.key: rule.fingerprint for rule in brain.all_rules()
             if rule.key.startswith("layout.")}
    assert before == after


def test_a_repos_structure_that_is_unchanged_is_never_marked(brain, tmp_path):
    root = _project(tmp_path / "project")
    _scan(brain, root)
    assert stale_by_fingerprint(brain, root, ["project:p"], tables=("rules",)) == []
