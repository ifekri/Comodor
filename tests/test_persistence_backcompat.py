"""Pre-change brain records stay readable (T137, T099; FR-081, SC-024).

A brain written before this feature had no provenance, fingerprint or
lifecycle columns. Opening it migrates additively — the columns are added,
not rebuilt — and every existing record reads back with the empty provenance
and an active lifecycle, still inspectable and still usable.
"""

from __future__ import annotations

import sqlite3

import pytest

from comodor.learning import BrainStore
from comodor.learning.store import Fact, Lesson

#: The columns this feature added, per table. Removing them simulates a brain
#: written by the version before the change.
ADDED = {
    "lessons": ("provenance", "source_ref", "fingerprint", "superseded_by"),
    "rules": ("provenance", "source_ref", "fingerprint", "lifecycle", "superseded_by"),
    "facts": ("provenance", "source_ref", "fingerprint", "lifecycle", "superseded_by"),
}


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def strip_new_columns(path):
    connection = sqlite3.connect(path)
    try:
        for table, columns in ADDED.items():
            present = _columns(connection, table)
            for column in columns:
                if column in present:
                    connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def pre_change_brain(tmp_path):
    path = tmp_path / "brain.db"
    store = BrainStore(path, async_writes=False)
    store.add_lesson(Lesson(provenance="user_statement", scope="global",
                            trigger="old trigger", guidance="old guidance"))
    store.add_fact(Fact(provenance="user_statement", scope="global", kind="memory",
                        text="the staging database is postgres 15", status="settled"))
    store.observe_rule(key="quotes.style", scope="global", source="observation",
                       statement="Use single quotes.", weight=6,
                       provenance="counted_convention", source_ref="sample:a.py")
    store.close()
    strip_new_columns(path)
    return path


def test_the_migration_is_additive(pre_change_brain):
    reopened = BrainStore(pre_change_brain, async_writes=False)
    try:
        for table, columns in ADDED.items():
            present = _columns(reopened.connection, table)
            assert set(columns) <= present, f"{table} did not get {columns}"
    finally:
        reopened.close()


def test_pre_change_lessons_stay_readable(pre_change_brain):
    reopened = BrainStore(pre_change_brain, async_writes=False)
    try:
        lessons = reopened.all_lessons()
        assert [lesson.guidance for lesson in lessons] == ["old guidance"]
        assert lessons[0].provenance == ""
        assert lessons[0].status == "active"          # the pre-existing lifecycle word
    finally:
        reopened.close()


def test_pre_change_rules_and_facts_stay_readable(pre_change_brain):
    reopened = BrainStore(pre_change_brain, async_writes=False)
    try:
        rules = reopened.all_rules()
        assert [rule.key for rule in rules] == ["quotes.style"]
        assert rules[0].provenance == ""
        assert rules[0].lifecycle == "active"

        facts = reopened.all_facts(settled_only=True)
        assert [fact.text for fact in facts] == ["the staging database is postgres 15"]
        assert facts[0].provenance == ""
    finally:
        reopened.close()


def test_a_migrated_brain_still_accepts_new_write(pre_change_brain):
    reopened = BrainStore(pre_change_brain, async_writes=False)
    try:
        added = reopened.add_lesson(Lesson(provenance="user_statement", scope="global",
                                           trigger="new trigger", guidance="new guidance"))
        assert added.id
        assert len(reopened.all_lessons()) == 2
    finally:
        reopened.close()
