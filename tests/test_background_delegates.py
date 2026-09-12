"""Background delegates: slots, turn-boundary delivery, honest crashes."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from comodor.agent.background import (
    BackgroundDelegates,
    DelegateCancellation,
    DelegateRun,
    completion_turn,
)
from comodor.config import Config
from comodor.events import Cancelled, EventBus, Kind


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


def settle(manager, seconds: float = 30.0) -> None:
    """Wait until no delegate is still running, and say so if none ever stops.

    The old shape here was a two-second deadline the loop fell out of in
    silence, so a runner slow enough to miss it went on to assert against work
    that was genuinely still in flight. That produced a failure describing the
    wrong thing: `test_finished_work_is_not_labelled_lost` reported a finished
    delegate marked lost, when nothing had finished at all.

    Thirty seconds because the bug actually being guarded is a delegate that
    never lands, and against that a generous ceiling costs nothing - a healthy
    run leaves in milliseconds. A `pytest.fail` rather than falling through,
    because "it did not finish" and "it finished wrongly" are different
    failures and only one of them is about this test.
    """
    deadline = time.monotonic() + seconds
    while manager.slots_busy:
        if time.monotonic() >= deadline:
            pytest.fail(
                f"{manager.slots_busy} delegate(s) still running after "
                f"{seconds:g}s, so nothing this test asserts would be about "
                f"what it is checking")
        time.sleep(0.01)

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
    settle(manager)
    ok, _, why = manager.start("next one")
    assert ok, why


# -- delivery at the boundary ----------------------------------------------- #

def test_completions_wait_until_drained(config, bus):
    manager = make_manager(
        config, bus, lambda **kwargs: FakeLoop(delay=0.05))
    _, identifier, _ = manager.start("read something")
    settle(manager)
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
    settle(manager)
    records = manager.take_pending()
    assert records and records[0]["state"] == "stopped"


# -- honest crashes --------------------------------------------------------- #

def test_a_crash_is_recorded_not_lost(config, bus, tmp_path):
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus,
                           lambda **kwargs: FakeLoop(fail=True),
                           persist=persist)
    manager.start("doomed")
    settle(manager)
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

    flushed(first)
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
    settle(first)

    flushed(first)
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
    settle(manager)
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


# --------------------------------------------------------------------------- #
# the persisted file, and two threads writing it
# --------------------------------------------------------------------------- #
#
# `start()` wrote the record after `thread.start()`, so the main thread and a
# worker could both be inside `_persist()` at once. `_persist()` takes a
# snapshot and then writes it, and the two halves were not atomic, so a
# snapshot taken before a delegate finished could be written after the snapshot
# that said it had:
#
#     main                                  worker
#     ────────────────────────────────────────────────────────────────────
#     _snapshot()  → "running"
#                                           state = "done"
#                                           _snapshot() → "done"
#                                           write("done")
#     write("running")   ← last write wins, and it is the older one
#
# The file then says a finished delegate is running, and the next session
# reads that and reports it lost. It failed `test_finished_work_is_not_
# labelled_lost` once on py3.11 in CI, which is the only way anybody was ever
# going to notice: the window is a few microseconds wide and closes on its own
# almost every time.
#
# The tests below force that interleaving rather than hoping for it.


class Interleave:
    """Holds the main thread between its snapshot and its write.

    The bug needs one specific order, and waiting for it to happen by accident
    is how a test ends up passing on a fast machine and failing in CI. So the
    order is imposed: the worker is released only once the main thread has
    taken its snapshot, and the main thread is then held until the worker has
    written.

    The hold is between staging and flushing, which is exactly where the two
    halves of a write are separable — and separable is the point: the revision
    decides which snapshot wins, not which write happens to arrive last.

    `escape` only stops a run that never reaches the worker's write from
    hanging the suite. It does not decide the outcome.
    """

    def __init__(self, manager, escape: float = 5.0) -> None:
        self.manager = manager
        self.escape = escape
        self.snapshotted = threading.Event()
        self.worker_wrote = threading.Event()
        self._real_flush = manager._flush
        self.main_thread = threading.current_thread()

        manager._flush = self._flush

    def _flush(self, revision, document, timeout=None):
        if threading.current_thread() is self.main_thread:
            # The main thread holds an older snapshot. Let the worker finish
            # and write first, so this one is attempted last and stale.
            self.snapshotted.set()
            self.worker_wrote.wait(self.escape)
            # The answer is passed back, not swallowed: a caller told its
            # snapshot was refused comes back with a current one, and a stand-in
            # that always says nothing would hide that from every test here.
            return self._real_flush(revision, document)
        wrote = self._real_flush(revision, document)
        self.worker_wrote.set()
        return wrote


class HeldLoop:
    """A child that does not finish until it is told to."""

    def __init__(self, release: threading.Event) -> None:
        self.release = release

    def run(self, brief: str) -> FakeResult:
        self.release.wait(10)
        return FakeResult()


def persisted(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def states(path: Path) -> dict[str, str]:
    return {record["id"]: record["state"] for record in persisted(path)["runs"]}


def flushed(manager, seconds: float = 30.0) -> None:
    """Wait until every staged snapshot has reached the disk.

    `settle()` waits for no delegate to be running, which used to imply the
    file agreed: the write happened under the same lock that published the
    state. It does not any more, and deliberately -- the write is outside the
    lock so a stalled disk cannot hang shutdown -- so "finished" and
    "written" are now two moments, microseconds apart.

    Nothing in the product depends on the gap: `_load` reads the file in a
    later process, and no code re-reads it inside one. Only a test that
    inspects the file needs to know, and this is how it waits -- on the
    revision counters rather than on a duration, so it is a wait for the thing
    itself and not for a guess about how long it takes.
    """
    deadline = time.monotonic() + seconds
    while True:
        with manager._lock:
            latest = manager._revision
        with manager._write_lock:
            written = manager._written
        if written >= latest:
            return
        if time.monotonic() >= deadline:
            pytest.fail(
                f"revision {written} is on disk and {latest} was staged, "
                f"after {seconds:g}s")
        time.sleep(0.005)


def test_a_finished_delegate_is_never_persisted_as_running(config, bus, tmp_path):
    """The race, forced.

    The main thread takes its snapshot while the delegate is still running, the
    delegate then finishes and writes `done`, and only then is the main thread
    allowed to write what it read. Whatever order the two writes land in, the
    file must not end up claiming that a delegate which has finished is still
    going.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)
    interleave = Interleave(manager)
    manager.spawner = lambda **kwargs: HeldLoop(interleave.snapshotted)

    manager.start("finished fine")
    settle(manager)
    interleave.worker_wrote.wait(5)

    flushed(manager)
    assert states(persist) == {"d1": "done"}, \
        "a delegate that finished was persisted as still running"


def test_the_next_session_does_not_report_finished_work_as_lost(config, bus,
                                                                tmp_path):
    """What the race costs, end to end.

    The same forced interleaving, then a reload. This is the failure a user
    would see: a delegate that finished perfectly well, reported as lost.
    """
    persist = tmp_path / "delegates.json"
    first = make_manager(config, bus, persist=persist)
    interleave = Interleave(first)
    first.spawner = lambda **kwargs: HeldLoop(interleave.snapshotted)

    first.start("finished fine")
    settle(first)
    interleave.worker_wrote.wait(5)

    flushed(first)
    second = make_manager(config, bus, persist=persist)

    assert second.take_pending() == [], "finished work was reported as lost"


