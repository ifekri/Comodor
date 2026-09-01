"""The jobs and the file they live in.

One JSON file, written atomically with a lock around read-modify-write, in
the pattern the user configuration established. Entries small enough to read
at a glance are the point: a schedule somebody can open in an editor is a
schedule they can debug when it misfires at 3am.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .parse import Schedule

#: Consecutive failures at which a job is auto-paused. Overridable per config,
#: but a number has to live here too so the default file layout stays sane.
DEFAULT_FAILURE_STREAK = 3


class JobError(ValueError):
    """A job request that cannot be honoured, said plainly."""


@dataclass
class Job:
    """One scheduled run."""

    id: str
    name: str
    prompt: str
    schedule: Schedule
    #: Where output goes. "origin" = the project the job belongs to; a
    #: "channel:key" pair names a chat an adapter knows. The scheduler never
    #: invents receivers: a delivery target nobody can resolve fails loudly.
    delivery: list[str] = field(default_factory=lambda: ["origin"])
    #: Blank = the configured model. Pinned at creation, not at fire time —
    #: a job that meant to run on one model running on whatever is current
    #: later is drift nobody asked for.
    model: str = ""
    project: str = ""                # working directory of the run
    enabled: bool = True
    last_fire: str = ""              # ISO, blank = never fired
    last_result: str = ""            # ok | failed | missed
    last_error: str = ""
    failure_streak: int = 0
    #: The answer of the last successful fire, as the fire left it. Read by
    #: the delivery side after a crash — the ledger may hold the envelope but
    #: the job always holds the words — and shown in the history lines.
    last_answer: str = ""
    created: str = ""                # ISO, anchors interval schedules

    # -- persistence -------------------------------------------------------- #

    def to_json(self) -> dict:
        return {
            "id": self.id, "name": self.name, "prompt": self.prompt,
            "schedule": self.schedule.to_json(),
            "delivery": list(self.delivery), "model": self.model,
            "project": self.project, "enabled": self.enabled,
            "last_fire": self.last_fire, "last_result": self.last_result,
            "last_error": self.last_error,
            "failure_streak": self.failure_streak,
            "last_answer": self.last_answer,
            "created": self.created,
        }

    @classmethod
    def from_json(cls, data: dict) -> "Job":
        schedule = Schedule(
            kind=str(data.get("schedule", {}).get("kind", "cron")),
            expr=str(data.get("schedule", {}).get("expr", "")),
            seconds=int(data.get("schedule", {}).get("seconds", 0)),
            at=_read_time(data.get("schedule", {}).get("at", "")),
        )
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:10]),
            name=str(data.get("name") or "unnamed"),
            prompt=str(data.get("prompt") or ""),
            schedule=schedule,
            delivery=list(data.get("delivery") or ["origin"]),
            model=str(data.get("model") or ""),
            project=str(data.get("project") or ""),
            enabled=bool(data.get("enabled", True)),
            last_fire=str(data.get("last_fire") or ""),
            last_result=str(data.get("last_result") or ""),
            last_error=str(data.get("last_error") or ""),
            failure_streak=int(data.get("failure_streak") or 0),
            last_answer=str(data.get("last_answer") or ""),
            created=str(data.get("created") or ""),
        )


def _read_time(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class JobStore:
    """Every job, behind one file lock."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.file = self.directory / "jobs.json"
        self._lock = threading.Lock()

    def _load(self) -> list[Job]:
        try:
            document = json.loads(self.file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            # An unreadable file must not silently delete the jobs: keep the
            # copy and start from nothing visible rather than from a guess.
            broken = self.file.with_suffix(".json.broken")
            try:
                self.file.replace(broken)
            except OSError:
                pass
            return []
        if not isinstance(document, list):
            return []
        return [Job.from_json(entry) for entry in document if isinstance(entry, dict)]

    def _save(self, jobs: list[Job]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps([job.to_json() for job in jobs], indent=2,
                             ensure_ascii=False) + "\n"
        temporary = self.file.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        temporary.replace(self.file)

    # -- operations ---------------------------------------------------------- #

    def all(self) -> list[Job]:
        with self._lock:
            return self._load()

    def get(self, job_id: str) -> Job | None:
        for job in self.all():
            if job.id == job_id:
                return job
        return None

    def add(self, job: Job) -> Job:
        if not job.prompt.strip():
            raise JobError("a job needs a prompt — what should it do?")
        with self._lock:
            jobs = self._load()
            if any(other.name == job.name for other in jobs):
                raise JobError(
                    f"a job called {job.name!r} already exists — pick another "
                    "name, or remove the old one first")
            jobs.append(job)
            self._save(jobs)
        return job

    def update(self, job_id: str, change) -> Job:
        """Apply `change(job)` to one job and save it back."""
        with self._lock:
            jobs = self._load()
            for index, candidate in enumerate(jobs):
                if candidate.id == job_id:
                    changed = change(candidate)
                    jobs[index] = changed
                    self._save(jobs)
                    return changed
        raise JobError(f"no job with id {job_id!r}")

    def remove(self, job_id: str) -> Job:
        with self._lock:
            jobs = self._load()
            for index, candidate in enumerate(jobs):
                if candidate.id == job_id:
                    self._save(jobs[:index] + jobs[index + 1:])
                    return candidate
        raise JobError(f"no job with id {job_id!r}")
