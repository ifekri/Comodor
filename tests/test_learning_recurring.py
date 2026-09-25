"""Standing instructions learned from repetition (T109; FR-108, SC-031).

The first time the person says *always X* it is a signal, not a rule: nothing
from a single message reaches the playbook. Said again — in a separate message
— it becomes a rule with provenance `user_statement`. A one-off instruction
never becomes durable, and a later instruction of the opposite polarity on the
same subject supersedes the earlier one without deleting it.
"""

from __future__ import annotations

import pytest

from comodor.learning import LearningEngine


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None)


def _instruction_rules(engine):
    return [rule for rule in engine.store.all_rules([engine.write_scope])
            if rule.key.startswith("instruction.")]


def test_one_message_does_not_make_a_rule(engine):
    engine.before_turn("always run the linter before committing")
    assert _instruction_rules(engine) == []


def test_the_same_instruction_twice_becomes_a_rule(engine):
    engine.before_turn("always run the linter before committing")
    engine.before_turn("always run the linter before committing")
    rules = _instruction_rules(engine)
    assert len(rules) == 1
    assert rules[0].source == "user"
    assert rules[0].provenance == "user_statement"
    assert rules[0].key.startswith("instruction.always.")


def test_the_repeated_instruction_is_applied_without_being_asked_again(engine):
    engine.before_turn("always run the linter before committing")
    engine.before_turn("always run the linter before committing")
    active = engine.active_rules()
    assert any(rule.key.startswith("instruction.always.") for rule in active)
    assert "linter" in engine.render_playbook([], rules=active).lower()


def test_a_one_off_instruction_never_becomes_durable(engine):
    engine.before_turn("always use the blue theme for this task, just this once")
    engine.before_turn("always run the linter before committing")
    engine.before_turn("always run the linter before committing")
    keys = {rule.key for rule in _instruction_rules(engine)}
    assert keys == {"instruction.always.run-the-linter-before-committing"}, keys


def test_a_contradicting_instruction_supersedes_the_earlier_one(engine):
    engine.before_turn("always run the linter before committing")
    engine.before_turn("always run the linter before committing")
    engine.before_turn("never run the linter before committing")
    engine.before_turn("never run the linter before committing")

    rules = _instruction_rules(engine)
    always = next(rule for rule in rules if rule.key.startswith("instruction.always."))
    never = next(rule for rule in rules if rule.key.startswith("instruction.never."))
    assert always.lifecycle == "superseded" and always.superseded_by == never.id
    assert never.lifecycle == "active"
    assert always in engine.store.all_rules([engine.write_scope]), "never deleted"

    active_keys = {rule.key for rule in engine.active_rules()}
    assert never.key in active_keys and always.key not in active_keys


def test_mutation_without_the_recurrence_guard_one_message_makes_a_rule(engine, monkeypatch):
    from comodor.learning import rules as rules_module
    from comodor.learning import signals as signals_module

    def eager(self, text, outcome, episode_id):
        for observation in rules_module.analyse_instructions(text):
            rule = self.store.observe_rule(
                key=observation.key, scope=self.scope, category=observation.category,
                statement=observation.statement, detail="stubbed", source="user",
                weight=1, provenance="user_statement", source_ref="stub")
            self._collect(rule, outcome)

    monkeypatch.setattr(signals_module.SignalDetector, "_learn_instructions", eager)
    engine.before_turn("always run the linter before committing")
    assert len(_instruction_rules(engine)) == 1, (
        "with the recurrence guard removed, a single message would land")


def test_restating_the_original_instruction_revives_its_rule(engine):
    """always X -> never X -> always X leaves `always X` active, not neither.

    The re-stated instruction updates its superseded row; if that row stayed
    superseded, superseding the contrary one would leave no rule applying.
    """
    engine.before_turn("always run the linter before committing")
    engine.before_turn("always run the linter before committing")
    engine.before_turn("never run the linter before committing")
    engine.before_turn("never run the linter before committing")
    engine.before_turn("always run the linter before committing")

    rules = _instruction_rules(engine)
    always = next(rule for rule in rules if rule.key.startswith("instruction.always."))
    never = next(rule for rule in rules if rule.key.startswith("instruction.never."))
    assert always.applies, "the re-stated instruction must apply again"
    assert not never.applies, "the contrary rule was superseded"
    active_keys = {rule.key for rule in engine.active_rules()}
    assert always.key in active_keys and never.key not in active_keys