@pytest.mark.parametrize(("spawner", "expected"), [
    (lambda **kwargs: FakeLoop(), "done"),
    (lambda **kwargs: FakeLoop(fail=True), "failed"),
])
def test_a_terminal_state_is_never_overwritten_by_running(config, bus, tmp_path,
                                                          spawner, expected):
    """Every way a delegate can end, against the same interleaving.

    `running` is the only state that may be replaced. Once a delegate has
    reached a terminal one, a snapshot taken before it got there must not be
    able to land on top.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)
    interleave = Interleave(manager)

    def held(**kwargs):
        interleave.snapshotted.wait(10)
        return spawner(**kwargs)

    manager.spawner = held

    manager.start("one task")
    settle(manager)
    interleave.worker_wrote.wait(5)

    flushed(manager)
    assert states(persist) == {"d1": expected}


def test_a_stopped_delegate_stays_stopped_on_disk(config, bus, tmp_path):
    """The third terminal state, which arrives by a different path: the run is
    cancelled rather than finishing or raising."""
    persist = tmp_path / "delegates.json"
    release = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: FakeLoop(delay=5,
                                                     cancel=kwargs.get("cancel")),
                           persist=persist)

    manager.start("a long one")
    manager.stop("d1")
    settle(manager)
    release.set()

    flushed(manager)
    assert states(persist)["d1"] in {"stopped", "cancelled"}


def test_two_delegates_finishing_at_once_both_land(config, bus, tmp_path):
    """Starting one delegate while another finishes is the same hazard by a
    different route: `start()` persists a snapshot that includes the other
    delegate, and can carry a stale copy of it."""
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(gate), persist=persist)

    identifiers = []
    for index in range(3):
        ok, identifier, _ = manager.start(f"task {index}")
        assert ok, "the slot limit changed; this test needs three"
        identifiers.append(identifier)

    gate.set()
    settle(manager)

    flushed(manager)
    on_disk = states(persist)
    assert set(on_disk) == set(identifiers)
    assert all(state == "done" for state in on_disk.values()), on_disk


def test_the_file_stays_valid_json_throughout(config, bus, tmp_path):
    """Whatever the ordering, the thing on disk is always readable. A reader
    that has to cope with half a document is a second bug waiting."""
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(gate), persist=persist)

    manager.start("one")
    manager.start("two")
    gate.set()
    settle(manager)

    flushed(manager)
    document = persisted(persist)
    assert isinstance(document.get("runs"), list)
    assert isinstance(document.get("saved_at"), float)


def test_the_record_exists_before_the_worker_can_change_it(config, bus, tmp_path):
    """A delegate that is still running must be on disk while it runs.

    The record used to be written after `thread.start()`, so a crash in the
    gap between them left no evidence at all — the case the file exists for.
    """
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(gate), persist=persist)

    manager.start("still going")

    assert states(persist) == {"d1": "running"}, \
        "nothing was on disk while the delegate was running"

    gate.set()
    settle(manager)
    flushed(manager)
    assert states(persist) == {"d1": "done"}


def test_a_genuinely_lost_delegate_is_still_reported(config, bus, tmp_path):
    """The behaviour that must survive the fix. A process that dies with work
    in flight leaves `running` on disk, and the next session says so."""
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    first = make_manager(config, bus,
                         lambda **kwargs: HeldLoop(gate), persist=persist)
    first.start("never finished")
    assert first.slots_busy == 1

    # No settle: the process "dies" here, with the delegate still going.
    flushed(first)
    second = make_manager(config, bus, persist=persist)
    records = second.take_pending()

    assert [record["id"] for record in records] == ["d1"]
    assert records[0]["state"] == "lost"
    gate.set()


def test_a_reload_after_finished_work_starts_clean(config, bus, tmp_path):
    """What a reload does with a delegate that finished, stated as it is.

    `_load` carries forward only records that say `running`, turning those
    into `lost`. A finished one is deliberately dropped: there is nothing to
    report and nothing to resume, so the counter is not advanced either and
    the next session numbers from the start again. That is by design, and it
    is only safe because the finished record is not kept — which is precisely
    what the race broke, by leaving `running` on disk for work that was done.
    """
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    first = make_manager(config, bus,
                         lambda **kwargs: HeldLoop(gate), persist=persist)
    first.start("one")
    gate.set()
    settle(first)
    flushed(first)
    assert states(persist) == {"d1": "done"}

    second = make_manager(config, bus, persist=persist)

    assert second.take_pending() == [], "a finished delegate has nothing to report"
    assert second.slots_busy == 0, "and holds no slot"

    ok, identifier, _ = second.start("after the reload")
    assert ok
    settle(second)


def test_ids_continue_past_a_lost_delegate(config, bus, tmp_path):
    """The case where the counter *is* carried: a record left saying
    `running` becomes `lost` and stays in the list, so a new delegate must not
    be given its id."""
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    first = make_manager(config, bus,
                         lambda **kwargs: HeldLoop(gate), persist=persist)
    first.start("never finished")

    flushed(first)
    second = make_manager(config, bus, persist=persist)
    ok, identifier, _ = second.start("after the crash")

    assert ok
    assert identifier != "d1"
    assert int(identifier[1:]) > 1
    gate.set()
    settle(second)


def test_every_persist_happens_while_the_lock_is_held():
    """The invariant, checked in the source rather than trusted to review.

    `_persist` snapshots and writes, and the two must not be separable — that
    separability is the whole bug. It has no lock of its own because the worker
    calls it while already holding one and `threading.Lock` is not reentrant,
    so the rule is that every caller holds it. A rule like that survives
    exactly as long as the next person reads the docstring, unless something
    checks.
    """
    import ast
    import inspect

    from comodor.agent import background

    source = inspect.getsource(background)
    tree = ast.parse(source)

    def persists(node) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_persist")

    def locked(node) -> bool:
        return any(
            isinstance(item.context_expr, ast.Attribute)
            # `_settled` is a Condition built on `_lock`; entering it holds
            # the same lock, so a checker that only knew one of the two names
            # would be reading the spelling rather than the property.
            and item.context_expr.attr in {"_lock", "_settled"}
            for item in getattr(node, "items", []))

    unguarded: list[int] = []

    def walk(node, under_lock: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if persists(child) and not under_lock:
                unguarded.append(child.lineno)
            walk(child, under_lock or (isinstance(child, ast.With) and locked(child)))

    walk(tree, under_lock=False)

    assert unguarded == [], (
        f"_persist() is called without the lock at line(s) {unguarded}. "
        f"Snapshot and write must be one step, or a stale snapshot can land "
        f"on top of a newer one.")


# --------------------------------------------------------------------------- #
# starting a thread, and the two ways it can go wrong
# --------------------------------------------------------------------------- #
#
# Both found by review of the change above, and both caused by it. Moving the
# persist before `thread.start()` put a filesystem write inside the window
# between recording a thread and starting it -- a window that already existed
# and was previously a few instructions wide.


def test_shutdown_never_joins_a_thread_that_has_not_started(config, bus,
                                                            tmp_path):
    """`wait()` joins everything in `_threads`, and joining an unstarted
    thread raises `RuntimeError: cannot join thread before it is started` --
    which would abort the rest of shutdown.

    The window is forced open here: the persist blocks, so `start()` is held
    at exactly the point where the thread used to be listed and not yet
    running, and `wait()` is called from another thread while it sits there.
    """
    persist = tmp_path / "delegates.json"
    gate = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(gate), persist=persist)

    inside = threading.Event()
    release = threading.Event()
    real_flush = manager._flush

    # The flush is the widest part of a launch and the part that is *not*
    # under the lock, which is precisely the gap `_launching` exists to cover.
    def slow_flush(revision, document, timeout=None):
        real_flush(revision, document)
        if threading.current_thread() is threading.main_thread():
            inside.set()
            release.wait(5)

    manager._flush = slow_flush

    failure: list[BaseException] = []

    def shut_down():
        inside.wait(5)
        try:
            manager.wait(timeout=0.2)
        except BaseException as problem:      # noqa: BLE001 - recording it
            failure.append(problem)
        finally:
            release.set()

    helper = threading.Thread(target=shut_down)
    helper.start()
    manager.start("one")
    helper.join(10)

    gate.set()
    settle(manager)

    assert failure == [], f"shutdown raised: {failure}"


def test_a_thread_that_cannot_start_leaves_no_record_behind(config, bus,
                                                            tmp_path):
    """The runtime refusing another thread is rare and not impossible.

    The record is written before the thread starts, so a failure to start
    leaves a run nothing will ever move out of `running`: the slot stays
    occupied for the session, and the next one reads the file and reports a
    task that never ran as lost.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    def refuse(self):
        raise RuntimeError("can't start new thread")

    original = threading.Thread.start
    threading.Thread.start = refuse
    try:
        ok, identifier, why = manager.start("one that cannot run")
    finally:
        threading.Thread.start = original

    assert not ok, "a delegate that could not start was reported as started"
    assert "could not be started" in why
    assert manager.slots_busy == 0, "the slot was left occupied"

    second = make_manager(config, bus, persist=persist)
    assert second.take_pending() == [],         "a delegate that never ran was reported as lost"


