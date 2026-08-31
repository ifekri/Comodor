"""The tick loop.

Every minute the scheduler wakes, finds the jobs whose time has come, and
runs them — each on its own thread, bounded by a concurrency cap so a dozen
jobs scheduled for nine o'clock do not become a dozen simultaneous agent
turns. A file lock keeps two schedulers from firing the same job: whichever
process loses the lock simply skips the tick, because the winner is doing
the work.

Delivery is deliberately thin here. The scheduler records the outcome and the
answer in the job itself; where the answer goes afterwards is the delivery
module's business, and a delivery failure must never read back as the job
having failed.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from .jobs import Job, JobStore
from .parse import next_fire

#: How often to look. Minute resolution matches cron; finer than that would
#: burn cycles for nothing, coarser would make "every minute" a lie.
TICK_SECONDS = 60.0


class Scheduler:
    """Runs due jobs, one process at a time."""

    def __init__(self, config, store: JobStore | None = None,
                 deliver=None, tick: float = TICK_SECONDS) -> None:
        self.config = config
        self.store = store or JobStore(config.paths.user / "cron")
        self._tick = tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running: set[str] = set()
        self._lock = threading.Lock()
        self._deliver = deliver                  # callable(job, outcome, answer)
        self._lock_file = self.store.directory / "tick.lock"
        self._held = False
        self.log: list[dict] = []                # recent fires, newest last

    # -- lifecycle ------------------------------------------------------------ #

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop,
                                        name="comodor-cron", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._release_lock()

    def _loop(self) -> None:
        while not self._stop.wait(self._tick):
            try:
                self.tick()
            except Exception:
                # A tick that throws must not kill the thread: the next tick
                # is a minute away and everything it needs is still on disk.
                pass

    # -- one tick -------------------------------------------------------------- #

    def tick(self, now: datetime | None = None) -> list[str]:
        """Fire everything due. Returns the ids it started.

        `now` is injected so tests can turn the clock by hand.
        """
        if not self.config.cron.enabled:
            return []
        now = now or datetime.now()
        if not self._acquire_lock():
            return []

        try:
            fired: list[str] = []
            for job in self.store.all():
                if not job.enabled or job.id in self._running:
                    continue
                if not self._due(job, now):
                    continue
                if self._start(job, now):
                    fired.append(job.id)
            return fired
        finally:
            self._release_lock()

    def _due(self, job: Job, now: datetime) -> bool:
        """Whether a fire time has come due since the last one.

        The question is asked backwards: look for the next matching time at
        or after the start of the grace window (but after the last fire, and
        after the job existed at all), and call it due when that time has
        already arrived. That is what makes a missed fire still run — a
        laptop that slept through nine o'clock wakes at 9:08, finds 9:00
        inside the window, and fires late once — while a fire that was missed
        by hours sleeps on until the schedule's next real occurrence.
        """
        from datetime import timedelta

        created = _read(job.created) or now
        grace = max(self.config.cron.misfire_grace_minutes * 60, self._tick)
        last = _read(job.last_fire)
        window_start = now - timedelta(seconds=grace)
        if last is not None:
            window_start = max(window_start, last)
        if created > window_start:
            # A job does not owe a fire for a time that passed before it
            # existed: its first chance is the schedule's next occurrence.
            window_start = created
        if window_start >= now:
            return False
        try:
            upcoming = next_fire(job.schedule, window_start, created)
        except Exception:
            return False
        if upcoming is None:
            # A one-shot past its time disables itself rather than sitting
            # in the list forever.
            if job.schedule.kind == "once" and job.schedule.at \
                    and job.schedule.at <= now:
                self.store.update(job.id, lambda j: _disable(j, "missed"))
            return False
        return upcoming <= now

    def _start(self, job: Job, now: datetime) -> bool:
        with self._lock:
            if len(self._running) >= self.config.cron.max_concurrency:
                return False
            self._running.add(job.id)
        thread = threading.Thread(target=self._run_and_record,
                                  args=(job, now), daemon=True,
                                  name=f"comodor-cron-{job.id}")
        thread.start()
        return True

    def _run_and_record(self, job: Job, now: datetime) -> None:
        from .runner import run_job

        try:
            outcome = run_job(self.config, job)
            self.store.update(job.id, lambda j: _record(j, now, outcome.ok,
                                                        outcome.error))
            if self._deliver is not None and outcome.ok:
                try:
                    self._deliver(job, outcome, outcome.answer)
                except Exception:
                    pass
            self.log.append({"job": job.id, "name": job.name, "at": now.isoformat(),
                             "ok": outcome.ok, "error": outcome.error})
        finally:
            with self._lock:
                self._running.discard(job.id)

    # -- the lock --------------------------------------------------------------- #

    def _acquire_lock(self) -> bool:
        """Only one scheduler process ticks at a time.

        The lock names its owner, so a lock left behind by a crashed process
        is recognised as stale rather than blocking every future tick.
        """
        try:
            self.store.directory.mkdir(parents=True, exist_ok=True)
            if self._lock_file.exists():
                try:
                    owner = json.loads(self._lock_file.read_text())
                    if time.time() - owner.get("time", 0) < 5 * self._tick:
                        return False
                except (OSError, ValueError):
                    return False
            self._lock_file.write_text(json.dumps(
                {"pid": __import__("os").getpid(), "time": time.time()}))
            self._held = True
            return True
        except OSError:
            return False

    def _release_lock(self) -> None:
        if not self._held:
            return
        try:
            self._lock_file.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False


def _disable(job: Job, why: str) -> Job:
    job.enabled = False
    job.last_result = why
    return job


def _record(job: Job, when: datetime, ok: bool, error: str,
            streak_limit: int = 3) -> Job:
    job.last_fire = when.isoformat()
    job.last_result = "ok" if ok else "failed"
    job.last_error = error if not ok else ""
    job.failure_streak = 0 if ok else job.failure_streak + 1
    if job.failure_streak >= streak_limit:
        # A job that keeps failing is paused, not deleted: the evidence of
        # what went wrong stays on the job for somebody to read.
        job.enabled = False
        job.last_error = (error or "failed") + \
            " — paused after repeated failures"
    return job


def _read(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
