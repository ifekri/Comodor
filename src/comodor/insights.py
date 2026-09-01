"""What the history on disk says, when you add it all up.

Everything shown here was already recorded: session files carry the model
and the spend, the brain's episodes carry the steps and the corrections.
Nothing new is collected and nothing is sent anywhere — the module is a
handful of aggregation queries over files the program wrote anyway.

The honesty rules are the ones `learning/progress.py` uses, borrowed
rather than reinvented:

* a spend or a rate with no price behind it is a dash, never a guess;
* a trend built from fewer than ``MIN_FOR_TREND`` samples is not a trend
  and is not shown as one;
* an unknown price contributes its tokens but not its dollars — counting
  it as zero would flatter the total the same way counting it as a guess
  would inflate it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

DAY = 86400.0

#: Below this many sessions, "trend" means noise.
MIN_SESSIONS = 3


@dataclass
class Insights:
    """Everything the view renders, already computed."""

    days: int
    sessions: int = 0
    messages: int = 0
    cost_usd: float = 0.0
    #: Sessions whose model has no published price. Their spend is unknown,
    #: not zero, and the view says so rather than implying the total is whole.
    unpriced_sessions: int = 0
    cache_tokens: int = 0
    prompt_tokens: int = 0
    projects: list[tuple[str, float]] = field(default_factory=list)
    models: list[tuple[str, float]] = field(default_factory=list)
    episodes: int = 0
    corrections_per_ten: float = 0.0
    recent_corrections_per_ten: float = 0.0
    cron_runs: int = 0
    cron_failures: int = 0

    @property
    def cache_hit_rate(self) -> float:
        if not self.prompt_tokens:
            return 0.0
        return self.cache_tokens / self.prompt_tokens

    @property
    def spend_is_whole(self) -> bool:
        """True when every session in the window had a published price."""
        return self.unpriced_sessions == 0

    @property
    def brain_improving(self) -> bool | None:
        """Fewer corrections per task over time — or None without evidence."""
        if self.episodes < MIN_SESSIONS or not self.episodes:
            return None
        if self.recent_corrections_per_ten == self.corrections_per_ten:
            return None                        # flat is not a direction
        return self.recent_corrections_per_ten < self.corrections_per_ten


def collect(config, days: int = 30) -> Insights:
    """Aggregate the last ``days`` of sessions and episodes. Pure reads."""
    since = time.time() - days * DAY
    result = Insights(days=days)
    _sessions(config, since, result)
    _episodes(config, since, result)
    _cron(config, since, result)
    return result


def _sessions(config, since: float, result: Insights) -> None:
    from .session.store import SessionStore

    store = SessionStore(config.paths.user / "sessions")
    by_project: dict[str, float] = {}
    by_model: dict[str, list[float]] = {}
    for meta in store.list_sessions(limit=100_000):
        # Filtered by the session's start: save_meta restamps updated_at on
        # every write, so a session still in flight would always qualify —
        # which is right for "active lately", but not for "this window".
        if meta.created_at < since:
            continue
        result.sessions += 1
        result.messages += meta.messages
        if meta.cost_usd:
            result.cost_usd += meta.cost_usd
        else:
            result.unpriced_sessions += 1
        project = _project_name(config, meta.cwd)
        by_project[project] = by_project.get(project, 0.0) + meta.cost_usd
        by_model.setdefault(meta.model or "unknown", []).append(meta.cost_usd)

    result.projects = sorted(
        ((name, spend) for name, spend in by_project.items() if spend),
        key=lambda item: item[1], reverse=True)[:5]
    total = sum(sum(shares) for shares in by_model.values()) or 0.0
    result.models = sorted(
        ((model, sum(shares) / total) for model, shares in by_model.items()
         if sum(shares)),
        key=lambda item: item[1], reverse=True)[:5]


def _project_name(config, cwd: str) -> str:
    """The folder's own name — a person recognises `client-site`, not a hash."""
    from .paths import project_key

    if not cwd:
        return "unknown"
    if cwd == str(config.paths.project):
        return f"{project_key(config.paths.project).rsplit('-', 1)[0]} (this)"
    return Path(cwd).name or cwd