def test_a_failed_start_does_not_consume_a_slot_forever(config, bus, tmp_path):
    """After a refusal the manager must still be usable, and the next delegate
    must still be able to run."""
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    original = threading.Thread.start
    threading.Thread.start = lambda self: (_ for _ in ()).throw(
        RuntimeError("no threads"))
    try:
        manager.start("doomed")
    finally:
        threading.Thread.start = original

    ok, identifier, _ = manager.start("this one works")
    settle(manager)

    assert ok
    flushed(manager)
    assert states(persist)[identifier] == "done"


def test_the_thread_list_is_only_touched_under_the_lock():
    """`wait()` used to copy and rebuild `_threads` without it, while
    `start()` appended under it."""
    import ast
    import inspect

    from comodor.agent import background

    tree = ast.parse(inspect.getsource(background))
    unguarded: list[int] = []

    def uses_threads(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "_threads"
                and isinstance(node.value, ast.Name) and node.value.id == "self")

    def walk(node, under_lock: bool) -> None:
        # A `try` immediately after `self._lock.acquire(...)` holds the lock
        # just as a `with` block does. `wait()` uses that form because its
        # acquisition is bounded by the shutdown budget, and a checker that
        # only understood `with` would be checking the spelling rather than
        # the property.
        acquired: set[int] = set()
        body = getattr(node, "body", [])
        if isinstance(body, list):
            for first, second in zip(body, body[1:], strict=False):
                if _acquires_the_lock(first) and isinstance(second, ast.Try):
                    acquired.add(id(second))

        for child in ast.iter_child_nodes(node):
            # `__init__` runs before any thread exists, so the list cannot be
            # contended there and requiring the lock would be theatre.
            if isinstance(child, ast.FunctionDef) and child.name == "__init__":
                continue
            if uses_threads(child) and not under_lock:
                unguarded.append(child.lineno)
            walk(child, under_lock
                 or (isinstance(child, ast.With) and _holds_the_lock(child))
                 or id(child) in acquired)

    walk(tree, under_lock=False)

    assert unguarded == [], f"_threads touched without the lock at {unguarded}"


def test_shutdown_cannot_step_over_a_launch_in_progress(config, bus, tmp_path):
    """`wait()` must not return having joined nothing while a delegate starts.

    Appending the thread after `start()` keeps unstarted threads out of the
    list, and leaves the opposite gap: a thread that is running and not yet
    listed. A `wait()` landing there snapshots without it, returns, and
    `_shutdown()` closes the tools and the history underneath a worker that is
    still going.

    Forced by holding the launch open at its widest point -- the persist --
    and calling `wait()` from another thread while it sits there. Under a
    correct implementation `wait()` blocks on the same lock the launch holds,
    so by the time it takes its snapshot the delegate is registered and gets
    joined.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    launching = threading.Event()
    arrived = threading.Event()
    real_flush = manager._flush

    def slow_flush(revision, document, timeout=None):
        real_flush(revision, document)
        if threading.current_thread() is threading.main_thread():
            launching.set()
            arrived.wait(5)           # held until wait() is genuinely waiting

    manager._flush = slow_flush

    busy_when_wait_returned: list[int] = []

    def shut_down():
        launching.wait(5)
        arrived.set()                 # the launch may proceed; wait() must not
        manager.wait(timeout=5)
        busy_when_wait_returned.append(manager.slots_busy)

    helper = threading.Thread(target=shut_down)
    helper.start()
    ok, identifier, _ = manager.start("racing the shutdown")
    helper.join(10)
    settle(manager)

    assert ok
    assert busy_when_wait_returned == [0], (
        "wait() returned while a delegate was still running: shutdown would "
        "have closed the tools underneath it")


def test_a_launch_is_one_step_as_far_as_the_thread_list_is_concerned():
    """Start and registration happen under one lock hold.

    Stated in the source rather than inferred: `thread.start()` and the append
    that records it must be inside the same `with self._lock` block. Either of
    them alone outside it reopens one of the two windows above.
    """
    import ast
    import inspect

    from comodor.agent import background

    tree = ast.parse(inspect.getsource(background))

    def locked(node) -> bool:
        return any(
            isinstance(item.context_expr, ast.Attribute)
            # `_settled` is a Condition built on `_lock`; entering it holds
            # the same lock, so a checker that only knew one of the two names
            # would be reading the spelling rather than the property.
            and item.context_expr.attr in {"_lock", "_settled"}
            for item in getattr(node, "items", []))

    starts: list[int] = []
    appends: list[int] = []

    def walk(node, under_lock: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "start"
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "thread"):
                starts.append(child.lineno if under_lock else -child.lineno)
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "append"
                    and isinstance(child.func.value, ast.Attribute)
                    and child.func.value.attr == "_threads"):
                appends.append(child.lineno if under_lock else -child.lineno)
            walk(child, under_lock or (isinstance(child, ast.With) and locked(child)))

    walk(tree, under_lock=False)

    assert starts and all(line > 0 for line in starts), (
        f"thread.start() outside the lock at "
        f"{[-n for n in starts if n < 0]}")
    assert appends and all(line > 0 for line in appends), (
        f"_threads.append outside the lock at "
        f"{[-n for n in appends if n < 0]}")


def test_a_stalled_disk_cannot_block_shutdown_cancellation(config, bus,
                                                           tmp_path):
    """`stop_all()` must not wait on the filesystem.

    `_shutdown()` calls `stop_all()` and then `wait()`, and both take the
    lifecycle lock. While the write happened under that lock, a user directory
    that stopped answering could hang either of them -- and bounding only
    `wait()` moved the hang one line earlier, into `stop_all()`.

    Held with an event rather than a sleep: the write does not finish until
    this test says so, and `stop_all()` must have returned long before then.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    stalled = threading.Event()
    let_go = threading.Event()
    real_flush = manager._flush

    def stalled_flush(revision, document, timeout=None):
        if threading.current_thread() is threading.main_thread():
            stalled.set()
            let_go.wait(10)          # a filesystem that is not answering
        real_flush(revision, document)

    manager._flush = stalled_flush

    cancelled: list[int] = []

    def shut_down():
        stalled.wait(5)
        # The write is in progress and going nowhere. Neither of these may
        # wait for it.
        cancelled.append(manager.stop_all())
        manager.listing()
        manager.running_ids()
        let_go.set()

    helper = threading.Thread(target=shut_down)
    helper.start()
    manager.start("while the disk is stalled")
    helper.join(15)
    settle(manager)

    assert cancelled == [1], (
        "stop_all() did not run while the write was stalled -- shutdown is "
        "waiting on the disk")


