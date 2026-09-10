"""Session persistence, history and reopening, through the real CoreService.

A session served over the protocol must leave the same record the terminal
leaves — one store, one account of earlier conversations — and reopening one
must restore what the person saw, never a second live handle appending to the
same file.
"""

from __future__ import annotations

import time

from comodor.application import CoreService
from comodor.providers.base import Message, Role


def store_of(service: CoreService):
    return service._store()


def test_a_turn_persists_like_the_terminal_saves(config):
    """A crash mid-next-turn finds this turn whole.

    The terminal saves at the turn boundary; a session served over the
    protocol must hit the same boundary, or `session.open` reopens every
    conversation one turn behind.
    """
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        service.send(session, "remember this question")
        service.release()
        deadline = time.monotonic() + 10
        while service.session(session).busy:
            if time.monotonic() > deadline:
                raise AssertionError("the turn never ended")
            time.sleep(0.01)

        store = store_of(service)
        # `busy` flips inside the turn's finally, and the persist runs right
        # after it on the same worker — so the record arriving is a condition
        # to wait on, not a fact to assert the moment the lock opens.
        meta = None
        deadline = time.monotonic() + 10
        while meta is None:
            meta = store.load_meta(session)
            if meta is not None:
                break
            if time.monotonic() > deadline:
                raise AssertionError("no meta was written for a finished turn")
            time.sleep(0.01)
        assert meta is not None, "no meta was written for a finished turn"
        assert meta.title == "remember this question"
        assert meta.messages >= 2, (
            "the person's question and the answer both belong on disk")
        messages = store.load(session)
        assert any("remember this question" in (m.content or "")
                   for m in messages)
    finally:
        service.close()


def test_history_lists_what_survived_and_open_restores_it(config):
    """A conversation from another process comes back whole.

    Transcript, plan and title return; the new live session is a different
    identity from the stored one — it continues the record, it does not
    impersonate it.
    """
    # A session somebody had, finished, and closed the process on.
    from comodor.session.store import SessionStore

    store = SessionStore(config.paths.user / "sessions")
    store.append("past-1", Message(role=Role.USER, content="the old question"))
    store.append("past-1", Message(role=Role.ASSISTANT,
                                   content="the old answer"))
    from comodor.session.store import SessionMeta

    store.save_meta(SessionMeta(id="past-1", title="the old question",
                                messages=2, updated_at=time.time(),
                                todos=[{"text": "the old plan",
                                        "state": "active"}]))

    service = CoreService(config)
    try:
        listed = service.history()["sessions"]
        assert [entry["id"] for entry in listed] == ["past-1"]
        assert listed[0]["title"] == "the old question"

        opened = service.open_session("past-1")["session"]
        assert opened["id"] != "past-1", (
            "the live session must be its own identity, not the stored id")
        assert opened["title"] == "the old question"

        snapshot = service.snapshot(opened["id"])
        texts = [message["text"] for message in snapshot["messages"]]
        assert "the old question" in texts
        assert "the old answer" in texts
        assert snapshot["tasks"] == [{"text": "the old plan",
                                      "state": "active"}]
    finally:
        service.close()


def test_opening_the_same_session_twice_hands_back_the_live_one(config):
    """Two handles, one file: the second open returns the first.

    Two live sessions appending to one transcript would interleave their
    lines into a record neither of them said — which is exactly the record
    `session.open` is later asked to restore.
    """
    from comodor.session.store import SessionMeta, SessionStore

    store = SessionStore(config.paths.user / "sessions")
    store.append("past-2", Message(role=Role.USER, content="only once"))
    store.save_meta(SessionMeta(id="past-2", title="only once", messages=1,
                                updated_at=time.time()))

    service = CoreService(config)
    try:
        first = service.open_session("past-2")["session"]["id"]
        second = service.open_session("past-2")["session"]["id"]
        assert first == second
        assert len(service.list_sessions()) == 1
    finally:
        service.close()


def test_opening_a_session_that_is_not_stored_is_a_plain_refusal(config):
    from comodor.application import Refused

    service = CoreService(config)
    try:
        try:
            service.open_session("no-such-session")
            raise AssertionError("opening a missing session must be refused")
        except Refused as problem:
            assert "no-such-session" in str(problem)
    finally:
        service.close()


