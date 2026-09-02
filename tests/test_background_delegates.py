"""Background delegates: slots, turn-boundary delivery, honest crashes."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from comodor.agent.background import BackgroundDelegates, completion_turn
from comodor.config import Config
from comodor.events import EventBus, Kind


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    output_tokens: int = 5


@dataclass
class FakeResult:
    text: str = "the answer"
    steps: int = 2
    tool_calls: int = 1
    stopped: str = "done"
    error: str = ""
    usage: FakeUsage = field(default_factory=FakeUsage)


class FakeLoop:
    """A child loop that can be made slow, loud, or broken."""

    def __init__(self, delay: float = 0.0, fail: bool = False,
                 cancel: object = None) -> None:
        self.delay = delay
        self.fail = fail
        self.cancel = cancel

    def run(self, brief: str) -> FakeResult:
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if self.cancel is not None and self.cancel.cancelled:
                return FakeResult(text="", stopped="cancelled")
            time.sleep(0.005)
        if self.fail:
            raise RuntimeError("child exploded")
        return FakeResult()


@pytest.fixture
def config(tmp_path):
    return Config(paths=type("P", (), {"user": tmp_path / "user"})())


@pytest.fixture
def bus():
    return EventBus()


def make_manager(config, bus, spawner=None, persist=None):
    return BackgroundDelegates(
        config, bus, spawner or (lambda **kwargs: FakeLoop()),
        persist_path=persist)


# -- slots ------------------------------------------------------------------ #

def test_slots_limit_launches_and_refuses_beyond_them(config, bus):
    gate = threading.Event()

    def spawner(**kwargs):
        loop = FakeLoop(delay=5.0)
        return loop

    manager = make_manager(config, bus, spawner)
    accepted = []
    for _ in range(3):
        ok, identifier, why = manager.start("do a thing")
        assert ok, why
        accepted.append(identifier)
    ok, _, why = manager.start("one too many")
    assert not ok
    assert "slots are busy" in why
    for identifier in accepted:
        assert identifier in why
    gate.set()


def test_a_slot_frees_when_a_delegate_finishes(config, bus):
    manager = make_manager(
        config, bus, lambda **kwargs: FakeLoop(delay=0.05))
    manager.start("quick one")
    deadline = time.monotonic() + 2.0
    while manager.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    ok, _, why = manager.start("next one")
    assert ok, why


# -- delivery at the boundary ----------------------------------------------- #

def test_completions_wait_until_drained(config, bus):
    manager = make_manager(
        config, bus, lambda **kwargs: FakeLoop(delay=0.05))
    _, identifier, _ = manager.start("read something")
    deadline = time.monotonic() + 2.0
    while manager.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    # finished, but nothing delivered until it is taken
    records = manager.take_pending()
    assert [record["id"] for record in records] == [identifier]
    assert records[0]["answer"] == "the answer"
    # taken once: the second read sees nothing
    assert manager.take_pending() == []


def test_stop_interrupts_the_child(config, bus):
    started = threading.Event()

    class SlowLoop(FakeLoop):
        def run(self, brief):
            started.set()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                if self.cancel is not None and self.cancel.cancelled:
                    return FakeResult(text="", stopped="cancelled")
                time.sleep(0.005)
            return FakeResult()

    manager = make_manager(
        config, bus,
        lambda **kwargs: SlowLoop(cancel=kwargs.get("cancel")))
    ok, identifier, _ = manager.start("long job")
    assert ok
    started.wait(2.0)
    assert manager.stop(identifier)
    deadline = time.monotonic() + 2.0
    while manager.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    records = manager.take_pending()
    assert records and records[0]["state"] == "stopped"


# -- honest crashes --------------------------------------------------------- #

def test_a_crash_is_recorded_not_lost(config, bus, tmp_path):
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus,
                           lambda **kwargs: FakeLoop(fail=True),
                           persist=persist)
    manager.start("doomed")
    deadline = time.monotonic() + 2.0
    while manager.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    records = manager.take_pending()
    assert records and records[0]["state"] == "failed"
    assert "exploded" in records[0]["error"]


def test_running_work_is_labelled_lost_on_reload(config, bus, tmp_path):
    persist = tmp_path / "delegates.json"
    # A predecessor session died with one delegate mid-flight.
    first = make_manager(config, bus,
                         lambda **kwargs: FakeLoop(delay=30.0),
                         persist=persist)
    _, identifier, _ = first.start("never finished")
    assert first.slots_busy == 1

    second = make_manager(config, bus, persist=persist)
    records = second.take_pending()
    assert [record["id"] for record in records] == [identifier]
    assert records[0]["state"] == "lost"
    assert "ended" in records[0]["error"]
    # ids continue after the lost one rather than colliding
    ok, fresh, _ = second.start("after the crash")
    assert ok
    assert fresh != identifier
    assert int(fresh[1:]) > int(identifier[1:])
    second.stop_all()


def test_finished_work_is_not_labelled_lost(config, bus, tmp_path):
    persist = tmp_path / "delegates.json"
    first = make_manager(config, bus,
                         lambda **kwargs: FakeLoop(delay=0.01),
                         persist=persist)
    first.start("finished fine")
    deadline = time.monotonic() + 2.0
    while first.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)

    second = make_manager(config, bus, persist=persist)
    assert second.take_pending() == []


# -- the completion turn ---------------------------------------------------- #

def test_completion_turn_is_self_contained():
    text = completion_turn({
        "id": "d2", "label": "grep the flake", "state": "done",
        "answer": "It is in loop.py line 42.",
    })
    assert "d2" in text
    assert "grep the flake" in text
    assert "loop.py line 42" in text


def test_an_oversized_answer_spills_to_a_file_not_the_void(tmp_path):
    full = "line\n" * 20_000
    text = completion_turn({"id": "d3", "state": "done", "answer": full},
                           summary_max=1_000)
    assert "full answer was longer" in text
    assert "read it with read_file" in text
    marker = "line"
    assert text.count(marker) < full.count(marker)      # summarised
    # and the spill file really holds everything
    start = text.rindex("all of it is at ") + len("all of it is at ")
    where = text[start:].split(" ")[0].rstrip(".")
    assert Path(where).read_text(encoding="utf-8") == full.strip()


def test_failed_and_lost_completions_tell_the_truth():
    failed = completion_turn({"id": "d4", "state": "failed",
                              "error": "provider down"})
    assert "failed" in failed and "provider down" in failed
    lost = completion_turn({"id": "d5", "state": "lost"})
    assert "lost" in lost


# -- events ----------------------------------------------------------------- #

@pytest.mark.performance
def test_the_bus_sees_the_lifecycle(config, bus):
    """Marked as timing-sensitive: it gives a background job two seconds to
    finish, which is generous on an idle machine and not always enough on a
    loaded one. It failed with `'done' in ['started']` — the job had begun and
    simply had not got there yet."""
    seen = []
    bus.subscribe(lambda event: seen.append(event)
                  if event.kind is Kind.DELEGATE else None)
    manager = make_manager(config, bus,
                           lambda **kwargs: FakeLoop(delay=0.05))
    manager.start("watched")
    deadline = time.monotonic() + 2.0
    while manager.slots_busy and time.monotonic() < deadline:
        time.sleep(0.01)
    states = [event.get("state") for event in seen]
    assert "started" in states
    assert "done" in states


def test_the_tool_refuses_background_where_nobody_is_listening(config, bus):
    from comodor.tools.delegate import Delegate

    bus.close()                       # nobody is receiving anything
    manager = make_manager(config, bus,
                           lambda **kwargs: FakeLoop(delay=0.05))
    tool = Delegate(lambda **kwargs: FakeLoop(), background=manager)
    context = type("C", (), {})()
    result = tool.run(context, task="try it", background=True)
    assert not result.ok
    assert "listener" in result.content


def test_the_tool_refuses_background_without_an_executor():
    from comodor.tools.delegate import Delegate

    tool = Delegate(lambda **kwargs: FakeLoop())
    context = type("C", (), {})()
    result = tool.run(context, task="try it", background=True)
    assert not result.ok
    assert "interface" in result.content
