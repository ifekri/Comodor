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

        # Curated memory: a small, separate shelf. The facts service is
        # cheap to build (one store handle, no threads) and is created even
        # when learning is off, so /memory can still list what was learned
        # before it was switched off.
        from .facts import FactService

        self.facts = FactService(
            self.store, scopes=["global", self.project_scope],
            write_scope=self.write_scope,
        )
        #: The briefing block, built once. Facts learned after this point
        #: join the next session, not this one — the prefix-cache rule.
        self.facts_briefing = ""

        # Reflex: the fast lane. Deterministic, model-free, always on.
        self.detector = SignalDetector(
            store=self.store, checkpoints=checkpoints, scope=self.project_scope,
            session_id=self.session_id, redact=redact,
        )
        self._prefetched: tuple[str, list[Lesson]] | None = None
        self._prefetch_lock = threading.Lock()
        #: The learned vocabulary. Read on first recall, not on start-up.
        self._associations = None
        self._reviewer: Any = None
        self.freeze_facts()

    # -- curated facts ----------------------------------------------------- #

    def freeze_facts(self) -> None:
        """Take the session's facts snapshot.

        Called once at construction. Everything the briefing says for the
        rest of this session was true when it was taken, which is exactly
        what keeps the head of every request byte-identical.
        """
        try:
            self.facts_briefing = self.facts.snapshot()
        except Exception:
            self.facts_briefing = ""

    def refresh_facts(self) -> str:
        """Rebuild the snapshot deliberately — a new conversation, a /memory change."""
        self.facts_briefing = self.facts.snapshot()
        return self.facts_briefing

    @property
    def review_spent(self) -> float:
        """What background review has cost this session, in USD."""
        reviewer = self._reviewer
        usage = getattr(reviewer, "usage", None) if reviewer else None
        return float(getattr(usage, "cost_usd", 0.0) or 0.0)

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

    @property
    def associations(self):
        """The learned vocabulary, read once and kept.

        Lazily, because a brain that is never asked to recall anything — a
        `--version`, a `doctor` — should not pay to parse it.
        """
        if self._associations is None:
            from .associations import Associations

            try:
                self._associations = self.store.load_associations()
            except Exception:              # noqa: BLE001 - never fatal
                self._associations = Associations()
        return self._associations

    def recall(self, query: str) -> list[Lesson]:
        """The lessons worth spending context on for this request.

        The query is searched as written *and* as the vocabulary implies. A
        request for "tests for the parser" and a lesson reading "use pytest
        fixtures" share no word at all, and without the second search the right
        lesson is invisible — see `associations.py` for how the link between
        them is learned by counting rather than guessed by a model.
        """
        if not self.config.learning.enabled or not query.strip():
            return []

        learning = self.config.learning
        selected: list[Lesson] = []
        seen: set[int] = set()

        # Pinned lessons are unconditional — the user asked for them every time.
        for lesson in self.store.pinned_lessons(self.scopes):
            selected.append(lesson)
            seen.add(lesson.id)

        # Both, and the results merged: an exact match must never be displaced
        # by an inferred one, so the original query's hits are ranked first and
        # the expansion only adds candidates the plain search never saw.
        ranked = self.store.search_lessons(query, self.scopes, limit=learning.top_k * 3)
        if learning.associative:
            ranked = self._with_associates(query, ranked, learning.top_k * 3)
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

    def _with_associates(self, query: str, ranked: list, limit: int) -> list:
        """Add what the learned vocabulary suggests, ranked below what matched.

        The expansion's relevance is scaled down before it competes, so a
        lesson found only by association can be recalled when nothing else was
        and cannot outrank a lesson the user's own words found.
        """
        enriched = self.associations.enrich(query)
        if enriched == query:
            return ranked

        try:
            extra = self.store.search_lessons(enriched, self.scopes, limit=limit)
        except Exception:                  # noqa: BLE001 - recall is best-effort
            return ranked

        from .associations import EXPANSION_WEIGHT

        seen = {lesson.id for lesson, _ in ranked}
        merged = list(ranked)
        for lesson, relevance in extra:
            if lesson.id in seen:
                continue
            merged.append((lesson, relevance * EXPANSION_WEIGHT))
            seen.add(lesson.id)
        return merged

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
                       corrections: int = 0, cancel_reason: str = "") -> None:
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

        # One task is one bag of words that belonged together. This is where
        # the vocabulary comes from, and it costs a few hundred microseconds
        # against work that has just taken seconds.
        if self.config.learning.associative:
            self._learn_vocabulary(goal, tools_used, messages)

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

        self._review_async(messages, stopped, episode.id)

    # -- 4. reflect ------------------------------------------------------- #

    def _reflect_async(self, goal: str, messages: list[Any], outcome: str,
                       episode_id: int) -> None:
        thread = threading.Thread(
            target=self._reflect, args=(goal, messages, outcome, episode_id),
            daemon=True, name="comodor-reflect",
        )
        thread.start()
        self._threads.append(thread)

    def _review_async(self, messages: list[Any], outcome: str,
                      episode_id: int, cancel_reason: str = "") -> None:
        """The curated-memory review, after the turn has fully ended.

        Announced through the bus when something stuck, for the same reason
        every other learned thing is announced: silent adaptation is the
        version of this feature nobody trusts.
        """
        if not self.config.learning.enabled or not self.config.learning.review:
            return
        if self.gateway is None:
            return

        if self._reviewer is None:
            from .review import Reviewer

            self._reviewer = Reviewer(
                self.facts, self.gateway,
                model=self.config.learning.review_model,
                write_scope=self.write_scope,
                staging=self.config.learning.review_write_approval,
            )
            self._reviewer.on_accepted = self._announce_facts
        thread = self._reviewer.review_async(
            messages, outcome, episode_id, cancel_reason=cancel_reason)
        if thread is not None:
            self._threads.append(thread)

    def _announce_facts(self, facts: list[Any], staged: bool) -> None:
        """Say what the review wrote, once it has actually written it."""
        if not facts:
            return
        verb = "proposed" if staged else "remembered"
        self.bus.emit(
            Kind.MEMORY, action="facts",
            items=[fact.as_dict() if hasattr(fact, "as_dict") else {"text": str(fact)}
                   for fact in facts],
            staged=staged, verb=verb)

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

    def _learn_vocabulary(self, goal: str, tools: list[str], messages: list) -> None:
        """Relate the words of one finished task.

        The goal, what the tools touched, and what the user said — not the
        model's own prose, which is long, fluent and mostly filler, and would
        swamp the counts with words nobody chose.
        """
        try:
            said = [message.content for message in messages
                    if getattr(message.role, "value", "") == "user"
                    and message.content][:6]
            targets = [message.name for message in messages
                       if getattr(message.role, "value", "") == "tool"
                       and message.name][:20]
            self.associations.observe(goal, " ".join(tools), " ".join(targets), *said)
        except Exception:                  # noqa: BLE001 - never fatal
            pass

    def consolidate(self) -> int:
        learning = self.config.learning
        if self._associations is not None:
            try:
                self._associations.prune()
                self.store.save_associations(self._associations)
            except Exception:              # noqa: BLE001 - never fatal
                pass
        self._curate_if_due()
        return self.store.consolidate(learning.min_confidence, learning.half_life_days)

    def _curate_if_due(self) -> None:
        """The curator's idle trigger, riding the shutdown path.

        This runs when the interface closes — the one moment the agent is
        provably not mid-task — and only when the interval has passed. A
        pass costs no tokens and takes milliseconds, so it rides here rather
        than earning its own daemon.
        """
        try:
            if not self.config.curator.enabled:
                return
            from . import curator

            if not curator.due(self.store, self.config.curator.interval_days):
                return
            curator.run(self.store, self.config, skills_root=self.config.paths.skills)
        except Exception:                  # noqa: BLE001 - never fatal
            pass

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

    # -- curated facts: user-facing controls ------------------------------- #

    def fact_entries(self, include_staged: bool = False) -> list:
        try:
            return self.facts.entries(include_staged=include_staged)
        except Exception:
            return []

    def add_fact(self, text: str, kind: str = "memory") -> Any:
        """The user wrote a fact by hand. Settled at once, pinned to nothing."""
        stored = self.facts.add(text, kind=kind)
        self.refresh_facts()
        self.bus.emit(Kind.MEMORY, action="taught", items=[stored.as_dict()])
        return stored

    def remove_fact(self, fact_id: int) -> bool:
        for fact in self.facts.entries(include_staged=True):
            if fact.id == fact_id:
                self.facts.store.delete_fact(fact_id)
                self.refresh_facts()
                self.bus.emit(Kind.MEMORY, action="forgot_fact", id=fact_id)
                return True
        return False

    def decide_fact(self, fact_id: int, approve: bool) -> bool:
        """Approve or reject a staged fact proposed by the review."""
        from .facts import STATUS_SETTLED

        if approve:
            done = self.facts.set_staged(fact_id, STATUS_SETTLED)
        else:
            done = self.facts.store.delete_fact(fact_id)
        if done:
            self.refresh_facts()
        return done

    def pin_fact(self, fact_id: int, pinned: bool = True) -> bool:
        done = self.facts.pin(fact_id, pinned)
        if done:
            self.refresh_facts()
        return done

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
        """What the store holds, and what applies *here*.

        `rules_active` is overridden on the way out. The store counts every
        confident rule it has, across every project it has ever learned in,
        which is the right answer for `doctor` and the wrong one for anything
        telling somebody what is shaping the conversation in front of them.

        The two disagreed by eight: rules learned in another folder, counted
        in the status strip, and absent from the panel that lists them —
        because the panel is scoped and the count was not. A number nobody can
        click through to is a number to distrust, and rightly.
        """
        data = self.store.stats()
        data["scope"] = self.project_scope
        data["rules_everywhere"] = data.get("rules_active", 0)
        data["rules_active"] = len(self.active_rules())
        data["rules_here"] = len(self.store.all_rules(self.scopes))
        data["facts_here"] = len(self.facts.entries())
        data["review_cost_usd"] = self.review_spent
        return data

    def close(self) -> None:
        self.wait_for_reflection(timeout=5.0)
        self.store.close()
