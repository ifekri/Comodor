"""The cron module: schedule parsing, the job store, and the tick.

Time is injected everywhere a clock is read, so the tests turn the hours by
hand and the suite runs in milliseconds.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timedelta

import pytest

from comodor.config import Config, CronConfig
from comodor.cron.jobs import Job, JobError, JobStore
from comodor.cron.parse import Schedule, UnparsableSchedule, next_fire, parse
from comodor.cron.scheduler import Scheduler, _keep_answer, _record

# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #

def test_an_interval_is_parsed():
    for text, seconds in (("every 2h", 7200), ("every 30m", 1800),
                          ("every 90s", 90), ("weekly", 604_800)):
        schedule = parse(text)
        assert schedule.kind == "interval", text
        assert schedule.seconds == seconds, text


def test_a_one_shot_from_a_duration_is_parsed():
    schedule = parse("in 45m")
    assert schedule.kind == "once"
    assert schedule.at is not None
    # The fire time sits in the future, near where "45 minutes" means.
    delta = schedule.at - datetime.now()
    assert timedelta(minutes=44) < delta < timedelta(minutes=46)


def test_a_named_time_compiles_to_a_cron_expression():
    schedule = parse("weekdays at 9am")
    assert schedule.kind == "cron"
    assert schedule.expr == "0 9 * * 1,2,3,4,5"

    schedule = parse("mon and thu at 9:30")
    assert schedule.expr == "30 9 * * 1,4"


def test_a_cron_expression_is_accepted():
    assert parse("0 9 * * 1-5").kind == "cron"
    assert parse("*/15 * * * *").kind == "cron"


def test_garbage_is_refused_with_advice():
    with pytest.raises(UnparsableSchedule) as problem:
        parse("whenever it feels right")
    assert "schedule" in str(problem.value).lower()


# --------------------------------------------------------------------------- #
# next fire
# --------------------------------------------------------------------------- #

def test_the_next_cron_fire_is_the_next_matching_minute():
    schedule = parse("0 9 * * 1-5")
    # A Tuesday evening: the next fire is Wednesday at nine.
    after = datetime(2026, 9, 1, 20, 0)          # a Tuesday
    nxt = next_fire(schedule, after, after)
    assert nxt == datetime(2026, 9, 2, 9, 0)

    # A Friday at 9:05: the next fire is Monday, not Saturday.
    after = datetime(2026, 9, 4, 9, 5)           # a Friday
    nxt = next_fire(schedule, after, after)
    assert nxt == datetime(2026, 9, 7, 9, 0)


def test_the_next_interval_fire_steps_from_creation():
    schedule = Schedule(kind="interval", expr="every 1h", seconds=3600)
    created = datetime(2026, 9, 1, 9, 0)
    after = datetime(2026, 9, 1, 10, 30)
    assert next_fire(schedule, after, created) == datetime(2026, 9, 1, 11, 0)


def test_a_past_one_shot_never_fires_again():
    schedule = parse("2026-09-01 09:00")
    after = datetime(2026, 9, 15, 9, 0)
    assert next_fire(schedule, after, after) is None


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #

@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "cron")


def make_job(name: str = "nightly", prompt: str = "summarise the day",
             **fields) -> Job:
    job = Job(id="job1", name=name, prompt=prompt,
              schedule=parse("daily at 9am"),
              project="/tmp/project", created="2026-08-01T00:00:00")
    for key, value in fields.items():
        setattr(job, key, value)
    return job


def test_a_job_survives_a_round_trip(store):
    store.add(make_job())
    loaded = store.get("job1")
    assert loaded is not None
    assert loaded.prompt == "summarise the day"
    assert loaded.schedule.expr == "0 9 * * 0,1,2,3,4,5,6"  # daily, cron-numbered


def test_a_duplicate_name_is_refused(store):
    store.add(make_job())
    with pytest.raises(JobError):
        store.add(make_job())


def test_a_job_without_a_prompt_is_refused(store):
    with pytest.raises(JobError):
        store.add(make_job(prompt="   "))


def test_an_update_and_a_removal_work(store):
    store.add(make_job())
    store.update("job1", lambda job: (setattr(job, "enabled", False), job)[1])
    assert store.get("job1").enabled is False
    removed = store.remove("job1")
    assert removed.name == "nightly"
    assert store.get("job1") is None


# --------------------------------------------------------------------------- #
# the tick
# --------------------------------------------------------------------------- #

@pytest.fixture
def config(tmp_path):
    from dataclasses import replace

    base = Config()
    return replace(base,
                   paths=replace(base.paths, user=tmp_path / "home"),
                   cron=CronConfig(enabled=True))


def test_a_due_job_fires_and_records_the_result(config, store, monkeypatch):
    # An hourly job created two hours ago is overdue no matter what the
    # wall clock says, which keeps the test off the time of day.
    job = make_job(name="hourly")
    job.schedule = parse("every 1h")
    job.created = (datetime.now() - timedelta(hours=2)).isoformat()
    store.add(job)
    fired = []

    monkeypatch.setattr("comodor.cron.scheduler.Scheduler._run_and_record",
                        lambda self, job, now: fired.append(job.id) or
                        store.update(job.id, lambda j: _mark(j)))
    scheduler = Scheduler(config, store=store, tick=60)
    due = scheduler.tick(now=datetime.now())
    assert due == ["job1"]
    assert fired == ["job1"]


def _mark(job):
    job.last_fire = datetime.now().isoformat()
    job.last_result = "ok"
    return job


def test_a_disabled_job_does_not_fire(config, store):
    job = make_job(created=(datetime.now() - timedelta(days=1)).isoformat())
    job.enabled = False
    store.add(job)
    scheduler = Scheduler(config, store=store, tick=60)
    assert scheduler.tick(now=datetime.now()) == []


def test_the_scheduler_is_inert_while_disabled(config, store):
    config.cron.enabled = False
    store.add(make_job())
    scheduler = Scheduler(config, store=store, tick=60)
    assert scheduler.tick(now=datetime.now()) == []


def test_a_job_pauses_after_a_failure_streak(config):
    config.cron.failure_streak = 2
    from comodor.cron.scheduler import _record

    job = make_job()
    _record(job, datetime.now(), ok=False, error="boom", streak_limit=2)
    assert job.enabled and job.failure_streak == 1
    _record(job, datetime.now(), ok=False, error="boom", streak_limit=2)
    assert not job.enabled, "two failures in a row should pause the job"
    assert "paused" in job.last_error


def test_a_success_resets_the_streak(config, store):
    from comodor.cron.scheduler import _record

    job = make_job()
    job.failure_streak = 1
    _record(job, datetime.now(), ok=True, error="", streak_limit=3)
    assert job.failure_streak == 0
    assert job.enabled


def test_a_misfired_job_still_fires_within_the_grace_window(config, store):
    """A laptop waking from sleep fires late, once — not never."""
    job = make_job(created="2026-08-01T00:00:00")
    job.schedule = parse("daily at 9am")
    store.add(job)

    scheduler = Scheduler(config, store=store, tick=60)
    # The 9am fire was missed by eight minutes; ten are allowed.
    late = datetime(2026, 9, 3, 9, 8)
    assert scheduler.tick(now=late) == ["job1"]


def _answer_mark(job):
    _mark(job)
    job.last_answer = "the scheduled answer"
    return job


def _fake_run(store, outcome):
    """What _run_and_record does, minus the agent: record, keep the answer,
    then let the scheduler's own delivery run for real.

    The `finally` matters as much as the body. This replaces the whole method,
    including the clause that takes the job out of `_running` — and that set
    is how anything else knows the thread is done. Without it a caller waiting
    for the scheduler to settle waits for ever.
    """
    def run(self, job, now):
        try:
            store.update(job.id, lambda j: _record(j, now, outcome.ok,
                                                   outcome.error))
            store.update(job.id, _keep_answer(outcome))
            self._deliver_to_channels(job, outcome)
        finally:
            with self._lock:
                self._running.discard(job.id)
    return run


def _tick_and_settle(scheduler, store, patience: float = 30.0):
    """Fire a tick and wait for the job's thread to actually finish.

    Waiting on `last_fire` was the obvious thing and the wrong one: the
    scheduler records it and *then* delivers, so the flag appears while the
    thread still has work to do. The helper slept ten more milliseconds and
    called that settled, which held on an idle desktop and lost on a loaded CI
    runner — `sent == []` on a delivery that had not happened yet, in one test
    or another, roughly one run in ten.

    `_running` is emptied in the thread's `finally`, after everything: the
    record, the answer, the delivery and the log. That is what "finished"
    means, so that is what this waits for. `tick` fills it before it returns,
    so a tick that started nothing leaves it empty and this comes back at
    once — which is correct.
    """
    scheduler.tick(now=datetime.now())

    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        with scheduler._lock:
            still_going = bool(scheduler._running)
        if not still_going:
            # The thread has left `_run_and_record`, so every write it makes
            # is done. Nothing after this is waiting on a race.
            return
        time.sleep(0.01)

    raise AssertionError(
        f"a job thread was still running {patience:.0f}s after the tick: "
        f"{scheduler._running}")


class _Outcome:
    def __init__(self, answer="the scheduled answer", ok=True, error=""):
        self.ok = ok
        self.answer = answer
        self.error = error


def test_an_answer_is_kept_on_the_job_record(config, store, monkeypatch):
    """The scheduler stores the answer on the job itself, so a crash in the
    delivery path can never lose the words — the job always holds them."""
    job = make_job(name="hourly")
    job.schedule = parse("every 1h")
    job.created = (datetime.now() - timedelta(hours=2)).isoformat()
    store.add(job)

    monkeypatch.setattr("comodor.cron.scheduler.Scheduler._run_and_record",
                        _fake_run(store, _Outcome()))
    scheduler = Scheduler(config, store=store, tick=60)
    _tick_and_settle(scheduler, store)

    assert store.get("job1").last_answer == "the scheduled answer"


def test_a_channel_target_is_delivered_through_the_ledger(
        config, store, tmp_path, monkeypatch):
    """A job naming `telegram:123` has its answer sent there, through the
    delivery ledger, and the send is recorded in the platform's file."""
    from comodor.channels.ledger import DeliveryLedger

    job = make_job(name="hourly")
    job.schedule = parse("every 1h")
    job.created = (datetime.now() - timedelta(hours=2)).isoformat()
    job.delivery = ["telegram:123"]
    store.add(job)
    config = dataclasses.replace(
        config, paths=dataclasses.replace(config.paths, user=tmp_path / "home"))

    sent: list[tuple[object, str]] = []
    monkeypatch.setattr("comodor.cron.deliver._sender",
                        lambda platform, cfg: lambda chat, body:
                        sent.append((chat, body)))
    monkeypatch.setattr("comodor.cron.scheduler.Scheduler._run_and_record",
                        _fake_run(store, _Outcome()))
    scheduler = Scheduler(config, store=store, tick=60)
    _tick_and_settle(scheduler, store)

    assert sent == [("123", "the scheduled answer")]
    ledger = DeliveryLedger(tmp_path / "home" / "delivery" / "telegram.jsonl",
                            "telegram")
    assert ledger.unclaimed() == [], "the delivery was marked sent"


def test_an_unconfigured_channel_is_reported_not_crashed(
        config, store, tmp_path, monkeypatch):
    """A job naming a channel this machine cannot send to is a delivery
    note on the job, never a failed run and never an exception."""
    job = make_job(name="hourly")
    job.schedule = parse("every 1h")
    job.created = (datetime.now() - timedelta(hours=2)).isoformat()
    job.delivery = ["discord:999"]
    store.add(job)
    config = dataclasses.replace(
        config, paths=dataclasses.replace(config.paths, user=tmp_path / "home"))

    monkeypatch.setattr("comodor.cron.scheduler.Scheduler._run_and_record",
                        _fake_run(store, _Outcome()))
    scheduler = Scheduler(config, store=store, tick=60)
    _tick_and_settle(scheduler, store)          # must not raise

    job = store.get("job1")
    assert job.last_result == "ok"
    assert "discord" in job.last_error
