"""Cross-project isolation of durable knowledge (T113; FR-058, SC-019).

Two project scopes share one brain. Nothing learned in one is retrieved for
the other: lessons, rules, facts and ranked search all filter by scope. The
mutation check removes the filter and shows the leakage it prevents.
"""

from __future__ import annotations

import pytest

from comodor.learning import BrainStore
from comodor.learning.store import Fact, Lesson


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


def _seeded(brain):
    lesson_a = brain.add_lesson(Lesson(
        provenance="user_statement", scope="project:a",
        trigger="deploying alpha", guidance="use the alpha makefile target"))
    lesson_b = brain.add_lesson(Lesson(
        provenance="user_statement", scope="project:b",
        trigger="deploying beta", guidance="use the beta makefile target"))
    rule_a = brain.observe_rule(key="quotes.style", scope="project:a",
                                statement="single quotes in alpha", source="observation",
                                weight=6, provenance="counted_convention", source_ref="a")
    rule_b = brain.observe_rule(key="quotes.style", scope="project:b",
                                statement="double quotes in beta", source="observation",
                                weight=6, provenance="counted_convention", source_ref="b")
    fact_a = brain.add_fact(Fact(provenance="user_statement", scope="project:a",
                                 kind="memory", text="alpha database is sqlite"))
    fact_b = brain.add_fact(Fact(provenance="user_statement", scope="project:b",
                                 kind="memory", text="beta database is postgres"))
    return lesson_a, lesson_b, rule_a, rule_b, fact_a, fact_b


def test_a_lessons_are_only_recalled_in_their_own_project(brain):
    lesson_a, lesson_b, *_ = _seeded(brain)
    assert [item.id for item in brain.all_lessons(["project:a"])] == [lesson_a.id]
    assert [item.id for item in brain.all_lessons(["project:b"])] == [lesson_b.id]


def test_ranked_search_respects_the_scope(brain):
    _seeded(brain)
    hits = [lesson.id for lesson, _ in brain.search_lessons("deploying", scopes=["project:a"])]
    lessons = {lesson.id: lesson for lesson in brain.all_lessons()}
    assert hits and all(lessons[hit].scope == "project:a" for hit in hits)


def test_rules_and_facts_are_scoped(brain):
    _, _, rule_a, rule_b, fact_a, fact_b = _seeded(brain)
    assert [rule.id for rule in brain.confident_rules(["project:a"])] == [rule_a.id]
    assert [rule.id for rule in brain.confident_rules(["project:b"])] == [rule_b.id]
    assert [fact.id for fact in brain.all_facts(["project:a"], settled_only=True)] == [fact_a.id]
    assert [fact.id for fact in brain.all_facts(["project:b"], settled_only=True)] == [fact_b.id]


def test_the_whole_brain_still_holds_both(brain):
    lesson_a, lesson_b, *_ = _seeded(brain)
    assert {item.id for item in brain.all_lessons()} == {lesson_a.id, lesson_b.id}


def test_mutation_without_the_scope_filter_projects_leak(brain, monkeypatch):
    real = BrainStore.all_lessons

    def unscoped(self, scopes=None):
        return real(self, None)          # the filter removed

    monkeypatch.setattr(BrainStore, "all_lessons", unscoped)
    _seeded(brain)
    leaked = {item.scope for item in brain.all_lessons(["project:a"])}
    assert leaked == {"project:a", "project:b"}, (
        "without the scope filter, one project applies another's lessons")
