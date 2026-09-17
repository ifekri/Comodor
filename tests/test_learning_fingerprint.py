"""Fingerprint granularity and invalidation (T111, T112; FR-060, FR-114,
FR-112, SC-029, SC-032).

The granularity is chosen from the real shapes: a counted convention is a
tally over a sample, so a change is the cue to *re-count* and the rule goes
stale only when the re-count flips it; a `tool_confirmed` fact is whole-file,
so any change to its file marks it stale; a `user_correction` is a statement
of preference and is never invalidated by an edit. The curator reports the
fingerprint-stale class without deleting anything.
"""

from __future__ import annotations

import pytest

from comodor.learning import BrainStore, curator
from comodor.learning import rules as rules_module
from comodor.learning.memory import stale_by_fingerprint
from comodor.learning.store import Fact, Lesson


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


def _sampled(root, quote):
    files = []
    for index in range(3):
        path = root / f"m{index}.py"
        path.write_text("\n".join(f"v = {quote}text{n}{quote}" for n in range(10)),
                        encoding="utf-8")
        files.append(path)
    return files


def _counted_rule(brain, root, quote):
    files = _sampled(root, quote)
    rule = brain.observe_rule(
        key="quotes.style", scope="project:p", agrees=True, category="style",
        statement="Use single quotes for string literals.", detail="counted from the sample",
        source="observation", weight=10,
        provenance="counted_convention",
        source_ref=rules_module.manifest_ref(root, files),
        fingerprint=rules_module.manifest_fingerprint(files))
    return rule, files


# --------------------------------------------------------------------------- #
# a counted convention: rule-level granularity, re-counted
# --------------------------------------------------------------------------- #


