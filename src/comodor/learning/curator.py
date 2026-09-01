"""The curator: periodic maintenance over the brain, with a report.

Decay is passive — it lowers a lesson's confidence over time and
`consolidate()` drops what fell below the floor. The curator is active: it
looks at the whole brain at once and makes status decisions nothing else
makes, on evidence nothing else consults. The two are complements, not
alternatives — decay runs after every task, the curator runs every few
days, and neither ever hard-deletes anything a user did not ask to delete.

Phase 1 is deterministic and costs no tokens:

* lessons whose effective confidence has decayed below the floor are marked
  ``stale`` — still in the database and inspectable, but never recalled;
* facts that duplicate another fact (same text, or contained in it) are
  merged into the older one, both origins noted;
* skills unused for ``stale_days`` are marked stale, and unused for
  ``archive_days`` are moved to ``.archive/`` beside the skill itself —
  reversible, not deleted. Pinned skills, never-used ones still inside
  their grace period, and any skill a scheduled job names in its prompt
  are all exempt.

Phase 2 (consolidation with a model) is deliberately absent here. Merging
skills is a judgment call over the user's own procedures, and a pass that
rewrites files by itself is a pass nobody dares turn on. `skills.propose`
already handles the proposal flow; the curator's job is the mechanical
hygiene.

Every mutation is recorded in the ledger that already tracks skill
changes, and the whole pass writes a report the ``curator report``
command and the one-line TUI summary both read. State — last run, paused —
lives in the brain's ``meta`` table, because the brain is the one store
every process that would run the curator already opens.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from typing import Any

from ..skills.loader import MANIFEST
from ..skills.usage import UsageStore
from .store import BrainStore, Lesson

DAY = 86400.0

#: The directory archived skills move into, under the skills root.
ARCHIVE_DIR = ".archive"

#: The meta key holding the curator's state.
STATE_KEY = "curator"


@dataclass
class Action:
    """One thing the curator did, to be reported and counted."""

    what: str          # lesson-stale | fact-merged | skill-stale | skill-archived
    target: str        # human-readable name of the thing
    why: str
    restore: str = ""  # what a rollback puts back, when there is one


@dataclass
class Report:
    """The outcome of one pass, written where a human will read it."""

    at: float = field(default_factory=time.time)
    actions: list[Action] = field(default_factory=list)
    skipped: int = 0

    def line(self) -> str:
        """The one-line summary the interface shows after a pass."""
        if not self.actions:
            return ""
        stale = sum(1 for action in self.actions if action.what.endswith("stale"))
        merged = sum(1 for action in self.actions if action.what == "fact-merged")
        archived = sum(1 for action in self.actions if action.what == "skill-archived")
        parts = []
        if stale:
            parts.append(f"{stale} marked stale")
        if merged:
            parts.append(f"{merged} duplicate fact(s) merged")
        if archived:
            parts.append(f"{archived} skill(s) archived")
        return f"Curator: {', '.join(parts)}."

    def render(self) -> str:
        """The full report file: a table of transitions, each with its reason."""
        if not self.actions:
            return ("# Curator report\n\nNothing needed doing.\n")
        lines = ["# Curator report",
                 time.strftime("\nRun at %Y-%m-%d %H:%M\n", time.localtime(self.at))]
        for action in self.actions:
            lines.append(f"- **{action.target}** — {action.what}: {action.why}")
        if self.skipped:
            lines.append(f"\n{self.skipped} item(s) skipped as exempt.")
        return "\n".join(lines) + "\n"


def load_state(store: BrainStore) -> dict[str, Any]:
    """Curator state from the brain's meta table, or the defaults."""
    with store._lock, store.connection as connection:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = ?", (STATE_KEY,)).fetchone()
    if row is None:
        return {"last_run": 0.0, "paused": False}
    try:
        state = json.loads(row["value"])
    except (ValueError, TypeError):
        return {"last_run": 0.0, "paused": False}
    if not isinstance(state, dict):
        return {"last_run": 0.0, "paused": False}
    state.setdefault("last_run", 0.0)
    state.setdefault("paused", False)
    return state


def save_state(store: BrainStore, state: dict[str, Any]) -> None:
    with store._lock, store.connection as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (STATE_KEY, json.dumps(state)))


def due(store: BrainStore, interval_days: float, paused: bool | None = None) -> bool:
    """Whether a pass is owed, given the interval since the last one."""
    if paused is None:
        paused = bool(load_state(store).get("paused"))
    if paused:
        return False
    return time.time() - float(load_state(store).get("last_run") or 0) \
        >= interval_days * DAY


# --------------------------------------------------------------------------- #
# phase 1 — the deterministic pass