def test_a_live_session_is_not_rewritten_by_opening_another(config):
    """The current conversation survives opening an earlier one beside it."""
    from comodor.session.store import SessionMeta, SessionStore

    store = SessionStore(config.paths.user / "sessions")
    store.append("past-3", Message(role=Role.USER, content="the earlier one"))
    store.save_meta(SessionMeta(id="past-3", title="the earlier one",
                                messages=1, updated_at=time.time()))

    service = CoreService(config)
    try:
        current = service.create_session()["id"]
        service.open_session("past-3")
        # The live session is untouched: its snapshot is its own, and the
        # opened one sits beside it rather than replacing it.
        assert service.snapshot(current)["messages"] == []
        assert len(service.list_sessions()) == 2
    finally:
        service.close()


def test_a_resumed_session_continues_the_same_record(config):
    """The continuation belongs in the file the history was loaded from.

    Appending under the new live id would split the conversation in two: the
    original record frozen at the moment of reopening, and a new one holding
    only the tail — after which opening either loses half the conversation.
    """
    from comodor.session.store import SessionMeta, SessionStore

    store = SessionStore(config.paths.user / "sessions")
    store.append("past-4", Message(role=Role.USER, content="chapter one"))
    store.append("past-4", Message(role=Role.ASSISTANT,
                                   content="chapter one, answered"))
    store.save_meta(SessionMeta(id="past-4", title="chapter one",
                                messages=2, updated_at=time.time()))

    service = CoreService(config)
    try:
        opened = service.open_session("past-4")["session"]["id"]
        service.send(opened, "chapter two")
        service.release()
        deadline = time.monotonic() + 10
        while service.session(opened).busy:
            if time.monotonic() > deadline:
                raise AssertionError("the turn never ended")
            time.sleep(0.01)

        meta = None
        deadline = time.monotonic() + 10
        while True:
            meta = store.load_meta("past-4")
            if meta is not None and meta.messages >= 4:
                break
            if time.monotonic() > deadline:
                break
            time.sleep(0.01)

        assert meta is not None and meta.messages >= 4, (
            "the continuation was written somewhere else: "
            f"{meta.messages if meta else 'no'} message(s) on the original "
            "record")
        texts = [m.content for m in store.load("past-4")]
        assert "chapter two" in texts
        # And nothing was written under the live id at all.
        assert store.load(opened) == []
    finally:
        service.close()


def test_a_resumed_session_restores_the_plan_for_the_agent_too(config):
    """The panel and the model must read the same plan.

    Seeding only the journal shows the person a plan the agent's next
    `todo_write` would silently replace with a list started from empty.
    """
    from comodor.session.store import SessionMeta, SessionStore

    store = SessionStore(config.paths.user / "sessions")
    store.append("past-5", Message(role=Role.USER, content="planning"))
    store.save_meta(SessionMeta(
        id="past-5", title="planning", messages=1, updated_at=time.time(),
        todos=[{"text": "finish the migration", "state": "active"}]))

    service = CoreService(config)
    try:
        opened = service.open_session("past-5")["session"]["id"]
        handle = service.session(opened)

        assert handle.journal.tasks() == [
            {"text": "finish the migration", "state": "active"}]
        context = handle.assembly.agent._tool_context()
        assert [item.text for item in context.todos] == [
            "finish the migration"], (
            "the agent's tool context never received the restored plan")
    finally:
        service.close()


def test_a_failed_append_retries_the_unwritten_tail(config):
    """A write that fails mid-turn must not lose the rest of the turn.

    The cursor follows the disk: only lines that landed count as saved, so
    the next boundary starts from the first line that did not — never past
    it.
    """
    service = CoreService(config)
    try:
        session = service.create_session()["id"]
        store = service._store()
        handle = service.session(session)

        # Simulate two queued messages and a store that fails the first one.
        conversation = handle.assembly.conversation
        conversation.add(Message(role=Role.USER, content="first half"))
        conversation.add(Message(role=Role.ASSISTANT, content="second half"))

        original_append = store.append
        calls = []

        def flaky(session_id, message):
            calls.append(message.content)
            if len(calls) == 1:
                raise OSError("disk full")
            return original_append(session_id, message)

        store.append = flaky
        service._persist(handle)

        # A record is append-only, so a failure stops the run at the failing
        # line: skipping ahead would reorder the conversation. The cursor
        # stayed at zero, so nothing is lost.
        assert calls == ["first half"]
        assert handle._saved == 0, (
            "a failed write must not advance the cursor past it")
        assert store.load(session) == []

        # Next boundary: both lines land, in order, and none twice.
        store.append = original_append
        service._persist(handle)
        assert [m.content for m in store.load(session)] == [
            "first half", "second half"]
    finally:
        service.close()
