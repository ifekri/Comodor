"""The evidence ledger: what the agent is relying on, and how it came to know it.

A record, not a reasoning engine. No model call, no inference, no network.
Every entry is written by something that happened — the user said it, a tool
observed it, a derivation was made from entries that were already sound, a
question was answered — and every state change is one row of a closed table.
What is not in the table cannot happen, and that is the whole point: an
unknown becomes usable only by being stated, observed, answered or derived,
never by being needed.

Three rules do most of the work.

*A derivation never rests on an unknown.* `derive()` refuses a premise that is
not `KNOWN`, `VERIFIED` or `DERIVED`. This is the mechanical form of "do not
fill the gap" (FR-002): a conclusion cannot be built on something the agent
has not got.

*A non-answer never becomes knowledge.* A decision that passed the
materiality test can leave `REQUIRES_CLARIFICATION` only for `KNOWN` (a real
answer), `UNRESOLVED` (cancelled, declined or expired) or `BLOCKED` (nobody
there). None of the last three is usable, and none of them has a path to an
agent-chosen assumption (FR-019, FR-130).

*Entries hold fingerprints, never material.* What a tool read is hashed, not
copied: the ledger knows *that* something was seen and *where*, and can tell
when it has changed, without ever holding a value that could be a secret
(Constitution VIII). The ledger lives on the turn's `ToolContext` and dies
with it; it is never persisted, journaled or snapshotted.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class EvidenceState(str, Enum):
    """The closed runtime lifecycle of an entry (data-model.md §2)."""

    KNOWN = "known"                    # the user stated it
    VERIFIED = "verified"              # observed through a tool or the repository
    DERIVED = "derived"                # follows deterministically from sound entries
    UNKNOWN = "unknown"                # absent, unresolved — the default
    REQUIRES_CLARIFICATION = "requires_clarification"   # an UNKNOWN that matters
    UNRESOLVED = "unresolved"          # asked, and cancelled, declined or expired
    BLOCKED = "blocked"                # mandatory, and nobody there to answer
    VALIDATED = "validated"            # the completion gate confirmed it
    FAILED = "failed"                  # contradicted, or validation failed


STATES: tuple[EvidenceState, ...] = tuple(EvidenceState)

#: The states a decision may rest on. Everything else blocks reliance.
USABLE = frozenset({EvidenceState.KNOWN, EvidenceState.VERIFIED,
                    EvidenceState.DERIVED, EvidenceState.VALIDATED})

#: What a derivation may be built from. `VALIDATED` is terminal and describes
#: delivered work, not a premise, so it is not here.
PREMISES = frozenset({EvidenceState.KNOWN, EvidenceState.VERIFIED,
                      EvidenceState.DERIVED})

#: The complete transition table. `(state, trigger) -> state`; anything not
#: listed is illegal and `transition()` refuses it. Read against data-model.md
#: §2 — the two must agree line for line, and `tests/test_evidence_ledger.py`
#: asserts that they do.
TRANSITIONS: dict[tuple[EvidenceState, str], EvidenceState] = {
    (EvidenceState.UNKNOWN, "materiality"): EvidenceState.REQUIRES_CLARIFICATION,
    (EvidenceState.REQUIRES_CLARIFICATION, "answered"): EvidenceState.KNOWN,
    (EvidenceState.REQUIRES_CLARIFICATION, "cancelled"): EvidenceState.UNRESOLVED,
    (EvidenceState.REQUIRES_CLARIFICATION, "expired"): EvidenceState.UNRESOLVED,
    (EvidenceState.REQUIRES_CLARIFICATION, "unattended"): EvidenceState.BLOCKED,
    (EvidenceState.UNRESOLVED, "answered"): EvidenceState.KNOWN,
    (EvidenceState.KNOWN, "confirmed"): EvidenceState.VALIDATED,
    (EvidenceState.VERIFIED, "confirmed"): EvidenceState.VALIDATED,
    (EvidenceState.DERIVED, "confirmed"): EvidenceState.VALIDATED,
    (EvidenceState.KNOWN, "contradicted"): EvidenceState.FAILED,
    (EvidenceState.VERIFIED, "contradicted"): EvidenceState.FAILED,
    (EvidenceState.DERIVED, "contradicted"): EvidenceState.FAILED,
    (EvidenceState.VERIFIED, "source_changed"): EvidenceState.UNKNOWN,
}

#: FR-001's classification of *how* something became known. Orthogonal to the
#: runtime state above: one entry has one of each.
CATEGORIES = ("stated", "verified", "knowledge", "derived", "unknown")

#: The eleven materiality classes of FR-007, exactly. A decision that can
#: change any of these is mandatory to ask about; one that can change none of
#: them is implementation discretion.
MATERIALITY = (
    "behaviour",
    "architecture",
    "data_loss",
    "security",
    "compatibility",
    "api_contract",
    "interface_behaviour",
    "destructive_operation",
    "release_action",
    "external_side_effect",
    "persisted_state",
)

#: Spellings a caller may use for a class, mapped to the canonical name. Only
#: exact, known words: a class the table does not know is not quietly folded
#: into "immaterial" (see `assess`).
_ALIASES = {
    "behavior": "behaviour", "requested behaviour": "behaviour",
    "requested behavior": "behaviour", "data loss": "data_loss",
    "api": "api_contract", "protocol": "api_contract", "api contract": "api_contract",
    "protocol contract": "api_contract", "interface": "interface_behaviour",
    "ui": "interface_behaviour", "interface behaviour": "interface_behaviour",
    "interface behavior": "interface_behaviour", "destructive": "destructive_operation",
    "destructive operation": "destructive_operation", "release": "release_action",
    "release action": "release_action", "side effect": "external_side_effect",
    "external side effect": "external_side_effect", "persistence": "persisted_state",
    "persisted state": "persisted_state",
}

#: How long a fingerprint is: a prefix of a SHA-256, in hex. Long enough to
#: tell two files apart, short enough that nobody mistakes it for content.
FINGERPRINT_LENGTH = 16
_FINGERPRINT = re.compile(rf"^[0-9a-f]{{{FINGERPRINT_LENGTH}}}$")


class IllegalEvidence(ValueError):
    """An entry that the validation rules refuse."""


class IllegalTransition(ValueError):
    """A state change that is not in the table."""


class MaterialDecision(ValueError):
    """An assumption was attempted on a decision that must be asked."""


def fingerprint_of(material: str | bytes) -> str:
    """The identity of some observed material — never the material itself."""
    if isinstance(material, str):
        material = material.encode("utf-8", errors="replace")
    return hashlib.sha256(material).hexdigest()[:FINGERPRINT_LENGTH]


def mint_ref() -> str:
    """A new semantic decision identity: opaque, random, collision-resistant.

    Nothing about the decision goes into it — not its wording, not its place
    in a list, not a counter. `OpenDecision.id` restarts with every ledger, so
    `d1` names a different decision in every turn; an answer keyed by it could
    close the wrong one. This is what an answer given later is keyed by
    instead. Eighty random bits, short enough for a channel's button payload.
    """
    return "dr-" + secrets.token_hex(10)


#: What a `decision_ref` may look like: what `mint_ref` produces, and what an
#: injected test minter produces. Anything else is malformed and is rejected
#: before it is looked up.
DECISION_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def well_formed_ref(value: object) -> bool:
    return isinstance(value, str) and DECISION_REF.match(value) is not None


def _decision_key(what: str) -> str:
    """The same decision stated the same way, whatever the spacing or case —
    the identity `ask` already uses to recognise a question put twice."""
    return " ".join(str(what).lower().split())


@dataclass
class EvidenceEntry:
    """One thing the agent is relying on (data-model.md §1)."""

    id: str
    claim: str
    state: EvidenceState
    source: str = ""
    category: str = "unknown"
    observed_at: int = 0
    fingerprint: str = ""
    derived_from: list[str] = field(default_factory=list)
    #: Where the material can be re-examined: the tool call that holds it
    #: in the conversation, or a path to read again (FR-103). A citation,
    #: never a copy.
    reference: str = ""
    #: For a KNOWN entry seeded from a settled decision: what was decided,
    #: so the question is answered from the record instead of re-asked.
    answer: str = ""


@dataclass
class OpenDecision:
    """An unresolved point that materially affects the work (data-model.md §3)."""

    #: Ledger-local (`d1`, `d2`, …): ties the decision to its entries within
    #: one turn. Never the decision's identity outside this ledger.
    id: str
    what: str
    entry_id: str
    candidates: list[str] = field(default_factory=list)
    evidence_consulted: list[str] = field(default_factory=list)
    #: One of `MATERIALITY`, or "" for a decision that is not material — in
    #: which case it is not a decision, and the agent records an assumption.
    materiality: str = ""
    state: str = "open"           # open | asked | answered | unresolved | blocked
    #: How the clarification ended when it did not end in an answer.
    outcome: str = ""             # "" | cancelled | expired | unattended
    answer: str = ""
    #: The assumption recorded for a non-material decision (FR-003).
    assumption: str = ""
    #: Whether inspection was permitted when this was raised (FR-009/FR-010).
    inspected: bool = True
    #: The semantic identity, serialized as `decision_ref`. Minted once, when
    #: the decision first needs asking, and never changed; empty for a
    #: decision that never needed asking (settled, or not material).
    ref: str = ""

    @property
    def material(self) -> bool:
        return bool(self.materiality)

    @property
    def resolved(self) -> bool:
        return self.state == "answered"

    @property
    def withholds(self) -> bool:
        """Whether work depending on this decision must not run."""
        return self.material and self.state in ("open", "asked", "unresolved", "blocked")


@dataclass
class Assumption:
    """A choice the agent made itself, on a non-material point (FR-003)."""

    decision_id: str
    what: str
    chosen: str


@dataclass
class Escalation:
    """What low confidence on a conclusion turned into (FR-115)."""

    kind: str                     # "clarification" | "hedge"
    claim: str
    would_settle: str
    decision: OpenDecision | None = None

    def report(self) -> str:
        if self.kind == "clarification":
            return (f"Not confident about: {self.claim}. This needs a decision "
                    f"before continuing — {self.would_settle} would settle it.")
        return (f"Low confidence: {self.claim}. Not verified; "
                f"{self.would_settle} would settle it.")


@dataclass
class InsufficientInformation:
    """The outcome when what is needed is absent and cannot be obtained (FR-113)."""

    missing: list[str]

    @property
    def ok(self) -> bool:
        return False

    def report(self) -> str:
        named = "\n".join(f"  - {item}" for item in self.missing)
        return ("Insufficient information to proceed. Missing, and not "
                f"obtainable here:\n{named}\nNo result was produced without it.")


@dataclass
class Conflict:
    """Two observations that disagree on a point that matters (FR-069)."""

    claim: str
    sources: list[str]

    def report(self) -> str:
        return (f"Conflicting evidence on: {self.claim} — "
                f"{' disagrees with '.join(self.sources)}. Not resolved silently; "
                f"this needs a decision.")


def assess(affects: Iterable[str] | None) -> str:
    """The materiality class a decision falls in, or "" for none (FR-007).

    Table-driven and deterministic. `affects` names what the decision can
    change. An empty set is the explicit statement that nothing material is
    affected, and only then is the decision left to discretion. `None` — the
    caller did not say — is treated as material: where the readings compete,
    the decision is material (FR-130), and "did not say" is the readings
    competing. A word the table does not know is likewise material, because
    an unknown class folded into "immaterial" would be exactly the quiet
    downgrade FR-130 forbids.
    """
    if affects is None:
        return MATERIALITY[0]
    names = [str(name).strip().lower() for name in affects if str(name).strip()]
    if not names:
        return ""
    for name in names:
        canonical = _ALIASES.get(name, name)
        if canonical in MATERIALITY:
            return canonical
    return MATERIALITY[0]


def may_inspect(mode: str | None) -> bool:
    """Whether this mode may gather evidence with tools (FR-009, FR-010).

    Read from the one policy table; never written. An unknown mode may do
    nothing, which for this question means it may not inspect.
    """
    from ..safety import modes

    return bool(modes.enforced(mode).may_use_read_tools)


class Ledger:
    """One turn's evidence and open decisions. Created and discarded with the turn."""

    def __init__(self, mode: str | None = "act",
                 mint: Callable[[], str] | None = None) -> None:
        self._entries: dict[str, EvidenceEntry] = {}
        self._decisions: dict[str, OpenDecision] = {}
        self._assumptions: list[Assumption] = []
        self._conflicts: list[Conflict] = []
        self._uninspected: list[str] = []
        self._repeats: dict[str, int] = {}
        self._ids = itertools.count(1)
        self.step = 0
        self.mode = mode
        #: Where a new `ref` comes from. Injected by a test that needs refs it
        #: can predict; otherwise `mint_ref`, looked up when it is called.
        self._mint = mint
        #: Refs of decisions this session raised earlier and never settled,
        #: by the decision they name. A decision raised again keeps its ref.
        self._outstanding: dict[str, str] = {}

    # -- reading ------------------------------------------------------------ #

    @property
    def entries(self) -> list[EvidenceEntry]:
        return list(self._entries.values())

    @property
    def decisions(self) -> list[OpenDecision]:
        return list(self._decisions.values())

    @property
    def assumptions(self) -> list[Assumption]:
        return list(self._assumptions)

    @property
    def conflicts(self) -> list[Conflict]:
        return list(self._conflicts)

    @property
    def uninspected(self) -> list[str]:
        return list(self._uninspected)

    @property
    def may_inspect(self) -> bool:
        return may_inspect(self.mode)

    def get(self, entry_id: str) -> EvidenceEntry:
        return self._entries[entry_id]

    def decision(self, decision_id: str) -> OpenDecision:
        return self._decisions[decision_id]

    def find(self, claim: str) -> EvidenceEntry | None:
        """The newest entry for a claim — the one that describes the source
        as it is now, after any earlier entry was sent back by a change."""
        wanted = claim.strip().lower()
        for entry in reversed(list(self._entries.values())):
            if entry.claim.strip().lower() == wanted:
                return entry
        return None

    def state_of(self, claim: str) -> EvidenceState:
        """The state of a claim; anything absent is UNKNOWN (E4.4)."""
        found = self.find(claim)
        return found.state if found is not None else EvidenceState.UNKNOWN

    def may_rely_on(self, claim: str) -> bool:
        return self.state_of(claim) in USABLE

    def settled(self, what: str) -> EvidenceEntry | None:
        """A usable entry that settles `what`, if the ledger holds one (FR-008)."""
        found = self.find(what)
        if found is not None and found.state in USABLE:
            return found
        return None

    def withheld(self) -> list[OpenDecision]:
        """Decisions no dependent work may run under (E3, FR-018)."""
        return [decision for decision in self._decisions.values() if decision.withholds]

    # -- writing: the producers of E2 ---------------------------------------- #

    def known(self, claim: str, source: str = "user",
              material: str | bytes = "") -> EvidenceEntry:
        """The user stated it. `material` is fingerprinted, never kept."""
        return self._add(claim, EvidenceState.KNOWN, source=source, category="stated",
                         fingerprint=fingerprint_of(material) if material else "")

    def knowledge(self, claim: str, ref: str, answer: str = "") -> EvidenceEntry:
        """Established project or user knowledge, by reference to its record."""
        entry = self._add(claim, EvidenceState.KNOWN, source=f"knowledge:{ref}",
                          category="knowledge")
        entry.answer = str(answer or "")
        return entry

    def verified(self, claim: str, source: str, material: str | bytes = "",
                 reference: str = "") -> EvidenceEntry:
        """Observed through a tool or the repository. Holds a fingerprint, never the material.

        A fresh observation of a source already recorded with a different
        fingerprint sends the earlier entry back to `UNKNOWN`: the source
        changed, and that — never the passage of steps or turns — is what
        invalidates a verified fact (FR-105). The same source with the same
        fingerprint is the same fact, already known: nothing is re-verified
        without cause, and the existing entry is returned.
        """
        fingerprint = fingerprint_of(material) if material else ""
        for entry in list(self._entries.values()):
            if entry.state is not EvidenceState.VERIFIED or entry.source != source:
                continue
            if fingerprint and entry.fingerprint and entry.fingerprint != fingerprint:
                self.transition(entry.id, "source_changed")
            elif fingerprint and entry.fingerprint == fingerprint \
                    and entry.claim.strip().lower() == claim.strip().lower():
                # Observed again, unchanged: the same fact, already known.
                # Counted as a rediscovery (FR-104), not re-verified.
                self._repeats[source] = self._repeats.get(source, 0) + 1
                if reference and not entry.reference:
                    entry.reference = reference
                return entry
        entry = self._add(claim, EvidenceState.VERIFIED, source=source,
                          category="verified", fingerprint=fingerprint)
        entry.reference = reference or source
        return entry

    def cite(self, claim: str) -> str:
        """Where a claim's material can be re-examined, or "" if it cannot.

        Only a usable entry cites anything: one sent back to `UNKNOWN` by a
        source change cites nothing, so stale evidence is never pointed at.
        """
        found = self.find(claim)
        if found is None or found.state not in USABLE:
            return ""
        return found.reference or found.source

    def rediscoveries(self, source: str) -> int:
        """How many times `source` was observed again unchanged this turn —
        the repeat-discovery count the incremental understanding removes."""
        return self._repeats.get(source, 0)

    def derive(self, claim: str, derived_from: list[str]) -> EvidenceEntry:
        """A deterministic conclusion. Every premise must itself be sound (E4.1)."""
        if not derived_from:
            raise IllegalEvidence("a derivation needs at least one premise")
        for premise_id in derived_from:
            premise = self._entries.get(premise_id)
            if premise is None:
                raise IllegalEvidence(f"no such premise {premise_id}")
            if premise.state not in PREMISES:
                raise IllegalEvidence(
                    f"a derivation cannot rest on {premise.claim!r}, which is "
                    f"{premise.state.value}")
        return self._add(claim, EvidenceState.DERIVED, source="derivation",
                         category="derived", derived_from=list(derived_from))

    def unknown(self, claim: str) -> EvidenceEntry:
        """Something needed and not had. Where every absent thing starts."""
        return self._add(claim, EvidenceState.UNKNOWN, category="unknown")

    def seed(self, claim: str, state: EvidenceState, source: str = "",
             fingerprint: str = "") -> EvidenceEntry:
        """An entry in a given state, for tests and for the gate's own records.

        Validated exactly as any other entry: a KNOWN entry still needs the
        user (or a knowledge reference) as its source, a VERIFIED one a
        source, and no fingerprint may be anything but a fingerprint.
        """
        if not source:
            source = {EvidenceState.KNOWN: "user", EvidenceState.VERIFIED: "tool",
                      EvidenceState.DERIVED: "derivation"}.get(state, "")
        category = {EvidenceState.KNOWN: "stated", EvidenceState.VERIFIED: "verified",
                    EvidenceState.DERIVED: "derived"}.get(state, "unknown")
        return self._add(claim, state, source=source, category=category,
                         fingerprint=fingerprint)

    def transition(self, entry_id: str, trigger: str) -> EvidenceEntry:
        """Apply one row of the table, or refuse."""
        entry = self._entries[entry_id]
        target = TRANSITIONS.get((entry.state, trigger))
        if target is None:
            raise IllegalTransition(
                f"{entry.state.value} --{trigger}--> is not a legal transition")
        entry.state = target
        return entry

    def source_changed(self, entry_id: str) -> EvidenceEntry:
        """The material a VERIFIED entry was observed from is not the same any more."""
        return self.transition(entry_id, "source_changed")

    def confirm(self, entry_id: str) -> EvidenceEntry:
        return self.transition(entry_id, "confirmed")

    def contradict(self, entry_id: str) -> EvidenceEntry:
        return self.transition(entry_id, "contradicted")

    # -- decisions: materiality, asking, and the ways asking can end ---------- #

    def outstanding(self, what: str, ref: str) -> None:
        """A decision raised earlier in this session is still open under `ref`.

        Raising it again in this ledger then keeps that ref instead of minting
        a new one, so an answer given later to either question closes the one
        decision (FR-020). The ref was minted; it is only remembered here.
        """
        if what and well_formed_ref(ref):
            self._outstanding.setdefault(_decision_key(what), ref)

    def open_decision(self, what: str, *, affects: Iterable[str] | None = None,
                      candidates: Iterable[str] = (),
                      evidence_consulted: Iterable[str] = (),
                      ref: str = "") -> OpenDecision:
        """Record a decision the agent cannot settle itself.

        Runs the materiality test. A material decision's entry moves
        `UNKNOWN -> REQUIRES_CLARIFICATION` and dependent work is withheld
        until a real answer arrives. A non-material one stays a plain UNKNOWN
        with `materiality = ""`; the agent may then `assume()` on it and must
        say so (FR-003). In a mode that may not inspect, `evidence_consulted`
        is empty and recorded as such — the ledger never lets the agent claim
        an inspection it could not make (FR-010).

        A material decision gets its semantic `ref` here, once. `ref` is given
        when the decision already has one — carried from a delegate, or
        answered in a later invocation — and is kept rather than replaced.
        """
        settled = self.settled(what)
        entry = settled or self.find(what) or self.unknown(what)
        materiality = assess(affects)
        if settled is not None:
            materiality = ""          # settled by evidence: nothing to ask (FR-008)
        inspected = self.may_inspect
        decision = OpenDecision(
            id=f"d{next(self._ids)}", what=what, entry_id=entry.id,
            candidates=[str(c) for c in candidates if str(c).strip()],
            evidence_consulted=[str(e) for e in evidence_consulted] if inspected else [],
            materiality=materiality, inspected=inspected,
        )
        if settled is not None:
            decision.state = "answered"
            decision.answer = settled.answer or f"settled by {settled.source}"
        elif materiality and entry.state is EvidenceState.UNKNOWN:
            self.transition(entry.id, "materiality")
        if settled is None and materiality:
            decision.ref = self._ref_for(decision, ref)
        self._decisions[decision.id] = decision
        return decision

    def _ref_for(self, decision: OpenDecision, given: str) -> str:
        """The one semantic identity this decision has: kept if it has one,
        shared with the same decision already open here, else newly minted."""
        if well_formed_ref(given):
            return given
        key = _decision_key(decision.what)
        for earlier in self._decisions.values():
            if earlier.ref and (earlier.entry_id == decision.entry_id
                                or _decision_key(earlier.what) == key):
                return earlier.ref
        known = self._outstanding.get(key)
        if known:
            return known
        return (self._mint or mint_ref)()

    def assume(self, decision_id: str, chosen: str) -> Assumption:
        """Decide a non-material point and record that it was assumed (FR-003).

        Unreachable for a material decision, whatever its state: once a
        decision has passed the materiality test there is no path from it to
        an agent-chosen value (FR-130, E4.7).
        """
        decision = self._decisions[decision_id]
        if decision.material:
            raise MaterialDecision(
                f"{decision.what!r} is material ({decision.materiality}); it must "
                f"be asked, not assumed")
        assumption = Assumption(decision_id=decision.id, what=decision.what,
                                chosen=chosen)
        decision.assumption = chosen
        decision.state = "answered"
        self._assumptions.append(assumption)
        return assumption

    def asked(self, decision_id: str) -> OpenDecision:
        decision = self._decisions[decision_id]
        if decision.state == "open":
            decision.state = "asked"
        return decision

    def answered(self, decision_id: str, answer: str) -> OpenDecision:
        """A real answer from the user — the only thing that resolves a decision."""
        decision = self._decisions[decision_id]
        if not str(answer).strip():
            raise IllegalEvidence("an answer with nothing in it does not resolve anything")
        entry = self._entries[decision.entry_id]
        if entry.state in (EvidenceState.REQUIRES_CLARIFICATION, EvidenceState.UNRESOLVED):
            self.transition(entry.id, "answered")
        elif entry.state is EvidenceState.UNKNOWN:
            entry.state = EvidenceState.KNOWN
        entry.source = "user"
        entry.category = "stated"
        decision.state = "answered"
        decision.outcome = ""
        decision.answer = str(answer)
        return decision

    def ended_without_answer(self, decision_id: str, outcome: str) -> OpenDecision:
        """The clarification ended and nothing was answered.

        `outcome` is `cancelled` (explicit cancellation, decline or dismissal),
        `expired`, or `unattended` (nobody present). The first two leave the
        entry UNRESOLVED; the third leaves it BLOCKED. None of them produces a
        value, a default or an assumption, and an outcome the caller cannot
        name is treated as `cancelled` — the safe side (E5).
        """
        decision = self._decisions[decision_id]
        trigger = outcome if outcome in ("cancelled", "expired", "unattended") else "cancelled"
        entry = self._entries[decision.entry_id]
        if entry.state is EvidenceState.REQUIRES_CLARIFICATION:
            self.transition(entry.id, trigger)
        elif not decision.material:
            # A non-material question that was dismissed: the agent may still
            # decide it (FR-011), and says so when it does.
            decision.state = "unresolved"
            decision.outcome = trigger
            return decision
        decision.state = "blocked" if trigger == "unattended" else "unresolved"
        decision.outcome = trigger
        return decision

    # -- uncertainty, insufficiency, conflict, partial access ----------------- #

    def escalate(self, claim: str, *, confidence: float,
                 affects: Iterable[str] | None = None, would_settle: str = "",
                 threshold: float = 0.5) -> Escalation | None:
        """Low confidence on a conclusion (FR-115).

        Above the threshold nothing happens. Below it, a material conclusion
        becomes a clarification — never a hedge, because a hedge is the
        conclusion delivered anyway — and a non-material one is reported as
        low confidence with what would settle it named.
        """
        if confidence >= threshold:
            return None
        if assess(affects):
            decision = self.open_decision(claim, affects=affects,
                                          evidence_consulted=[])
            return Escalation(kind="clarification", claim=claim,
                              would_settle=would_settle or "an answer",
                              decision=decision)
        return Escalation(kind="hedge", claim=claim,
                          would_settle=would_settle or "verification")

    def insufficient(self, missing: Iterable[str]) -> InsufficientInformation:
        """Name what is absent and cannot be obtained (FR-113)."""
        named = [str(item) for item in missing if str(item).strip()]
        if not named:
            raise IllegalEvidence("an insufficiency must name what is missing")
        for item in named:
            if self.find(item) is None:
                self.unknown(item)
        return InsufficientInformation(missing=named)

    def observe_conflict(self, claim: str, sources: Iterable[str]) -> Conflict:
        """Two observations disagree. Both stay; the conflict is surfaced (FR-069)."""
        conflict = Conflict(claim=claim, sources=[str(s) for s in sources])
        self._conflicts.append(conflict)
        found = self.find(claim)
        if found is None:
            self.unknown(claim)
        return conflict

    def could_not_inspect(self, where: str) -> None:
        """Part of the repository was out of reach (FR-070)."""
        if where and where not in self._uninspected:
            self._uninspected.append(where)

    def report_partial_access(self) -> str:
        if not self._uninspected:
            return ""
        return ("Not inspected: " + ", ".join(self._uninspected)
                + ". Nothing is claimed about those parts.")

    # -- internals ------------------------------------------------------------ #

    def _add(self, claim: str, state: EvidenceState, *, source: str = "",
             category: str = "unknown", fingerprint: str = "",
             derived_from: list[str] | None = None) -> EvidenceEntry:
        claim = str(claim).strip()
        if not claim:
            raise IllegalEvidence("an entry needs a claim")
        if state is EvidenceState.VERIFIED and not source:
            raise IllegalEvidence("a VERIFIED entry needs a source naming a tool or a path")
        if state is EvidenceState.KNOWN and not (
                source == "user" or source.startswith("knowledge:")):
            raise IllegalEvidence("a KNOWN entry comes from the user or from "
                                  "established knowledge, not from the model")
        if fingerprint and not _FINGERPRINT.match(fingerprint):
            raise IllegalEvidence("a fingerprint is a hash of the material, never "
                                  "the material")
        if category not in CATEGORIES:
            raise IllegalEvidence(f"{category!r} is not an FR-001 category")
        entry = EvidenceEntry(
            id=f"e{next(self._ids)}", claim=claim, state=state, source=source,
            category=category, observed_at=self.step, fingerprint=fingerprint,
            derived_from=list(derived_from or []),
        )
        self._entries[entry.id] = entry
        return entry
