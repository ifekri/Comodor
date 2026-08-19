"""The learning engine — what makes Comodor better the more it is used.

The cycle, once per task:

1. **Recall.** Before answering, rank stored lessons against the request and
   inject the best few as a *Playbook* block, under a hard token cap.
2. **Act.** The agent works normally.
3. **Credit.** Whatever was recalled shares the outcome: a clean finish is a win
   for those lessons, a failure is a loss. Confidence moves accordingly.
4. **Reflect.** In the background, the model reads the episode and proposes new
   lessons. Near-duplicates merge into the existing lesson instead of piling up.
5. **Consolidate.** Old, unused, low-confidence lessons decay away.

Two design choices are load-bearing. Reflection runs on a background thread so a
finished task never waits on it. And everything recalled is *shown* to the user
— a memory system you cannot inspect is one you cannot trust, and a wrong lesson
that silently shapes every answer is worse than no memory at all.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..events import EventBus, Kind
from ..paths import project_key
from . import reflect as reflection_module
from . import rules as rules_module
from .signals import Outcome, SignalDetector
from .store import BrainStore, Episode, Lesson, Rule, Skill, score

PLAYBOOK_HEADER = """\
Learned playbook — things earlier sessions established. Treat these as strong \
priors, not orders: if what you observe now contradicts one, trust your \
observation and say so."""


@dataclass
class RecallResult:
    lessons: list[Lesson]
    skills: list[Skill]


class LearningEngine:
    """Owns the brain: recall, credit assignment, reflection, consolidation."""

    def __init__(self, config: Config, bus: EventBus, gateway: Any = None,
                 store: BrainStore | None = None, checkpoints: Any = None,
                 redact: Any = None) -> None:
        self.config = config
        self.bus = bus
        self.gateway = gateway
        self.store = store or BrainStore(config.paths.brain_db)
        self.session_id = f"s{int(time.time())}"
        self.project_scope = f"project:{project_key(config.paths.project)}"
        self._reflect_lock = threading.Lock()
        self._threads: list[threading.Thread] = []

        # Reflex: the fast lane. Deterministic, model-free, always on.
        self.detector = SignalDetector(
            store=self.store, checkpoints=checkpoints, scope=self.project_scope,
            session_id=self.session_id, redact=redact,
        )
        self._prefetched: tuple[str, list[Lesson]] | None = None
        self._prefetch_lock = threading.Lock()

    # -- scoping ---------------------------------------------------------- #

    @property
    def scopes(self) -> list[str]:
        """Which buckets of memory apply to the current project."""
        return ["global", self.project_scope]

    @property
    def write_scope(self) -> str:
        return (self.project_scope if self.config.learning.share_scope == "project"
                else "global")

    # -- 0. reflex: what the user changed since last time ------------------ #

    def before_turn(self, user_text: str, episode_id: int = 0) -> Outcome:
        """Fold in everything the user has done since the previous turn.

        Deliberately runs *before* recall rather than after the task, so a
        correction made a moment ago is already in force for the request being
        typed now. That immediacy is the whole point: fix it once, and the next
        answer is different.
        """
        if not self.config.learning.enabled or not self.config.learning.corrections:
            return Outcome()

        outcome = self.detector.scan_corrections(episode_id)
        message_outcome = self.detector.record_user_message(user_text, episode_id)
        outcome.new_rules.extend(message_outcome.new_rules)

        if outcome.new_rules and self.config.learning.announce:
            self.bus.emit(Kind.MEMORY, action="rule",
                          items=[rule.as_dict() for rule in outcome.new_rules],
                          corrections=len(outcome.corrections))
        return outcome

    def on_undo(self, paths: list[str]) -> None:
        self.detector.record_undo(paths)

    def on_denied(self, tool: str, subject: str) -> Outcome:
        """A refused permission, recorded as a preference."""
        if not self.config.learning.enabled or not self.config.learning.corrections:
            return Outcome()
        outcome = self.detector.record_denial(tool, subject)
        if outcome.new_rules and self.config.learning.announce:
            self.bus.emit(Kind.MEMORY, action="rule",
                          items=[rule.as_dict() for rule in outcome.new_rules])
        return outcome

    def bootstrap_project(self) -> int:
        """Read the project's existing conventions once, in the background."""
        if not self.config.learning.enabled or not self.config.learning.rules:
            return 0

        def work() -> None:
            try:
                self.detector.scan_project(self.config.paths.project)
            except Exception:
                pass

        thread = threading.Thread(target=work, daemon=True, name="comodor-scan")
        thread.start()
        self._threads.append(thread)
        return 1

    # -- 1. recall -------------------------------------------------------- #

    def active_rules(self) -> list[Rule]:
        """The house rules confident enough to shape this turn."""
        if not self.config.learning.enabled or not self.config.learning.rules:
            return []
        return self.store.confident_rules(self.scopes)

    def prefetch(self, query: str) -> None:
        """Warm recall for a draft the user is still typing.

        Called from the UI's idle path. By the time Enter is pressed the answer
        is usually already computed, so recall costs nothing on the turn itself.
        """
        if not query.strip() or not self.config.learning.enabled:
            return
        try:
            lessons = self.recall(query)
        except Exception:
            return
        with self._prefetch_lock:
            self._prefetched = (query, lessons)

    def take_prefetched(self, query: str) -> list[Lesson] | None:
        """The prefetched result, if it was for this exact query."""
        with self._prefetch_lock:
            cached = self._prefetched
            self._prefetched = None
        if cached and cached[0].strip() == query.strip():
            return cached[1]
        return None

    def recall(self, query: str) -> list[Lesson]:
        """The lessons worth spending context on for this request."""
        if not self.config.learning.enabled or not query.strip():
            return []

        learning = self.config.learning
        selected: list[Lesson] = []
        seen: set[int] = set()

        # Pinned lessons are unconditional — the user asked for them every time.
        for lesson in self.store.pinned_lessons(self.scopes):
            selected.append(lesson)
            seen.add(lesson.id)

        ranked = self.store.search_lessons(query, self.scopes, limit=learning.top_k * 3)
        scored = sorted(
            ((lesson, score(relevance, lesson, learning.half_life_days, query))
             for lesson, relevance in ranked if lesson.id not in seen),
            key=lambda pair: pair[1], reverse=True,
        )
        for lesson, value in scored:
            if len(selected) >= learning.top_k:
                break
            if value <= 0.01:              # too weak or too distrusted to bother
                continue
            selected.append(lesson)
            seen.add(lesson.id)

        return selected

    def recall_skills(self, query: str, limit: int = 2) -> list[Skill]:
        if not self.config.learning.enabled:
            return []
        return [skill for skill, _ in self.store.search_skills(query, limit=limit)
                if skill.success_rate >= 0.4]

    def render_playbook(self, lessons: list[Lesson], skills: list[Skill] | None = None,
                        max_tokens: int | None = None,
                        rules: list[Rule] | None = None) -> str:
        """Format recalled memory for the system prompt, within a token budget.

        House rules come first and carry their own budget. They are counted facts
        about how this user works rather than prose a model wrote, so they are
        both cheaper and more reliable than a lesson, and they should survive a
        tight budget that truncates the rest.
        """
        blocks: list[str] = []
        if rules:
            rules_block = rules_module.render_rules(rules, max_tokens=300)
            if rules_block:
                blocks.append(rules_block)

        if not lessons and not skills:
            return "\n\n".join(blocks)

        budget = max_tokens or self.config.learning.max_playbook_tokens
        lines = [PLAYBOOK_HEADER, ""]
        used = len(PLAYBOOK_HEADER) // 4

        for lesson in lessons:
            confidence = lesson.effective_confidence(self.config.learning.half_life_days)
            entry = f"- ({lesson.kind}, {confidence:.0%}) When {lesson.trigger}: {lesson.guidance}"
            cost = len(entry) // 4 + 1
            if used + cost > budget:
                break
            lines.append(entry)
            used += cost

        for skill in skills or []:
            entry = (f"- (skill: {skill.name}, {skill.success_rate:.0%} success) "
                     f"{skill.description} Steps: {'; '.join(skill.steps[:6])}")
            cost = len(entry) // 4 + 1
            if used + cost > budget:
                break
            lines.append(entry)
            used += cost

        if len(lines) > 2:
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    # -- 3. credit -------------------------------------------------------- #

    def record_outcome(self, goal: str, messages: list[Any], recalled: list[Lesson],
                       success: bool, stopped: str, steps: int, elapsed: float,
                       approvals: int = 0, tokens: int = 0,
                       corrections: int = 0) -> None:
        """Close the loop on one task: credit, store, then reflect in the background."""
        tools_used = sorted({message.name for message in messages
                             if getattr(message.role, "value", "") == "tool" and message.name})
        errors = [message for message in messages
                  if getattr(message.role, "value", "") == "tool" and message.is_error]

        episode = self.store.add_episode(Episode(
            session_id=self.session_id,
            goal=goal[:1000],
            scope=self.project_scope,
            success=success,
            stopped=stopped,
            steps=steps,
            elapsed=elapsed,
            tools_used=tools_used,
            error_kind=(errors[-1].name if errors else ""),
            approvals_asked=approvals,
            tokens=tokens,
            corrections=corrections,
            retries=len(errors),
            rules_active=len(self.active_rules()),
        ))

        if self.config.learning.corrections:
            self.detector.record_retries(messages, episode.id)

        if recalled:
            # Credit assignment is coarse on purpose: precisely attributing a
            # multi-step outcome to individual lessons is not solvable here, and
            # over many episodes the coarse signal still separates the useful
            # lessons from the useless ones.
            self.store.credit([lesson.id for lesson in recalled], won=success)

        if self.config.learning.reflect and self.gateway is not None:
            self._reflect_async(goal, list(messages), stopped, episode.id)

    # -- 4. reflect ------------------------------------------------------- #

    def _reflect_async(self, goal: str, messages: list[Any], outcome: str,
                       episode_id: int) -> None:
        thread = threading.Thread(
            target=self._reflect, args=(goal, messages, outcome, episode_id),
            daemon=True, name="comodor-reflect",
        )
        thread.start()
        self._threads.append(thread)

    def _reflect(self, goal: str, messages: list[Any], outcome: str,
                 episode_id: int) -> None:
        model = self.config.learning.reflect_model or self.config.active_model()
        result = reflection_module.reflect(
            gateway=self.gateway, model=model, goal=goal, messages=messages,
            outcome=outcome, scope=self.write_scope, source=f"episode:{episode_id}",
        )
        if result.empty:
            return

        with self._reflect_lock:
            learned, merged = self._absorb(result.lessons)
            if result.skill is not None:
                self.store.add_skill(result.skill)

        if learned or merged or result.skill:
            self.bus.emit(
                Kind.MEMORY, action="learned",
                items=[lesson.as_dict() for lesson in learned],
                merged=merged,
                skill=result.skill.name if result.skill else "",
            )

    def _absorb(self, lessons: list[Lesson]) -> tuple[list[Lesson], int]:
        """Store new lessons, merging anything we already know."""
        stored: list[Lesson] = []
        merged = 0
        for lesson in lessons:
            existing = self.store.find_similar(lesson.text, threshold=0.55,
                                               scopes=self.scopes)
            if existing is not None:
                # Seeing the same thing twice is evidence, not a duplicate.
                existing.confidence = min(0.98, existing.confidence + 0.08)
                existing.wins += 1
                self.store.update_lesson(existing)
                merged += 1
                continue
            stored.append(self.store.add_lesson(lesson))
        return stored, merged

    def wait_for_reflection(self, timeout: float = 30.0) -> None:
        """Block until background reflection settles — used by tests and exit."""
        deadline = time.monotonic() + timeout
        for thread in list(self._threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        self._threads = [thread for thread in self._threads if thread.is_alive()]

    # -- 5. consolidate --------------------------------------------------- #

    def consolidate(self) -> int:
        learning = self.config.learning
        return self.store.consolidate(learning.min_confidence, learning.half_life_days)

    # -- user-facing controls --------------------------------------------- #

    def teach(self, text: str, kind: str = "preference", pinned: bool = True) -> Lesson:
        """Record something the user stated directly.

        Pinned by default and given high confidence: an explicit instruction is
        much better evidence than anything the agent infers on its own.
        """
        trigger, _, guidance = text.partition(":")
        if not guidance:
            trigger, guidance = "generally", text
        lesson = Lesson(
            kind=kind, scope=self.write_scope,
            trigger=trigger.strip()[:300] or "generally",
            guidance=guidance.strip()[:600],
            confidence=0.9, pinned=pinned, source="user",
        )
        stored = self.store.add_lesson(lesson)
        self.bus.emit(Kind.MEMORY, action="taught", items=[stored.as_dict()])
        return stored

    def forget(self, lesson_id: int) -> bool:
        removed = self.store.delete_lesson(lesson_id)
        if removed:
            self.bus.emit(Kind.MEMORY, action="forgot", id=lesson_id)
        return removed

    def pin(self, lesson_id: int, pinned: bool = True) -> bool:
        for lesson in self.store.all_lessons():
            if lesson.id == lesson_id:
                lesson.pinned = pinned
                self.store.update_lesson(lesson)
                return True
        return False

    def feedback(self, lessons: list[Lesson], good: bool, note: str = "") -> None:
        """Explicit /good or /bad on the last answer."""
        if lessons:
            self.store.credit([lesson.id for lesson in lessons], won=good)
        for lesson in lessons:
            self.store.add_feedback("lesson", lesson.id, 1.0 if good else -1.0, note)
        self.bus.emit(Kind.MEMORY, action="feedback", good=good,
                      count=len(lessons), note=note)

    def search(self, query: str, limit: int = 20) -> list[Lesson]:
        if not query.strip():
            return self.store.all_lessons(self.scopes)[:limit]
        return [lesson for lesson, _ in
                self.store.search_lessons(query, self.scopes, limit=limit)]

    # -- house rules ------------------------------------------------------ #

    def all_rules(self) -> list[Rule]:
        return self.store.all_rules(self.scopes)

    def teach_rule(self, statement: str) -> Rule:
        """A rule the user stated outright, which outranks anything inferred."""
        key = "user." + "-".join(statement.lower().split()[:4])[:60]
        rule = self.store.observe_rule(
            key=key, scope=self.write_scope, category="preference",
            statement=statement.strip()[:300], detail="you told me directly",
            source="user", weight=3)
        self.bus.emit(Kind.MEMORY, action="rule", items=[rule.as_dict()])
        return rule

    def forget_rule(self, rule_id: int) -> bool:
        removed = self.store.delete_rule(rule_id)
        if removed:
            self.bus.emit(Kind.MEMORY, action="forgot_rule", id=rule_id)
        return removed

    def set_rule(self, rule_id: int, *, pinned: bool | None = None,
                 active: bool | None = None) -> bool:
        return self.store.set_rule_flags(rule_id, pinned=pinned, active=active)

    def export_rules(self, target: Path | None = None) -> Path:
        """Write the learned conventions where a team can read and commit them."""
        destination = Path(target) if target else (
            self.config.paths.project_dir / "house-rules.md")
        rules = [rule for rule in self.all_rules() if rule.confident]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            rules_module.export_markdown(rules, project=str(self.config.paths.project)),
            encoding="utf-8")
        return destination

    def stats(self) -> dict[str, Any]:
        data = self.store.stats()
        data["scope"] = self.project_scope
        return data

    def close(self) -> None:
        self.wait_for_reflection(timeout=5.0)
        self.store.close()
