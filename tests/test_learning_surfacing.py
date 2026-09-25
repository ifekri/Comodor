"""Provenance and status are visible, and every item is removable (T115;
FR-061, FR-111, SC-020).

`comodor journey` lists every durable item with where it came from and what
state it is in, and each can be retired individually without deleting the
others. The memory tool lists the same origin for the curated shelf. Coverage
is asserted: every stored item appears.
"""

from __future__ import annotations

import pytest

from comodor.learning import BrainStore
from comodor.learning.facts import FactService
from comodor.learning.journey import build, remove
from comodor.learning.store import Fact, Lesson
from comodor.tools.memory import Memory


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


def _seeded(brain):
    lesson = brain.add_lesson(Lesson(
        provenance="user_correction", scope="global", trigger="writing python",
        guidance="use single quotes", source_ref="a.py"))
    other = brain.add_lesson(Lesson(
        provenance="user_statement", scope="global", trigger="old habit",
        guidance="use double quotes"))
    brain.supersede("lessons", other.id, lesson.id)
    rule = brain.observe_rule(
        key="quotes.style", scope="global", source="observation", weight=6,
        statement="Use single quotes.", provenance="counted_convention",
        source_ref="sample:a.py,b.py")
    fact = brain.add_fact(Fact(
        provenance="tool_confirmed", scope="global", kind="memory",
        text="the staging database is postgres 15", source_ref="read_file:env.py"))
    return lesson, other, rule, fact


def test_every_stored_item_appears(brain):
    lesson, other, rule, fact = _seeded(brain)
    listed = {event.node_id for event in build(brain).events}
    expected = {f"lesson:{lesson.id}", f"lesson:{other.id}",
                f"rule:{rule.id}", f"fact:{fact.id}"}
    assert expected <= listed, "100% coverage of stored items"


def test_origin_is_shown(brain):
    lesson, _, rule, fact = _seeded(brain)
    details = {event.node_id: event.detail for event in build(brain).events}
    assert "user_correction" in details[f"lesson:{lesson.id}"]
    assert "a.py" in details[f"lesson:{lesson.id}"]
    assert "counted_convention" in details[f"rule:{rule.id}"]
    assert "tool_confirmed" in details[f"fact:{fact.id}"]


def test_status_is_shown(brain):
    lesson, other, _, _ = _seeded(brain)
    details = {event.node_id: event.detail for event in build(brain).events}
    assert "superseded" in details[f"lesson:{other.id}"]
    assert "superseded" not in details[f"lesson:{lesson.id}"]


def test_each_item_is_individually_removable(brain):
    lesson, other, rule, fact = _seeded(brain)
    ok, message = remove(brain, f"lesson:{lesson.id}")
    assert ok, message
    remaining = {event.node_id for event in build(brain).events}
    assert f"lesson:{lesson.id}" not in remaining
    assert {f"lesson:{other.id}", f"rule:{rule.id}", f"fact:{fact.id}"} <= remaining


def test_the_memory_tool_lists_origin(tool_context, brain):
    service = FactService(brain, scopes=["global"], write_scope="global")
    service.add("the staging database is postgres 15", provenance="user_statement")
    result = Memory(service).run(tool_context, action="list")
    assert result.ok
    assert "user_statement" in result.content
    assert "postgres 15" in result.content
