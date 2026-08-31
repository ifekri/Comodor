"""Create and manage scheduled jobs from inside a conversation.

"Remind me every morning to check the failing test" is a request the agent
should be able to honour without the user opening another terminal, so the
same store the `comodor cron` commands use is reachable as a tool.

The tool is *not* advertised to runs started by the scheduler itself. That is
the whole recursion guard, and it lives in the wiring rather than in this
class: `cron/runner.py` builds its registry without it, so a cron run cannot
schedule another cron run no matter what its prompt asks for. A gate inside
`run` would be softer — a check a model might find another path around —
where an absent tool is simply absent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ..cron.jobs import Job, JobError
from ..cron.parse import UnparsableSchedule, parse
from ..safety import Risk
from .base import Tool, ToolContext, ToolResult


class CronJob(Tool):
    """Schedule agent runs: create, list, pause, resume, remove."""

    name = "cronjob"
    risk = Risk.DANGEROUS
    description = (
        "Manage scheduled agent jobs — runs that fire on a schedule with no "
        "conversation behind them and record their answer on the job.\n"
        "\n"
        "Actions:\n"
        "- create: name, schedule, prompt. The schedule is words: \"every 2h\", "
        "\"daily at 9am\", \"weekdays at 14:00\", \"mon and thu at 9:30\", "
        "\"in 30m\", \"2026-09-01 09:00\", \"hourly\", \"daily\", \"weekly\", "
        "or a five-field cron expression like \"0 9 * * 1-5\".\n"
        "- list: every job, when it last fired, and what happened.\n"
        "- pause / resume / remove: by name.\n"
        "\n"
        "A job's prompt should be self-contained — it runs in a fresh agent "
        "that cannot see this conversation. Creating, pausing or removing a "
        "job changes what will run unattended later, so confirm the schedule "
        "and prompt with the user before calling this."
    )

    def __init__(self, store: Any) -> None:
        super().__init__()
        self._store = store

    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "pause", "resume", "remove"],
                "description": "What to do.",
            },
            "name": {
                "type": "string",
                "description": "Job name, unique. For create, a short handle "
                               "the user will recognise in a list.",
            },
            "schedule": {
                "type": "string",
                "description": "For create: when it fires, in words.",
            },
            "prompt": {
                "type": "string",
                "description": "For create: what the agent should do, "
                               "self-contained.",
            },
            "model": {
                "type": "string",
                "description": "For create: pin a model. Leave blank for the "
                               "configured one.",
            },
        },
        "required": ["action"],
    }

    def summary(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "list")
        name = str(args.get("name") or "")
        head = {"create": "scheduling job", "list": "listing scheduled jobs",
                "pause": "pausing job", "resume": "resuming job",
                "remove": "removing job"}.get(action, action)
        return f"{head} {name}".strip()

    def detail(self, ctx: ToolContext, args: dict[str, Any]) -> str:
        if args.get("action") != "create":
            return ""
        return "\n".join(filter(None, (
            f"schedule: {args.get('schedule', '')}",
            f"prompt: {args.get('prompt', '')}",
            f"model: {args.get('model') or '(configured)'}")))

    def run(self, ctx: ToolContext, **args: Any) -> ToolResult:
        action = str(args.get("action") or "").strip().lower()
        store = self._store

        try:
            if action == "list":
                return self._list(store)
            if action == "create":
                return self._create(ctx, store, args)
            name = str(args.get("name") or "").strip()
            if not name:
                return ToolResult.failure(
                    f"{action} needs the job's `name`")
            if action == "pause":
                return self._flip(ctx, store, name, False)
            if action == "resume":
                return self._flip(ctx, store, name, True)
            if action == "remove":
                job = self._by_name(store, name)
                store.remove(job.id)
                return ToolResult.success(f"Removed job {name!r}.")
        except (JobError, UnparsableSchedule) as problem:
            return ToolResult.failure(str(problem))
        return ToolResult.failure(
            f"unknown action {action!r}. One of: create, list, pause, "
            "resume, remove.")

    # -- actions ------------------------------------------------------------- #

    def _list(self, store) -> ToolResult:
        jobs = store.all()
        if not jobs:
            return ToolResult.success(
                "No scheduled jobs exist yet. Offer to create one with the "
                "`create` action.")
        lines = []
        for job in jobs:
            state = "enabled" if job.enabled else "paused"
            last = job.last_result or "never fired"
            lines.append(f"- {job.name} — {job.schedule.expr} — {state}, "
                         f"last: {last}")
        return ToolResult.success("\n".join(lines))

    def _create(self, ctx: ToolContext, store, args: dict[str, Any]) -> ToolResult:
        name = " ".join(str(args.get("name") or "").split())
        prompt = " ".join(str(args.get("prompt") or "").split())
        schedule_text = str(args.get("schedule") or "").strip()
        if not name:
            return ToolResult.failure("`name` is required — what should the "
                                      "job be called?")
        if not schedule_text:
            return ToolResult.failure("`schedule` is required — when should "
                                      "it fire? e.g. \"daily at 9am\"")

        schedule = parse(schedule_text)
        if not prompt:
            return ToolResult.failure("`prompt` is required — a job runs in a "
                                      "fresh agent that cannot see this "
                                      "conversation, so the prompt must say "
                                      "the whole task")

        current = getattr(ctx.config, "cron", None)
        if current is not None and not current.enabled:
            return ToolResult.failure(
                "the scheduler is disabled in settings (cron.enabled); the "
                "job would be created and never fire — enable it first")

        job = Job(id=uuid.uuid4().hex[:10], name=name, prompt=prompt,
                  schedule=schedule, model=str(args.get("model") or ""),
                  project=str(ctx.cwd), created=datetime.now().isoformat(
                      timespec="seconds"))
        store.add(job)
        return ToolResult.success(
            f"Scheduled {name!r}: {schedule.expr}. It will fire on its own; "
            "the answer is recorded on the job (`comodor cron list`).",
            display=f"job {name}: {schedule.expr}")

    def _flip(self, ctx: ToolContext, store, name: str,
              enabled: bool) -> ToolResult:
        job = self._by_name(store, name)
        if job.enabled == enabled:
            state = "already enabled" if enabled else "already paused"
            return ToolResult.success(f"{name!r} is {state}.")
        store.update(job.id, lambda j: (setattr(j, "enabled", enabled), j)[1])
        what = "resumed" if enabled else "paused"
        return ToolResult.success(f"{what.capitalize()} job {name!r}.",
                                  display=f"{what}: {name}")

    @staticmethod
    def _by_name(store, name: str):
        for job in store.all():
            if job.name == name:
                return job
        raise JobError(f"no job called {name!r}")
