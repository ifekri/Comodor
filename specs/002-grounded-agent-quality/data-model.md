# Plan Phase 1 Data Model: Grounded High-Quality Agent

**Feature**: 002-grounded-agent-quality | **Date**: 2026-09-14

Entities are described by their fields, rules and transitions. Five of the
eight already exist — §4 Question, §5 Durable knowledge record, §6
TaskMeasurement, §7 Turn outcome and §8 Completion assessment (the return value
of the existing completion verification path) — and are shown with only their
additions, so the "extend, don't duplicate" constraint stays checkable. Only §1
EvidenceEntry, §2 Evidence state and §3 OpenDecision are new. The
specification's `Answer` entity is the existing question response payload and
is noted under §4 rather than modelled separately.

---

## 1. EvidenceEntry — **new**

One thing the agent is relying on. Lives on the turn's `ToolContext`; never
persisted (research R7).

| Field | Type | Rule |
| --- | --- | --- |
| `claim` | text | What is asserted. Short; not the content itself |
| `state` | enum | Exactly one member of the closed `EvidenceState` set defined in §2 |
| `source` | text | Where it came from — a path, a tool name, `user`, or a derivation reference |
| `observed_at` | turn-relative step | Which step established it |
| `fingerprint` | opaque | Identity of the observed material. **Never the material, never a secret value** |
| `derived_from` | list of entry ids | Present only when `state = DERIVED` |

**Validation rules**

- `state = VERIFIED` requires a non-empty `source` naming a tool or a path.
- `state = KNOWN` requires `source = user`.
- `state = DERIVED` requires at least one `derived_from`, and every referenced
  entry must itself be `KNOWN`, `VERIFIED` or `DERIVED` — a derivation may never
  rest on an `UNKNOWN`. This single rule is what mechanically prevents a gap from
  being filled (FR-002).
- `fingerprint` must never contain credential material (Constitution VIII).

---

## 2. Evidence state — **new**

| State | Meaning | Entered by | May a decision rest on it? |
| --- | --- | --- | --- |
| `KNOWN` | The user stated it | User message | Yes |
| `VERIFIED` | Observed through a tool or the repository | Tool result | Yes |
| `DERIVED` | Deterministically follows from `KNOWN`/`VERIFIED`/`DERIVED` | Derivation | Yes |
| `UNKNOWN` | Absent, unresolved | Default for anything absent | **No** |
| `REQUIRES_CLARIFICATION` | `UNKNOWN` that passed the materiality test | Materiality test (FR-007) | No — dependent work pauses |
| `UNRESOLVED` | A mandatory clarification ended without an answer — cancelled, declined or expired | User cancellation / decline / expiry | **No** — dependent work does not run; only a later real answer resolves it |
| `BLOCKED` | Clarification mandatory, nobody present | `listening = false` | No — turn ends |
| `VALIDATED` | Completion gate confirmed delivered work against it | Completion gate | Terminal, positive |
| `FAILED` | Contradicted by later observation, or validation failed | New observation / gate | Terminal, negative |

**Transitions** (the complete table; no other transition is legal)

```text
UNKNOWN --materiality passes--> REQUIRES_CLARIFICATION
UNKNOWN --immaterial--------->  (agent discretion; assumption recorded, FR-003)
        ^^ the ONLY path that may end in an agent-selected assumption.
           A decision that passed the materiality test may never take it.
REQUIRES_CLARIFICATION --answered----------> KNOWN
REQUIRES_CLARIFICATION --cancelled/declined-> UNRESOLVED   (clarification.outcome: cancelled)
REQUIRES_CLARIFICATION --expired-----------> UNRESOLVED   (clarification.outcome: expired)
REQUIRES_CLARIFICATION --nobody present---> BLOCKED       (clarification.outcome: unattended)
   ^^ all three report ONE turn outcome: stopped = "clarification_required".
      stopped = "cancelled" stays reserved for turn-level cancellation.
UNRESOLVED --user later supplies an answer-> KNOWN
KNOWN | VERIFIED | DERIVED --gate confirms--> VALIDATED
KNOWN | VERIFIED | DERIVED --contradicted--> FAILED
VERIFIED --source fingerprint changed------> UNKNOWN
```

`BLOCKED`, `VALIDATED` and `FAILED` are terminal within the turn.

---

## 3. OpenDecision — **new**

An unresolved point that materially affects the work. One becomes one question.

| Field | Type | Rule |
| --- | --- | --- |
| `id` | stable id | Survives into the question as `decision_ref` |
| `what` | text | The decision, stated so it can be answered without re-reading the request |
| `candidates` | list | Grounded readings or observed conventions. **Never invented** (FR-016). May be empty when no alternative can be enumerated |
| `evidence_consulted` | list of entry ids | What was already checked — so the user is not asked to repeat the agent's work |
| `materiality` | enum | Which class of FR-007 it falls in: behaviour, architecture, data loss, security, compatibility, API contract, interface behaviour, destructive operation, release action, external side effect, persistence |
| `state` | enum | `open` → `asked` → `answered` \| `unresolved` (cancelled, declined or expired) \| `blocked` (nobody present). Only `answered` resolves the decision; `unresolved` and `blocked` both leave dependent work unrun |

