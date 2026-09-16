"""Corrections carry provenance, and are in force next turn (T105; FR-109,
SC-016).

A rewrite, an undo and a refusal each produce a durable item with provenance
`user_correction`, detected deterministically with no model call. What the
person corrected is applied on the next relevant turn without being restated.
"""

from __future__ import annotations

import pytest

from comodor.learning import LearningEngine
from comodor.safety import CheckpointStore

DOUBLE = "\n".join(f'v{n} = "t{n}"' for n in range(8)) + "\n"
SINGLE = "\n".join(f"v{n} = 't{n}'" for n in range(8)) + "\n"


@pytest.fixture
def engine(config, bus, workspace):
    config.learning.reflect = False
    return LearningEngine(config, bus, gateway=None,
                          checkpoints=CheckpointStore(config.paths.checkpoints))


def test_a_rewrite_produces_a_user_correction(engine, workspace):
    target = workspace / "sample.py"
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=DOUBLE)
    target.write_text(DOUBLE, encoding="utf-8")
    target.write_text(SINGLE, encoding="utf-8")

    outcome = engine.detector.scan_corrections()
    assert outcome.corrections
    rules = outcome.new_rules + outcome.reinforced
    assert rules and all(rule.provenance == "user_correction" for rule in rules)
    assert any(rule.source_ref == str(target) for rule in rules)
    assert any(rule.fingerprint for rule in rules)


def test_an_undo_produces_a_user_correction(engine, workspace):
    target = workspace / "sample.py"
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=DOUBLE)
    target.write_text(DOUBLE, encoding="utf-8")
    target.write_text(SINGLE, encoding="utf-8")     # the user reverted the agent's edit

    outcome = engine.detector.record_undo([str(target)])
    assert outcome.corrections, "an undo is a correction, not just a signal"
    rules = outcome.new_rules + outcome.reinforced
    assert rules and all(rule.provenance == "user_correction" for rule in rules)


def test_a_refusal_produces_a_user_correction(engine):
    outcome = engine.detector.record_denial("run_shell", "run: rm -rf build")
    rules = outcome.new_rules + outcome.reinforced
    assert rules and all(rule.provenance == "user_correction" for rule in rules)
    assert any(rule.key.startswith("avoid.run_shell") for rule in rules)


def test_detection_needs_no_model(engine):
    assert engine.gateway is None
    rule = engine.store.observe_rule(
        key="quotes.style", scope=engine.write_scope, source="correction", weight=2,
        statement="Use single quotes.", provenance="user_correction", source_ref="x.py")
    assert rule.provenance == "user_correction"


def test_the_correction_is_in_force_next_turn_without_restatement(engine, workspace):
    target = workspace / "sample.py"
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=DOUBLE)
    target.write_text(DOUBLE, encoding="utf-8")
    target.write_text(SINGLE, encoding="utf-8")
    engine.before_turn("now do the next thing")     # no restatement of the style

    applied = [rule for rule in engine.active_rules() if rule.key == "quotes.style"]
    assert applied, "the correction should be in force on the next turn"
    assert "single" in applied[0].statement.lower()


def test_an_unchanged_file_on_undo_teaches_nothing(engine, workspace):
    target = workspace / "sample.py"
    engine.detector.checkpoints.snapshot(target, action="create", tool="write_file",
                                         after=SINGLE)
    target.write_text(SINGLE, encoding="utf-8")
    outcome = engine.detector.record_undo([str(target)])
    assert outcome.corrections == []
