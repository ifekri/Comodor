"""Deterministic supersession and the retrieval policy (T110, T114; FR-059,
FR-060, FR-110, FR-062).

Supersession is by `established_at`: the newer item governs, the older is
kept and marked, never silently deleted. Recall excludes stale and superseded
items and stays inside the existing cap.
"""

from __future__ import annotations

import pytest

from comodor.learning import BrainStore, LearningEngine
from comodor.learning.store import Fact, Lesson


@pytest.fixture
def brain(tmp_path):
    store = BrainStore(tmp_path / "brain.db", async_writes=False)
    yield store
    store.close()


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None)


def test_the_newer_item_governs_and_the_older_is_kept(brain):
    first = brain.add_lesson(Lesson(provenance="user_statement", scope="global",
                                    trigger="choosing a database", guidance="use SQLite"))
    second = brain.add_lesson(Lesson(provenance="user_statement", scope="global",
                                     trigger="choosing a database", guidance="use Postgres"))
    assert brain.supersede("lessons", first.id, second.id)

    rows = {lesson.id: lesson for lesson in brain.all_lessons()}
    assert rows[first.id].status == "superseded"
    assert rows[first.id].superseded_by == second.id
    assert rows[second.id].status == "active"
    assert len(rows) == 2, "nothing vanished"


def test_only_the_active_one_is_searched(brain):
    first = brain.add_lesson(Lesson(provenance="user_statement", scope="global",
                                    trigger="choosing a database", guidance="use SQLite"))
    second = brain.add_lesson(Lesson(provenance="user_statement", scope="global",
                                     trigger="choosing a database", guidance="use Postgres"))
    brain.supersede("lessons", first.id, second.id)
    hits = {lesson.id for lesson, _ in brain.search_lessons("choosing a database")}
    assert second.id in hits and first.id not in hits


def test_an_illegal_lifecycle_is_refused(brain):
    lesson = brain.add_lesson(Lesson(provenance="user_statement", scope="global",
                                     guidance="something"))
    with pytest.raises(ValueError):
        brain.set_lifecycle("lessons", lesson.id, "teleported")


def test_settling_the_same_question_twice_supersedes(engine):
    older = engine.settle_decision("Which database?", "SQLite")
    newer = engine.settle_decision("Which database?", "Postgres")
    assert older.id != newer.id
    rows = {lesson.id: lesson for lesson in engine.store.all_lessons()}
    assert rows[older.id].status == "superseded" and rows[older.id].superseded_by == newer.id
    assert [d.id for d in engine.settled_decisions()] == [newer.id]


# --------------------------------------------------------------------------- #
# retrieval policy
# --------------------------------------------------------------------------- #


def test_a_stale_lesson_is_not_recalled(engine):
    lesson = engine.store.add_lesson(Lesson(
        provenance="user_statement", scope=engine.write_scope,
        trigger="running the test suite", guidance="run pytest from the root"))
    assert engine.recall("running the test suite")
    engine.store.mark_stale("lessons", lesson.id)
    assert engine.recall("running the test suite") == []


def test_a_superseded_lesson_is_not_recalled(engine):
    older = engine.store.add_lesson(Lesson(
        provenance="user_statement", scope=engine.write_scope,
        trigger="deploying the service", guidance="use the raw docker command"))
    newer = engine.store.add_lesson(Lesson(
        provenance="user_statement", scope=engine.write_scope,
        trigger="deploying the service", guidance="use the makefile target"))
    engine.store.supersede("lessons", older.id, newer.id)
    hit_ids = [lesson.id for lesson in engine.recall("deploying the service")]
    assert hit_ids == [newer.id]


def test_a_stale_rule_does_not_apply(engine):
    rule = engine.store.observe_rule(
        key="quotes.style", scope=engine.write_scope, source="observation", weight=6,
        statement="Use single quotes.", provenance="counted_convention", source_ref="sample")
    assert any(r.id == rule.id for r in engine.active_rules())
    engine.store.mark_stale("rules", rule.id)
    assert all(r.id != rule.id for r in engine.active_rules())


def test_a_stale_fact_is_not_settled(engine):
    fact = engine.store.add_fact(Fact(
        provenance="user_statement", scope="global", kind="memory",
        text="the staging database is postgres 15"))
    assert any(f.id == fact.id for f in engine.store.all_facts(settled_only=True))
    engine.store.mark_stale("facts", fact.id)
    assert all(f.id != fact.id for f in engine.store.all_facts(settled_only=True))


def test_recall_stays_within_the_existing_cap(engine):
    for index in range(20):
        engine.store.add_lesson(Lesson(
            provenance="user_statement", scope=engine.write_scope,
            trigger=f"running the test suite number {index}",
            guidance="a long piece of guidance " * 8, confidence=0.9))
    recalled = engine.recall("running the test suite")
    assert 0 < len(recalled) <= engine.config.learning.top_k


# --------------------------------------------------------------------------- #
# settled decisions (T106, SC-017)
# --------------------------------------------------------------------------- #


def _agent(config, bus, engine):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    return AgentLoop(config, Gateway(config, scripts=[]), ToolRegistry(), bus,
                     PermissionEngine(config, bus), Conversation(), engine)


def _form(answers, outcome="answered"):
    return {"questions": [{"header": "Database", "prompt": "Which database?"}],
            "answers": answers, "outcome": outcome}


def _result(meta):
    from comodor.tools.base import ToolResult

    return ToolResult.success("form", **meta)


def test_an_answered_form_is_learned_as_a_settled_decision(config, bus, engine):
    agent = _agent(config, bus, engine)
    agent._learn_decisions(_result({"form": _form(
        [{"header": "Database", "chosen": ["SQLite"], "written": ""}])}))
    decisions = engine.settled_decisions()
    assert len(decisions) == 1
    assert decisions[0].provenance == "settled_decision"
    assert "SQLite" in decisions[0].guidance


@pytest.mark.parametrize("outcome", ["cancelled", "expired", "unattended"])
def test_a_non_answer_learns_nothing(config, bus, engine, outcome):
    agent = _agent(config, bus, engine)
    agent._learn_decisions(_result({"form": _form([], outcome=outcome)}))
    assert engine.settled_decisions() == []


def test_a_blank_answer_to_a_material_question_learns_nothing(config, bus, engine):
    agent = _agent(config, bus, engine)
    agent._learn_decisions(_result({"form": _form(
        [{"header": "Database", "chosen": [], "written": ""}], outcome="cancelled")}))
    assert engine.settled_decisions() == []