def test_the_lifecycle_lock_is_never_held_across_a_write():
    """The invariant behind the one above, checked in the source.

    A write is the only unbounded operation here. Holding the lifecycle lock
    across one makes every other caller -- `stop_all()`, `slots_busy`,
    `listing()`, `wait()` -- wait on a disk, and that is what hung shutdown.

    Checked structurally rather than by timing, because the property is about
    where the call sits and a test that measured it would be measuring the
    filesystem.
    """
    import ast
    import inspect

    from comodor.agent import background

    tree = ast.parse(inspect.getsource(background))
    held: list[int] = []

    def locking(node) -> bool:
        return any(
            isinstance(item.context_expr, ast.Attribute)
            and item.context_expr.attr in {"_lock", "_settled"}
            for item in getattr(node, "items", []))

    def walk(node, under_lock: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr in {"_flush", "_flush_or_catch_up",
                                            "_write"}
                    and under_lock):
                held.append(child.lineno)
            walk(child, under_lock
                 or (isinstance(child, ast.With) and locking(child)))

    walk(tree, under_lock=False)

    assert held == [], f"_flush called while holding the lock at {held}"


def test_a_lower_revision_never_becomes_the_durable_state(config, bus, tmp_path):
    """Writing outside the lock is safe only because the revision orders it.

    Physical completion order is reversed deliberately here: the newer
    snapshot is written first and the older one attempted afterwards. The
    older one must be dropped.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        older = manager._stage()                 # says "running"
        manager._runs["d1"].state = "done"
        newer = manager._stage()                 # says "done"

    manager._flush(*newer)                       # the newer one lands first
    manager._flush(*older)                       # the older one arrives late

    flushed(manager)
    assert states(persist) == {"d1": "done"}, "a stale revision was written"


def test_concurrent_writers_cannot_reorder_the_durable_state(config, bus,
                                                             tmp_path):
    """The same property under real threads, with the writes released in
    reverse order."""
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        older = manager._stage()
        manager._runs["d1"].state = "done"
        newer = manager._stage()

    newer_done = threading.Event()

    def write_newer():
        manager._flush(*newer)
        newer_done.set()

    def write_older():
        newer_done.wait(5)                       # strictly afterwards
        manager._flush(*older)

    threads = [threading.Thread(target=write_newer),
               threading.Thread(target=write_older)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)

    flushed(manager)
    assert states(persist) == {"d1": "done"}


def test_a_write_that_fails_leaves_the_manager_usable(config, bus, tmp_path):
    """An `OSError` from the filesystem must not corrupt the state machine,
    strand the lock, or stop the next delegate from running."""
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    real_flush = manager._flush
    refuse_once = [True]

    def sometimes(revision, document, timeout=None):
        if refuse_once[0]:
            refuse_once[0] = False
            raise OSError("no space left on device")
        real_flush(revision, document)

    manager._flush = sometimes

    with pytest.raises(OSError):
        manager.start("the one that cannot be written")

    # The lock is free, and the manager still works.
    assert manager.slots_busy <= 1
    manager._flush = real_flush
    manager.stop_all()
    settle(manager)

    ok, identifier, _ = manager.start("the one after it")
    assert ok
    settle(manager)
    flushed(manager)
    assert states(persist)[identifier] == "done"


def _holds_the_lock(node) -> bool:
    """Whether a `with` block holds the lifecycle lock.

    `_settled` is a Condition built on `_lock`, so entering it holds the same
    lock. A checker that knew only one of the two names would be reading the
    spelling rather than the property.
    """
    import ast

    return any(
        isinstance(item.context_expr, ast.Attribute)
        and item.context_expr.attr in {"_lock", "_settled"}
        for item in getattr(node, "items", []))


def _acquires_the_lock(node) -> bool:
    """Whether a statement is `... = self._lock.acquire(...)`."""
    import ast

    call = node.value if isinstance(node, (ast.Assign, ast.Expr)) else None
    return (isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "acquire"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr in {"_lock", "_settled"})


def test_the_real_shutdown_sequence_does_not_hang_or_leave_a_worker(config, bus,
                                                                    tmp_path):
    """The pair `_shutdown()` actually calls, in that order.

    `CoreService.close` does `stop_all()` and then `wait(SHUTDOWN_SECONDS)` before
    closing the tools and the history. Both used to be able to block on a
    stalled write, and the second could return having joined nothing.

    Driven here at the manager rather than through the whole App, because what
    is being checked belongs to the manager and an App fixture would bring a
    provider, a terminal and a history along with it.
    """
    from comodor.agent.background import SHUTDOWN_SECONDS as SHUTDOWN_JOIN_SECONDS

    persist = tmp_path / "delegates.json"
    release = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(release), persist=persist)

    stalled = threading.Event()
    let_go = threading.Event()
    real_flush = manager._flush

    def stalled_flush(revision, document, timeout=None):
        if threading.current_thread() is threading.main_thread():
            stalled.set()
            let_go.wait(10)
        real_flush(revision, document)

    manager._flush = stalled_flush

    outcome: list[tuple[float, int]] = []

    def shut_down():
        stalled.wait(5)
        started = time.monotonic()
        manager.stop_all()
        release.set()                     # the child notices the cancellation
        let_go.set()                      # and the write finally lands
        manager.wait(SHUTDOWN_JOIN_SECONDS)
        outcome.append((time.monotonic() - started, manager.slots_busy))

    helper = threading.Thread(target=shut_down)
    helper.start()
    manager.start("racing the shutdown")
    helper.join(20)
    settle(manager)

    assert outcome, "the shutdown helper never finished"
    taken, busy = outcome[0]
    assert taken < SHUTDOWN_JOIN_SECONDS + 1.0, (
        f"shutdown took {taken:.2f}s against a {SHUTDOWN_JOIN_SECONDS}s budget")
    assert busy == 0, (
        "wait() returned with a delegate still running: the tools and the "
        "history would be closed underneath it")


def test_wait_leaves_the_file_agreeing_with_the_manager(config, bus, tmp_path):
    """After `wait()` returns, what is on disk is what the manager believes.

    Taking the write off the lifecycle lock made "finished" and "written" two
    moments -- microseconds apart, but two. `_shutdown()` calls `wait()` and
    then closes everything, so that is the one place the gap would matter, and
    `wait()` closes it before returning.

    No `flushed()` here on purpose: this test is the assertion that waiting is
    enough on its own.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    manager.start("one")
    manager.wait(timeout=10)

    assert states(persist) == {"d1": "done"}
    assert manager._written == manager._revision, (
        "a staged snapshot was still unwritten when wait() returned")


