"""The session boundaries of background delegates, under one CoreService.

Two sessions served by one process must not hear each other's delegates or
clobber each other's crash record — and the child an agent launches must not
stream its own answer as the parent's. These are the regressions for exactly
that, written against the real service the way `test_protocol.py` drives it.
"""

from __future__ import annotations

import time
from typing import Any

from comodor.agent import AgentLoop, Conversation
from comodor.application import Assembly, CoreService
from comodor.events import EventBus, Kind, ScopedBus
from comodor.providers.base import ToolCall
from comodor.providers.fake import Script
from comodor.providers.gateway import Gateway
from comodor.safety import PermissionEngine
from comodor.tools import ToolRegistry
from comodor.tools.delegate import Delegate


class Recorder:
    """Every protocol event the service emits."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, session_id: str, name: str, params: dict[str, Any],
                 seq: int) -> None:
        self.events.append({"session": session_id, "event": name,
                            **params, "seq": seq})

    def of(self, session_id: str, name: str) -> list[dict[str, Any]]:
        return [entry for entry in self.events
                if entry["session"] == session_id and entry["event"] == name]

    def names(self, session_id: str) -> list[str]:
        return [entry["event"] for entry in self.events
                if entry["session"] == session_id]


def serve(config, recorder) -> CoreService:
    return CoreService(config, on_event=recorder)


# --------------------------------------------------------------------------- #
# a session does not stream what its delegates say
# --------------------------------------------------------------------------- #


def test_a_delegates_own_events_never_become_the_parents_turn(config):
    """The child's words, tools and plan are not the parent's turn.

    The spawner used to hand the child the same `EventBus` the relay is
    subscribed to: the child's answer streamed into the parent's transcript
    as the parent's message, and its `todo_write` replaced the parent's plan —
    before the completion machinery delivered the same answer again as its
    own turn. The child's bus now stamps an origin, and the relay drops
    everything carrying one.
    """
    from comodor.agent.spawn import DELEGATE_ORIGIN

    recorder = Recorder()
    service = serve(config, recorder)
    try:
        session = service.create_session()["id"]
        bus = service.session(session).assembly.bus

        # What the child emits: a message, a tool, a plan.
        bus.emit(Kind.ASSISTANT_START, id="child-message",
                 origin=DELEGATE_ORIGIN)
        bus.emit(Kind.ASSISTANT_DELTA, text="the child's raw answer",
                 origin=DELEGATE_ORIGIN)
        bus.emit(Kind.TOOL_START, id="child-tool", name="read_file",
                 summary="read: x", origin=DELEGATE_ORIGIN)
        bus.emit(Kind.TODO, origin=DELEGATE_ORIGIN,
                 items=[{"text": "a child's plan", "state": "pending"}])
        # A permission the child needs: the person's to answer, so it does
        # ride through, and arrives as the structured primitive.
        bus.emit(Kind.REQUEST, origin=DELEGATE_ORIGIN,
                 request=_request("r1", "Allow the child to write?"))
        # The parent's own message, unstamped, still streams.
        bus.emit(Kind.ASSISTANT_START, id="parent-message")
        bus.emit(Kind.ASSISTANT_DELTA, text="the parent's answer")

        names = recorder.names(session)
        assert "message.started" in names
        assert "message.delta" in names
        assert "permission.requested" in names
        # Nothing the child said became the parent's message, tool or plan.
        assert not recorder.of(session, "tool.started"), (
            "the child's tool was streamed into the parent's turn")
        assert not recorder.of(session, "tasks.updated"), (
            "the child's plan replaced the parent's")
        deltas = [entry["text"] for entry in
                  recorder.of(session, "message.delta")]
        assert deltas == ["the parent's answer"], (
            f"the child's answer leaked into the parent's transcript: {deltas}")
        started = [entry["message_id"] for entry in
                   recorder.of(session, "message.started")]
        assert started == ["parent-message"]
    finally:
        service.close()


def test_a_request_the_child_raised_still_resolves_for_the_client(config):
    """The exception to the origin filter: requests ride through.

    A permission the child needs answered is the person's to give, and the
    expiry the scoped bus publishes when nobody answers is the same observable
    resolution the client's own prompts produce.
    """
    from comodor.agent.spawn import DELEGATE_ORIGIN

    recorder = Recorder()
    service = serve(config, recorder)
    try:
        session = service.create_session()["id"]
        bus = service.session(session).assembly.bus
        request = _request("r2", "Allow the child to run this?")
        bus.emit(Kind.REQUEST_EXPIRED, origin=DELEGATE_ORIGIN,
                 request=request, choice="no")
        resolved = recorder.of(session, "permission.resolved")
        assert resolved and resolved[0]["choice"] == "no", (
            "a request the child raised never resolved for the client")
    finally:
        service.close()


def test_a_real_spawned_child_leaks_nothing_into_the_relay(config):
    """End to end: a background delegate runs a scripted child.

    The child's provider is scripted to answer; the parent's turn is the tool
    call and its own words. What must not happen is the child's answer
    streaming as the parent's message — the relay hears the child's events on
    the same bus, and only the origin tag keeps them apart.
    """
    parent_scripts = [Script(
        text="Delegating.",
        tool_calls=[ToolCall(id="c1", name="delegate",
                             arguments={"task": "survey the tests",
                                        "background": True,
                                        "label": "survey"})]),
        Script(text="Carried on while it runs."),
    ]
    child_scripts = [Script(text="the child's private survey answer")]

    def build(built_config, *, bus=None, plugins=None,
              delegates=None) -> Assembly:
        bus = bus or EventBus()
        from comodor.agent.spawn import spawner

        # The spawner the delegate tool launches on, built the production
        # way: a real AgentLoop behind a ScopedBus, on a scripted provider.
        spawn = spawner(built_config, Gateway(built_config,
                                              scripts=child_scripts), bus)
        if hasattr(delegates, "attach"):
            delegates.attach(bus, spawn)
        tools = ToolRegistry(config=built_config)
        tools.add(Delegate(spawn, background=delegates))
        permissions = PermissionEngine(built_config, bus)
        agent = AgentLoop(built_config, Gateway(built_config,
                                                scripts=parent_scripts),
                          tools, bus, permissions, Conversation())
        return Assembly(config=built_config, bus=bus, gateway=None,
                        memory=None, permissions=permissions, skills=None,
                        mcp=None, tools=tools, agent=agent,
                        delegates=delegates
                        if hasattr(delegates, "attach") else None)

    config.safety.auto_approve_safe = True
    recorder = Recorder()
    service = CoreService(config, assemble_with=build, on_event=recorder)
    try:
        session = service.create_session()["id"]
        service.send(session, "go and survey")
        service.release()
        _settled(service, session)
        # The child runs on its own thread; wait for it to finish so every
        # event it will ever emit has been emitted before asserting on what
        # the relay did with them.
        _store_settled(service.session(session).assembly.delegates, None)

        # The launch itself was announced to the client.
        assert recorder.of(session, "delegate.updated"), (
            "the launch was never announced")
        # Nothing of the child's streamed as the parent's message.
        deltas = "".join(entry["text"] for entry in
                         recorder.of(session, "message.delta"))
        assert "private survey" not in deltas, (
            "the child's answer appeared in the parent's turn")
        assert "Carried on while it runs." in deltas, (
            f"the parent's own words are missing: {deltas!r}")
        # And the parent's plan was never the child's to write.
        assert not recorder.of(session, "tasks.updated"), (
            "a task list the child wrote replaced the parent's plan")
    finally:
        service.close()


def test_the_scoped_bus_stamps_an_origin_and_leaves_requests_answerable():
    """The tag itself: set once, never overwritten, and requests still work."""
    parent = EventBus()
    seen: list[dict[str, Any]] = []
    parent.subscribe(lambda event: seen.append(event.payload))
    scoped = ScopedBus(parent, origin="delegate")

    scoped.emit(Kind.NOTICE, text="hello")
    scoped.emit(Kind.NOTICE, text="kept", origin="already-set")
    assert seen[0]["origin"] == "delegate"
    # An origin already there is the truth — the scope does not rewrite it.
    assert seen[1]["origin"] == "already-set"

    request = _request("r3", "Allow?")
    choice, expired = scoped.resolve(request, timeout=0.05)
    assert expired and choice == "deny"
    kinds = [payload.get("choice") for payload in seen]
    assert "deny" in kinds  # the expiry was published through the scope


# --------------------------------------------------------------------------- #
# two sessions, one store
# --------------------------------------------------------------------------- #


def test_a_second_session_does_not_adopt_a_live_delegate_as_lost(config):
    """The crash in the review: session B loading session A's running record.

    Two `BackgroundDelegates` on one file meant B's `_load()` read A's live
    run, marked it `lost`, rewrote the file, and seeded the foreign delegate
    into B's snapshot. The store is shared now: one owner of the document,
    and a session sees only the runs it launched.
    """
    recorder = Recorder()
    service = serve(config, recorder)
    try:
        first = service.create_session()["id"]
        first_view = service.session(first).assembly.delegates
        _children_are(service, first, _until_cancelled)
        accepted, identifier, why = first_view.start("a live brief",
                                                     label="live")
        assert accepted, why

        second = service.create_session()["id"]
        second_ids = [entry["id"]
                      for entry in service.snapshot(second)["delegates"]]
        assert second_ids == [], (
            f"session two was seeded with session one's work: {second_ids}")

        # And the run itself was not rewritten as lost.
        first_states = {entry["id"]: entry["state"]
                        for entry in service.snapshot(first)["delegates"]}
        assert first_states.get(identifier) == "running", (
            f"the live run was rewritten behind its owner's back: "
            f"{first_states}")
    finally:
        service.close()


def test_a_completion_drains_only_into_the_session_that_launched_it(config):
    """One session is never handed another's answer.

    A completion delivered to the wrong conversation would answer a question
    that conversation never asked, with the full turn machinery behind it.
    """
    recorder = Recorder()
    service = serve(config, recorder)
    try:
        first = service.create_session()["id"]
        first_view = service.session(first).assembly.delegates
        _children_are(service, first, _finishing)
        accepted, identifier, why = first_view.start("session one's brief",
                                                     label="one")
        assert accepted, why
        _store_settled(first_view, identifier)

        second = service.create_session()["id"]
        second_view = service.session(second).assembly.delegates
        assert second_view.take_pending() == [], (
            "session two drained session one's answer")

        # The launching session still sees its own work as undelivered.
        pending = first_view.take_pending()
        assert [entry["id"] for entry in pending] == [identifier]
    finally:
        service.close()


def test_one_session_cannot_stop_anothers_delegate(config):
    """The record is shared; the work is not."""
    recorder = Recorder()
    service = serve(config, recorder)
    try:
        first = service.create_session()["id"]
        first_view = service.session(first).assembly.delegates
        _children_are(service, first, _until_cancelled)
        accepted, identifier, why = first_view.start("session one's brief")
        assert accepted, why

        # Another session's stop of that id: refused, and the run untouched.
        second = service.create_session()["id"]
        second_view = service.session(second).assembly.delegates
        assert second_view.stop(identifier) is False
        assert first_view._store.running_ids() == [identifier]

        # The owner's stop still works.
        assert first_view.stop(identifier) is True
        _store_settled(first_view, identifier)
        assert first_view._store.running_ids() == []
    finally:
        service.close()


def test_two_sessions_share_the_slots_but_not_the_listing(config):
    """The slot limit is the store's; the view of the work is each session's.

    `max_background` is a promise about work nobody supervises, and the store
    is what knows the whole truth — two sessions are counted together. What
    each *sees*, though, is only what it launched.
    """
    recorder = Recorder()
    service = serve(config, recorder)
    try:
        first = service.create_session()["id"]
        second = service.create_session()["id"]
        first_view = service.session(first).assembly.delegates
        second_view = service.session(second).assembly.delegates
        _children_are(service, first, _until_cancelled)
        _children_are(service, second, _until_cancelled)

        for view in (first_view, second_view):
            accepted, _, why = view.start("a brief")
            assert accepted, why

        assert first_view._store.slots_busy == 2
        mine = first_view.listing()
        theirs = second_view.listing()
        assert len(mine) == 1 and len(theirs) == 1
        assert mine[0]["id"] != theirs[0]["id"]
    finally:
        service.close()


def test_a_crash_record_from_a_dead_process_is_adopted_by_the_next_session(
        config):
    """A run with no owner belongs to whichever session asks next.

    The crash record is one honest account per machine: a run that was
    `running` when the process died comes back as `lost`, and the next
    session — not the process that spawned it, which is gone — reports it.
    """
    import json

    (config.paths.user / "delegates.json").write_text(json.dumps({
        "saved_at": time.time(),
        "runs": [{
            "id": "d9", "brief": "a brief from a dead process", "label": "old",
            "state": "running", "started_at": time.time() - 60, "ended_at": 0,
            "steps": 0, "tool_calls": 0, "tokens": 0, "answer": "",
            "error": "", "delivered": False, "owner": "",
        }]}), encoding="utf-8")

    recorder = Recorder()
    service = serve(config, recorder)
    try:
        session = service.create_session()["id"]
        lost = [entry for entry in service.snapshot(session)["delegates"]
                if entry["id"] == "d9"]
        assert lost and lost[0]["state"] == "lost", (
            f"the crash record did not survive as lost: {lost}")

        # It drains into this session: ownerless work is the next asker's.
        view = service.session(session).assembly.delegates
        pending = view.take_pending()
        assert [entry["id"] for entry in pending] == ["d9"]
    finally:
        service.close()


def test_closing_one_session_leaves_the_store_open_for_another(config):
    """A session on its way out stops its own work, not the store's."""
    recorder = Recorder()
    service = serve(config, recorder)
    try:
        first = service.create_session()["id"]
        second = service.create_session()["id"]
        first_view = service.session(first).assembly.delegates
        second_view = service.session(second).assembly.delegates
        _children_are(service, first, _finishing)
        _children_are(service, second, _finishing)

        first_view.closing()
        refused, _, why = first_view.start("late work")
        assert not refused
        accepted, _, why = second_view.start("fine work")
        assert accepted, why
        _store_settled(second_view, None)
    finally:
        service.close()


