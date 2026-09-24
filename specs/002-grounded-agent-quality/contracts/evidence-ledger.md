# Contract: Evidence Ledger

**Feature**: 002-grounded-agent-quality

The ledger is **internal**. It has no protocol surface, is never persisted, and
is not rendered to the user except where an open decision becomes a question or
the completion gate cites it. This contract therefore governs the boundary
between the ledger and the parts of the system that use it.

---

## E1. Lifetime and ownership

| Property | Value | Why |
| --- | --- | --- |
| Owner | `ToolContext` (one per turn) | Already has exactly the right lifetime and already records file reads via `note_read` |
| Created | At turn start, with the loop's existing context construction | No new lifecycle |
| Destroyed | At turn end | Research R7 |
| Persisted | **Never** | Security (Constitution VIII); what deserves to outlive a turn is a learned fact, which `learning/` already owns |
| Cost | No model call, no network, no new dependency | Every transition is triggered by a tool result, a user message, or the completion gate |

**How `UNRESOLVED → KNOWN` works across turns.** The ledger still dies with its
turn; that rule is unchanged. A **live form** survives reconnect through the
existing pending-interaction slot (FR-023). If the form ends cancelled, expired
or unattended while its material decision remains unresolved, the **semantic
decision** — not the ledger — stays resolvable through the form record the
session transcript already stores, keyed by its stable `decision_ref`. That ref
is the decision's `ref`, minted by the ledger once, when the materiality test
promotes the decision to `REQUIRES_CLARIFICATION` (data-model.md §3). A later explicit
DecisionAnswer must match that exact ref (FR-129); only then does the answer enter
the **new** turn's ledger as user/caller-provided `KNOWN`. Missing, malformed,
unknown, stale or unresolvable refs seed nothing and resolve nothing. No evidence
ledger is persisted, and no decision is reconstructed by guessing from prose.

---

## E2. Producers — who writes to the ledger

| Producer | Writes | State |
| --- | --- | --- |
| User message | The request's stated facts and constraints | `KNOWN` |
| Tool result (read, search, shell) | What was observed, with its source and fingerprint | `VERIFIED` |
| `ToolContext.note_read` | File reads — **already called today** | `VERIFIED` |
| Derivation | A conclusion from existing entries | `DERIVED` |
| Materiality test | Promotes an `UNKNOWN` that matters | `REQUIRES_CLARIFICATION` |
| Question answer / valid DecisionAnswer | A real answer closes the exact decision; cross-turn resumption must match its `decision_ref` | `KNOWN` |
| Question lifecycle (`events.Request` claim and expiry, via `bus.resolve`) | A mandatory clarification ended **without** an answer — explicitly cancelled, declined/dismissed, or expired | `UNRESOLVED` |
| Question lifecycle — later answer | The user supplies a real answer to a decision left `UNRESOLVED` | `KNOWN` |
| Absence of a listener (`bus.listening` is false) | Clarification is mandatory and nobody can answer | `BLOCKED` |
| Completion gate | Confirms or contradicts | `VALIDATED` / `FAILED` |
| New observation | Contradicts an existing entry, or its source fingerprint changed | `FAILED` / back to `UNKNOWN` |

**Rule**: nothing else writes, and this table is exhaustive — **every legal
transition in [data-model.md §2](../data-model.md) that results in an
`EvidenceState` has an authorised producer above.** In particular the model does
not write to the ledger: it is a record of what happened, not of what was
asserted.

The one transition with no producer row is `UNKNOWN → immaterial agent
discretion`, and that is deliberate: it terminates in a recorded assumption
rather than in an `EvidenceState`, so there is no ledger state to write. It is
reachable only from `UNKNOWN` **before** the materiality test would have promoted
the decision, never from `REQUIRES_CLARIFICATION` (E4.7, FR-130).

**Note on the non-answer rows.** Cancellation, decline/dismissal and expiry share
one producer because the repository already handles them through one lifecycle —
the atomic claim on `events.Request` and its published expiry. They are still
reported as distinct lifecycle outcomes to the caller; they are identical only in
their effect on the ledger, which is `UNRESOLVED` in all three cases. The
unattended case is **not** `UNRESOLVED`: nobody was there to decide, so it is
`BLOCKED`.

---

## E3. Consumers — who reads it

| Consumer | Reads | To do what |
| --- | --- | --- |
| Ask decision (`tools/ask.py`) | Open decisions and their `evidence_consulted` | Decide whether to ask, and ask about what inspection could not settle (FR-009) |
| Completion gate | Entries backing the answer's claims | Compare requested against delivered (FR-036) |
| Turn outcome | `BLOCKED` decisions | Produce `clarification_required` with `clarification.outcome = "unattended"` (FR-123) |
| Turn outcome | `UNRESOLVED` decisions | Report `clarification_required` with `clarification.outcome` of `cancelled` or `expired`, naming the decision that stayed open (FR-022, FR-035) |
| Dependent-work guard | `REQUIRES_CLARIFICATION`, `UNRESOLVED` and `BLOCKED` decisions | Withhold any work depending on them; only a `KNOWN` resolution releases it (FR-018) |
| Learning admission gate | Provenance of a candidate item | Refuse unverified model assertions (FR-056) |
| Measurement | Counts only | Report, never expose content |