def test_wait_does_not_queue_behind_a_write_that_is_already_stuck(config, bus,
                                                                  tmp_path):
    """The final flush must respect the budget it was given.

    A launch stalled inside its own write holds `_write_lock` for as long as
    the filesystem takes. `wait()` stages the unwritten state on the way out
    and writes it -- and an unbounded write there would queue behind the stuck
    one, after the deadline had already passed.

    The lock is held by this test rather than by a stalled delegate, which is
    the same thing from `wait()`'s side and does not depend on timing to
    arrange.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    # Something staged and not yet written, so the flush at the end has work.
    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        manager._stage()

    holding = threading.Event()
    let_go = threading.Event()

    def hold_the_writer():
        with manager._write_lock:
            holding.set()
            let_go.wait(10)

    holder = threading.Thread(target=hold_the_writer)
    holder.start()
    holding.wait(5)

    started = time.monotonic()
    manager.wait(timeout=0.3)
    taken = time.monotonic() - started

    let_go.set()
    holder.join(10)

    assert taken < 2.0, (
        f"wait(timeout=0.3) took {taken:.2f}s -- the final write queued "
        f"behind a stuck one instead of giving up")


def test_a_launch_cancelled_while_it_was_recorded_never_starts(config, bus,
                                                               tmp_path):
    """`stop_all()` during a launch must actually stop it.

    Cancelling before the worker starts does not survive: `AgentLoop.run()`
    opens with `cancel.reset()`, so a flag set a moment earlier is erased and
    the delegate runs on -- after `_shutdown()` has begun closing the tools
    and the history it would use.

    The window is held open at the record write, which is where it is widest.
    """
    persist = tmp_path / "delegates.json"
    ran = threading.Event()

    class Watched:
        def run(self, brief):
            ran.set()
            return FakeResult()

    manager = make_manager(config, bus, lambda **kwargs: Watched(),
                           persist=persist)

    seen: list = []
    bus.subscribe(seen.append)

    recording = threading.Event()
    let_go = threading.Event()
    real_flush = manager._flush

    def slow_flush(revision, document, timeout=None):
        real_flush(revision, document, timeout=timeout)
        if threading.current_thread() is threading.main_thread():
            recording.set()
            let_go.wait(10)

    manager._flush = slow_flush

    def shut_down():
        recording.wait(5)
        manager.stop_all()
        let_go.set()

    helper = threading.Thread(target=shut_down)
    helper.start()
    ok, identifier, why = manager.start("cancelled on the way in")
    helper.join(10)
    settle(manager)

    assert not ok, "a delegate cancelled before it started was reported started"
    assert "stopped" in why
    assert not ran.is_set(), "the worker ran after shutdown had begun"
    assert manager.slots_busy == 0

    flushed(manager)
    assert states(persist) == {"d1": "stopped"}

    # And the watchers are told it settled. `stop_all()` emitted `stopping`;
    # without a terminal event after it, a delegate panel shows one that never
    # finishes while the listing and the file both say it did.
    delegate_states = [event.payload.get("state") for event in seen
                       if event.kind is Kind.DELEGATE]
    assert "stopped" in delegate_states, delegate_states


def test_wait_gives_up_on_a_write_that_never_returns(config, bus, tmp_path):
    """A timeout on the lock does not bound the write itself.

    `write_text` returns when the filesystem says so and cannot be
    interrupted, so the final write happens on a thread `wait()` is willing to
    abandon. The file is then left one revision behind -- where an
    unresponsive disk was always going to leave it -- and shutdown still ends
    on time.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        manager._stage()

    inside = threading.Event()
    let_go = threading.Event()
    real_flush = manager._flush

    def never_returns(revision, document, timeout=None):
        inside.set()
        let_go.wait(10)                  # the write that does not come back
        real_flush(revision, document, timeout=timeout)

    manager._flush = never_returns

    started = time.monotonic()
    manager.wait(timeout=0.3)
    taken = time.monotonic() - started

    let_go.set()

    assert inside.is_set(), "the final write never began"
    assert taken < 2.0, (
        f"wait(timeout=0.3) took {taken:.2f}s -- the write itself is not "
        f"bounded, only the wait for the lock")


def test_wait_survives_a_runtime_that_will_not_start_the_final_writer(
        config, bus, tmp_path):
    """The last write is best-effort, and so is the thread that does it.

    `_shutdown()` still has the tools, the history and MCP to close after
    `wait()` returns. An exception escaping here would leave all of them open
    -- a far worse outcome than a file one revision behind.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        manager._stage()

    original = threading.Thread.start

    def refuse(self):
        if self.name == "comodor-delegate-final-write":
            raise RuntimeError("can't start new thread")
        original(self)

    threading.Thread.start = refuse
    try:
        manager.wait(timeout=1.0)          # must return, not raise
    finally:
        threading.Thread.start = original


def test_no_delegate_is_admitted_once_shutdown_has_begun(config, bus, tmp_path):
    """A turn reaching a delegate tool call during a shutdown.

    `stop_all()` cancels what it can see. One arriving after it is not in
    `_cancelled`, so nothing stopped it: if its record write outlasted
    `wait()`, the worker started once the disk answered -- against tools and a
    history `_shutdown()` had already closed.
    """
    persist = tmp_path / "delegates.json"
    ran = threading.Event()

    class Watched:
        def run(self, brief):
            ran.set()
            return FakeResult()

    manager = make_manager(config, bus, lambda **kwargs: Watched(),
                           persist=persist)

    manager.closing()
    manager.stop_all()

    ok, identifier, why = manager.start("too late")
    manager.wait(timeout=2.0)

    assert not ok
    assert "shutting down" in why
    assert not ran.is_set(), "a delegate started after shutdown had begun"
    assert manager.slots_busy == 0


def test_stopping_everything_is_not_shutting_down(config, bus, tmp_path):
    """`/stop` stops the delegates; it does not close the session.

    Latching in `stop_all()` would have been simpler and wrong: a user who
    stopped their delegates could never start another one.
    """
    persist = tmp_path / "delegates.json"
    release = threading.Event()
    manager = make_manager(config, bus,
                           lambda **kwargs: HeldLoop(release), persist=persist)

    manager.start("the first one")
    manager.stop_all()
    release.set()
    settle(manager)

    ok, identifier, _ = manager.start("and one after it")
    release.set()
    settle(manager)

    assert ok, "stopping everything must not close the manager"
    flushed(manager)
    assert states(persist)[identifier] == "done"


def test_no_event_says_a_settled_run_is_still_going(config, bus, tmp_path):
    """`stop()` emits `stopping` after releasing the lock, so a run that
    settles in between could have its terminal event overtaken -- and a panel
    would keep showing a delegate that had already finished.

    A settled run reports what it settled as, whoever is doing the telling.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    seen: list = []
    bus.subscribe(seen.append)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        manager._runs["d1"].state = "stopped"

    manager._emit("d1", "stopping")          # the late notice

    states_seen = [event.payload.get("state") for event in seen
                   if event.kind is Kind.DELEGATE]
    assert states_seen == ["stopped"], states_seen



