"""Learning from what the user does, not from what they say.

Praise is rare and vague; correction is frequent and precise. When somebody
rewrites the function the agent just wrote, undoes an edit, or refuses a command,
they have labelled that behaviour more clearly than any rating could — and they
did it as a side effect of working, at no cost to themselves.

Every detector here is deterministic and runs in microseconds, so this learning
continues when the user is offline, on a cheap model, or has reflection switched
off. That is the difference between a memory that needs a budget and one that is
simply always on.

Detection happens at the *start* of a turn rather than the end, which gives the
system its most useful property: fix something the agent wrote, ask it for the
next thing, and the correction is already in force.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import rules as rules_module
from .bm25 import similarity
from .store import BrainStore, Rule, Signal

# A correction is only attributed to the agent for a while after it wrote the
# file. Beyond that the user is simply working on their code, and reading intent
# into it would be an invention.
CORRECTION_WINDOW = 90 * 60.0
REPHRASE_WINDOW = 120.0
REPHRASE_SIMILARITY = 0.6
MAX_DIFF_CHARS = 4000


@dataclass
class Correction:
    """One file the user changed after the agent wrote it."""

    path: str
    before: str                    # what the agent left
    after: str                     # what the user made of it
    observations: list[rules_module.Observation] = field(default_factory=list)

    @property
    def understood(self) -> bool:
        """Whether anything transferable was extracted from the change."""
        return bool(self.observations)


@dataclass
class Outcome:
    """What one detection pass found, and what it changed."""

    corrections: list[Correction] = field(default_factory=list)
    new_rules: list[Rule] = field(default_factory=list)
    reinforced: list[Rule] = field(default_factory=list)
    #: Facts admitted from the user's own words this pass (terminology),
    #: and what was refused at the door — a cap, an injection — with why.
    new_facts: list[Any] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    #: Items a newer contradicting one displaced (FR-059): (older, newer).
    superseded: list[tuple[Any, Any]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.corrections or self.new_rules or self.reinforced
                    or self.new_facts or self.superseded)


class SignalDetector:
    """Turns observed user actions into counted rules."""

    def __init__(self, store: BrainStore, checkpoints: Any, scope: str,
                 session_id: str = "", redact: Any = None, facts: Any = None) -> None:
        self.store = store
        self.checkpoints = checkpoints
        self.scope = scope
        self.session_id = session_id
        self.redact = redact or (lambda text: text)
        #: The curated shelf, for what the user defines in their own words.
        #: Optional: a detector built without one tallies and learns rules
        #: but admits no facts.
        self.facts = facts
        self.last_user_text = ""
        self.last_user_at = 0.0
        self._seen_hashes: dict[str, str] = {}
        #: Which user message this is; an instruction is "recurring" when
        #: it arrived in more than one (FR-108).
        self._turn = 0
        #: Instruction messages seen per subject, keyed `(session, marker)`.
        #: Held in memory so a repeat is recognised before the async writer
        #: has flushed the earlier one; the database is still the record.
        self._instruction_seen: dict[str, set[tuple[str, str]]] = {}

    # -- 1. the file the user rewrote ------------------------------------- #

    def scan_corrections(self, episode_id: int = 0) -> Outcome:
        """Find files the agent wrote that the user has since changed."""
        outcome = Outcome()
        if self.checkpoints is None:
            return outcome

        cutoff = time.time() - CORRECTION_WINDOW
        try:
            entries = self.checkpoints.touched_since(cutoff)
        except Exception:
            return outcome

        for entry in entries:
            current = self.checkpoints.hash_of(entry.path)
            if current is None or current == entry.after_blob:
                continue
            # Only report a given rewrite once, however many turns follow it.
            if self._seen_hashes.get(entry.path) == current:
                continue
            self._seen_hashes[entry.path] = current

            written = self.checkpoints.read_blob(entry.after_blob)
            try:
                now_text = Path(entry.path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not written or written == now_text:
                continue

            observations = rules_module.analyse_correction(written, now_text, entry.path)
            correction = Correction(path=entry.path, before=written, after=now_text,
                                    observations=observations)
            outcome.corrections.append(correction)

            self.store.add_signal(Signal(
                kind="correction", session_id=self.session_id, episode_id=episode_id,
                subject=entry.path,
                payload=self.redact(_summarise_change(written, now_text)),
                weight=2.0,
            ))
            self._apply(observations, source="correction", outcome=outcome,
                        provenance="user_correction", source_ref=entry.path,
                        fingerprint=_fingerprint(now_text))

        return outcome

    # -- 2. the change the user threw away -------------------------------- #

    def record_undo(self, paths: list[str], episode_id: int = 0) -> Outcome:
        """An undo is an unambiguous rejection of what the agent just did.

        It is also a correction (contract L1): the checkpoint holds what the
        agent wrote, the file holds what the user reverted it to, and the
        difference is a preference stated by action — with provenance
        `user_correction` (FR-109).
        """
        outcome = Outcome()
        for path in paths:
            self.store.add_signal(Signal(
                kind="undo", session_id=self.session_id, episode_id=episode_id,
                subject=str(path), weight=2.0,
            ))
            # Whatever the agent wrote there is no longer the user's file, so it
            # must not later be read back as if they had accepted it.
            self._seen_hashes.pop(str(path), None)

            written = self._written_blob(path)
            now_text = _read_text(path)
            if not written or not now_text or written == now_text:
                continue
            observations = rules_module.analyse_correction(written, now_text, str(path))
            if not observations:
                continue
            outcome.corrections.append(Correction(
                path=str(path), before=written, after=now_text, observations=observations))
            self._apply(observations, source="correction", outcome=outcome,
                        provenance="user_correction", source_ref=str(path),
                        fingerprint=_fingerprint(now_text))
        return outcome

    def _written_blob(self, path: str) -> str:
        """What the agent last wrote to `path`, from the checkpoint record."""
        newest = ""
        newest_at = -1.0
        try:
            entries = self.checkpoints.entries()
        except Exception:                  # noqa: BLE001 - learning is best-effort
            return ""
        for entry in entries:
            if str(getattr(entry, "path", "")) != str(path):
                continue
            at = float(getattr(entry, "at", 0.0) or 0.0)
            if at < newest_at:
                continue
            try:
                blob = self.checkpoints.read_blob(entry.after_blob)
            except Exception:              # noqa: BLE001
                continue
            if blob:
                newest, newest_at = blob, at
        return newest

    # -- 3. the command the user refused ---------------------------------- #

    def record_denial(self, tool: str, subject: str, episode_id: int = 0) -> Outcome:
        """A denied permission names one thing this user does not want done."""
        outcome = Outcome()
        self.store.add_signal(Signal(
            kind="denial", session_id=self.session_id, episode_id=episode_id,
            subject=f"{tool}:{subject}"[:200], payload=self.redact(subject)[:400],
            weight=2.0,
        ))
        target, statement = _describe_denial(tool, subject)
        rule = self.store.observe_rule(
            key=f"avoid.{tool}.{target}"[:80],
            scope=self.scope,
            category="avoid",
            statement=statement,
            detail=f"declined: {self.redact(subject)[:120]}",
            source="correction",
            weight=2,               # a refusal is explicit; it needs no repetition
            provenance="user_correction",
            source_ref=f"{tool}:{target}",
        )
        self._collect(rule, outcome)
        return outcome

    # -- 4. the question the user had to ask twice ------------------------ #

    def record_user_message(self, text: str, episode_id: int = 0) -> Outcome:
        """What one user message teaches, deterministically.

        A near-repeat of the last message means the answer missed. A
        definition in the user's own words is a fact (FR-106). A standing
        instruction is tallied, and becomes a rule only once it has been
        given in more than one message — a one-off stays a one-off (FR-108).
        """
        outcome = Outcome()
        now = time.time()
        self._turn += 1
        previous, previous_at = self.last_user_text, self.last_user_at
        self.last_user_text, self.last_user_at = text, now

        self._learn_terminology(text, outcome, episode_id)
        self._learn_instructions(text, outcome, episode_id)

        if not previous or now - previous_at > REPHRASE_WINDOW:
            return outcome
        if similarity(previous, text) < REPHRASE_SIMILARITY:
            return outcome

        self.store.add_signal(Signal(
            kind="rephrase", session_id=self.session_id, episode_id=episode_id,
            subject=self.redact(text)[:200], weight=1.0,
        ))
        return outcome

    def _learn_terminology(self, text: str, outcome: Outcome, episode_id: int) -> None:
        """A term the user defined is a fact on the shelf, at once.

        Provenance `user_statement`, the message as its source. A later
        definition of the same term supersedes the earlier one: the older
        fact is kept and marked, never dropped (FR-059). The shelf's cap is
        the cap — at it, the refusal is reported, not worked around (FR-065).
        """
        if self.facts is None:
            return
        for observation in rules_module.analyse_terminology(text):
            term = observation.key[len("term."):]
            prefix = f'"{term}" means '
            # Every row for the term, superseded ones included: defining a term
            # back to something it said before must revive that row, not insert
            # a duplicate the unique `(scope, kind, text)` index would refuse.
            known = [fact for fact in self.store.all_facts(
                        self.facts.scopes, kinds=["memory"], settled_only=False)
                     if fact.text.lower().startswith(prefix)]
            active = [fact for fact in known if fact.lifecycle == "active"]
            wanted = observation.statement.lower()
            revived = next((fact for fact in known if fact.text.lower() == wanted), None)
            if revived is not None:
                if revived.lifecycle != "active":
                    self.store.set_lifecycle("facts", revived.id, "active")
                for fact in active:
                    if fact.id != revived.id:
                        self.store.supersede("facts", fact.id, revived.id)
                        outcome.superseded.append((fact, revived))
                continue
            # A new definition: the active ones step aside first so the
            # replacement is not refused by a cap an older one is holding; put
            # them back if nothing lands.
            for fact in active:
                self.store.set_lifecycle("facts", fact.id, "superseded")
            try:
                stored = self.facts.add(
                    observation.statement, kind="memory", origin_episode=episode_id,
                    provenance="user_statement",
                    source_ref=f"user message (turn {self._turn})")
            except ValueError as refused:
                for fact in active:
                    self.store.set_lifecycle("facts", fact.id, "active")
                outcome.refused.append(f"{observation.statement}: {refused}")
                continue
            for fact in active:
                self.store.supersede("facts", fact.id, stored.id)
                outcome.superseded.append((fact, stored))
            outcome.new_facts.append(stored)

    def _learn_instructions(self, text: str, outcome: Outcome, episode_id: int) -> None:
        """A standing instruction becomes a rule the second time it is given.

        The first time is a signal — a durable tally, not a durable rule:
        nothing from a single message reaches the playbook. On the second
        message the rule is admitted with provenance `user_statement`, and
        an active rule of the opposite polarity on the same subject is
        superseded by it (FR-059).
        """
        for observation in rules_module.analyse_instructions(text):
            marker = f"turn:{self._turn}"
            earlier = [signal for signal in self.store.recent_signals("instruction", limit=400)
                       if signal.subject == observation.key]
            # Signals are queued asynchronously, so a message earlier in *this*
            # session may not have reached the database yet. The in-memory
            # record makes recurrence deterministic rather than a function of
            # how quickly the writer flushed (FR-108, SC-025).
            seen = self._instruction_seen.setdefault(observation.key, set())
            seen.update((signal.session_id, signal.payload) for signal in earlier)
            if (self.session_id, marker) in seen:
                continue                                 # same message, seen
            seen.add((self.session_id, marker))
            self.store.add_signal(Signal(
                kind="instruction", session_id=self.session_id, episode_id=episode_id,
                subject=observation.key, payload=marker, weight=1.0))
            messages = {(signal.session_id, signal.payload) for signal in earlier} | seen
            if len(messages) < 2:
                continue
            rule = self.store.observe_rule(
                key=observation.key, scope=self.scope,
                category=observation.category, statement=observation.statement,
                detail=f"given in {len(messages)} separate messages",
                source="user", weight=1,
                provenance="user_statement", source_ref="user messages")
            self._collect(rule, outcome)
            contrary = rules_module.opposite_key(observation.key)
            for older in self.store.all_rules([self.scope], active_only=True):
                if older.key == contrary and older.id != rule.id:
                    self.store.supersede("rules", older.id, rule.id)
                    outcome.superseded.append((older, rule))

    # -- 5. the tool that kept failing the same way ----------------------- #

    def record_retries(self, messages: list[Any], episode_id: int = 0) -> Outcome:
        """Two identical failures in one task is a pitfall, not bad luck."""
        outcome = Outcome()
        failures: dict[tuple[str, str], int] = {}
        for message in messages:
            if getattr(message.role, "value", "") != "tool" or not message.is_error:
                continue
            key = (message.name, _error_class(message.content))
            failures[key] = failures.get(key, 0) + 1

        for (tool, error), count in failures.items():
            if count < 2 or not error:
                continue
            self.store.add_signal(Signal(
                kind="retry", session_id=self.session_id, episode_id=episode_id,
                subject=f"{tool}:{error}", weight=1.0,
            ))
            rule = self.store.observe_rule(
                key=f"pitfall.{tool}.{error}"[:80],
                scope=self.scope,
                category="workflow",
                statement=f"`{tool}` fails here with \"{error}\" — check that "
                          f"before calling it again.",
                detail=f"hit {count} times in one task",
                source="evidence",
                weight=2,
                # The tool itself showed the failure, twice: confirmed by
                # its output, not asserted by the model.
                provenance="tool_confirmed",
                source_ref=f"{tool}:{error}"[:120],
            )
            self._collect(rule, outcome)
        return outcome

    # -- 6. what the project already looks like --------------------------- #

    def scan_project(self, root: Path, max_files: int = 60) -> Outcome:
        """A one-off read of the codebase's existing conventions."""
        outcome = Outcome()
        try:
            observations = rules_module.scan_project(Path(root), max_files=max_files)
            sample = rules_module.sampled_files(Path(root), max_files=max_files)
        except Exception:
            return outcome
        # A counted convention names the files it was counted over and
        # carries a fingerprint of their contents, so a later change to the
        # sample can be checked against the verdict (T111).
        self._apply(observations, source="observation", outcome=outcome,
                    provenance="counted_convention",
                    source_ref=rules_module.manifest_ref(root, sample),
                    fingerprint=rules_module.manifest_fingerprint(sample))
        return outcome

    # -- shared ----------------------------------------------------------- #

    def _apply(self, observations: list[rules_module.Observation], source: str,
               outcome: Outcome, *, provenance: str = "counted_convention",
               source_ref: str = "", fingerprint: str = "") -> None:
        for observation in observations:
            rule = self.store.observe_rule(
                key=observation.key,
                scope=self.scope,
                agrees=observation.agrees,
                category=observation.category,
                statement=observation.statement,
                detail=observation.detail,
                source=source if observation.agrees else "observation",
                weight=observation.weight,
                provenance=provenance,
                source_ref=observation.source_ref or source_ref or observation.key,
                fingerprint=observation.fingerprint or fingerprint,
            )
            self._collect(rule, outcome)

    def _collect(self, rule: Rule, outcome: Outcome) -> None:
        """Separate rules that just crossed into use from ones already in use.

        Only a rule that has *become* confident is worth announcing; repeating
        "learned: use single quotes" on every turn would be noise.
        """
        if not rule.confident:
            return
        from .store import FLOORS

        floor = FLOORS.get(rule.source, 4)
        just_became_confident = rule.source == "user" or rule.support - 2 < floor
        (outcome.new_rules if just_became_confident else outcome.reinforced).append(rule)