**Rules**

- A decision with `materiality = none` is not a decision; the agent decides and
  records an assumption (FR-011, FR-012).
- `evidence_consulted` must be non-empty in a mode permitted to use inspection
  tools (FR-009), and may be empty in a conversation-only mode (FR-010).
- A decision reaching `blocked` ends the turn with `clarification_required`.

---

## 4. Question / QuestionRequest — **exists, extended**

Already defined in `schemas/protocol/v2.json` and `questions.py`. Existing fields
unchanged: `id`, `session_id`, `title`, `questions[]`, and per question `header`
(the stable match key), `prompt`, `options[]`, `multiple`.

**Additions — all optional, so an old client ignores them (research R8)**

| Field | Type | Purpose |
| --- | --- | --- |
| `reason` | text | Which materiality class required this |
| `evidence_consulted` | list of text | What was checked first |
| `decision_ref` | id | Links back to the `OpenDecision` |

**Invariant preserved, not rebuilt**: the final `QuestionOption` with `free =
true` is appended centrally by `questions.py::_options()`, which also strips
model-authored escape hatches. No caller may add or remove it.

**`Answer` (spec §Key Entities) is not a new entity.** It is the existing
question response payload — the chosen option ids and any written text per
question, bound to the question by its stable `header` and decoded by
`questions.py::decode_answers` — carried today by the TUI, the Web page
(`web/session.py`) and the API. No new runtime representation is introduced;
the only change is that a non-answer (cancel, decline, expiry, absence) no
longer yields a synthesised answer (§7).

---

## 5. Durable knowledge record — **exists, extended**

Already in `learning/store.py` as `Lesson` / `Fact` / `Rule` / `Skill` with
`scope` and hard caps (8 project facts, 6 user facts).

**Additions**

| Field | Type | Rule |
| --- | --- | --- |
| `provenance` | enum | `user_correction`, `user_statement`, `settled_decision`, `counted_convention`, `validated_outcome`, `tool_confirmed`. **No other value is admissible** (FR-056) |
| `source_ref` | text | What it was derived from |
| `fingerprint` | opaque | Of the derivation source; mismatch ⇒ stale (research R5). **Granularity (whole file vs region/rule) is deliberately undecided here**: T111 (tasks Phase 6; plan Phase 5) decides it from real `rules.py` observation shapes and records the choice, rationale and invalidation implications in this row |
| `confidence` | float | Where meaningful |
| `established_at` | timestamp | For supersession ordering |
| `status` | enum | `active` \| `superseded` \| `stale` \| `removed` |
| `superseded_by` | record id | Set when a newer item governs |

**Lifecycle**

```text
proposed --admission gate--> active
active --newer contradicting correction--> superseded (superseded_by set)
active --source fingerprint mismatch-----> stale
active --decayed below floor (curator)---> stale
active --user deletes--------------------> removed
```

**Rules**

- The admission gate rejects anything whose only origin is an unverified model
  assertion, including proposals from `reflect.py` and `review.py` (FR-056).
- Supersession is deterministic: newer `established_at` governs; the older is
  retained as `superseded`, never silently dropped (FR-059).
- `stale` and `superseded` items are excluded from recall but remain inspectable
  (FR-061).
- Scope prevents cross-project application (FR-058).
- Caps are unchanged; reaching one produces an explicit refusal listing current
  contents (FR-065).

---

## 6. TaskMeasurement — **exists in part, extended**

Benchmark and local metrics. Extends `bench/` reporting and `insights.py`
aggregation.

| Field | Source |
| --- | --- |
| `task`, `category`, `result`, `correctness` | benchmark judge |
| `input_tokens`, `output_tokens`, `cached_tokens`, `total_tokens` | provider `Usage` (truth), estimator only where absent |
| `context_size` | `Conversation.used_tokens()` |
| `model_turns`, `tool_calls`, `retries` | `TurnResult` |
| `clarifications_raised`, `clarifications_answered` | question events |
| `corrections` | `learning/signals.py` detectors |
| `knowledge_hits`, `knowledge_stale` | recall path |
| `validation_outcome` | completion gate |

**Rules**

- A token figure is never published without its outcome rate (FR-076).
- No credential may appear in any field (FR-074).
- Figures stay local unless the user explicitly chooses otherwise (FR-075).

---

## 7. Turn outcome — **exists, extended**

`TurnResult.stopped` gains one value.

| Value | Meaning | `ok` |
| --- | --- | --- |
| `done`, `max_steps` | existing | true |
| `budget`, `error` | existing | false |
| `cancelled` | existing — **the whole turn** was cancelled or interrupted (`cancel_reason` `stop` \| `interrupt`). **Unchanged, and never reused for a dismissed question** | false |
| **`clarification_required`** | **new** — the single category for *every* mandatory clarification that ended without the required answer | false |

