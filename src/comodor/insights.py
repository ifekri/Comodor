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
    #: From the paired record each episode carries (FR-072, FR-073): counts
    #: over the window, zero when no episode recorded one.
    measured_episodes: int = 0
    task_input_tokens: int = 0
    task_output_tokens: int = 0
    task_cached_tokens: int = 0
    task_written_tokens: int = 0
    model_turns: int = 0
    tool_calls: int = 0
    clarifications_raised: int = 0
    clarifications_answered: int = 0
    knowledge_hits: int = 0
    knowledge_stale: int = 0
    validation_failures: int = 0

    @property
    def knowledge_stale_rate(self) -> float:
        seen = self.knowledge_hits + self.knowledge_stale
        return self.knowledge_stale / seen if seen else 0.0

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
        "SELECT steps, corrections, created_at, measurement FROM episodes "
        "WHERE created_at >= ? ORDER BY created_at", (since,)).fetchall()
    result.episodes = len(rows)
    if not rows:
        return
    _measured(rows, result)
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


def _measured(rows, result: Insights) -> None:
    """Sum the paired records the episodes carry. Counts only; an episode
    from before the record existed contributes nothing."""
    import json

    for row in rows:
        try:
            record = json.loads(row["measurement"] or "{}")
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not isinstance(record, dict) or not record:
            continue
        result.measured_episodes += 1
        result.task_input_tokens += int(record.get("input_tokens", 0) or 0)
        result.task_output_tokens += int(record.get("output_tokens", 0) or 0)
        result.task_cached_tokens += int(record.get("cached_tokens", 0) or 0)
        result.task_written_tokens += int(record.get("written_tokens", 0) or 0)
        result.model_turns += int(record.get("model_turns", 0) or 0)
        result.tool_calls += int(record.get("tool_calls", 0) or 0)
        result.clarifications_raised += int(record.get("clarifications_raised", 0) or 0)
        result.clarifications_answered += int(record.get("clarifications_answered", 0) or 0)
        result.knowledge_hits += int(record.get("knowledge_hits", 0) or 0)
        result.knowledge_stale += int(record.get("knowledge_stale", 0) or 0)
        if str(record.get("validation_outcome", "")) in ("failed", "contradicted"):
            result.validation_failures += 1


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
    if result.episodes:
        # The per-task measurement the paired work records, surfaced here so a
        # person can read it rather than only a benchmark report.
        lines.append(
            f"- tasks: {result.episodes:,} · tool calls: {result.tool_calls:,} · "
            f"questions: {result.clarifications_raised:,} asked, "
            f"{result.clarifications_answered:,} answered · "
            f"knowledge: {result.knowledge_hits:,} recalled, "
            f"{result.knowledge_stale:,} stale")
    if result.measured_episodes:
        lines.append(
            f"- measured tasks: {result.measured_episodes:,} · tokens "
            f"in/out/cached/written: {result.task_input_tokens:,}/"
            f"{result.task_output_tokens:,}/{result.task_cached_tokens:,}/"
            f"{result.task_written_tokens:,} · "
            f"model turns: {result.model_turns:,} · validation failures: "
            f"{result.validation_failures:,}")
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
        # The per-task measurement the product records, exposed for scripts.
        "measured_episodes": result.measured_episodes,
        "task_input_tokens": result.task_input_tokens,
        "task_output_tokens": result.task_output_tokens,
        "task_cached_tokens": result.task_cached_tokens,
        "task_written_tokens": result.task_written_tokens,
        "model_turns": result.model_turns,
        "tool_calls": result.tool_calls,
        "clarifications_raised": result.clarifications_raised,
        "clarifications_answered": result.clarifications_answered,
        "knowledge_hits": result.knowledge_hits,
        "knowledge_stale": result.knowledge_stale,
        "knowledge_stale_rate": round(result.knowledge_stale_rate, 4),
        "validation_failures": result.validation_failures,
        "cron_jobs": result.cron_runs,
        "cron_failures": result.cron_failures,
    }
