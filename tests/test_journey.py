"""The journey: the timeline of everything the brain has learned.

The acceptance from the spec: after real use the timeline shows what was
learned and in what order, nothing appears twice, and retiring a node
follows the curator's rules — disable or forget, never destroy the
evidence. On a near-empty brain it says so honestly rather than drawing
a story out of three events.
"""

from __future__ import annotations

import time

import pytest

from comodor.learning.journey import MIN_FOR_STORY, build, remove
from comodor.learning.store import (
    BrainStore,
    Fact,
    Lesson,
    Rule,
    Skill,
)


@pytest.fixture
def store(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


def _seed(store, *, offset_days: float = 0.0):
    now = time.time() - offset_days * 86400.0
    lesson = Lesson(trigger="when touching deploys",
                    guidance="run the smoke test first",
                    created_at=now, updated_at=now)
    store.add_lesson(lesson)
    rule = Rule(key="python.quotes", statement="single quotes in python",
                support=31, against=3, created_at=now, updated_at=now)
    with store._lock, store.connection as connection:
        connection.execute(
            """INSERT INTO rules(category, key, statement, detail, scope,
                                  support, against, source, created_at, updated_at)
               VALUES('style', ?, ?, '', 'global', ?, ?, 'observation', ?, ?)""",
            (rule.key, rule.statement, rule.support, rule.against, now, now))
    store.add_skill(Skill(name="migrate-alembic", uses=4, wins=3, losses=1))
    store.add_fact(Fact(text="staging database is postgres 15"))
    return store


def test_the_timeline_lists_every_kind_in_order(store):
    _seed(store)
    timeline = build(store)
    kinds = [event.kind for event in timeline.events]
    assert set(kinds) == {"lesson", "rule", "skill", "fact"}
    stamps = [event.when for event in timeline.events]
    assert stamps == sorted(stamps), "a timeline that is not in order lies"


def test_no_event_appears_twice(store):
    _seed(store)
    timeline = build(store)
    ids = [event.node_id for event in timeline.events]
    assert len(ids) == len(set(ids))


def test_the_rule_carries_its_evidence(store):
    _seed(store)
    timeline = build(store)
    rule = next(event for event in timeline.events if event.kind == "rule")
    assert "31" in rule.detail


def test_a_stale_lesson_says_so(store):
    _seed(store)
    with store._lock, store.connection as connection:
        connection.execute("UPDATE lessons SET status='stale'")
    timeline = build(store)
    lesson = next(event for event in timeline.events if event.kind == "lesson")
    assert "stale" in lesson.detail


def test_a_thin_timeline_admits_it(store):
    _seed(store)
    timeline = build(store)
    assert len(timeline.events) < MIN_FOR_STORY
    assert timeline.thin


def test_removing_a_rule_disables_it_instead_of_deleting(store):
    _seed(store)
    timeline = build(store)
    node = next(event for event in timeline.events if event.kind == "rule")
    done, said = remove(store, node.node_id)
    assert done, said
    remaining = store.all_rules()
    assert len(remaining) == 1 and remaining[0].active is False


def test_removing_a_lesson_forgives_nothing_later(store):
    _seed(store)
    timeline = build(store)
    node = next(event for event in timeline.events if event.kind == "lesson")
    done, _said = remove(store, node.node_id)
    assert done
    assert build(store).events == [] or all(
        event.kind != "lesson" for event in build(store).events)


def test_removing_a_fact_removes_it(store):
    _seed(store)
    timeline = build(store)
    node = next(event for event in timeline.events if event.kind == "fact")
    done, _said = remove(store, node.node_id)
    assert done
    assert all(event.kind != "fact" for event in build(store).events)


def test_a_nonsense_node_id_is_refused_with_words(store):
    done, said = remove(store, "lesson:not-a-number")
    assert not done
    assert "not a node id" in said
