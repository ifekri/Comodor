"""A verified fact outranks learned knowledge (T116; FR-114, FR-067, SC-029).

When a learned item contradicts what a fresh observation shows, the
observation governs and the item is marked stale — announced, not silently
resolved. Mutation-checked: with the staleness check removed, the
contradicted item stays live.
"""

from __future__ import annotations

import pytest

from comodor.learning import LearningEngine
from comodor.learning import memory as memory_module
from comodor.learning import rules as rules_module
from comodor.learning.store import Fact


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None)


def _learned_fact(engine, path, text="the CI runner is Linux only"):
    return engine.store.add_fact(Fact(
        provenance="tool_confirmed", scope="global", kind="memory", text=text,
        status="settled", source_ref=f"read_file:{path}",
        fingerprint=rules_module.file_fingerprint(engine.config.paths.project / path)))


def test_a_changed_file_marks_the_learned_fact_stale(engine):
    root = engine.config.paths.project
    (root / "ci.yml").write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    fact = _learned_fact(engine, "ci.yml")
    assert fact.lifecycle == "active"

    (root / "ci.yml").write_text("runs-on: windows-latest\n", encoding="utf-8")
    marked = engine.check_staleness(paths=["ci.yml"])
    assert any(item["id"] == fact.id for item in marked)

    stored = next(f for f in engine.store.all_facts(settled_only=False) if f.id == fact.id)
    assert stored.lifecycle == "stale"
    active = {f.id for f in engine.store.all_facts(settled_only=True)}
    assert fact.id not in active, "a contradicted fact is no longer recalled"


def test_an_unrelated_change_does_not_mark_the_fact(engine):
    root = engine.config.paths.project
    (root / "ci.yml").write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    fact = _learned_fact(engine, "ci.yml")
    (root / "other.py").write_text("x = 1\n", encoding="utf-8")

    marked = engine.check_staleness(paths=["other.py"])
    assert not any(item["id"] == fact.id for item in marked)
    stored = next(f for f in engine.store.all_facts(settled_only=False) if f.id == fact.id)
    assert stored.lifecycle == "active"


def test_the_contradiction_is_announced(engine, config, bus):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    root = config.paths.project
    (root / "ci.yml").write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    _learned_fact(engine, "ci.yml")
    (root / "ci.yml").write_text("runs-on: windows-latest\n", encoding="utf-8")

    agent = AgentLoop(config, Gateway(config, scripts=[]), ToolRegistry(), bus,
                      PermissionEngine(config, bus), Conversation(), engine)
    note = agent._learning_contradicted("ci.yml")
    assert "contradicted" in note.lower()
    assert "CI runner is Linux only" in note


def test_mutation_without_the_check_the_contradiction_stays_live(engine, monkeypatch):
    root = engine.config.paths.project
    (root / "ci.yml").write_text("runs-on: ubuntu-latest\n", encoding="utf-8")
    fact = _learned_fact(engine, "ci.yml")
    (root / "ci.yml").write_text("runs-on: windows-latest\n", encoding="utf-8")

    monkeypatch.setattr(memory_module, "stale_by_fingerprint",
                        lambda *args, **kwargs: [])
    marked = engine.check_staleness(paths=["ci.yml"])
    assert marked == []
    stored = next(f for f in engine.store.all_facts(settled_only=False) if f.id == fact.id)
    assert stored.lifecycle == "active", (
        "with the check removed, the learned item would override the observation")