def test_a_delegate_stopped_before_its_first_turn_never_runs(config, bus,
                                                             tmp_path):
    """The other half of the window `start()` closes.

    `start()` catches a cancellation that arrives before the thread exists.
    This is the one that arrives after: the thread is running but has not
    reached `loop.run()` yet, and `run()` opens with `cancel.reset()`, so the
    flag on its own is wiped by the first thing the child does with it.
    """
    persist = tmp_path / "delegates.json"
    ran = threading.Event()

    class Watched:
        def run(self, brief):
            ran.set()
            return FakeResult()

    manager = make_manager(config, bus, lambda **kwargs: Watched(),
                           persist=persist)

    # The worker is parked on its way in, so the cancellation lands after the
    # thread is alive and before it has touched the loop -- the exact window,
    # held open by an event rather than hoped for.
    entered = threading.Event()
    released = threading.Event()
    work = manager._work

    def parked(*arguments):
        entered.set()
        assert released.wait(30.0), "the worker was never released"
        work(*arguments)

    manager._work = parked

    ok, identifier, _ = manager.start("a turn that is about to be stopped")
    assert ok
    assert entered.wait(30.0), "the worker never started"

    manager.stop_all()
    released.set()
    manager.wait(timeout=30.0)
    flushed(manager)

    assert not ran.is_set(), "the loop ran after the delegate was stopped"
    assert states(persist)[identifier] == "stopped"
    assert manager.running_ids() == []


def test_a_delegate_stop_survives_the_loop_resetting_it():
    """The one line every check-then-act in this file was working around.

    `AgentLoop.run()` opens with `cancel.reset()`. For a delegate a stop is
    terminal, so the handle refuses to un-cancel itself -- and no window before
    the child's first step can erase what a user asked for.
    """
    cancel = DelegateCancellation()

    cancel.reset()
    assert not cancel.cancelled, "an untouched handle should reset freely"

    cancel.cancel()
    cancel.reset()
    assert cancel.cancelled, "the stop was erased by the child's start-up"
    with pytest.raises(Cancelled):
        cancel.raise_if_cancelled()


def test_a_stop_during_the_childs_construction_is_not_erased(config, bus,
                                                             tmp_path):
    """The window a check inside `_work` cannot close.

    Building the child's loop and toolset takes real time. A `stop_all()`
    landing in the middle of it is past every check `_work` could make, and
    used to be erased by `run()` the moment construction finished.
    """
    persist = tmp_path / "delegates.json"
    building = threading.Event()
    release = threading.Event()
    ran = threading.Event()

    class Child:
        def __init__(self, cancel):
            self.cancel = cancel

        def run(self, brief):
            # What `AgentLoop.run` does: reset on the way in, and catch its own
            # `Cancelled` on the first step -- `loop.py:163`.
            self.cancel.reset()
            try:
                self.cancel.raise_if_cancelled()
            except Cancelled:
                return FakeResult(text="", stopped="cancelled")
            ran.set()
            return FakeResult()

    def slow_spawner(**kwargs):
        building.set()
        assert release.wait(30.0), "construction was never released"
        return Child(kwargs["cancel"])

    manager = make_manager(config, bus, slow_spawner, persist=persist)

    ok, identifier, _ = manager.start("a turn stopped mid-construction")
    assert ok
    assert building.wait(30.0), "the child was never constructed"

    manager.stop_all()
    release.set()
    manager.wait(timeout=30.0)
    flushed(manager)

    assert not ran.is_set(), "the stop was lost while the child was built"
    assert states(persist)[identifier] == "stopped"
    assert manager.running_ids() == []



class Interleaved(DelegateCancellation):
    """A handle that stops itself at the worst possible instant.

    `reset()` reads the flag and then clears it. This one cancels from another
    thread while that read is happening, which is the only moment where a stop
    can be made and then thrown away.
    """

    def __init__(self) -> None:
        super().__init__()
        self.calling = threading.Event()
        self.reached = threading.Event()
        self.stopper = threading.Thread(target=self._stop, daemon=True)

    def _stop(self) -> None:
        self.calling.set()
        self.cancel()

    @property
    def cancelled(self) -> bool:
        answer = super().cancelled
        if not self.reached.is_set():
            self.reached.set()
            self.stopper.start()
            assert self.calling.wait(30.0), "the stop was never attempted"
            # The stop is in flight. Where the check and the clear are one
            # operation it has to wait for this one to finish; where they are
            # two it lands between them. The bound is an escape hatch, not the
            # thing being measured -- it cannot be met while the pair is held
            # together, and two seconds is not a race for a set() that has
            # already been entered.
            self.stopper.join(timeout=2.0)
        return answer


def test_a_stop_is_never_lost_between_the_check_and_the_clear():
    """The race this class exists to remove, reintroduced one level down."""
    cancel = Interleaved()

    cancel.reset()
    cancel.stopper.join(30.0)
    assert not cancel.stopper.is_alive()

    assert cancel.cancelled, "a stop made during reset() was thrown away"


def test_no_event_walks_a_run_backwards(config, bus, tmp_path):
    """A `started` overtaken by a `stopping` must not undo it.

    Both events are prepared on one thread and sent on another, so either can
    arrive second. The run is still `running` at that moment, so preferring a
    terminal state does not help -- there is not one yet.
    """
    manager = make_manager(config, bus, persist=tmp_path / "delegates.json")

    seen: list = []
    bus.subscribe(seen.append)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")

    manager._emit("d1", "stopping")
    manager._emit("d1", "started")           # the overtaken notice

    states_seen = [event.payload.get("state") for event in seen
                   if event.kind is Kind.DELEGATE]
    assert states_seen == ["stopping", "stopping"], states_seen