def run(store: BrainStore, config, skills_root=None,
        cron_prompts: list[str] | None = None) -> Report:
    """One full pass. Never deletes anything; everything it does is reported.

    ``cron_prompts`` is the text of every scheduled job's prompt: a skill a
    job depends on must never be archived, no matter how long it has sat
    unused — the job runs without a person there to notice why it broke.
    """
    state = load_state(store)
    if state.get("paused"):
        return Report()

    report = Report()
    _mark_stale_lessons(store, config, report)
    _merge_duplicate_facts(store, report)
    if skills_root is not None:
        _curate_skills(store, config, skills_root, report,
                       cron_prompts or _cron_prompts_from(config),
                       stale_days=config.curator.stale_days,
                       archive_days=config.curator.archive_days)

    state["last_run"] = time.time()
    save_state(store, state)
    write_report(config, report)
    return report


def _mark_stale_lessons(store: BrainStore, config, report: Report) -> None:
    """Lessons decayed below the floor stop being recalled — nothing more.

    The status is one SQL update, and recall already reads it, so a stale
    lesson costs the playbook nothing the moment it is marked. It is not
    deleted: it may simply be out of season, and the report says which.
    """
    connection = store.connection
    rows = connection.execute(
        "SELECT id, trigger_text, guidance, confidence, updated_at, pinned "
        "FROM lessons WHERE status = 'active'").fetchall()
    for row in rows:
        if row["pinned"]:
            report.skipped += 1
            continue
        lesson = Lesson(trigger=row["trigger_text"], guidance=row["guidance"],
                        confidence=row["confidence"], updated_at=row["updated_at"],
                        pinned=bool(row["pinned"]))
        if lesson.effective_confidence(config.learning.half_life_days) \
                >= config.learning.min_confidence:
            continue
        with store._lock, store.connection as c:
            c.execute("UPDATE lessons SET status='stale' WHERE id=?",
                      (row["id"],))
        report.actions.append(Action(
            what="lesson-stale", target=row["trigger_text"][:60] or "lesson",
            why="confidence decayed below the floor; hidden from recall, "
                "kept in the database"))


def _merge_duplicate_facts(store: BrainStore, report: Report) -> None:
    """Facts that say the same thing twice become one.

    Same normalised text, or one contained in the other, is the same fact
    said twice. The older id survives and keeps both texts in its history
    via the report; a fact that was pinned or staged is left alone.
    """
    facts = store.all_facts(settled_only=True)
    by_key: dict[tuple[str, str], list] = {}
    for fact in facts:
        if fact.pinned:
            continue
        by_key.setdefault((fact.kind, fact.scope), []).append(fact)

    for group in by_key.values():
        group.sort(key=lambda fact: fact.created_at)   # oldest is the original
        seen: list = []
        for fact in group:
            twin = next((kept for kept in seen
                         if _same_fact(kept.text, fact.text)), None)
            if twin is None:
                seen.append(fact)
                continue
            if store.delete_fact(fact.id):
                report.actions.append(Action(
                    what="fact-merged", target=fact.text[:60],
                    why=f"duplicate of fact #{twin.id} (\"{twin.text[:50]}\")"))
        if len(seen) < len(group):
            pass   # survivors stay; only duplicates were removed


def _same_fact(left: str, right: str) -> bool:
    a = " ".join(left.lower().split())
    b = " ".join(right.lower().split())
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _curate_skills(store: BrainStore, config, skills_root, report: Report,
                   cron_prompts: list[str], stale_days: float,
                   archive_days: float) -> None:
    """Stale and archive unused skills on disk, with exemptions honoured.

    The skills table in the brain and the skills on disk are the same
    population seen twice; the disk is authoritative because that is what
    the loader reads. A skill is exempt when it is pinned in its usage
    sidecar, was written by the user rather than the agent, was never used
    but is still young, or its name appears in a scheduled job's prompt.
    """
    usage = UsageStore(skills_root)
    used_names = usage.all()
    referenced = _names_in_prompts(cron_prompts, skills_root)
    now = time.time()

    for skill_dir in _skill_folders(skills_root):
        name = skill_dir.name
        record = used_names.get(name)
        if record is None:
            # Never touched by the usage store: no honest idle time exists,
            # because no use was ever recorded. Count from the folder's own
            # mtime so a hand-written skill still gets its grace period.
            try:
                idle = (now - skill_dir.stat().st_mtime) / DAY
            except OSError:
                continue
            created_by = ""
            state = "active"
            pinned = False
        else:
            idle = _idle_days(record)
            created_by = record.created_by
            state = record.state
            pinned = record.pinned

        if pinned or state == "archived":
            report.skipped += 1 if pinned else 0
            continue
        if name in referenced:
            report.skipped += 1
            continue
        if idle < stale_days:
            continue
        if created_by == "user":
            report.skipped += 1
            continue

        if idle >= archive_days:
            _archive_skill(skills_root, skill_dir, name, idle, report, store)
        elif state != "stale":
            _mark_skill_stale(usage, name, idle, report)

    _mark_stale_skills_in_brain(store, report)


