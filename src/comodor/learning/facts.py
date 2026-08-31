"""The curated memory: a handful of durable truths, kept deliberately small.

Two kinds share one table and one discipline. ``memory`` facts say what the
project and its environment are like; ``user`` facts say what the person is
like, and travel with them to the next repository. Both are few — eight and
six — and short, because a summary that never ends is a log with better
handwriting, and a log is injected into every turn at full price.

The caps are not a quota to fill. Most sessions should add nothing: the
review's prompt leans hard toward NOTHING, and the tool refuses a thirteenth
fact rather than quietly evicting one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .store import BrainStore, Fact

#: Facts about the project and its environment. Eight is the whole budget —
#: past this, the honest move is to merge, not to grow.
MEMORY_CAP = 8
#: Facts about the person. They apply everywhere, so they are even fewer.
USER_CAP = 6
#: Longest text per fact, in characters. Roughly a sentence.
FACT_MAX_CHARS = 120

KINDS = ("memory", "user")

STATUS_SETTLED = "settled"
STATUS_STAGED = "staged"

#: Shown to the model when a cap is hit. It has to say what to do next, not
#: just that the answer is no — otherwise the model tries the same call again
#: with one word changed.
_CAP_GUIDANCE = "No free slot — replace or remove one instead. Current entries:\n{list}"


class FactError(ValueError):
    """A refusal with the current state attached, so the caller can recover."""


@dataclass
class FactService:
    """Cap, duplicate and matching rules over the facts table."""

    store: BrainStore
    scopes: list[str]
    write_scope: str = "global"

    # -- reading ----------------------------------------------------------- #

    def entries(self, kind: str = "", include_staged: bool = False) -> list[Fact]:
        kinds = [kind] if kind in KINDS else None
        return self.store.all_facts(self.scopes, kinds, settled_only=not include_staged)

    def usage(self, kind: str) -> tuple[int, int]:
        """How many slots are taken and how many exist, for one kind."""
        cap = USER_CAP if kind == "user" else MEMORY_CAP
        return len(self.entries(kind)), cap

    def usage_line(self) -> str:
        """The one-line budget report, as in '67% — 8 of 12'."""
        parts = []
        for kind in KINDS:
            used, cap = self.usage(kind)
            label = "user" if kind == "user" else "memory"
            parts.append(f"{label}: {used}/{cap}")
        return " · ".join(parts)

    # -- writing ------------------------------------------------------------ #

    def add(
        self, text: str, kind: str = "memory", *, staged: bool = False, origin_episode: int = 0
    ) -> Fact:
        """Add one fact, or raise :class:`FactError` saying why not.

        An exact repeat is a success that changed nothing — a model told
        "duplicate" will rephrase and try again, which is how a memory system
        fills with five wordings of one fact.
        """
        kind = _clean_kind(kind)
        text = _clean_text(text)
        _check_injection(text)
        if not text:
            raise FactError("a fact needs text")
        if len(text) > FACT_MAX_CHARS:
            raise FactError(
                f"that is {len(text)} characters; a fact is one sentence, "
                f"{FACT_MAX_CHARS} at most. Trim it and try again."
            )

        existing = [
            fact for fact in self.entries(kind) if fact.text.strip().lower() == text.lower()
        ]
        if existing:
            return existing[0]

        current = self.entries(kind)
        cap = USER_CAP if kind == "user" else MEMORY_CAP
        if len(current) >= cap:
            listing = "\n".join(f"- #{fact.id}: {fact.text}" for fact in current)
            raise FactError(_CAP_GUIDANCE.format(list=listing))

        fact = self.store.add_fact(
            Fact(
                kind=kind,
                scope=self.write_scope,
                text=text,
                origin_episode=origin_episode,
                status=STATUS_STAGED if staged else STATUS_SETTLED,
            )
        )
        if fact is None:  # raced another writer; it won
            for candidate in self.entries(kind):
                if candidate.text.strip().lower() == text.lower():
                    return candidate
            raise FactError("the fact could not be written — try again")
        return fact

    def replace(self, match: str, text: str, kind: str = "memory") -> Fact:
        """Swap the text of one fact for new text, keeping its identity."""
        fact = self._one(match, kind)
        text = _clean_text(text)
        _check_injection(text)
        if len(text) > FACT_MAX_CHARS:
            raise FactError(
                f"that is {len(text)} characters; a fact is one sentence, {FACT_MAX_CHARS} at most."
            )
        updated = self.store.replace_fact(fact.id, text)
        if updated is None:
            raise FactError(f"fact #{fact.id} is gone — list again")
        return updated

    def remove(self, match: str, kind: str = "memory") -> Fact:
        fact = self._one(match, kind)
        self.store.delete_fact(fact.id)
        return fact

    def set_staged(self, fact_id: int, status: str) -> bool:
        """Approve or reject a staged fact. Only staged facts can change."""
        if status not in (STATUS_SETTLED, STATUS_STAGED):
            return False
        for fact in self.entries(include_staged=True):
            if fact.id == fact_id:
                if fact.status != STATUS_STAGED:
                    return False
                return self.store.set_fact_status(fact_id, status)
        return False

    def pin(self, fact_id: int, pinned: bool) -> bool:
        for fact in self.entries(include_staged=True):
            if fact.id == fact_id:
                return self.store.set_fact_pinned(fact_id, pinned)
        return False

    # -- matching ------------------------------------------------------------ #

    def _one(self, match: str, kind: str) -> Fact:
        """Resolve a substring to exactly one fact, or say which ones compete.

        A model asked to drop "the Postgres fact" says what it remembers, not
        the stored sentence. One hit acts; two refuse and name both, because
        picking the first of two is how the wrong one gets deleted.
        """
        needle = match.strip().lower()
        hits = [fact for fact in self.entries(kind) if needle and needle in fact.text.lower()]
        if not hits:
            raise FactError(f"no stored fact contains {match!r} — list the current entries first")
        if len(hits) > 1:
            listing = "\n".join(f"- #{fact.id}: {fact.text}" for fact in hits)
            raise FactError(
                f"{len(hits)} facts match {match!r} — quote more of the one you mean:\n{listing}"
            )
        return hits[0]

    # -- briefing ------------------------------------------------------------ #

    def snapshot(self) -> str:
        """The block injected into the user message, frozen for the session.

        Called once, when the session starts. A fact written mid-session
        shapes the next conversation, not the rest of this one — the same
        rule the playbook lives under, and for the same reason: the head of
        the request must never change, or the provider's prefix cache is
        thrown away on every turn.
        """
        from .render import render_facts

        facts = self.entries(include_staged=False)
        if not facts:
            return ""
        return render_facts(facts)

    # -- background review --------------------------------------------------- #

    def review_async(
        self, gateway: Any, messages: list, outcome: str, episode_id: int = 0, config: Any = None
    ) -> threading.Thread | None:
        """Start the background review of a finished turn, if one is wanted.

        Returns the thread so a caller can wait for it at shutdown. The
        engine owns the collision policy — a new review replaces the old —
        so this only launches.
        """
        from .review import Reviewer

        settings = getattr(config, "learning", None)
        model = ""
        if settings is not None:
            model = getattr(settings, "review_model", "")
        reviewer = Reviewer(self, gateway, model=model)
        return reviewer.review_async(messages, outcome, episode_id)


def _clean_kind(kind: str) -> str:
    kind = (kind or "memory").strip().lower()
    if kind not in KINDS:
        raise FactError(f"kind is 'memory' or 'user', not {kind!r}")
    return kind


def _clean_text(text: str) -> str:
    return " ".join((text or "").split())


def _check_injection(text: str) -> None:
    """Refuse text that is an instruction to a model rather than a fact.

    Nothing here is clever. The patterns are the handful of openers an
    injected fact reliably uses, and the point is not to be a firewall — it
    is that a curated memory the user can read should never read like a
    forged order. Anything that slips through is still visible: facts are
    shown, not hidden, and the user can remove one in one action.
    """
    lowered = text.lower()
    for phrase in (
        "ignore previous instructions",
        "ignore all previous",
        "disregard all previous",
        "disregard the above",
        "forget your instructions",
        "you are now",
        "new instructions:",
        "system prompt",
    ):
        if phrase in lowered:
            raise FactError(
                "that reads like an instruction to the model, not a fact — "
                "facts describe things; they do not give orders"
            )