def test_a_stop_landing_mid_launch_is_not_undone_by_started(config, bus,
                                                            tmp_path):
    """The same thing along the real path.

    `stop()` runs once the worker is registered and before `start()` has
    emitted; forced here rather than waited for.
    """
    persist = tmp_path / "delegates.json"
    release = threading.Event()
    manager = make_manager(config, bus, lambda **kwargs: HeldLoop(release),
                           persist=persist)

    seen: list = []
    bus.subscribe(seen.append)

    emit = manager._emit
    stopped_first = threading.Event()

    def racing(identifier, state):
        if state == "started" and not stopped_first.is_set():
            stopped_first.set()
            manager.stop(identifier)         # emits `stopping` first
        emit(identifier, state)

    manager._emit = racing

    ok, identifier, _ = manager.start("a turn stopped as it starts")
    assert ok
    assert stopped_first.is_set(), "the stop never raced the start"

    states_seen = [event.payload.get("state") for event in seen
                   if event.kind is Kind.DELEGATE]
    assert "started" not in states_seen, states_seen
    # Which state comes first is the run's business, not this test's: if it
    # had already settled by then, `stopped` is the honest answer and
    # `stopping` would be the lie. What must hold either way is that nothing
    # goes backwards.
    steps = [BackgroundDelegates.PROGRESS[state] for state in states_seen]
    assert steps == sorted(steps), states_seen

    release.set()
    manager.stop_all()
    manager.wait(timeout=30.0)


def test_events_reach_the_bus_in_the_order_they_were_decided(config, bus,
                                                             tmp_path):
    """Deciding in order is not enough; they have to be sent in order too.

    A thread that has decided `started` can be descheduled after it lets go of
    the lifecycle lock and before it sends. Another decides *and sends*
    `stopping`, and the first then sends a payload that is already out of date
    -- so a panel is told the run it just stopped is alive again.

    The hand-off is forced at exactly that point: the payload is finished, the
    lifecycle lock is released, nothing has been sent.
    """
    manager = make_manager(config, bus, persist=tmp_path / "delegates.json")

    seen: list = []
    bus.subscribe(seen.append)

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")

    sent = threading.Event()
    other = threading.Thread(
        target=lambda: (manager._emit("d1", "stopping"), sent.set()),
        daemon=True)

    class HandsOver(dict):
        """Lets the other thread try to overtake, once, at the worst moment."""

        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if key == "state" and value == "started" and not other.is_alive():
                other.start()
                # Where deciding and sending are one step the other thread
                # cannot get past the door and this bound is never met; where
                # they are two it sails through. The bound is the escape
                # hatch, not the assertion.
                sent.wait(2.0)

    shape = manager._runs["d1"].as_dict
    manager._runs["d1"].as_dict = lambda: HandsOver(shape())

    manager._emit("d1", "started")
    other.join(30.0)
    assert not other.is_alive()

    states_seen = [event.payload.get("state") for event in seen
                   if event.kind is Kind.DELEGATE]
    assert states_seen == ["started", "stopping"], states_seen


def test_the_bus_is_never_told_anything_under_the_lifecycle_lock():
    """`bus.emit` runs a subscriber, which is arbitrary code.

    Under `_lock` that would make every panel, log and web session a party to
    the manager's own deadlocks -- and the lock order here is `_telling` then
    `_lock`, never the reverse, so an `_emit` under `_lock` could invert it.
    """
    import ast

    from comodor.agent import background

    source = Path(background.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    def holds_the_lifecycle_lock(node):
        return isinstance(node, ast.With) and any(
            isinstance(item.context_expr, ast.Attribute)
            and item.context_expr.attr in {"_lock", "_settled"}
            for item in node.items)

    offenders = []
    for node in ast.walk(tree):
        if not holds_the_lifecycle_lock(node):
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr in {"_emit", "emit"}):
                offenders.append(inner.lineno)

    assert not offenders, (
        f"the bus is told something under the lifecycle lock at {offenders}")


def test_a_subscriber_emitting_cannot_jump_the_queue_it_is_in(config, bus,
                                                              tmp_path):
    """A subscriber that stops a delegate on hearing it started.

    That call re-enters the manager on the same thread, so a reentrant lock
    lets it straight through. The subscriber that made the call has already
    heard `started`; every subscriber behind it in the delivery hears
    `stopping` first and `started` afterwards -- told the run came back.
    """
    manager = make_manager(config, bus, persist=tmp_path / "delegates.json")

    with manager._lock:
        manager._runs["d1"] = DelegateRun(id="d1", brief="one")
        manager._cancels["d1"] = DelegateCancellation()

    def stopper(event):
        if (event.kind is Kind.DELEGATE
                and event.payload.get("state") == "started"):
            manager.stop("d1")               # straight back in, same thread

    behind: list = []

    def listener(event):
        if event.kind is Kind.DELEGATE:
            behind.append(event.payload.get("state"))

    bus.subscribe(stopper)
    bus.subscribe(listener)                  # behind it in the delivery

    manager._emit("d1", "started")

    assert behind == ["started", "stopping"], behind


def test_a_failed_write_does_not_let_an_older_snapshot_in(config, bus,
                                                          tmp_path,
                                                          monkeypatch):
    """A newer write that fails must still close the door on older ones.

    Two delegates finish together, so an older staged snapshot can still be
    in flight when a newer one reaches the disk. If the newer write fails and
    the older one is then admitted, the file ends up saying a delegate that
    has finished is running -- and a reload calls it lost. Dropping it says
    nothing at all, which is true.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["a"] = DelegateRun(id="a", brief="one")
        manager._runs["b"] = DelegateRun(id="b", brief="two")
        older = manager._stage()                 # both running

    with manager._lock:
        manager._runs["a"].state = "done"
        manager._runs["a"].answer = "finished"
        newer = manager._stage()                 # `a` has finished

    def refusing(self, *arguments, **keywords):
        raise OSError("the disk said no")

    monkeypatch.setattr(Path, "write_text", refusing)
    manager._flush(*newer)
    monkeypatch.undo()

    manager._flush(*older)                       # the delayed older write

    assert not persist.exists(), (
        f"a snapshot the manager knew was stale became the record: "
        f"{states(persist)}")

    # And the state is not lost: the next write carries a newer number.
    manager.wait(timeout=30.0)
    flushed(manager)
    assert states(persist)["a"] == "done"


def test_a_launch_whose_snapshot_is_refused_is_still_recorded(config, bus,
                                                              tmp_path):
    """A refusal is not a reason to leave a delegate off the disk.

    A launch stages its record and writes it before the worker exists, so a
    crash in that gap still leaves evidence of the delegate. If a completing
    delegate's newer write reaches the disk first and fails, the launch's
    snapshot is stale by the time it is offered -- correctly refused, and the
    launch would have had no record at all.

    The newer write is made to happen in exactly that gap, between the
    launch's stage and its flush.
    """
    persist = tmp_path / "delegates.json"
    release = threading.Event()
    manager = make_manager(config, bus, lambda **kwargs: HeldLoop(release),
                           persist=persist)

    with manager._lock:
        manager._runs["old"] = DelegateRun(id="old", brief="finished")
        manager._runs["old"].state = "done"

    write = manager._flush
    once = threading.Event()

    def racing(revision, document, timeout=None):
        if not once.is_set():
            once.set()
            with manager._lock:
                newer = manager._stage()
            def refusing(*arguments, **keywords):
                raise OSError("the disk said no")
            kept, Path.write_text = Path.write_text, refusing
            try:
                write(*newer)                    # fails, but takes the number
            finally:
                Path.write_text = kept
        return write(revision, document, timeout)

    manager._flush = racing
    ok, identifier, _ = manager.start("a launch behind a failed write")
    manager._flush = write
    assert ok

    # Asserted here, not after the worker has been and gone: `start()` writes
    # the record before the worker exists precisely so a crash in that gap
    # still leaves evidence. A later write by somebody else is not the same
    # guarantee, and waiting for one would let this test agree with the bug.
    assert persist.exists(), "the launch left no record at all"
    assert identifier in states(persist), (
        f"the launch left no record: {persisted(persist)}")

    release.set()
    manager.stop_all()
    manager.wait(timeout=30.0)


def test_the_catch_up_cannot_itself_be_overtaken(config, bus, tmp_path):
    """Trying again and hoping is not a fix.

    The repair stages a fresh number, and a number can be overtaken exactly as
    the first one was -- so a catch-up that lets go in between is a race with
    fewer rounds, not one fewer. It holds the write lock across numbering and
    writing, and the proof is that a competitor trying to slip in during the
    repair cannot.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    with manager._lock:
        manager._runs["a"] = DelegateRun(id="a", brief="one")
        stale = manager._stage()

    with manager._lock:
        manager._runs["a"].state = "done"
        newer = manager._stage()

    def refusing(*arguments, **keywords):
        raise OSError("the disk said no")

    kept, Path.write_text = Path.write_text, refusing
    try:
        manager._flush(*newer)               # fails, and takes the number
    finally:
        Path.write_text = kept

    # A competitor that attempts a newer write, and fails, the moment the
    # repair lets go of the write lock. Written as the mark a failed write
    # leaves rather than as another patched `write_text`, because patching
    # that from a second thread would break the repair's own write and prove
    # the wrong thing.
    stage = manager._stage
    competitor_done = threading.Event()

    def competing():
        with manager._write_lock:
            manager._attempted = manager._revision + 1
        competitor_done.set()

    other = threading.Thread(target=competing, daemon=True)
    slipped = threading.Event()

    def racing():
        numbered = stage()
        if not slipped.is_set():
            slipped.set()
            other.start()
            # The bound is the escape hatch: the competitor cannot get in
            # while the repair holds the write lock, and two seconds is not a
            # race for a thread that is free to run.
            competitor_done.wait(2.0)
        return numbered

    manager._stage = racing
    manager._flush_or_catch_up(stale)
    manager._stage = stage
    other.join(30.0)
    assert not other.is_alive()

    assert persist.exists(), "the repair never landed"
    assert states(persist)["a"] == "done"


