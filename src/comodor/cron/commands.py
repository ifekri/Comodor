"""The `comodor cron` command line.

The commands map onto the store one to one, and the point of the whole
surface is that a job somebody can read and edit in a terminal is a job they
can trust: every command prints the schedule as it will actually be read,
including the compiled expression behind a named time like "weekdays at 9am".
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime

from ..config import Config
from .jobs import Job, JobError, JobStore
from .parse import UnparsableSchedule, next_fire, parse


def register(sub: argparse._SubParsersAction) -> None:
    cron = sub.add_parser("cron", help="list, add, and manage scheduled jobs")
    verbs = cron.add_subparsers(dest="verb")

    verbs.add_parser("list", help="show every job and when it next fires")
    verbs.add_parser("status", help="whether the scheduler is enabled")

    add = verbs.add_parser("add", help="create a job")
    add.add_argument("name", help="a short name, unique among jobs")
    add.add_argument("schedule", help='e.g. "daily at 9am", "every 2h", "in 30m", "0 9 * * 1-5"')
    add.add_argument("prompt", help="what the agent should do when it fires")
    add.add_argument("--project", help="working directory for the run "
                                        "(default: this one)")
    add.add_argument("--model", help="pin the model; refused to run on another")

    pause = verbs.add_parser("pause", help="stop a job from firing")
    pause.add_argument("name")

    resume = verbs.add_parser("resume", help="start a paused job again")
    resume.add_argument("name")

    remove = verbs.add_parser("remove", help="delete a job")
    remove.add_argument("name")

    once = verbs.add_parser("run", help="fire a job once, right now")
    once.add_argument("name")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    store = JobStore(config.paths.user / "cron")

    try:
        verb = getattr(args, "verb", None) or "list"
        if verb == "list":
            return _list(config, console, store)
        if verb == "status":
            return _status(console, config, store)
        if verb == "add":
            return _add(config, console, store, args)
        if verb == "pause":
            return _flip(console, store, args.name, enabled=False)
        if verb == "resume":
            return _flip(console, store, args.name, enabled=True)
        if verb == "remove":
            return _remove(console, store, args.name)
        if verb == "run":
            return _run_once(config, console, store, args.name)
    except (JobError, UnparsableSchedule) as problem:
        console.print(f"\n  [bad]{problem}[/bad]\n")
        return 1
    return 0


def _job(job: Job) -> str:
    state = "enabled" if job.enabled else "paused"
    model = f"  model {job.model}" if job.model else ""
    # What the last successful fire said, in one short line. A job that has
    # never fired shows its next fire; a job that has shows what came out,
    # which is the only way to tell a working job from one that runs and
    # says nothing.
    answer = ""
    if job.last_answer:
        head = " ".join(job.last_answer.split())
        answer = (f"\n    [dim]last answer: {head[:160]}"
                  f"{'…' if len(head) > 160 else ''}[/dim]")
    return (f"  {job.name}  [dim]{state} · {job.schedule.expr}{model}[/dim]\n"
            f"    [dim]{job.prompt}[/dim]{answer}")


def _list(config: Config, console, store: JobStore) -> int:
    jobs = store.all()
    if not jobs:
        console.print(
            "\n  No scheduled jobs. Add one:\n\n"
            "  [accent]comodor cron add nightly \"daily at 9am\" "
            "\"summarise yesterday's git log\"[/accent]\n")
        return 0
    now = datetime.now()
    lines = []
    for job in jobs:
        when = ""
        if job.enabled:
            try:
                upcoming = next_fire(job.schedule, now,
                                     _read(job.created) or now)
                when = f"  next {upcoming:%a %H:%M}" if upcoming else ""
            except Exception:
                when = "  next ?"
        lines.append(_job(job) + when)
    title = "Cron" + ("" if config.cron.enabled
                      else "  [dim](scheduler disabled — set cron.enabled in "
                           "settings to fire)[/dim]")
    console.print(f"\n[title]{title}[/title]\n")
    console.print("\n".join(lines))
    console.print()
    return 0


def _status(console, config: Config, store: JobStore) -> int:
    jobs = store.all()
    enabled = sum(1 for job in jobs if job.enabled)
    console.print(
        f"\n  scheduler {'[good]enabled[/good]' if config.cron.enabled else '[bad]disabled[/bad]'}"
        f"  ·  {enabled} of {len(jobs)} jobs enabled"
        f"  ·  grace {config.cron.misfire_grace_minutes}m"
        f"  ·  concurrency {config.cron.max_concurrency}\n")
    return 0


def _add(config: Config, console, store: JobStore, args: argparse.Namespace) -> int:
    schedule = parse(args.schedule)
    job = Job(id=uuid.uuid4().hex[:10], name=args.name, prompt=args.prompt,
              schedule=schedule, model=args.model or "",
              project=args.project or "",
              created=datetime.now().isoformat(timespec="seconds"))
    store.add(job)
    console.print(f"\n  [good]added job {job.name!r}[/good] — {job.schedule.expr}\n")
    return 0


def _flip(console, store: JobStore, name: str, enabled: bool) -> int:
    job = _by_name(store, name)
    store.update(job.id, lambda j: (setattr(j, "enabled", enabled), j)[1])
    console.print(f"\n  {'[good]resumed' if enabled else '[warn]paused'}"
                  f"[/good] {name}\n")
    return 0


def _remove(console, store: JobStore, name: str) -> int:
    job = _by_name(store, name)
    store.remove(job.id)
    console.print(f"\n  [warn]removed[/warn] {name}\n")
    return 0


def _run_once(config: Config, console, store: JobStore, name: str) -> int:
    """Fire a job now, in this terminal, and print the answer."""
    from .runner import run_job

    job = _by_name(store, name)
    console.print(f"\n  running [accent]{name}[/accent] …\n")
    outcome = run_job(config, job)
    if outcome.ok:
        console.print(outcome.answer or "(no answer)")
        return 0
    console.print(f"[bad]{outcome.error}[/bad]")
    return 1


def _by_name(store: JobStore, name: str) -> Job:
    for job in store.all():
        if job.name == name:
            return job
    raise JobError(f"no job called {name!r}")


def _read(text: str) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
