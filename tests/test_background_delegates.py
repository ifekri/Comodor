"""Background delegates: slots, turn-boundary delivery, honest crashes."""

from __future__ import annotations

import json
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

    `escape` is what stops a *fixed* implementation from deadlocking here. Once
    the snapshot and the write are one atomic step under the lock, the worker
    cannot reach its own write while the main thread waits — so the wait has to
    end by itself. It does not decide the outcome, only how long the correct
    path pauses: on the broken code the worker writes and the wait ends early,
    and on the fixed code the wait expires and the assertion still holds.
    """

    def __init__(self, manager, escape: float = 0.5) -> None:
        self.manager = manager
        self.escape = escape
        self.snapshotted = threading.Event()
        self.worker_wrote = threading.Event()
        self._real_snapshot = manager._snapshot
        self._real_persist = manager._persist
        self.main_thread = threading.current_thread()

        manager._snapshot = self._snapshot
        manager._persist = self._persist

    def _snapshot(self):
        document = self._real_snapshot()
        if threading.current_thread() is self.main_thread:
            # The main thread has read the state. Let the worker finish, then
            # hold here so its write lands first.
            self.snapshotted.set()
            self.worker_wrote.wait(self.escape)
        return document

    def _persist(self):
        self._real_persist()
        if threading.current_thread() is not self.main_thread:
            self.worker_wrote.set()


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
            and item.context_expr.attr == "_lock"
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
    real_persist = manager._persist

    def slow_persist():
        real_persist()
        if threading.current_thread() is threading.main_thread():
            inside.set()
            release.wait(5)

    manager._persist = slow_persist

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
    real_persist = manager._persist

    def slow_persist():
        real_persist()
        if threading.current_thread() is threading.main_thread():
            launching.set()
            time.sleep(0.05)          # long enough for wait() to be waiting

    manager._persist = slow_persist

    busy_when_wait_returned: list[int] = []

    def shut_down():
        launching.wait(5)
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
            and item.context_expr.attr == "_lock"
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


def test_waiting_is_bounded_even_when_the_disk_is_slow(config, bus, tmp_path):
    """`wait(timeout)` is a budget for the whole call, lock included.

    `start()` holds the lock across a write to the user directory. On a
    network mount or a full disk that write can take as long as it likes, and
    an unbounded acquisition here would let a two-second shutdown hang for
    exactly as long -- after which `_shutdown()` closes the tools and the
    history under a live worker anyway.

    Measured rather than asserted in the abstract: with a three-second stall
    in the persist, a two-second wait took 3.00s before this and 2.01s after.
    """
    persist = tmp_path / "delegates.json"
    manager = make_manager(config, bus, persist=persist)

    stalled = threading.Event()
    real_persist = manager._persist

    def slow_persist():
        real_persist()
        if threading.current_thread() is threading.main_thread():
            stalled.set()
            time.sleep(1.5)          # a filesystem that is not answering

    manager._persist = slow_persist

    taken: list[float] = []

    def shut_down():
        stalled.wait(5)
        started = time.monotonic()
        manager.wait(timeout=0.4)
        taken.append(time.monotonic() - started)

    helper = threading.Thread(target=shut_down)
    helper.start()
    manager.start("while the disk is slow")
    helper.join(15)
    settle(manager)

    assert taken, "the shutdown helper never ran"
    assert taken[0] < 1.0, (
        f"wait(timeout=0.4) took {taken[0]:.2f}s -- the budget does not cover "
        f"acquiring the lock, so shutdown can hang on a slow write")


def _holds_the_lock(node) -> bool:
    """Whether a `with` block is `with self._lock:`."""
    import ast

    return any(
        isinstance(item.context_expr, ast.Attribute)
        and item.context_expr.attr == "_lock"
        for item in getattr(node, "items", []))


def _acquires_the_lock(node) -> bool:
    """Whether a statement is `... = self._lock.acquire(...)`."""
    import ast

    call = node.value if isinstance(node, (ast.Assign, ast.Expr)) else None
    return (isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "acquire"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "_lock")
