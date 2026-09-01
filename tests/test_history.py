"""Searching past conversations.

The index is a cache built from transcripts, so most of these tests are about
what happens when the transcripts and the cache disagree: a session that grew, a
session that was deleted, a database that was thrown away.
"""

from __future__ import annotations

import time

import pytest

from comodor.providers.base import Message
from comodor.session import SessionIndex, SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions")


def converse(store, session_id, *pairs):
    """Write a session as it would have been recorded."""
    for asked, answered in pairs:
        store.append(session_id, Message.user(asked))
        store.append(session_id, Message.assistant(answered))


@pytest.fixture
def indexed(store):
    converse(
        store, "20260301-101500",
        ("the auth middleware raises a KeyError when the token refreshes",
         "The token cache had no default. I added one and a regression test."),
        ("does that cover the concurrent case",
         "Not yet — I added a lock around the refresh."),
    )
    converse(
        store, "20260415-090000",
        ("add cursor pagination to the results endpoint",
         "Added a cursor parameter and a next_cursor field in the response."),
    )
    index = SessionIndex(store)
    index.refresh()
    return index


# --------------------------------------------------------------------------- #
# finding things
# --------------------------------------------------------------------------- #


def test_a_past_conversation_can_be_found(indexed):
    hits = indexed.search("KeyError token refresh")
    assert hits
    assert hits[0].session_id == "20260301-101500"
    assert "KeyError" in hits[0].text or "token cache" in hits[0].text.lower()


def test_the_right_session_wins(indexed):
    assert indexed.search("cursor pagination")[0].session_id == "20260415-090000"


def test_nothing_relevant_returns_nothing(indexed):
    """An empty answer is useful; a bad one sends the agent down a wrong path."""
    assert indexed.search("quantum chromodynamics") == []


def test_tool_output_is_not_searched(store):
    """Otherwise a search for a filename matches every directory listing ever."""
    store.append("s1", Message.user("what is in the config"))
    store.append("s1", Message.tool("1", "read_file", "distinctivetooloutput123"))
    index = SessionIndex(store)
    index.refresh()

    assert index.search("distinctivetooloutput123") == []


def test_the_current_session_can_be_excluded(indexed):
    """Repeating what is already on screen back at the user helps nobody."""
    every = indexed.search("KeyError")
    assert every

    without = indexed.search("KeyError", exclude_session="20260301-101500")
    assert all(hit.session_id != "20260301-101500" for hit in without)


def test_punctuation_in_a_query_is_not_syntax(indexed):
    """FTS5 would read these as operators and raise rather than search."""
    for query in ("KeyError: token", 'the "auth" middleware', "auth-middleware",
                  "refresh*", "(token)", "^start"):
        indexed.search(query)         # must not raise


def test_an_empty_query_finds_nothing(indexed):
    assert indexed.search("") == []
    assert indexed.search("   ") == []


# --------------------------------------------------------------------------- #
# staying in step with the transcripts
# --------------------------------------------------------------------------- #


def test_only_new_lines_are_indexed_on_a_second_pass(store):
    converse(store, "s1", ("first question about widgets", "first answer"))
    index = SessionIndex(store)
    assert index.refresh() == 2

    assert index.refresh() == 0, "nothing changed, so nothing should be re-read"

    time.sleep(0.01)
    converse(store, "s1", ("second question about sprockets", "second answer"))
    assert index.refresh() == 2
    assert index.search("sprockets")


def test_a_deleted_session_disappears_from_search(store):
    converse(store, "s1", ("something quite distinctive about penguins", "sure"))
    index = SessionIndex(store)
    index.refresh()
    assert index.search("penguins")

    store.delete("s1")
    index.refresh()
    assert index.search("penguins") == [], "search must not offer a transcript that is gone"


def test_the_index_rebuilds_from_scratch(store, tmp_path):
    """It is a cache. Deleting it must cost nothing but time."""
    converse(store, "s1", ("a question about hedgehogs", "a long enough answer"))
    first = SessionIndex(store)
    first.refresh()
    first.close()

    index_path = store.root / "search.db"
    assert index_path.exists()
    for suffix in ("", "-wal", "-shm"):
        candidate = index_path.with_name(index_path.name + suffix)
        if candidate.exists():
            candidate.unlink()

    rebuilt = SessionIndex(store)
    assert rebuilt.refresh() == 2
    assert rebuilt.search("hedgehogs")