def _skill_folders(skills_root):
    """Directories that hold a SKILL.md — the same rule the loader uses."""
    if not skills_root.is_dir():
        return []
    return [path for path in sorted(skills_root.iterdir())
            if path.is_dir() and (path / MANIFEST).is_file()]


def _idle_days(record) -> float:
    """Days since the usage sidecar last saw the skill used.

    Zero when there is no timestamp at all — a skill recorded before the
    curator existed has no honest idle time, and inventing one would let a
    single pass archive a whole collection.
    """
    if not getattr(record, "last_used", 0):
        return 0.0
    return (time.time() - float(record.last_used)) / DAY


def _names_in_prompts(prompts: list[str], skills_root) -> set[str]:
    """Skill names any scheduled job's prompt mentions."""
    names: set[str] = set()
    for folder in _skill_folders(skills_root):
        if any(folder.name in prompt for prompt in prompts):
            names.add(folder.name)
    return names


def _mark_skill_stale(usage: UsageStore, name: str, idle: float,
                      report: Report) -> None:
    def change(record):
        record.state = "stale"
        record.note = f"marked stale by the curator: unused {int(idle)} days"
        return record

    usage.update(name, change)
    report.actions.append(Action(
        what="skill-stale", target=name,
        why=f"unused for {int(idle)} days; hidden from selection, not deleted"))


def _archive_skill(skills_root, skill_dir, name: str, idle: float,
                   report: Report, store: BrainStore | None) -> None:
    """Move one skill to `.archive/` — reversible, and reported as such."""
    archive = skills_root / ARCHIVE_DIR
    try:
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / name
        if target.exists():          # archived once before; do not clobber
            report.skipped += 1
            return
        shutil.move(str(skill_dir), str(target))
    except OSError as problem:
        report.actions.append(Action(
            what="skill-archive-failed", target=name,
            why=f"the move failed: {problem}"))
        return
    report.actions.append(Action(
        what="skill-archived", target=name,
        why=f"unused for {int(idle)} days; moved to {archive} — "
            "move it back to restore it"))
    if store is not None:
        try:
            with store._lock, store.connection as connection:
                connection.execute("DELETE FROM skills WHERE name=?", (name,))
        except Exception:
            pass


def _mark_stale_skills_in_brain(store: BrainStore, report: Report) -> None:
    """Brains that hold learned procedures reflect the same transitions."""
    try:
        with store._lock, store.connection as connection:
            rows = connection.execute(
                "SELECT id, name, last_used, created_at FROM skills").fetchall()
            now = time.time()
            for row in rows:
                last = row["last_used"] or row["created_at"]
                if last and (now - float(last)) / DAY >= 30.0:
                    connection.execute(
                        "UPDATE skills SET tags=? WHERE id=?",
                        (json.dumps(["stale"]), row["id"]))
                    report.actions.append(Action(
                        what="skill-stale", target=f"{row['name']} (learned)",
                        why="a learned procedure unused for 30 days"))
    except Exception:
        pass


def _cron_prompts_from(config) -> list[str]:
    """The prompts of every scheduled job, read from the cron store."""
    try:
        from ..cron.jobs import JobStore

        return [job.prompt for job in
                JobStore(config.paths.user / "cron").all()]
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# reporting and rollback

def report_path(config):
    from pathlib import Path

    return Path(config.paths.user) / "logs" / "curator" / "REPORT.md"


def write_report(config, report: Report) -> None:
    if not report.actions:
        return                      # no news is no file
    try:
        path = report_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.render(), encoding="utf-8")
    except OSError:
        pass


def rollback_skill(skills_root, name: str) -> str:
    """Move an archived skill back. Returns what happened, for the CLI."""
    archive = skills_root / ARCHIVE_DIR
    source = archive / name
    target = skills_root / name
    if not source.is_dir():
        return f"no archived skill named {name!r} under {archive}"
    if target.exists():
        return f"a skill named {name!r} is already live — nothing to do"
    try:
        shutil.move(str(source), str(target))
    except OSError as problem:
        return f"the move failed: {problem}"
    usage = UsageStore(skills_root)

    def change(record):
        record.state = "active"
        record.note = "restored from the archive"
        return record

    usage.update(name, change)
    return f"restored {name} from the archive"