---

## E4. Invariants

1. **A derivation never rests on an unknown.** `DERIVED` requires every
   `derived_from` entry to be `KNOWN`, `VERIFIED` or `DERIVED`. This single rule
   is the mechanical prevention of gap-filling (FR-002).
2. **No promotion without a transition.** An `UNKNOWN` becomes usable only by
   being observed, stated, answered, or derived — never by being needed.
3. **No secret values.** Entries carry a fingerprint and a source, never content
   that could be credential material.
4. **Degradation is safe.** Anything the ledger cannot classify stays `UNKNOWN`,
   which blocks reliance rather than permitting it.
5. **Not in the system prompt.** The ledger never enters `build_system_prompt`;
   the cached prefix must stay byte-identical across turns.
6. **Mode-aware.** The evidence-first duty reads `safety/modes.py`. Where
   `may_use_read_tools` is false, an empty `evidence_consulted` is correct and the
   agent must not claim otherwise.
7. **A non-answer never becomes knowledge or an assumption.** Once a decision has
   passed the materiality test and entered `REQUIRES_CLARIFICATION`, none of
   **cancellation, decline/dismissal, expiry, or absence of a listener** may
   produce `KNOWN`, `VERIFIED`, `DERIVED`, an agent-selected assumption, a
   default, a selected option, or any fabricated value.
   - Cancellation, decline and expiry produce `UNRESOLVED`.
   - Absence of a listener produces `BLOCKED`.
   - **Only a genuine user answer** may resolve that required information into
     `KNOWN`, whether it arrives during the original wait or later against an
     `UNRESOLVED` decision.

   The agent-assumption path remains legal **only** for a decision determined to
   be non-material *before* it would have become `REQUIRES_CLARIFICATION`
   (`UNKNOWN → non-material discretion`). A decision that reached
   `REQUIRES_CLARIFICATION` can never reach that path.

   Preserves FR-002 (an unknown is never converted into an assumed value),
   FR-003 (assumptions are stated, and only for non-material decisions), FR-019
   (no non-answer becomes a default or assumption), FR-022 (cancellation is a
   lifecycle outcome, not an information outcome) and FR-130 (discretion confined
   to non-material decisions).

---

## E5. Failure behaviour

| Situation | Contract |
| --- | --- |
| Ledger raises internally | The turn continues; entries default to `UNKNOWN`. A bookkeeping bug must never kill a turn — the same rule `claims.py` and `_say_if_unverified` already follow |
| A tool result cannot be classified | `UNKNOWN`, not `VERIFIED` |
| Contradiction between two entries | Both retained; the decision that depends on them is surfaced as a conflict (FR-069) |
| Completion gate cannot reach a verdict | Falls back to annotating rather than withholding (FR-127) |
| The lifecycle outcome cannot be determined (cancelled vs expired unclear) | Treated as `UNRESOLVED` — the safe side, since every `UNRESOLVED` path withholds dependent work. **Never resolved to `KNOWN` by default** |
| A decision is `UNRESOLVED` or `BLOCKED` at turn end | The turn reports it; it is never recorded as satisfied, and no assumption is emitted in its place (E4.7) |


---

## E8. Cross-turn decision boundary

The evidence ledger is deliberately ephemeral. Keeping an unresolved decision
resolvable is a session concern, not evidence-ledger persistence. The session
already stores each form's record — the questions as shown, with their
`decision_ref`, prompt, grounded options, reason and consulted evidence, plus
the answers and the lifecycle outcome — and the unresolved set is derived from
those records. No new record type is added, and nothing in it is evidence
material or a secret. For a stateless run (`comodor run`, a scheduled job, a
webhook event), those records exist only when the run ended
`clarification_required`: that is the one case in which a fresh stateless run's
transcript is kept, as a continuation that is never listed as a session
(data-model.md §Stateless-run continuation).

The layering is fixed. The ledger and everything else inside a turn belong to
`AgentLoop`. Loading a continuation, validating a later answer against it, and
persisting it belong to the shared turn entry `run_turn` in the application
layer, which calls the loop only after validation succeeds (plan §B). The
ledger never learns about sessions, continuations or bindings.

When a new turn receives a valid DecisionAnswer, the session layer resolves the exact stored decision and the new ledger records the answer as `KNOWN`. Invalid or ambiguous refs never cause a ledger transition. This preserves the invariant that only genuine user/caller input can move an unresolved material decision into a usable state.
