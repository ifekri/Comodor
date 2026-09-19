"""Characterization: the learning cycle's ordering and its caps (T005).

Pinned before spec 002 hardens the learning subsystem (FR-063, FR-065):
corrections are folded in *before* recall so a fix made a moment ago governs
the answer being typed; the curated fact shelf refuses at its cap and lists
what is there rather than evicting; and the caps themselves are the numbers
the plan promises not to raise (8 project facts, 6 user facts).
"""

from __future__ import annotations

import pytest

from comodor.agent import AgentLoop, Conversation
from comodor.learning import LearningEngine
from comodor.learning.facts import MEMORY_CAP, USER_CAP, FactError
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


@pytest.fixture
def engine(config, bus):
    config.learning.enabled = True
    made = LearningEngine(config, bus)
    yield made
    made.close()


def test_the_caps_are_eight_project_facts_and_six_user_facts():
    assert MEMORY_CAP == 8
    assert USER_CAP == 6


@pytest.mark.parametrize("kind, cap", [("memory", MEMORY_CAP), ("user", USER_CAP)])
def test_an_add_at_cap_refuses_and_lists_the_contents_rather_than_evicting(engine, kind, cap):
    for index in range(cap):
        engine.facts.add(f"fact number {index} about {kind}", kind=kind)
    before = [fact.text for fact in engine.facts.entries(kind)]
    assert len(before) == cap

    with pytest.raises(FactError) as refused:
        engine.facts.add(f"one fact too many for {kind}", kind=kind)

    assert "No free slot" in str(refused.value)
    for text in before:
        assert text in str(refused.value)
    assert [fact.text for fact in engine.facts.entries(kind)] == before


def test_an_exact_repeat_is_a_no_op_not_a_second_entry(engine):
    first = engine.facts.add("The project targets PostgreSQL 15")
    again = engine.facts.add("the project targets postgresql 15")
    assert again.id == first.id
    assert len(engine.facts.entries("memory")) == 1


def test_recall_happens_before_the_user_message_is_stored(config, bus):
    """The order inside one turn: before_turn → recall → conversation.add."""
    config.learning.enabled = True
    order: list[str] = []

    class Spy:
        store = None
        facts_briefing = ""

        def before_turn(self, text):
            order.append("before_turn")

        def take_prefetched(self, text):
            order.append("recall")
            return []

        def recall(self, text):
            return []

        def active_rules(self):
            return []

        def external_briefing(self, text):
            return ""

        def render_playbook(self, lessons, rules=None):
            return ""

        def record_outcome(self, **kwargs):
            order.append("record_outcome")

    class Watching(Conversation):
        def add(self, message):
            if message.role.value == "user":
                order.append("stored")
            return super().add(message)

    gateway = Gateway(config, scripts=[Script(text="ok")])
    agent = AgentLoop(config, gateway, ToolRegistry(), bus,
                      PermissionEngine(config, bus), Watching(), memory=Spy())
    agent.run("hello")

    assert order == ["before_turn", "recall", "stored", "record_outcome"]


def test_the_facts_briefing_is_frozen_at_construction(engine):
    """Facts learned mid-session join the next session, not this one."""
    frozen = engine.facts_briefing
    engine.facts.add("A fact learned after the session began")
    assert engine.facts_briefing == frozen
    assert "learned after" not in engine.facts_briefing
    assert "learned after" in engine.refresh_facts()


def test_recall_is_scoped_to_this_project_and_global(engine):
    scopes = engine.scopes
    assert "global" in scopes
    assert any(scope.startswith("project:") for scope in scopes)
    assert len(scopes) == 2
