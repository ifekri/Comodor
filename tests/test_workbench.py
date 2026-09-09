"""The workbench state a served session carries: tasks, delegates, delivery.

The core already knew all of this — `todo_write` replaces a task list, the
background-delegate manager announces a monotonic lifecycle, and a finished
delegate's answer becomes a turn at the next boundary. None of it crossed the
protocol. These tests drive `CoreService` the way a transport does and hold
the threads with events and conditions rather than sleeps: a child delegate
that must not finish until the test says so is gated, not delayed.

Three guarantees carry the phase:

* the relay is an allow-list — a field the internal record grows later does
  not ride to every client by accident;
* the journal's fold is forward-only — a late announcement cannot re-describe
  a stopped delegate as alive, wherever it comes from;
* delivery happens at a turn boundary and nowhere else — a completion that
  arrives between turns waits for the next one rather than splicing itself
  into a conversation or vanishing.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field

import pytest

from comodor.application import CoreService, Refused, assemble
from comodor.events import Kind
from comodor.providers.fake import FakeProvider, Script

# --------------------------------------------------------------------------- #
# the harness
# --------------------------------------------------------------------------- #

class Collector:
    """Every protocol event the service emits, with a bounded wait.

    A condition rather than a polling sleep: a wait returns the moment the
    event it is watching for is appended, and fails with the transcript it did
    see when the deadline passes — so a failure names what arrived instead of
    merely timing out.
    """

    def __init__(self) -> None:
        self.events: list[tuple[str, dict, int]] = []
        self._condition = threading.Condition()

    def __call__(self, session_id: str, name: str, params: dict,
                 seq: int) -> None:
        with self._condition:
            self.events.append((name, params, seq))
            self._condition.notify_all()

    def wait_for(self, predicate, timeout: float = 15.0):
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                for entry in self.events:
                    if predicate(*entry):
                        return entry
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    seen = ", ".join(name for name, _, _ in self.events)
                    raise AssertionError(
                        f"no event matched; saw: {seen or 'nothing'}")
                self._condition.wait(remaining)

    def of(self, name: str) -> list[tuple[dict, int]]:
        return [(params, seq) for held, params, seq in self.events
                if held == name]

    def names(self) -> list[str]:
        return [name for name, _, _ in self.events]


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    output_tokens: int = 5


@dataclass
class FakeResult:
    text: str = "the delegated answer"
    steps: int = 2
    tool_calls: int = 1
    stopped: str = "done"
    error: str = ""
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeChild:
    """A delegate's loop that runs when the test says so, and stops when asked.

    The gate is the only thing that releases it; the cancellation is polled
    while waiting, exactly the way the manager's own fakes do it, so a stop
    lands without the test setting the gate.
    """

    def __init__(self, started: threading.Event, gate: threading.Event,
                 cancel=None) -> None:
        self.started = started
        self.gate = gate
        self.cancel = cancel
        self.brief = ""

    def run(self, brief: str) -> FakeResult:
        self.brief = brief
        self.started.set()
        deadline = time.monotonic() + 30.0
        while not self.gate.is_set():
            if self.cancel is not None and self.cancel.cancelled:
                return FakeResult(text="", stopped="cancelled")
            if time.monotonic() >= deadline:
                raise AssertionError("the test never released the child")
            self.gate.wait(timeout=0.02)
        if self.cancel is not None and self.cancel.cancelled:
            return FakeResult(text="", stopped="cancelled")
        return FakeResult()


@pytest.fixture
def child(monkeypatch):
    """Patch the spawner so every delegate this service builds is a FakeChild.

    Patched before the session exists, because `assemble` hands the manager
    the spawner it builds at wiring time.
    """
    started = threading.Event()
    gate = threading.Event()
    children: list[FakeChild] = []

    def fake_spawner(config, gateway, bus, skills=None, mcp=None):
        def spawn(**kwargs):
            made = FakeChild(started, gate, cancel=kwargs.get("cancel"))
            children.append(made)
            return made
        return spawn

    monkeypatch.setattr("comodor.agent.spawn.spawner", fake_spawner)
    return type("Child", (), {"started": started, "gate": gate,
                              "children": children})()


def served(config, collector=None):
    """A service with a session, its manager, and every event collected."""
    service = CoreService(config)
    collector = collector if collector is not None else Collector()
    service.on_event = collector
    session = service.create_session()
    handle = service.session(session["id"])
    return service, handle, collector


def scripts(handle, *texts):
    handle.assembly.gateway._instances["fake"] = FakeProvider(
        [Script(text=text) for text in texts])


def delegate_states(collector, identifier="d1"):
    return [params["delegate"]["state"]
            for params, _ in collector.of("delegate.updated")
            if params["delegate"]["id"] == identifier]


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

def test_a_served_session_gets_a_delegate_manager(config):
    service, handle, _ = served(config)
    try:
        assert handle.assembly.delegates is not None
        assert handle.assembly.agent.delegates is handle.assembly.delegates
        tool = handle.assembly.tools.get("delegate")
        assert tool._background is handle.assembly.delegates
    finally:
        service.close()


def test_a_headless_wiring_keeps_the_refusal(config):
    """No manager, no delivery path, no background launches — the refusal the
    delegate tool already makes is preserved for every wiring that has nowhere
    to deliver a finished answer."""
    built = assemble(config)
    try:
        assert built.delegates is None
        assert built.tools.get("delegate")._background is None
    finally:
        built.close()


def test_closing_an_assembly_closes_its_delegates(config):
    built = assemble(config, delegates=True)
    built.close()
    assert built.delegates._closing is True


# --------------------------------------------------------------------------- #
# the relay
# --------------------------------------------------------------------------- #

def test_a_todo_event_becomes_the_whole_task_list(config):
    service, handle, collector = served(config)
    try:
        handle.assembly.bus.emit(Kind.TODO, items=[
            {"text": "read the code", "state": "done"},
            {"text": "write the tests", "state": "active"},
        ])

        _, params, _ = collector.wait_for(
            lambda name, params, seq: name == "tasks.updated")
        assert params["session_id"] == handle.id
        assert params["tasks"] == [{"text": "read the code", "state": "done"},
                                   {"text": "write the tests",
                                    "state": "active"}]
        assert service.snapshot(handle.id)["tasks"] == params["tasks"]
    finally:
        service.close()


def test_the_relay_carries_the_tool_vocabulary_not_a_louder_one(config):
    service, handle, collector = served(config)
    try:
        handle.assembly.bus.emit(Kind.TODO, items=[
            {"text": "kept", "state": "blocked"},
            {"text": "coerced", "state": "exploded"},
            {"text": "", "state": "pending"},          # no text: dropped
            "not a dict",                               # dropped
        ])

        _, params, _ = collector.wait_for(
            lambda name, params, seq: name == "tasks.updated")
        assert params["tasks"] == [{"text": "kept", "state": "blocked"},
                                   {"text": "coerced", "state": "pending"}]
    finally:
        service.close()


def test_a_delegate_announcement_is_relayed_in_protocol_words(config, child):
    service, handle, collector = served(config)
    try:
        accepted, identifier, why = handle.assembly.delegates.start(
            "survey the retry module", label="retries")
        assert accepted, why

        _, params, _ = collector.wait_for(
            lambda name, params, seq: name == "delegate.updated")
        record = params["delegate"]
        # The manager announces `started`; the protocol's word is `running`.
        assert record["state"] == "running"
        assert record["id"] == identifier == "d1"
        assert record["label"] == "retries"
        assert record["started_at"] > 0

        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")
        assert delegate_states(collector) == ["running", "done"]
    finally:
        child.gate.set()
        service.close()


def test_the_relay_is_an_allow_list(config):
    """A field the internal record grows later does not ride along. The bus
    payload here carries an answer and a brief — neither is a wire field, and
    a future internal field must fail the same quiet way."""
    service, handle, collector = served(config)
    try:
        handle.assembly.bus.emit(
            Kind.DELEGATE, id="d9", label="x", state="started", steps=3,
            tool_calls=2, tokens=99, elapsed=1.5, started_at=1234.5,
            error="", answer="a long private answer",
            brief="the private brief", delivered=False,
            some_future_field="no")

        _, params, _ = collector.wait_for(
            lambda name, params, seq: name == "delegate.updated")
        record = params["delegate"]
        assert set(record) == {"id", "label", "state", "steps", "tool_calls",
                               "tokens", "elapsed", "started_at"}
        assert record["state"] == "running"
        assert "a long private answer" not in json.dumps(params)

        # An unknown state word drops the announcement rather than inventing
        # a protocol word for it. No wait is involved: the bus delivers to
        # subscribers on the emitting thread, so by the time `emit` returns,
        # the relay has already decided.
        before = len(collector.of("delegate.updated"))
        handle.assembly.bus.emit(
            Kind.DELEGATE, id="d9", label="x", state="exploded", steps=0,
            tool_calls=0, tokens=0, elapsed=0.0, started_at=1.0)
        assert len(collector.of("delegate.updated")) == before
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# crash truth
# --------------------------------------------------------------------------- #

def test_a_delegate_that_died_with_the_process_is_seeded_as_lost(config):
    """The manager's crash record predates the stream: nothing will ever
    announce it, so the journal adopts it without spending a sequence number,
    and the first snapshot a client can ask for tells the truth."""
    persist = config.paths.user / "delegates.json"
    persist.parent.mkdir(parents=True, exist_ok=True)
    persist.write_text(json.dumps({
        "saved_at": time.time(),
        "runs": [{"id": "d7", "brief": "old work", "label": "old",
                  "state": "running", "started_at": time.time() - 60,
                  "ended_at": 0, "steps": 3, "tool_calls": 2, "tokens": 50,
                  "answer": "", "error": "", "delivered": False}],
    }), encoding="utf-8")

    service, handle, collector = served(config)
    try:
        delegates = service.snapshot(handle.id)["delegates"]
        assert [record["id"] for record in delegates] == ["d7"]
        assert delegates[0]["state"] == "lost"
        assert "the session ended" in delegates[0]["error"]

        # Seeding spent no number: the session's own creation is still 1.
        created = collector.of("session.created")
        assert created and created[0][1] == 1
        assert service.snapshot(handle.id)["revision"] == len(collector.events)
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# stopping
# --------------------------------------------------------------------------- #

def test_stopping_a_running_delegate_flows_through_the_core(config, child):
    service, handle, collector = served(config)
    try:
        accepted, identifier, why = handle.assembly.delegates.start("work")
        assert accepted, why
        assert child.started.wait(timeout=15.0)

        answer = service.stop_delegate(handle.id, identifier)
        assert answer == {"stopped": True}
        # The stop is the core's: the announcement it made on the way through
        # is `stopping`, never a fabricated `stopped`.
        assert delegate_states(collector) == ["running", "stopping"]

        # A second stop while the worker has not settled is idempotent, not a
        # duplicate: the run is still `running` (only the worker ends it), so
        # there is still something to stop, and no state moves backwards.
        again = service.stop_delegate(handle.id, identifier)
        assert again == {"stopped": True}
        states = delegate_states(collector)
        assert "running" not in states[states.index("stopping"):], \
            f"a state moved backwards: {states}"

        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "stopped")
        states = delegate_states(collector)
        assert states[0] == "running"
        assert states[-1] == "stopped"
        assert "running" not in states[1:], f"a state moved backwards: {states}"

        snapshot = service.snapshot(handle.id)
        assert snapshot["delegates"][0]["state"] == "stopped"
        # One delegate, one completion — the double stop duplicated nothing.
        pending = handle.assembly.delegates.take_pending()
        assert [record["id"] for record in pending] == ["d1"]
        # And a stop after it settled is the honest false.
        assert service.stop_delegate(handle.id, identifier) == {"stopped": False}
    finally:
        child.gate.set()
        service.close()


def test_stopping_a_finished_or_unknown_delegate_is_an_honest_false(
        config, child):
    service, handle, collector = served(config)
    try:
        handle.assembly.delegates.start("work")
        assert child.started.wait(timeout=15.0)
        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")

        assert service.stop_delegate(handle.id, "d1") == {"stopped": False}
        assert service.stop_delegate(handle.id, "d404") == {"stopped": False}
        # And a terminal delegate stays terminal whatever was asked of it.
        assert service.snapshot(handle.id)["delegates"][0]["state"] == "done"
    finally:
        child.gate.set()
        service.close()


def test_a_session_without_a_manager_refuses_the_stop(config):
    service = CoreService(config, assemble_with=lambda cfg, **kw: assemble(cfg))
    collector = Collector()
    service.on_event = collector
    session = service.create_session()
    try:
        with pytest.raises(Refused):
            service.stop_delegate(session["id"], "d1")
    finally:
        service.close()


# --------------------------------------------------------------------------- #
# turn-boundary delivery
# --------------------------------------------------------------------------- #

def test_a_finished_delegate_arrives_as_its_own_turn(config, child):
    service, handle, collector = served(config)
    try:
        scripts(handle, "the first answer", "the second answer")
        accepted, identifier, why = handle.assembly.delegates.start(
            "survey the retries", label="retries")
        assert accepted, why
        assert child.started.wait(timeout=15.0)
        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")

        send = service.send(handle.id, "carry on")
        assert send["accepted"]
        service.release()

        _, notice, notice_seq = collector.wait_for(
            lambda name, params, seq:
            name == "notification.created"
            and "background task d1" in params.get("text", ""))
        _, second, second_seq = collector.wait_for(
            lambda name, params, seq:
            name == "message.completed"
            and params.get("text") == "the second answer")

        # The delivered turn's `message.completed` fires mid-turn; the worker
        # still has to unwind before `busy` settles. Joining it is what makes
        # the snapshot below a read of the finished state rather than of one
        # moment inside the wind-down.
        handle._worker.join(timeout=15.0)
        assert not handle._worker.is_alive()

        # One sequence domain: the lifecycle, the notice and the delivered
        # turn's answer are numbered in the order they happened.
        done_seq = {params["delegate"]["state"]: seq
                    for params, seq in collector.of("delegate.updated")}
        assert done_seq["done"] < notice_seq < second_seq

        snapshot = service.snapshot(handle.id)
        delivered = [message for message in snapshot["messages"]
                     if message["role"] == "user"
                     and "Background task d1" in message["text"]]
        assert delivered, "the completion text is not in the conversation"
        assert "the delegated answer" in delivered[0]["text"]
        assert "(retries)" in delivered[0]["text"]
        assert handle.assembly.delegates.take_pending() == []
        assert snapshot["session"]["busy"] is False
    finally:
        child.gate.set()
        service.close()


def test_two_delegates_share_the_boundary_in_order(config, child):
    service, handle, collector = served(config)
    try:
        scripts(handle, "the first answer", "the second answer")
        for brief in ("survey one", "survey two"):
            accepted, _, why = handle.assembly.delegates.start(brief)
            assert accepted, why
        assert child.started.wait(timeout=15.0)
        child.gate.set()
        for identifier in ("d1", "d2"):
            collector.wait_for(
                lambda name, params, seq, want=identifier:
                name == "delegate.updated"
                and params["delegate"]["id"] == want
                and params["delegate"]["state"] == "done")

        service.send(handle.id, "carry on")
        service.release()
        collector.wait_for(
            lambda name, params, seq:
            name == "message.completed"
            and params.get("text") == "the second answer")

        snapshot = service.snapshot(handle.id)
        delivered = [message for message in snapshot["messages"]
                     if message["role"] == "user"
                     and "Background task" in message["text"]]
        assert len(delivered) == 1, "one boundary, one turn, both answers"
        assert "d1" in delivered[0]["text"]
        assert "d2" in delivered[0]["text"]
        notices = [params["text"] for params, _ in collector.of(
            "notification.created")]
        assert any("d1" in text for text in notices)
        assert any("d2" in text for text in notices)
    finally:
        child.gate.set()
        service.close()


def test_a_completion_between_turns_waits_for_the_next_boundary(config, child):
    """Nothing splices into a conversation that is not running, and nothing
    delivers while it is not a boundary: the answer waits, whole, for the turn
    after next."""
    service, handle, collector = served(config)
    try:
        scripts(handle, "the first answer", "the second answer",
                "the third answer")
        handle.assembly.delegates.start("slow work")
        assert child.started.wait(timeout=15.0)

        service.send(handle.id, "a question")
        service.release()
        collector.wait_for(
            lambda name, params, seq:
            name == "message.completed"
            and params.get("text") == "the first answer")
        # `message.completed` fires mid-turn; the boundary is the worker's own
        # end. Waiting for busy to fall and the worker to finish is what makes
        # "the child ends between turns" true rather than nearly true — a
        # child finishing during the turn's wind-down would quite correctly be
        # delivered at this boundary, and the test would be measuring a race.
        collector.wait_for(
            lambda name, params, seq:
            name == "session.updated"
            and params.get("session", {}).get("busy") is False)
        handle._worker.join(timeout=15.0)
        assert not handle._worker.is_alive()

        # The child finishes while the session is idle.
        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")
        assert not collector.of("notification.created"), \
            "a completion was delivered away from a boundary"

        # The next turn's end is the boundary that delivers it.
        service.send(handle.id, "another question")
        service.release()
        collector.wait_for(
            lambda name, params, seq:
            name == "notification.created"
            and "background task d1" in params.get("text", ""))
        collector.wait_for(
            lambda name, params, seq:
            name == "message.completed"
            and params.get("text") == "the third answer")
        delivered = [message
                     for message in service.snapshot(handle.id)["messages"]
                     if message["role"] == "user"
                     and "Background task d1" in message["text"]]
        assert delivered
    finally:
        child.gate.set()
        service.close()


def test_a_completion_yield_to_a_message_that_took_the_turn(config, child):
    """If the session is busy when delivery looks, the records go back to
    pending rather than being dropped — the boundary after next still finds
    them."""
    service, handle, collector = served(config)
    try:
        handle.assembly.delegates.start("work")
        assert child.started.wait(timeout=15.0)
        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")

        with handle._lock:
            handle.busy = True
        service._deliver_completions(handle)      # finds the session working
        with handle._lock:
            handle.busy = False

        assert not collector.of("notification.created")
        pending = handle.assembly.delegates.take_pending()
        assert [record["id"] for record in pending] == ["d1"], \
            "the completion was dropped instead of restored"
    finally:
        child.gate.set()
        service.close()


def test_closing_a_session_delivers_nothing(config, child):
    service, handle, collector = served(config)
    try:
        handle.assembly.delegates.start("work")
        assert child.started.wait(timeout=15.0)
        child.gate.set()
        collector.wait_for(
            lambda name, params, seq:
            name == "delegate.updated"
            and params["delegate"]["state"] == "done")

        handle._closing = True
        service._deliver_completions(handle)

        assert not collector.of("notification.created")
        # The record is still pending — untouched, not consumed-and-dropped.
        pending = handle.assembly.delegates.take_pending()
        assert [record["id"] for record in pending] == ["d1"]
    finally:
        child.gate.set()
        service.close()