def _episodes(config, since: float, result: Insights) -> None:
    from .learning.progress import MIN_FOR_TREND
    from .learning.store import BrainStore

    store = BrainStore(config.paths.brain_db)
    rows = store.connection.execute(
        "SELECT steps, corrections, created_at FROM episodes "
        "WHERE created_at >= ? ORDER BY created_at", (since,)).fetchall()
    result.episodes = len(rows)
    if not rows:
        return
    total_steps = sum(max(1, row["steps"]) for row in rows)
    total_corrections = sum(row["corrections"] for row in rows)
    result.corrections_per_ten = total_corrections / total_steps * 10.0
    # The recent window is the same fraction of the series progress.py uses;
    # under its sample floor the "recent" number is not shown at all.
    if len(rows) >= MIN_FOR_TREND:
        size = max(2, int(len(rows) * 0.3))
        recent = rows[-size:]
        recent_steps = sum(max(1, row["steps"]) for row in recent)
        result.recent_corrections_per_ten = (
            sum(row["corrections"] for row in recent) / recent_steps * 10.0)


def _cron(config, since: float, result: Insights) -> None:
    """Runs in the window, and how many failed.

    The job store keeps only each job's latest outcome, so this counts
    jobs, not executions — said that way in the view rather than dressed
    up as a run count we do not have.
    """
    try:
        from .cron.jobs import JobStore
    except ImportError:
        return
    try:
        jobs = JobStore(config.paths.user / "cron").all()
    except Exception:
        return
    result.cron_runs = len(jobs)
    result.cron_failures = sum(
        1 for job in jobs if job.last_result not in ("", "ok"))


# --------------------------------------------------------------------------- #
# rendering

def render(result: Insights) -> str:
    """Markdown, as the interface's info overlays render."""
    since = time.strftime("%d %b", time.localtime(time.time() - result.days * DAY))
    lines = [f"**The last {result.days} days** (since {since})", ""]

    if result.sessions < MIN_SESSIONS:
        lines.append("Not enough sessions yet for this to mean anything — "
                     f"{result.sessions} in the window.")
        return "\n".join(lines)

    spend = f"${result.cost_usd:.2f}" if result.cost_usd else "-"
    if not result.spend_is_whole:
        spend += (f"  \n\n*+{result.unpriced_sessions} session(s) on models "
                  "with no published price — not counted, not guessed.*")
    lines += [
        f"- cost: {spend}",
        f"- sessions: {result.sessions:,} · messages: {result.messages:,}",
    ]
    if result.prompt_tokens:
        lines.append(f"- served from cache: {result.cache_hit_rate:.0%} of "
                     "the prompt")
    if result.projects:
        listed = " · ".join(f"**{name}** ${spend:.2f}"
                            for name, spend in result.projects[:3])
        lines.append(f"- biggest projects: {listed}")
    if result.models:
        listed = " · ".join(f"**{model}** {share:.0%}"
                            for model, share in result.models[:3])
        lines.append(f"- workhorse models: {listed}")
    lines.append("")
    if result.episodes >= MIN_SESSIONS:
        verdict = {True: "fewer corrections per task than before — improving",
                   False: "more corrections per task than before",
                   None: "flat so far"}
        lines.append(f"**Brain** ({result.episodes} tasks): "
                     f"{verdict[result.brain_improving]}.")
    else:
        lines.append(f"**Brain**: {result.episodes} tasks recorded — too few "
                     "to read a direction from.")
    if result.cron_runs:
        lines.append(f"**Scheduled jobs**: {result.cron_runs}, with "
                     f"{result.cron_failures} not ok on their latest run."
                     if result.cron_failures else
                     f"**Scheduled jobs**: {result.cron_runs}, all ok on "
                     "their latest run.")
    return "\n".join(lines)


def to_json(result: Insights) -> dict:
    """The same numbers, for scripts."""
    return {
        "days": result.days,
        "sessions": result.sessions,
        "messages": result.messages,
        "cost_usd": round(result.cost_usd, 4),
        "unpriced_sessions": result.unpriced_sessions,
        "cache_hit_rate": round(result.cache_hit_rate, 4),
        "projects": [{"name": name, "cost_usd": round(spend, 4)}
                     for name, spend in result.projects],
        "models": [{"model": model, "share": round(share, 4)}
                   for model, share in result.models],
        "episodes": result.episodes,
        "corrections_per_ten_steps": round(result.corrections_per_ten, 3),
        "recent_corrections_per_ten_steps":
            round(result.recent_corrections_per_ten, 3),
        "brain_improving": result.brain_improving,
        "cron_jobs": result.cron_runs,
        "cron_failures": result.cron_failures,
    }