def test_a_corrupt_line_does_not_stop_the_rest(store):
    converse(store, "s1", ("a question about aardvarks", "a long enough answer"))
    with store.path_for("s1").open("a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
    converse(store, "s1", ("a question about zebras", "another answer"))

    index = SessionIndex(store)
    index.refresh()
    assert index.search("aardvarks") and index.search("zebras")


def test_no_sessions_is_not_an_error(store):
    index = SessionIndex(store)
    assert index.refresh() == 0
    assert index.search("anything") == []
    assert index.stats() == {"turns": 0, "sessions": 0}


# --------------------------------------------------------------------------- #
# the tool the agent uses
# --------------------------------------------------------------------------- #


def tool_context(tmp_path):
    from comodor.config import Config
    from comodor.events import Cancellation, EventBus
    from comodor.paths import Paths
    from comodor.safety import CheckpointStore, PermissionEngine, Redactor
    from comodor.tools.base import ToolContext

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    bus = EventBus()
    return ToolContext(
        config=config, permissions=PermissionEngine(config, bus),
        checkpoints=CheckpointStore(tmp_path / "cp"), bus=bus,
        redact=Redactor([]), cancel=Cancellation(), cwd=tmp_path)


def test_the_agent_gets_dated_results(indexed, tmp_path):
    from comodor.tools.history import SearchHistory

    result = SearchHistory(indexed).run(tool_context(tmp_path), query="KeyError token")

    assert result.ok
    assert "session 20260301-101500" in result.content
    assert "ago" in result.content or "20" in result.content


def test_the_agent_is_told_plainly_when_there_is_nothing(indexed, tmp_path):
    """A vague answer here sends it searching again instead of working."""
    result = SearchHistory_run(indexed, tmp_path, "chromodynamics")

    assert result.ok, "finding nothing is not a failure"
    assert "Nothing" in result.content or "not come up" in result.content


def SearchHistory_run(index, tmp_path, query):
    from comodor.tools.history import SearchHistory

    return SearchHistory(index).run(tool_context(tmp_path), query=query)


def test_the_result_count_is_capped(indexed, tmp_path):
    from comodor.tools.history import MAX_RESULTS, SearchHistory

    result = SearchHistory(indexed).run(tool_context(tmp_path),
                                        query="the", limit=999)
    assert result.ok
    assert result.meta.get("matches", 0) <= MAX_RESULTS


def test_the_tool_is_absent_until_there_is_history(store, tmp_path):
    """A tool that can only answer 'nothing' teaches the model to keep asking."""
    from comodor.tools import ToolRegistry

    empty = SessionIndex(store)
    empty.refresh()
    assert "search_history" not in ToolRegistry(history=empty)

    converse(store, "s1", ("a question worth remembering", "a long enough answer"))
    filled = SessionIndex(store)
    filled.refresh()
    assert "search_history" in ToolRegistry(history=filled)

# --------------------------------------------------------------------------- #
# the compaction trail
# --------------------------------------------------------------------------- #

def test_a_session_that_was_compacted_says_so(store):
    from comodor.session.store import SessionMeta

    store.append("20260501-120000", Message.user("begin"))
    store.append("20260501-120000", Message.assistant("done"))
    meta = SessionMeta(id="20260501-120000", messages=2,
                       cost_usd=0.5, compactions=3)
    store.save_meta(meta)

    loaded = store.load_meta("20260501-120000")
    assert loaded.compactions == 3

def test_an_older_meta_without_the_field_reads_as_never_compacted(store):
    """Metas written before the field existed load with the default."""
    import json

    from comodor.session.store import SessionMeta

    store.append("20260502-130000", Message.user("begin"))
    store.save_meta(SessionMeta(id="20260502-130000", messages=1))
    path = store.meta_path("20260502-130000")
    document = json.loads(path.read_text())
    document.pop("compactions", None)
    path.write_text(json.dumps(document))

    loaded = store.load_meta("20260502-130000")
    assert loaded is not None
    assert loaded.compactions == 0
