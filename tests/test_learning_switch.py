"""Learning is an explicit switch (T067; FR-064).

Off means no durable write from any automatic path — episode, reflection,
review, correction signal, vocabulary, the model's memory tool — and no
recall.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from comodor.agent import AgentLoop, Conversation
from comodor.learning import LearningEngine
from comodor.learning.store import Signal
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry


def _row_counts(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables if not table.endswith(("_fts", "_config", "_data",
                                                            "_idx", "_docsize"))}
    finally:
        connection.close()


def _reflecting_scripts():
    """A turn, then the reflection and review replies a live engine would make."""
    return [
        Script(text="Fixed it."),
        Script(text=json.dumps({"lessons": [{"kind": "fact", "trigger": "always",
                                             "guidance": "use tabs", "confidence": 0.9}],
                                "skill": None})),
        Script(text=json.dumps({"facts": [{"kind": "memory", "text": "The project uses tabs"}]})),
    ]


def test_with_learning_off_no_durable_write_occurs_from_any_automatic_path(config, bus):
    config.learning.enabled = False
    engine = LearningEngine(config, bus, gateway=Gateway(config, scripts=_reflecting_scripts()))
    try:
        before = _row_counts(config.paths.brain_db)
        agent = AgentLoop(config, Gateway(config, scripts=_reflecting_scripts()),
                          ToolRegistry(), bus, PermissionEngine(config, bus), Conversation(),
                          memory=engine)
        agent.run("fix the indentation, and no, do not use spaces")
        engine.wait_for_reflection(timeout=5.0)
        # A correction-shaped second message, and an undo: the reflex paths.
        agent.run("no, I said tabs")
        engine.on_undo(["a.py"])
        engine.wait_for_reflection(timeout=5.0)
        # The writer commits in batches; drain it so this asserts what was
        # *queued*, not how quickly the background thread happened to run.
        engine.store.flush()
        after = _row_counts(config.paths.brain_db)
        assert after == before, {k: (before.get(k), after.get(k))
                                 for k in after if after.get(k) != before.get(k)}
        assert engine.recall("indentation") == []
    finally:
        engine.close()


def _signals(path: Path) -> int:
    return _row_counts(path).get("signals", 0)


def test_learning_off_on_undo_queues_no_signal(config, bus):
    """The undo path is an automatic learning path, so the switch covers it:
    with learning off, no undo signal is queued at all (FR-064)."""
    config.learning.enabled = False
    engine = LearningEngine(config, bus)
    try:
        before = _signals(config.paths.brain_db)
        engine.on_undo(["a.py"])
        engine.store.flush()                    # deterministic: drain the writer
        assert _signals(config.paths.brain_db) == before
        assert engine.store.recent_signals("undo") == []
    finally:
        engine.close()


def test_corrections_off_on_undo_queues_no_signal(config, bus):
    """The `corrections` switch governs the undo path too (FR-064)."""
    config.learning.enabled = True
    config.learning.corrections = False
    engine = LearningEngine(config, bus)
    try:
        before = _signals(config.paths.brain_db)
        engine.on_undo(["a.py"])
        engine.store.flush()
        assert _signals(config.paths.brain_db) == before
        assert engine.store.recent_signals("undo") == []
    finally:
        engine.close()


def test_an_enabled_undo_records_its_signal(config, bus):
    """The guard is not a blanket refusal: with learning and corrections on, a
    legitimate undo still records its signal (FR-109)."""
    config.learning.enabled = True
    config.learning.corrections = True
    engine = LearningEngine(config, bus)
    try:
        before = _signals(config.paths.brain_db)
        engine.on_undo(["a.py"])
        engine.store.flush()
        assert _signals(config.paths.brain_db) == before + 1
        assert [signal.kind for signal in engine.store.recent_signals("undo")] \
            == ["undo"]
    finally:
        engine.close()


def test_learning_off_still_reads_what_was_learned_before(config, bus):
    """Off stops automatic writes, not reads: what was learned before stays
    inspectable, as the `LearningConfig.enabled` contract promises."""
    writer = LearningEngine(config, bus)
    try:
        writer.store.add_signal(Signal(kind="undo", session_id="s", subject="a.py"))
        writer.store.flush()
    finally:
        writer.close()

    config.learning.enabled = False
    reader = LearningEngine(config, bus)
    try:
        assert any(signal.subject == "a.py"
                   for signal in reader.store.recent_signals("undo"))
    finally:
        reader.close()


def test_with_learning_off_the_models_memory_tool_cannot_write(config, bus, tool_context):
    from comodor.learning.facts import FactService
    from comodor.tools.memory import Memory

    config.learning.enabled = False
    engine = LearningEngine(config, bus)
    try:
        tool = Memory(FactService(engine.store, scopes=["global"], write_scope="global"))
        result = tool.run(tool_context, action="add", text="The project uses tabs")
        assert not result.ok and "switched off" in result.content
        assert engine.facts.entries("memory") == []
        listing = tool.run(tool_context, action="list")
        assert listing.ok, "reading what was learned before stays possible"
    finally:
        engine.close()


def test_with_learning_on_the_same_turn_does_write(config, bus):
    config.learning.enabled = True
    config.learning.review = False
    engine = LearningEngine(config, bus, gateway=Gateway(config, scripts=_reflecting_scripts()[1:]))
    try:
        before = _row_counts(config.paths.brain_db)
        agent = AgentLoop(config, Gateway(config, scripts=[Script(text="Fixed it.")]),
                          ToolRegistry(), bus, PermissionEngine(config, bus), Conversation(),
                          memory=engine)
        agent.run("fix the indentation")
        engine.wait_for_reflection(timeout=5.0)
        after = _row_counts(config.paths.brain_db)
        assert after["episodes"] == before.get("episodes", 0) + 1
    finally:
        engine.close()


def test_the_switch_is_a_documented_setting_not_an_inference(config):
    import dataclasses

    from comodor.config import LearningConfig

    names = [field.name for field in dataclasses.fields(LearningConfig)]
    assert names[0] == "enabled"
    source = (Path(__file__).resolve().parents[1] / "src/comodor/config.py").read_text(
        encoding="utf-8")
    assert "Off means no durable" in source
