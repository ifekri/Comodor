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

    @property
    def empty(self) -> bool:
        return not (self.corrections or self.new_rules or self.reinforced)


class SignalDetector:
    """Turns observed user actions into counted rules."""

    def __init__(self, store: BrainStore, checkpoints: Any, scope: str,
                 session_id: str = "", redact: Any = None) -> None:
        self.store = store
        self.checkpoints = checkpoints
        self.scope = scope
        self.session_id = session_id
        self.redact = redact or (lambda text: text)
        self.last_user_text = ""
        self.last_user_at = 0.0
        self._seen_hashes: dict[str, str] = {}

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
            self._apply(observations, source="correction", outcome=outcome)

        return outcome

    # -- 2. the change the user threw away -------------------------------- #

    def record_undo(self, paths: list[str], episode_id: int = 0) -> Outcome:
        """`/undo` is an unambiguous rejection of what the agent just did."""
        outcome = Outcome()
        for path in paths:
            self.store.add_signal(Signal(
                kind="undo", session_id=self.session_id, episode_id=episode_id,
                subject=str(path), weight=2.0,
            ))
            # Whatever the agent wrote there is no longer the user's file, so it
            # must not later be read back as if they had accepted it.
            self._seen_hashes.pop(str(path), None)
        return outcome

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
        )
        self._collect(rule, outcome)
        return outcome

    # -- 4. the question the user had to ask twice ------------------------ #

    def record_user_message(self, text: str, episode_id: int = 0) -> Outcome:
        """A near-repeat of the last message means the answer missed."""
        outcome = Outcome()
        now = time.time()
        previous, previous_at = self.last_user_text, self.last_user_at
        self.last_user_text, self.last_user_at = text, now

        if not previous or now - previous_at > REPHRASE_WINDOW:
            return outcome
        if similarity(previous, text) < REPHRASE_SIMILARITY:
            return outcome

        self.store.add_signal(Signal(
            kind="rephrase", session_id=self.session_id, episode_id=episode_id,
            subject=self.redact(text)[:200], weight=1.0,
        ))
        return outcome

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
            )
            self._collect(rule, outcome)
        return outcome

    # -- 6. what the project already looks like --------------------------- #

    def scan_project(self, root: Path, max_files: int = 60) -> Outcome:
        """A one-off read of the codebase's existing conventions."""
        outcome = Outcome()
        try:
            observations = rules_module.scan_project(Path(root), max_files=max_files)
        except Exception:
            return outcome
        self._apply(observations, source="observation", outcome=outcome)
        return outcome

    # -- shared ----------------------------------------------------------- #

    def _apply(self, observations: list[rules_module.Observation], source: str,
               outcome: Outcome) -> None:
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