def test_a_view_that_was_never_attached_refuses_plainly(config):
    """No spawner bound, no launch — a refusal, not a delegate going nowhere."""
    from comodor.agent.background import BackgroundDelegates

    store = BackgroundDelegates(config)
    accepted, identifier, why = store.start("work", owner="nobody")
    assert not accepted and identifier == ""
    assert "no way to build" in why


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _request(identifier: str, prompt: str):
    from comodor.events import Request

    return Request(id=identifier, prompt=prompt, options=["allow", "deny"])


def _children_are(service: CoreService, session_id: str,
                  spawner: Any) -> None:
    """Point one session's delegate launches at a scripted child.

    The real spawner builds a whole agent on a provider; these tests are about
    who may launch, see, drain and stop — not about what a child says — so
    the session's view is re-attached to a child the test controls.
    """
    bus = service.session(session_id).assembly.bus
    service.session(session_id).assembly.delegates.attach(bus, spawner)


def _until_cancelled(cancel: Any = None, **_: Any):
    """A child that runs until it is told to stop — and no longer."""

    class Endless:
        def run(self, brief: str):
            while cancel is None or not cancel.cancelled:
                time.sleep(0.01)
            return _Result(text="", stopped="cancelled")

    return Endless()


def _finishing(**_: Any):
    """A child that answers at once."""

    class Quick:
        def run(self, brief: str):
            return _Result()

    return Quick()


class _Result:
    def __init__(self, text: str = "the finished answer",
                 stopped: str = "done") -> None:
        self.text = text
        self.steps = 1
        self.tool_calls = 0
        self.stopped = stopped
        self.error = ""
        self.usage = type("Usage", (), {"prompt_tokens": 3})()


def _store_settled(view, identifier: str | None,
                   seconds: float = 30.0) -> None:
    store = view._store
    deadline = time.monotonic() + seconds
    while store.slots_busy:
        if time.monotonic() >= deadline:
            raise AssertionError(f"{identifier or 'a delegate'} never settled")
        time.sleep(0.01)


def _settled(service: CoreService, session_id: str,
             seconds: float = 30.0) -> None:
    deadline = time.monotonic() + seconds
    while service.session(session_id).busy:
        if time.monotonic() >= deadline:
            raise AssertionError("the turn never ended")
        time.sleep(0.01)