**Structured clarification payload** — carries the `OpenDecision` (`what`,
`candidates`, `evidence_consulted`, `reason`, FR-034) plus the clarification
lifecycle discriminator:

```text
outcome?: "cancelled" | "expired" | "unattended"
```

| Rule | |
| --- | --- |
| Optionality | Optional and additive, under the negotiated clarification capability (FR-080). A client that does not negotiate it never receives it |
| Presence | Present whenever a clarification causes a terminal no-answer outcome; absent for a still-pending form |
| No `answered` value | An answer produces **no** clarification stop — it resolves the decision and dependent execution resumes. `answered` is therefore not a terminal clarification outcome and is not a value of this field |
| Layer | Belongs to the **clarification** lifecycle. `stopped` belongs to the **turn** lifecycle. The nested field exists precisely so that no existing turn-level stop reason is overloaded — in particular `cancelled` keeps its meaning and gains no second one |

Must be distinguishable from both success and failure so a caller routes it for
an answer rather than retrying it as an error (FR-123). The **turn** lifecycle
(`stopped`) and the **clarification** lifecycle (`clarification.outcome`) are
separate vocabularies and MUST NOT be conflated.

---

## 8. Completion assessment — **exists in part, extended**

The transient result of the existing completion verification path — the
unverified-claim inspector in `agent/claims.py`, project-check execution in
`agent/verify.py`, and the completion guards in `agent/loop.py` — widened at IP-4
to a request-versus-delivery comparison (T120–T129; FR-036 to FR-043, FR-124 to
FR-127). It is a **return value computed at the end of a turn, never durable
state**: it is not persisted, not journaled, not snapshotted, and it creates no
workflow engine. Only its `validation_outcome` is copied into §6
TaskMeasurement.

| Field | Type | Rule |
| --- | --- | --- |
| `requested` | list of element | What the request asked for, as the gate understood it (FR-036) |
| `delivered` | list of element + evidence refs | Elements satisfied, each citing the `EvidenceEntry` fingerprints or check outcomes that show it (FR-036, FR-103) |
| `unresolved` | list of element | Elements not satisfied, named individually (FR-037) |
| `unresolved_reasons` | map element → reason + evidence refs | Why each is unresolved: check failed, not attempted, blocked by an open decision, could not be executed (FR-037, FR-041) |
| `claims_completion` | bool | Whether the answer text explicitly claims the task is complete (`claims.py`) |
| `contradicted` | bool | Whether gathered evidence contradicts that completion claim |
| `pending_clarification` | `OpenDecision` ref or none | A required clarification still `UNRESOLVED` / `BLOCKED` (§2) |
| `verdict` | enum | `no_intervention` \| `annotate` \| `block_contradicted_claim` |

**Verdict rules**

1. Honest partial output is never withheld: an answer that does not claim
   completion is never `block_contradicted_claim` (FR-126).
2. Unresolved work is annotated: any non-empty `unresolved` yields at least
   `annotate`, with each element named beside the answer (FR-037, FR-124).
3. Blocking occurs only when `claims_completion` **and** `contradicted` are both
   true; the answer is corrected to state the work as incomplete before delivery
   (FR-125).
4. Blocking costs at most one additional correction turn (FR-127).
5. If the gate cannot reach a verdict — a check that cannot run, evidence
   unavailable, time bound reached (FR-040, FR-041) — it falls back to
   `annotate`, never to withholding.
6. A `pending_clarification` prevents a successful completion outcome: the
   evidence state cannot reach `VALIDATED` while a required decision is open
   (T124; FR-035).
7. Validation is proportional to the affected surfaces: only checks relevant to
   what the turn touched run, and a turn that changed nothing runs none
   (FR-042, FR-043).

---

## Entity relationships

```text
        ToolContext (one per turn, never persisted)
              │ holds
              ▼
      ┌───────────────┐         raises        ┌──────────────┐
      │ EvidenceEntry │◄──── evidence_consulted ──│ OpenDecision │
      └───────────────┘                       └──────────────┘
              │                                      │ becomes
              │ confirms                             ▼
              ▼                            ┌──────────────────┐
      ┌───────────────┐                    │ QuestionRequest  │ (exists)
      │ completion    │                    └──────────────────┘
      │ gate          │                             │ answered
      └───────────────┘                             ▼
              │ VALIDATED outcome            ┌──────────────┐
              ▼                              │   Answer     │ (exists)
      ┌───────────────┐   admission gate     └──────────────┘
      │ TaskMeasure   │          │                  │
      └───────────────┘          ▼                  │ settled_decision
                        ┌──────────────────┐◄───────┘
                        │ Durable knowledge│ (exists, extended)
                        └──────────────────┘
```

**Persistence boundary**: everything above the dashed line of the turn —
`EvidenceEntry`, `OpenDecision` — is in-memory only. Only `QuestionRequest`
(through the existing pending-interaction slot), durable knowledge and
measurements cross into storage.
