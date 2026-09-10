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
