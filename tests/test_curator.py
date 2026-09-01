"""The curator: periodic maintenance that acts where decay only scores.

Phase 1 is deterministic: lessons below the confidence floor go stale,
duplicate facts merge, unused skills go stale and then to the archive.
Everything is reversible, exemptions are honoured, and every transition is
reported with its reason.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path

from comodor.config import Config
from comodor.learning import curator
from comodor.learning.store import BrainStore, Fact, Lesson
from comodor.skills.usage import UsageStore


def _config(tmp_path: Path) -> Config:
    return Config(paths=dataclasses.replace(Config().paths.ensure(), user=tmp_path / "home"))


def _brain(tmp_path: Path) -> BrainStore:
    return BrainStore(tmp_path / "brain.db")


def _skill(skills_root: Path, name: str, body: str = "do the thing") -> Path:
    folder = skills_root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} does things\n---\n\n{body}\n",
        encoding="utf-8")
    return folder


def _aged(config: Config, tmp_path: Path, days: float) -> Config:
    """Curator windows shrunk to days=seconds, for tests that live in ms."""
    return dataclasses.replace(
        config,
        curator=dataclasses.replace(config.curator,
                                    stale_days=days / 86400,
                                    archive_days=days / 86400 * 3))


# -- lessons ----------------------------------------------------------------- #

def test_a_decayed_lesson_goes_stale(tmp_path):
    config = _config(tmp_path)
    config.learning.min_confidence = 0.5
    store = _brain(tmp_path)
    lesson = store.add_lesson(Lesson(trigger="old advice", guidance="do it",
                                     confidence=0.1, updated_at=time.time() - 90 * 86400))
    report = curator.run(store, config)
    assert any(action.what == "lesson-stale" for action in report.actions)
    row = store.connection.execute(
        "SELECT status FROM lessons WHERE id=?", (lesson.id,)).fetchone()
    assert row["status"] == "stale"


def test_a_stale_lesson_is_not_recalled(tmp_path):
    store = _brain(tmp_path)
    lesson = store.add_lesson(Lesson(trigger="unique-widget-advice",
                                     guidance="use the flange"))
    store.connection.execute("UPDATE lessons SET status='stale' WHERE id=?",
                             (lesson.id,))
    store.connection.commit()
    hits = store.search_lessons("unique-widget-advice flange")
    assert all(found.id != lesson.id for found, _ in hits)


def test_a_pinned_lesson_is_never_marked_stale(tmp_path):
    config = _config(tmp_path)
    config.learning.min_confidence = 0.99
    store = _brain(tmp_path)
    lesson = store.add_lesson(Lesson(trigger="the rule", guidance="keep it",
                                     confidence=0.1, pinned=True))
    report = curator.run(store, config)
    assert not any(action.what == "lesson-stale" for action in report.actions)
    row = store.connection.execute(
        "SELECT status FROM lessons WHERE id=?", (lesson.id,)).fetchone()
    assert row["status"] == "active"


# -- facts ------------------------------------------------------------------- #

def test_duplicate_facts_merge_into_the_older_one(tmp_path):
    store = _brain(tmp_path)
    first = store.add_fact(Fact(kind="memory", scope="global",
                                text="The build tool is Bazel.", status="settled"))
    second = store.add_fact(Fact(kind="memory", scope="global",
                                 text="the build tool is bazel", status="settled"))
    report = curator.run(store, _config(tmp_path))
    assert any(action.what == "fact-merged" and action.target == second.text
               for action in report.actions)
    remaining = {fact.id for fact in store.all_facts()}
    assert first.id in remaining and second.id not in remaining


def test_distinct_facts_are_left_alone(tmp_path):
    store = _brain(tmp_path)
    one = store.add_fact(Fact(kind="memory", scope="global",
                              text="The build tool is Bazel.", status="settled"))
    two = store.add_fact(Fact(kind="memory", scope="global",
                              text="Tests run with pytest.", status="settled"))
    curator.run(store, _config(tmp_path))
    remaining = {fact.id for fact in store.all_facts()}
    assert {one.id, two.id} <= remaining


def test_a_pinned_fact_is_never_merged_away(tmp_path):
    store = _brain(tmp_path)
    store.add_fact(Fact(kind="memory", scope="global", text="same words",
                        status="settled"))
    pinned = store.add_fact(Fact(kind="memory", scope="global",
                                 text="same words again", status="settled",
                                 pinned=True))
    curator.run(store, _config(tmp_path))
    assert pinned.id in {fact.id for fact in store.all_facts()}


# -- skills ------------------------------------------------------------------ #

def test_an_unused_skill_goes_stale_then_is_archived(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0,
                                            archive_days=0.00002))
    skills = tmp_path / "skills"
    folder = _skill(skills, "deploy")
    # A recorded use, long ago: the sidecar is the evidence of idleness.
    usage = UsageStore(skills)
    usage.record_use("deploy")
    store = _brain(tmp_path)

    curator.run(store, config, skills_root=skills, cron_prompts=[])
    assert usage.get("deploy").state == "stale"
    assert folder.exists(), "one pass marks stale; it does not archive"

    # Time cannot be waited out in a test; a second pass with the archive
    # window already passed does the move.
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0,
                                            archive_days=0.0))
    curator.run(store, config, skills_root=skills, cron_prompts=[])
    assert not folder.exists()
    assert (skills / ".archive" / "deploy" / "SKILL.md").is_file()


def test_a_restored_skill_comes_back(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0, archive_days=0.0))
    skills = tmp_path / "skills"
    _skill(skills, "deploy")
    usage = UsageStore(skills)
    usage.record_use("deploy")
    store = _brain(tmp_path)
    curator.run(store, config, skills_root=skills, cron_prompts=[])
    assert (skills / ".archive" / "deploy").is_dir()

    message = curator.rollback_skill(skills, "deploy")
    assert "restored" in message
    assert (skills / "deploy" / "SKILL.md").is_file()
    assert usage.get("deploy").state == "active"


def test_a_pinned_skill_is_exempt(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0, archive_days=0.0))
    skills = tmp_path / "skills"
    _skill(skills, "deploy")
    usage = UsageStore(skills)
    usage.record_use("deploy")

    def pin(record):
        record.pinned = True
        return record
    usage.update("deploy", pin)

    report = curator.run(_brain(tmp_path), config, skills_root=skills,
                         cron_prompts=[])
    assert (skills / "deploy" / "SKILL.md").is_file()
    assert report.skipped >= 1


def test_a_skill_a_cron_job_references_is_exempt(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0, archive_days=0.0))
    skills = tmp_path / "skills"
    _skill(skills, "deploy")
    usage = UsageStore(skills)
    usage.record_use("deploy")
    store = _brain(tmp_path)

    curator.run(store, config, skills_root=skills,
                cron_prompts=["run the deploy skill on staging"])
    assert (skills / "deploy" / "SKILL.md").is_file(), \
        "archiving a job's skill would break a job nobody is watching"


def test_a_user_authored_skill_is_exempt(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0, archive_days=0.0))
    skills = tmp_path / "skills"
    _skill(skills, "mine")
    usage = UsageStore(skills)
    usage.record_use("mine")

    def mark(record):
        record.created_by = "user"
        return record
    usage.update("mine", mark)

    curator.run(_brain(tmp_path), config, skills_root=skills, cron_prompts=[])
    assert (skills / "mine" / "SKILL.md").is_file()


def test_a_stale_skill_is_not_offered_by_the_registry(tmp_path):
    skills = tmp_path / "skills"
    _skill(skills, "deploy", "deploy the staging service")
    usage = UsageStore(skills)
    usage.record_use("deploy")

    def stale(record):
        record.state = "stale"
        return record
    usage.update("deploy", stale)

    from comodor.skills.registry import SkillRegistry

    registry = SkillRegistry()
    registry.discover(skills, tmp_path / "project-skills")
    matches = registry.match("deploy the staging service")
    assert all(skill.name != "deploy" for skill in matches)
    assert not registry.get("deploy").enabled


# -- state, reports, the line ------------------------------------------------ #

def test_pause_stops_a_pass_from_running(tmp_path):
    store = _brain(tmp_path)
    config = _config(tmp_path)
    curator.save_state(store, {"last_run": 0.0, "paused": True})
    report = curator.run(store, config)
    assert report.actions == []


def test_due_respects_the_interval(tmp_path):
    store = _brain(tmp_path)
    assert curator.due(store, interval_days=7.0, paused=False)
    curator.save_state(store, {"last_run": time.time(), "paused": False})
    assert not curator.due(store, interval_days=7.0, paused=False)


def test_the_report_names_every_transition_with_its_reason(tmp_path):
    config = _config(tmp_path)
    config = dataclasses.replace(
        config, curator=dataclasses.replace(config.curator,
                                            stale_days=0.0, archive_days=0.0))
    skills = tmp_path / "skills"
    _skill(skills, "deploy")
    usage = UsageStore(skills)
    usage.record_use("deploy")
    store = _brain(tmp_path)
    store.add_lesson(Lesson(trigger="t", guidance="g", confidence=0.0,
                            updated_at=time.time() - 90 * 86400))

    curator.run(store, config, skills_root=skills, cron_prompts=[])
    text = (tmp_path / "home" / "logs" / "curator" / "REPORT.md").read_text()
    assert "deploy" in text
    assert "why" not in text  # the reason follows an em dash, not a literal


def test_the_one_line_summary_counts(tmp_path):
    report = curator.Report()
    report.actions = [
        curator.Action(what="lesson-stale", target="a", why=""),
        curator.Action(what="lesson-stale", target="b", why=""),
        curator.Action(what="fact-merged", target="c", why=""),
        curator.Action(what="skill-archived", target="deploy", why=""),
    ]
    line = report.line()
    assert "2 marked stale" in line
    assert "1 duplicate fact(s) merged" in line
    assert "1 skill(s) archived" in line


def test_an_empty_pass_writes_no_report_file(tmp_path):
    store = _brain(tmp_path)
    config = _config(tmp_path)
    curator.run(store, config)
    assert not (tmp_path / "home" / "logs" / "curator" / "REPORT.md").exists()