def _fingerprint(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _describe_denial(tool: str, subject: str) -> tuple[str, str]:
    """Name what was refused, in the terms that tool works in.

    The permission dialog shows a human summary like ``run: rm -rf build``, so
    the leading verb has to come off before the real subject — a rule that says
    "do not run `run:`" is worse than no rule at all.
    """
    text = subject.strip()
    if ": " in text:
        text = text.split(": ", 1)[1].strip()

    if tool == "run_shell":
        command = text.split()[0] if text.split() else "that command"
        return command, (f"Do not run `{command}` without asking first — this "
                         f"user declined it before.")
    if tool in ("web_fetch", "web_search"):
        return tool, (f"Be careful with `{tool}`: this user declined it before, "
                      f"so ask before reaching the network.")

    target = text.split()[0] if text.split() else tool
    return target, (f"Ask before using `{tool}` on {target} — this user "
                    f"declined that before.")


def _summarise_change(before: str, after: str) -> str:
    """A compact record of a correction, capped so the brain stays small."""
    import difflib

    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                     lineterm="", n=1))
    text = "\n".join(diff[:80])
    return text[:MAX_DIFF_CHARS]


def _error_class(content: str) -> str:
    """A stable label for an error, so the same failure groups together.

    Paths, numbers and quoted values are stripped out: "file a.py not found" and
    "file b.py not found" are the same pitfall.
    """
    text = (content or "").strip().lower()
    if text.startswith("error:"):
        text = text[6:].strip()
    words: list[str] = []
    for word in text.split()[:6]:
        if any(character.isdigit() for character in word):
            continue
        if "/" in word or "\\" in word or word.endswith((".py", ".js", ".ts")):
            continue
        words.append(word.strip("`'\".,:;()"))
    return " ".join(word for word in words if word)[:60]