def test_a_rollback_refused_as_stale_is_still_written(config, bus, tmp_path):
    """A launch that could not start must not stay on the disk.

    The rollback matters as much as the record it undoes: refused, the file
    keeps a `running` delegate that never existed, and the next session calls
    it lost -- for work nobody ever did.

    The newer failed write is placed between the rollback being staged and
    being written, which is the only order that makes it stale.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    write = manager._flush
    calls = []

    def racing(revision, document, timeout=None):
        calls.append(revision)
        if len(calls) == 2:                  # the rollback, on its way out
            with manager._lock:
                newer = manager._stage()

            def refusing(*arguments, **keywords):
                raise OSError("the disk said no")

            kept, Path.write_text = Path.write_text, refusing
            try:
                write(*newer)                # fails, and takes the number
            finally:
                Path.write_text = kept
        return write(revision, document, timeout)

    class Refused:
        """A thread the runtime will not start."""

        def start(self):
            raise RuntimeError("no threads today")

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    manager._flush = racing
    kept_thread, threading.Thread = threading.Thread, lambda *a, **k: Refused()
    try:
        ok, _, why = manager.start("a launch the runtime refuses")
    finally:
        threading.Thread = kept_thread
        manager._flush = write

    assert not ok and "could not be started" in why
    assert states(persist) == {}, (
        f"a delegate that never ran was left on the disk: {states(persist)}")


def test_every_unbounded_write_repairs_a_refusal():
    """One rule instead of one review round per call site.

    `_flush` can refuse -- a newer write was tried and failed -- and a caller
    that ignores the answer leaves the disk behind with nobody coming back.
    Every write outside `_flush_or_catch_up` therefore has to be the one that
    cannot repair: shutdown's, which has a budget, and a repair is unbounded
    by construction.
    """
    import ast
    import inspect

    from comodor.agent import background

    tree = ast.parse(inspect.getsource(background))
    bare: list[int] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_flush"):
            continue
        bounded = any(keyword.arg == "timeout" for keyword in node.keywords)
        inside_the_repair = any(
            isinstance(parent, ast.FunctionDef)
            and parent.name == "_flush_or_catch_up"
            for parent in ast.walk(tree)
            if isinstance(parent, ast.FunctionDef)
            and node.lineno >= parent.lineno
            and node.lineno <= max(
                child.lineno for child in ast.walk(parent)
                if hasattr(child, "lineno")))
        if not bounded and not inside_the_repair:
            bare.append(node.lineno)

    assert not bare, (
        f"a write that cannot repair a refusal, at {bare}; use "
        f"_flush_or_catch_up unless it is the bounded shutdown write")


def test_a_pre_start_stop_refused_as_stale_is_still_written(config, bus,
                                                            tmp_path):
    """A delegate stopped before its first turn is terminal, so it must land.

    Refused, the file keeps it `running` and the next session calls it lost --
    the exact lie this file exists to stop, for a delegate that was stopped on
    purpose.
    """
    persist = tmp_path / "delegates.json"
    ran = threading.Event()

    class Watched:
        def run(self, brief):
            ran.set()
            return FakeResult()

    manager = make_manager(config, bus, lambda **kwargs: Watched(),
                           persist=persist)

    entered = threading.Event()
    released = threading.Event()
    work = manager._work

    def parked(*arguments):
        entered.set()
        assert released.wait(30.0), "the worker was never released"
        work(*arguments)

    manager._work = parked

    write = manager._flush
    once = threading.Event()

    def racing(revision, document, timeout=None):
        if not once.is_set():
            # A newer write, failing, between this snapshot being numbered and
            # being offered -- which is what makes it stale.
            once.set()
            with manager._lock:
                newer = manager._stage()

            def refusing(*arguments, **keywords):
                raise OSError("the disk said no")

            kept, Path.write_text = Path.write_text, refusing
            try:
                write(*newer)           # fails, and takes the number
            finally:
                Path.write_text = kept
        return write(revision, document, timeout)

    # The stop is recorded and then announced, so the announcement is the
    # signal that the record is as final as it is going to get.
    settled = threading.Event()
    emit = manager._emit

    def watching(identifier_, state):
        emit(identifier_, state)
        if state == "stopped":
            settled.set()

    ok, identifier, _ = manager.start("a turn that is about to be stopped")
    assert ok
    assert entered.wait(30.0), "the worker never started"

    manager._emit = watching
    manager._flush = racing
    manager.stop_all()
    released.set()
    assert settled.wait(30.0), "the worker never recorded the stop"
    manager._flush = write
    manager._emit = emit

    # Asserted before `wait()`, which stages a fresh snapshot on the way out
    # and would repair this for free -- a guarantee that only holds at
    # shutdown is not the guarantee a running session needs.
    assert not ran.is_set(), "the loop ran after it had been stopped"
    assert states(persist)[identifier] == "stopped", (
        f"a stopped delegate was left on the disk as running: "
        f"{states(persist)}")

    manager.wait(timeout=30.0)