def test_a_change_that_flips_the_count_marks_the_rule_stale(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    rule, _ = _counted_rule(brain, root, "'")
    assert rule.fingerprint and rule.lifecycle == "active"

    _sampled(root, '"')                       # the convention moved
    marked = stale_by_fingerprint(brain, root, ["project:p"])
    assert any(item["id"] == rule.id for item in marked)
    assert brain.all_rules(["project:p"])[0].lifecycle == "stale"


def test_a_change_that_does_not_flip_the_count_refreshes_the_fingerprint(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    rule, files = _counted_rule(brain, root, "'")
    old = rule.fingerprint

    files[0].write_text(files[0].read_text(encoding="utf-8") + "# a comment\n",
                        encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, ["project:p"])
    assert marked == [], "a comment did not change the convention"
    refreshed = brain.all_rules(["project:p"])[0]
    assert refreshed.lifecycle == "active"
    assert refreshed.fingerprint != old and refreshed.fingerprint
    assert refreshed.fingerprint == rules_module.manifest_fingerprint(files)


# --------------------------------------------------------------------------- #
# a tool_confirmed fact: whole-file granularity
# --------------------------------------------------------------------------- #


def test_a_tool_confirmed_fact_goes_stale_when_its_file_changes(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "ci.yml"
    target.write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    fact = brain.add_fact(Fact(
        provenance="tool_confirmed", scope="project:p", kind="memory",
        text="the CI runner is Linux only", status="settled",
        source_ref="read_file:ci.yml",
        fingerprint=rules_module.file_fingerprint(target)))

    assert stale_by_fingerprint(brain, root, ["project:p"]) == []
    target.write_text("runs-on: windows-latest\n", encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, ["project:p"])
    assert any(item["id"] == fact.id for item in marked)
    assert brain.all_facts(["project:p"], settled_only=False)[0].lifecycle == "stale"


def test_a_tool_confirmed_fact_with_an_unchanged_file_is_untouched(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "ci.yml"
    target.write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    brain.add_fact(Fact(provenance="tool_confirmed", scope="project:p", kind="memory",
                        text="the CI runner is Linux only", status="settled",
                        source_ref="read_file:ci.yml",
                        fingerprint=rules_module.file_fingerprint(target)))
    assert stale_by_fingerprint(brain, root, ["project:p"]) == []


# --------------------------------------------------------------------------- #
# a user correction: not a statement about the file
# --------------------------------------------------------------------------- #


def test_a_user_correction_is_not_invalidated_by_an_edit(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "style.py"
    target.write_text("x = 1\n", encoding="utf-8")
    brain.add_lesson(Lesson(
        provenance="user_correction", scope="project:p",
        trigger="writing style.py", guidance="single quotes here",
        source_ref="style.py", fingerprint=rules_module.file_fingerprint(target)))

    target.write_text("x = 2\n", encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, ["project:p"])
    assert all(item["table"] != "lessons" for item in marked)
    assert brain.all_lessons(["project:p"])[0].status == "active"


# --------------------------------------------------------------------------- #
# the curator reports the class, deletes nothing
# --------------------------------------------------------------------------- #


def test_the_curator_report_lists_a_fingerprint_stale_item(config, brain, tmp_path):
    root = config.paths.project
    (root / "ci.yml").write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    fact = brain.add_fact(Fact(
        provenance="tool_confirmed", scope="global", kind="memory",
        text="the CI runner is Linux only", status="settled",
        source_ref="read_file:ci.yml",
        fingerprint=rules_module.file_fingerprint(root / "ci.yml")))
    (root / "ci.yml").write_text("runs-on: windows-latest\n", encoding="utf-8")

    report = curator.run(brain, config)
    assert any(action.what == "fact-stale" for action in report.actions)
    assert any(fact.id == item.id for item in brain.all_facts(settled_only=False)), (
        "a stale item stays inspectable; nothing is deleted")


def test_mutation_without_the_fingerprint_check_the_fact_stays_live(brain, tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    target = root / "ci.yml"
    target.write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    brain.add_fact(Fact(provenance="tool_confirmed", scope="project:p", kind="memory",
                        text="the CI runner is Linux only", status="settled",
                        source_ref="read_file:ci.yml",
                        fingerprint=rules_module.file_fingerprint(target)))
    target.write_text("runs-on: windows-latest\n", encoding="utf-8")
    assert stale_by_fingerprint(brain, root, ["project:p"]) != [], (
        "the changed file is what marks the fact stale")


def test_recount_compares_the_prevailing_convention_not_the_first_file(tmp_path):
    """A mixed sample is judged by its prevailing weighted statement.

    With two single-quote files and one double-quote file, the convention is
    single regardless of which file is scanned first; comparing the first
    file's statement would mark a correct, unchanged rule stale.
    """
    from comodor.learning import rules as rules_module

    root = tmp_path / "project"
    root.mkdir()
    files = []
    for index in range(2):
        path = root / f"single{index}.py"
        path.write_text("\n".join(f"v{n} = 't'" for n in range(10)), encoding="utf-8")
        files.append(path)
    double = root / "double.py"
    double.write_text("\n".join(f'v{n} = "t"' for n in range(10)), encoding="utf-8")
    files.append(double)

    assert rules_module.recount(files, "quotes.style", root,
                                "Use single quotes for string literals.") is True
    assert rules_module.recount(files, "quotes.style", root,
                                "Use double quotes for string literals.") is False


def test_a_tool_confirmed_lesson_goes_stale_when_its_file_changes(brain, tmp_path):
    """A reflection can admit a lesson corroborated by a tool observation,
    with the same source_ref and fingerprint a fact gets; a lesson still
    describing a changed file must not stay active (FR-060, FR-114)."""
    root = tmp_path / "project"
    root.mkdir()
    target = root / "ci.yml"
    target.write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    lesson = brain.add_lesson(Lesson(
        provenance="tool_confirmed", scope="project:p",
        trigger="editing ci.yml", guidance="the CI runner is Linux only",
        source_ref="read_file:ci.yml",
        fingerprint=rules_module.file_fingerprint(target)))

    assert stale_by_fingerprint(brain, root, ["project:p"]) == []

    target.write_text("runs-on: windows-latest\n", encoding="utf-8")
    marked = stale_by_fingerprint(brain, root, ["project:p"])

    assert any(item["table"] == "lessons" and item["id"] == lesson.id for item in marked)
    assert brain.all_lessons(["project:p"])[0].status == "stale"
