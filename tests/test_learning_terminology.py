"""Project terminology learned from the person's own definition (T107; FR-106).

A term is admitted only when the person defined it — quoted it and said what
it means — with provenance `user_statement`, project scope. A term the model
coined, or one that merely recurs, is not a definition and produces nothing.
A redefinition supersedes the earlier one; the earlier stays on record.
"""

from __future__ import annotations

import pytest

from comodor.learning import LearningEngine
from comodor.learning import rules as rules_module


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None)


def _memory_facts(engine):
    return [fact for fact in engine.store.all_facts(settled_only=False)
            if fact.kind == "memory"]


def test_a_definition_the_person_gave_becomes_a_fact(engine):
    engine.before_turn('the "smoke test" means the deploy check we run first')
    facts = _memory_facts(engine)
    assert len(facts) == 1
    assert facts[0].provenance == "user_statement"
    assert "smoke test" in facts[0].text.lower()


def test_a_model_coined_term_is_not_a_definition(engine):
    """Nothing without the person's explicit wording is extractable."""
    assert rules_module.analyse_terminology(
        "We could call the retry path the smoke test here.") == []
    engine.before_turn("let's just call it a smoke test for now")
    assert _memory_facts(engine) == []


def test_a_term_merely_used_but_not_defined_is_not_learned(engine):
    engine.before_turn("run the smoke test before you ship")
    assert _memory_facts(engine) == []


def test_the_defined_term_reaches_the_briefing(engine):
    engine.before_turn('the "smoke test" means the deploy check we run first')
    briefing = engine.refresh_facts()
    assert "smoke test" in briefing.lower()


def test_a_redefinition_supersedes_the_earlier_definition(engine):
    engine.before_turn('the "smoke test" means the deploy check we run first')
    engine.before_turn('the "smoke test" means the post-deploy sanity check')

    facts = _memory_facts(engine)
    assert len(facts) == 2, "nothing is deleted on supersession"
    older = next(f for f in facts if "deploy check" in f.text)
    newer = next(f for f in facts if "sanity check" in f.text)
    assert older.lifecycle == "superseded" and older.superseded_by == newer.id
    assert newer.lifecycle == "active"

    active = [f for f in engine.store.all_facts(settled_only=True) if f.kind == "memory"]
    assert [f.id for f in active] == [newer.id], "only the newer one is recalled"


def test_the_earlier_definition_is_still_inspectable(engine):
    engine.before_turn('the "smoke test" means the deploy check we run first')
    engine.before_turn('the "smoke test" means the post-deploy sanity check')
    everything = engine.store.all_facts(settled_only=False)
    assert any("deploy check" in f.text for f in everything)


def test_a_definition_at_the_cap_is_refused_not_evicted(config, bus, workspace):
    config.learning.reflect = False
    engine = LearningEngine(config, bus, gateway=None)
    for index in range(8):
        engine.before_turn(f'the "term{index}" means the {index}th thing we count')
    assert len(_memory_facts(engine)) == 8
    engine.before_turn('the "overflow" means a term that cannot fit the shelf')
    facts = _memory_facts(engine)
    assert len(facts) == 8, "the shelf did not evict to make room"


def test_mutation_without_the_definition_pattern_nothing_is_learned(engine, monkeypatch):
    monkeypatch.setattr(rules_module, "analyse_terminology", lambda text: [])
    engine.before_turn('the "smoke test" means the deploy check we run first')
    assert _memory_facts(engine) == []
