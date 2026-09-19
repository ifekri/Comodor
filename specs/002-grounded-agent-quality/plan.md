# Implementation Plan: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Branch**: `002-grounded-agent-quality` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-grounded-agent-quality/spec.md` (130 functional requirements, 44 success criteria — 174 in total; three clarifications resolved 2026-09-14)

---

## Summary

The specification's 174 requirements (130 FR, 44 SC) map onto an existing product that already
implements most of the machinery. The audit below found that **the dominant work
is not construction but enforcement, measurement and connection**: the
clarification transport exists end to end, the custom-answer invariant is already
guaranteed in one shared layer, the token mechanisms exist individually but are
unmeasured, and the learning store already has scope and caps but not provenance
or invalidation.

The approach is therefore: introduce **one new first-class concept** — an
evidence ledger carried on the existing turn boundary — and use it to drive
three behaviours that already have homes in the code (asking, completing,
learning). Everything else is extension of an existing module, a new test, or a
measurement.

**One concept added. Eleven modules extended. Zero parallel subsystems.**

---

## Technical Context

**Language/Version**: Python 3.11+ (core, authoritative); TypeScript on Bun (OpenTUI terminal interface, shared client packages)

**Primary Dependencies**: `rich>=13.7` is the **only** runtime dependency of the Python core. This is a deliberate product constraint and this feature introduces no new one. Dev: `pytest>=8.0`, `pytest-xdist>=3.5`, `ruff>=0.14`, `pyyaml>=6.0`. Frontend: OpenTUI/React under Bun.

**Storage**: SQLite at `~/.comodor/brain.db` (learning; FTS5 where the build has it, pure-Python BM25 fallback). Sessions as JSON Lines under the user directory, one record per message, appended.

**Testing**: `pytest` (134 test modules, `-n auto --dist loadfile`, `performance` marker excluded by default); Bun renderer tests for the terminal interface; `bench/` for quality-and-cost measurement.

**Target Platform**: Windows, Linux, macOS — equally supported (Constitution II).

**Project Type**: Cross-platform terminal coding agent with a browser interface, a headless command line, an API/ACP protocol surface, channel integrations and a packaged container.

**Performance Goals**: No regression in the existing performance ceilings (`pytest -m performance`). Recall stays off the critical path between Enter and first token — the existing in-memory index exists precisely for that. Context assembly must not add a model call.

**Constraints**: No new runtime dependency. No change to the cached system-prompt prefix mid-task (worth ~99% prefix-cache retention, measured; larger than anything this feature could recover). Protocol v2 stays compatible; any addition is negotiated. Secrets never enter state, snapshots, journals, checkpoints, logs or fixtures.

**Scale/Scope**: 174 requirements (130 FR, 44 SC) across 8 plan phases. Estimated surface: ~11 Python modules extended, **one new product/runtime module** (`src/comodor/agent/evidence.py`), **two new benchmark-harness helper modules** (`bench/integrity.py`, `bench/baseline.py` — measurement infrastructure, never imported by `src/comodor/`), 1 schema addition, 1 shared TS package touched, the browser question surface (`src/comodor/web/`) characterized and verified, ~20 new deterministic test modules, benchmark harness extended.

---

## Constitution Check

*GATE: evaluated before plan Phase 0 and re-evaluated after plan Phase 1 design (below).*

Checked against `.specify/memory/constitution.md` **v1.1.0** (21 principles).

| Principle | Gate | Status |
| --- | --- | --- |
| I — Backward compatibility | Exactly one intended behaviour change (non-interactive blocking), named and release-noted; everything else additive | **PASS** — FR-082; plan Phase 3 (enforcement) / Phase 6 (surface wiring) — tasks Phase 3 / tasks Phase 8 |
| II — Three platforms | Every phase validated on the CI matrix; no platform-conditional logic introduced | **PASS** |
| III — Fix the invariant | No sleeps, no raised timeouts, no weakened assertions; clarification waiting uses the existing claim-and-expire primitive, not timing | **PASS** — see Clarification Architecture |
| IV — Deterministic regression tests | Every guard gets a mutation-checked test (SC-025); Phase-gated | **PASS** |
| V — Narrow scope | Eight bounded phases, each independently validatable and revertable | **PASS** |
| VI — Architectural boundaries | Evidence ledger lives in the core; frontends render it. Protocol change goes through the schema and codegen, never hand-edited | **PASS** |
| VII — Reproducible artifacts | Terminal-interface bundle rebuilt and committed if TS changes | **PASS** — TS/TUI-affecting work lands in plan Phase 3 (clarification enforcement: protocol fields, overlay) and plan Phase 6 (surface wiring); the committed bundle rebuild is owned by T141 (tasks Phase 8), verified by T166 |
| VIII — Security not weakened | Mode policy untouched; clarification never becomes a route to a forbidden action; no secret enters the ledger | **PASS** — explicit non-goal below |
| IX — Release infra is production code | No release action in this initiative at all | **N/A** — FR-084 |
| X — Quality gates mandatory | Full baseline runs per phase on the exact commit | **PASS** |
| XI — Specifications name surfaces | All ten canonical surfaces classified in [plan.md §Surface Impact](#surface-impact) using only REQUIRED / UNCHANGED BUT VERIFIED / NOT APPLICABLE, each row carrying task IDs and file evidence; spec.md §Surface classification points to that table | **PASS** — the table exists below; re-checked against the repository (Web UI is a live question surface; the desktop application is planned, not built) |
| XII — Done means everything agrees | Phase not complete until implementation, tests, docs and evidence agree | **PASS** |
| XIII — Quality-first | The whole feature | **PASS** |
| XIV — Evidence before assumption | Evidence ledger is the mechanism | **PASS** |
| XV — Clarification a product invariant | Phases 2–3; non-interactive blocking implements XV directly | **PASS** |
| XVI — Token efficiency | plan Phase 4 (tasks Phase 5), gated on the plan Phase 1 baseline (T015) | **PASS** |
| XVII — Progressive learning | plan Phase 5 (tasks Phase 6) | **PASS** |
| XVIII — Extend, don't duplicate | Audit below names the existing owner of every behaviour; one new product/runtime module total (`agent/evidence.py`), plus two harness-only benchmark helpers never imported by `src/comodor/`, all justified in Complexity Tracking | **PASS** |
| XIX — Grounded tool use | Evidence ledger + completion gate | **PASS** |
| XX — User control | No merge, tag, publish or deploy | **PASS** — FR-084, FR-085 |
| XXI — Quality and tokens measured together | plan Phase 1 baseline (T015) precedes all optimization; plan Phase 7 (tasks Phase 9) paired report | **PASS** — the ordering is a gate, not a convention |

**Gate result: PASS.** One justified addition recorded in Complexity Tracking.

---

## Architecture Audit

Every area the request named, with what owns it today and what the feature needs
from it. *Extend* means the module changes; *reuse* means it is already correct
and only needs to be called or tested.

| # | Area | Current owner | Verdict |
| --- | --- | --- | --- |
| 1 | Model orchestration | `agent/loop.py` — `AgentLoop.run` → `_iterate` → `_stream_once` → `_execute`; guards on steps, wall clock, spend | **Extend** — turn outcome gains a clarification-required state; completion gate widened |
| 2 | Prompt construction | `agent/prompts.py` — fixed order (identity, environment, mode, playbook) chosen so the stable head caches | **Reuse, do not touch the head** — evidence never enters the system prompt |
| 3 | Model adapters | `providers/base.py` (`Message`, `ToolSpec`, `Usage`, `Provider` protocol), `openai_compat.py`, `anthropic.py`; `providers/gateway.py` routes with health and key pools | **Reuse** — `Usage` already carries cached-token counts |
| 4 | Token accounting | `agent/tokens.py` — estimation calibrated against each reply's real `usage.input_tokens` | **Extend** — per-turn/per-task record, split sent/generated/cached |
| 5 | Sessions | `session/store.py` — JSON Lines, append-per-message, crash-safe by format | **Extend** — persist pending clarification |
| 6 | History | `agent/context.py` — `Conversation`; `render()` is the single funnel every request passes through | **Extend** — the one intervention point for all context work |
| 7 | Learning | `learning/` — recall → credit → reflect → consolidate; `memory.py` engine, `store.py` SQLite, `signals.py`/`rules.py` deterministic detectors, `curator.py` maintenance, `reflect.py`/`review.py` model passes, `writer.py` async durability | **Extend** — provenance, invalidation, supersession |
| 8 | Persistence | `store.py` (brain), `session/store.py`, `safety/checkpoints.py` | **Extend** — additive columns only |
| 9 | ASK mode | `safety/modes.py` — frozen policy table; `may_ask_questions=True` in every real mode; conversation-only modes have `may_use_read_tools=False`; unknown mode denies everything | **Reuse unchanged** — but the evidence-first duty must read this table (Finding 3) |
| 10 | Questions | `questions.py` (shapes, parsing, **central escape-hatch append**), `tools/ask.py` (the tool), `packages/questions` (shared reducer) | **Reuse the invariant; extend the no-answer path** |
| 11 | Permission interactions | `safety/permissions.py` — `PermissionEngine.check`, risk tiers, grants; same `Request`/bus mechanism as questions | **Reuse untouched** — regression-tested only |
| 12 | TUI input | `apps/tui/src/App.tsx` overlay; `packages/questions` holds form state as a pure reducer with no rendering | **Reuse** — deterministic by construction; add renderer tests |
| 13 | Headless / API protocol | `schemas/protocol/v2.json` → `protocol/_generated.py` + `packages/protocol`; `api/server.py`, `acp/`; `question.requested`/`question.answer`/`question.resolved`; `questions` is a negotiated capability | **Extend additively** — new event/field behind capability negotiation |
| 14 | Tool orchestration | `tools/registry.py` (mode-filtered advertisement), `agent/loop.py::_execute` (parallel for SAFE read-only rounds, deterministic report order) | **Reuse** — advertisement filtering already satisfies FR-117/118 |
| 15 | Tool-result handling | `tools/overflow.py` — spill with head/tail/pointer; originals pointed at in place, never copied | **Extend** — dedup + log summarisation |
| 16 | Context assembly | `Conversation.render()`; `agent/staleness.py` superseded-read removal; `context_refs.py` `@` expansion with credential/binary/budget refusals | **Extend** — budget manager sits here |
| 17 | Repository/file retrieval | `tools/fs.py`, `tools/search.py`, `tools/matching.py`; `ToolContext.note_read`/`was_read` already track reads | **Reuse** — `note_read` is the seed of the evidence ledger |
| 18 | Capability discovery | `tools/registry.py` advertises per mode; `tools/capability-map.py` generates `CAPABILITIES.md`; protocol `x-capabilities` handshake | **Reuse** — register new capability, keep `--check` green |
| 19 | Background agents | `agent/background.py` — slots not a queue, completions held to turn boundaries, `lost` on crash; `ScopedBus` stamps origin; requests ride to the parent | **Reuse** — origin tagging already satisfies FR-029 |
| 20 | Reconnect / resume | `session.snapshot` with `revision`; `PendingInteraction` carries `question` or `permission`; client drops events at or below revision | **Reuse** — the pending-question slot already exists |

---

## Current Data Flow (as built)

Traced from source, not inferred. This is the chain the request asked to be made
explicit; the numbered points are where this feature intervenes.

```text
user input
  │  cli.py / api/server.py / acp / channels
  ▼
AgentLoop.run(user_text)
  │  ① prohibitions(user_text)        constraints.py — patterns, no model call
  │  ② _recall(user_text)             skills + learned playbook
  │     └─ memory.before_turn()       corrections folded in FIRST
  │  ③ conversation.add(Message.user(..., briefing=playbook))
  │       ▲ recall rides the USER MESSAGE, not the system prompt —
  │         this is what keeps the cached head byte-identical
  ▼
_iterate()  ── loop ──────────────────────────────────────────────┐
  │  ④ tools.specs(mode)              mode-filtered ADVERTISEMENT  │
  │  ⑤ build_system_prompt(...)       stable head, cache-ordered   │
  │  ⑥ _maybe_compact(...)            safe_cut → summarise         │
  │  ⑦ _stream_once()                                              │
  │       conversation.render(system_prompt)  ◄── SINGLE FUNNEL    │
  │       gateway.stream(...) → provider → Usage(cached/input/out) │
  │  ⑧ assistant message added                                     │
  │                                                                │
  │  if tool_calls:                                                │
  │     ⑨ _execute() → permission check → tool.invoke()            │
  │            ├─ ask tool → bus.resolve(Request, 1800s)           │
  │            │     └─ claim-and-expire; publishes REQUEST_EXPIRED │
  │            └─ overflow.contain(result)                         │
  │        loop ───────────────────────────────────────────────────┘
  │  else (no tool calls):
  │     ⑩ if changed_anything() and not checked:
  │            _project_check_failed() → one correction turn
  │        stopped = "done"
  ▼
⑪ _say_if_unverified(result)          claims.py — notice, not a block
⑫ _learn(user_text, result)           credit → reflect (background thread)
  ▼
persisted state: session JSONL, brain.db (async writer, batched)
  ▼
next request
```

### Minimum intervention points

Exactly **six**. Everything in the feature reduces to these.

| # | Point in the flow | Change | Serves |
| --- | --- | --- | --- |
| **IP-1** | `ToolContext` (③–⑨, lives across the turn) | Carry an **evidence ledger**; `note_read` already writes to it | FR-001 to FR-005 |
| **IP-2** | `tools/ask.py` no-answer branch (⑨) | Remove the "choose sensible defaults, carry on" result from **every** no-answer path, and stop discarding the expiry flag `bus.resolve()` already returns. **Owns the clarification lifecycle outcome**, producing `cancelled` (dismissal or decline), `expired` (from the flag `bus.resolve()` already returns and `ask.py` currently discards) or `unattended` (from the bus's `listening`). It does **not** decide the turn's stop category — IP-3 does. All three leave the required information unsupplied and prohibit dependent work | FR-018, FR-019, FR-022, FR-033 to FR-035, FR-121, FR-129 |
| **IP-3** | `TurnResult.stopped` + `_iterate` (⑩) | **Owns the transport.** Exactly one new terminal value, `clarification_required`, for every mandatory clarification that ends the run without an answer; attach the structured clarification payload carrying `clarification.outcome` produced by IP-2; propagate to CLI exit, API, the Web session bridge, ACP and channels. **No other `stopped` value is added, and `cancelled` is not touched** | FR-022, FR-035, FR-123 |
| **IP-4** | completion gate (⑩–⑪) | Widen from "unverified pass-claim" to request-vs-delivery; annotate by default, block only a contradicted completion claim | FR-036 to FR-043, FR-124 to FR-127 |
| **IP-5** | `Conversation.render()` (⑦) | Budget manager, dedup, delta and reference assembly all sit behind this one funnel | FR-044 to FR-105 |
| **IP-6** | `learning/store.py` + `_learn` (⑫) | Provenance, supersession, repository-fact invalidation | FR-056 to FR-067, FR-106 to FR-112 |

Nothing else in the flow changes. In particular **⑤ `build_system_prompt` is not
touched** — evidence, clarification state and learned material all ride the user
message or tool results, preserving the cached prefix.

---

## Quality Architecture: the Evidence Ledger

The spec requires distinguishing known / verified / derived / unknown, and adding
requires-clarification, blocked, validated and failed. The deliberate design
choice is to make this **a bookkeeping record, not a reasoning engine**. No
theorem prover, no model call, no inference.

### The one new concept

An **evidence ledger** hangs off the existing `ToolContext`, which already lives
for exactly the right lifetime (one turn) and already records file reads via
`note_read`. It holds entries and open decisions.

```text
EvidenceEntry:  claim · state · source · observed_at · fingerprint
OpenDecision:   what · candidates · evidence_consulted · materiality · state
```

### The state machine

```text
                 ┌──────────┐
   observed ───► │ VERIFIED │ ──── contradicted by new observation ──┐
                 └──────────┘                                        │
                       │ used as premise                             ▼
                       ▼                                       ┌────────┐
   stated by user ► ┌─────────┐   derivation    ┌─────────┐    │ FAILED │
                    │  KNOWN  │ ─────────────►  │ DERIVED │    └────────┘
                    └─────────┘                 └─────────┘
                         ▲
   absent ────────► ┌─────────┐  materiality test (FR-007)
                    │ UNKNOWN │ ──────────────┐
                    └─────────┘               ▼
                         │           ┌────────────────────────┐
                         │ immaterial│ REQUIRES_CLARIFICATION │
                         ▼           └────────────────────────┘
                 agent discretion,      │        │          │
                 states assumption      │        │          │
                 (FR-003, FR-130)  answered  cancelled   nobody
                 ↑ THE ONLY PATH        │    declined    present
                   TO AN ASSUMPTION     │    expired        │
                                        ▼        ▼          ▼
                                     KNOWN  ┌──────────┐ ┌─────────┐
                                        ▲   │UNRESOLVED│ │ BLOCKED │
                                        │   └──────────┘ └─────────┘
                                        │        │            │
                                        └────────┘            │
                                   later REAL user            │
                                   answer (FR-129)            │
                                                              │
   ── transport (IP-3) ───────────────────────────────────────┴──────────────
      answered            → no clarification stop; dependent work resumes
      cancelled/declined  → stopped: clarification_required
                            clarification.outcome: cancelled
      expired             → stopped: clarification_required
                            clarification.outcome: expired
      unattended          → stopped: clarification_required
                            clarification.outcome: unattended

      stopped: "cancelled" is NOT produced by any branch above. It means the
      whole TURN was cancelled or interrupted — a different lifecycle.
      A cancelled QUESTION is never a cancelled TURN.

   ┌───────────┐
   │ VALIDATED │ ◄── completion gate confirmed against evidence
   └───────────┘

   UNRESOLVED and BLOCKED are NOT success. Neither authorises dependent
   mutation, an assumption, a default, a selected option or a fabricated
   value (FR-019, FR-022, E4.7). Only a real answer reaches KNOWN.
```

**Nine states — the closed `EvidenceState` set defined in
[data-model.md §2](./data-model.md) — one transition table, all deterministic.**
`VALIDATED` is distinct from `VERIFIED`: verified means observed, validated means
the completion gate confirmed the delivered work against it. `UNRESOLVED` is
distinct from `BLOCKED`: a person was asked and chose not to answer, versus
nobody was there to ask. Neither resolves anything.

**These states are not the same thing as FR-001's classification categories.**
FR-001 defines *how an item of information became known* — stated by the user,
verified from the repository or a tool, established project or user knowledge,
deterministically derived, or unknown. The state machine above is the *runtime
lifecycle* an entry or decision moves through. A single `VERIFIED` entry has one
FR-001 category and one runtime state; the two vocabularies must not be
conflated.

### What keeps it simple

- **No model call.** Every transition is triggered by a tool result, a user
  message, or the completion gate.
- **No new lifetime.** It is created and discarded with the existing turn.
- **Not in the prompt by default.** The ledger is bookkeeping; only an open
  decision ever becomes visible text, and then as a question.
- **Failure is degradation, not breakage.** A ledger that cannot classify
  something leaves it `UNKNOWN`, which is the safe state.

### Explicit non-goal (security)

The ledger records *that* a fact was observed and *from where* — never secret
values. Entries store a fingerprint, not content. The ledger is never persisted
into a session snapshot, journal or checkpoint (Constitution VIII).

---

## Token-Efficiency Architecture

**Ordering is a gate, not a preference.** Plan Phase 1 (T015) publishes the baseline; no
optimization is accepted before it exists (SC-036, Constitution XXI). Each entry
below carries the five facts the request demanded.

| # | Optimization | Exists? | Tokens saved | Information at risk | What prevents correctness loss | Invalidation | Test |
| --- | --- | --- | --- | --- | --- | --- | --- |
| T1 | **Superseded-read removal** | Yes (`staleness.py`) | A stale file copy × every remaining step | The pre-edit contents | Never the newest read; never an unedited file; the diff that superseded it is retained plus a re-read instruction | On write to that path | Assert zero superseded copies in any assembled request (SC-013) |
| T2 | **Oversized-result spill** | Yes (`overflow.py`) | Result size − (head+tail) × remaining steps | The middle of the output | Nothing discarded — spilled to a retrievable file with an exact pointer; on-disk files pointed at in place | Turn end / pruning | Assert full recoverability (SC-014) |
| T3 | **Prefix caching** | Yes (`caching.py`) | Provider-side, ~90% on the resent prefix | None | Head must stay byte-identical; no optimization may alter it mid-task | Model or prompt change | Assert byte-identical stable portion across turns (SC-015) |
| T4 | **History compaction** | Yes (`context.py`) | Everything before the safe cut | Detail of early steps | Cut only where no tool call is outstanding; original request always preserved; summary replaces, never drops | Threshold fraction of window | Existing tests + orphaned-tool-call assertion |
| T5 | **Context budget manager** | **New**, behind `render()` | Prevents unbounded growth | Low-relevance material | Explicit budget; what was withheld is determinable and retrievable | Per turn | Assert budget respected and withheld set recorded |
| T6 | **Relevance ranking** | Partial (`bm25.py`, `hotindex.py`, `associations.py` exist for recall) | Reuse over recency | Material ranked low but needed | Retrievable on demand (T9); ranking never removes the current request or an outstanding tool result | Per turn | Fixed corpus, fixed ranking assertion |
| T7 | **Content-hash dedup** | **New** | Duplicate reads/results, common in multi-file work | None — identical content by definition | Hash equality only; near-duplicates handled separately and conservatively | Content change ⇒ new hash | Assert zero duplicate-bearing requests (SC-028) |
| T8 | **Delta context** | **New** | Re-statement of changed material | Full prior state | Delta is against material still present in the conversation; if the base is gone, the full form is sent | Base evicted ⇒ full send | Round-trip: delta + base reconstructs exactly |
| T9 | **Selective expansion / references** | Partial (`overflow.py` pointers, `context_refs.py`) | Carrying detail not yet needed | Detail the model did not know to ask for | A reference names what it points at and how to fetch it; the agent can always expand | Source change | Assert expansion returns the referenced content |
| T10 | **Log summarisation** | **New** | Passing runs collapse to an outcome | The body of a passing log | **Failing runs are never summarised to a flag** — failing case, location and message preserved (FR-090) | Re-run | Assert failure recoverable from carried form (SC-027) |
| T11 | **Repository knowledge index** | Partial (`learning/` indices) | Re-discovery within a task | Facts believed stable that changed | Fingerprint per fact; a changed source invalidates | Source fingerprint mismatch | Assert no re-verification without cause (SC-029) |
| T12 | **Compact structured session state** | Partial (`session/store.py`) | Resume re-derivation | Nuance of original phrasing | Resume reuses stored conversation; nothing re-derived | Session write | Resume sends no re-derived context |
| T13 | **Learned project facts** | Yes (`facts.py`, caps 8+6) | Re-explaining known project facts | Nuance behind a short fact | Hard caps; visible in the briefing; deletable | Curator + repo-fact invalidation | Recall-budget assertion (FR-062) |

**Anti-gaming rule.** No optimization is accepted on the estimator alone. Every
claim is validated against providers' reported `usage` (already carried on every
reply and already used to calibrate the counter), and paired with the outcome
rate. An estimator-only improvement is not a result.

---

## Clarification Architecture

### What already exists (do not rebuild)

Verified in source during the audit:

- **The custom-answer invariant is already centrally enforced.**
  `questions.py::_options()` appends the write-your-own row to every question
  **and strips model-authored escape hatches** (`_is_an_escape_hatch`) so the
  user never sees two, one of which does not work. This is exactly the "one
  shared layer" the request asked for. **Nothing to build — tests to add.**
- **Transport**: `question.requested` / `question.answer` / `question.resolved`,
  `QuestionField` with a stable `header`, answers matched by header not position.
- **Waiting**: `bus.resolve()` asks, waits, and atomically claims — expiry
  publishes `REQUEST_EXPIRED` so no client shows a settled decision. Duplicate
  answers are resolved by the claim, not by timing.
- **Reconnect**: `SessionSnapshot.PendingInteraction` already carries a pending
  `question`.
- **TUI determinism**: `packages/questions` is a pure reducer holding form
  position and selection with no rendering and no timers. Keyboard behaviour is
  deterministic by construction.

### The structured clarification object

Extends the existing `Question`/`QuestionRequest` rather than replacing it. New
fields are **additive and optional**, so an old client ignores them:

| Field | Status | Purpose |
| --- | --- | --- |
| `id`, `header`, `prompt`, `options`, `multiple` | exists | identity, text, choices |
| custom-answer row | exists, auto-appended | FR-017 |
| waiting / cancelled / expired | exists (`Request` + bus claim) | FR-022, FR-027 |
| session persistence, reconnect | exists (`PendingInteraction`) | FR-023 |
| **`reason`** | **new** | why clarification was required — which materiality class of FR-007 |
| **`evidence_consulted`** | **new** | what was already checked, so the user is not asked to repeat the agent's work |
| **`decision_ref`** | **new** | links the question to its `OpenDecision` so the answer closes the right one |

### Determinism rules

- Waiting uses the existing claim-and-expire primitive. **No sleeps, no polling,
  no timing-dependent correctness** (Constitution III).
- A stale answer is rejected by the claim, not by a timestamp comparison.
- Mode-aware asking reads `safety/modes.py` rather than reimplementing the rule
  (Finding 3): in a mode with `may_use_read_tools=False`, the evidence-first duty
  is satisfied vacuously and the agent must not claim it inspected anything.

---

## Non-Interactive Surfaces

Resolved clarification Q2: **all** non-interactive surfaces block. Implemented at
IP-2 and IP-3.

```text
mandatory clarification (passes FR-007 materiality)
        │
        ├── a client is listening ──► existing form
        │        │
        │        ├─ answer ─────────► evidence state: KNOWN — RESOLVED
        │        │                    lifecycle outcome: answered
        │        │                    dependent work RESUMES
        │        │
        │        ├─ cancelled │ declined
        │        │            └──────► evidence state: UNRESOLVED
        │        │                     clarification.outcome = "cancelled"
        │        │                     dependent work DOES NOT RUN
        │        │                     not re-raised this attempt (FR-129)
        │        │
        │        └─ expired ─────────► evidence state: UNRESOLVED
        │                              clarification.outcome = "expired"
        │                              dependent work DOES NOT RUN
        │
        └── nobody listening ────────► evidence state: BLOCKED
                                       clarification.outcome = "unattended"
                                       dependent work DOES NOT RUN

   ALL THREE non-answer branches report ONE top-level category:
         TurnResult.stopped = "clarification_required"
         payload: decision, candidates, evidence_consulted, reason, outcome
                                       │
                                       ├─ CLI: distinct non-zero exit code ≠ error
                                       ├─ API/ACP: structured outcome, negotiated capability
                                       └─ channels: message naming the decision

   stopped = "cancelled" is NOT used here. It keeps its existing meaning:
   the whole TURN was cancelled or interrupted (cancel_reason stop|interrupt).

   NO VALUE INVENTED on any of the three branches — no default, no selected
   option, no assumption, no fabricated value (FR-019).
   Only a later REAL user answer moves UNRESOLVED ──► KNOWN (FR-129).

`UNRESOLVED` and `BLOCKED` are **evidence states**. The **clarification
lifecycle** is what `clarification.outcome` reports (`cancelled`, `expired`,
`unattended`), and it is distinct from the **turn lifecycle** that `stopped`
reports. The three non-answer branches differ only in that clarification outcome,
never in permission to guess (FR-035). An agent-selected assumption is reachable
only from a NON-material decision that never entered this diagram (FR-130).
```

Presence is read from the bus's existing `listening` property — a fact the system
already tracks, not a new heuristic. The outcome is distinguishable from both
success and failure so a scheduler routes it for an answer rather than retrying
it as an error (FR-123).

---

## Learning Architecture

Extends `learning/`; no new store, no second memory.

### Admission gate (FR-056)

```text
proposed item
   │
   ├─ origin ∈ {user correction, user statement, settled decision,
   │            counted repository convention, validated outcome,
   │            tool- or source-confirmed fact}  ──► admit with provenance
   │
   └─ origin = unverified model assertion ──────────► REFUSE
```

`signals.py` and `rules.py` already produce exactly the trustworthy classes
(deterministic, evidence-carrying, no model call). `reflect.py`/`review.py`
propose from a model and therefore **must pass the gate**, not bypass it.

### Record extensions (additive columns)

`provenance` · `scope` (already present) · `source_ref` · `fingerprint` ·
`confidence` · `established_at` · `status` (active | superseded | stale |
removed) · `superseded_by`

### Lifecycle and invalidation

```text
admitted ──► active ──┬── contradicted by newer correction ──► superseded
                      ├── source fingerprint changed ────────► stale
                      ├── decayed below floor (curator) ─────► stale
                      └── user deletes ──────────────────────► removed
```

- **Supersession is deterministic**: newer governs, older retained as superseded
  (FR-059). Never a silent disappearance.
- **Repository-derived staleness**: each repository-derived item stores a
  fingerprint of what it was derived from. A mismatch at recall marks it stale
  and excludes it (FR-060, FR-114). This is the mechanism the request asked for.
- **Cross-project leakage**: scope already exists in `store.py`; plan Phase 5
  (tasks Phase 6, T113) adds the test that proves it (SC-019).
- **Compact facts over history**: caps stay (8 project + 6 user). This feature
  does not raise them — a memory that grows is a log injected at full price.

---

## Quality/Token Benchmark

Extends `bench/` rather than replacing it. The existing harness already has the
isolation properties a measurement needs: per-attempt workspace and
`COMODOR_HOME`, learning switched off, hard timeout, repeated attempts reported
as rates.

### Per-scenario record

`task` · `category` · `result` · `correctness` · `input_tokens` ·
`output_tokens` · `cached_tokens` · `total_tokens` · `model_turns` ·
`tool_calls` · `clarifications` · `corrections` · `validation_outcome`

### Scenarios

The existing thirteen tasks across five categories, plus additions this feature
requires:

| Scenario | Measures |
| --- | --- |
| Existing `fix` / `feature` / `find` / `refactor` | outcome rate must not fall |
| Existing `careful` (ambiguity, only-what-was-asked, unknowable) | assumption prevention — already the category nobody else measures |
| **New**: repository-settled ambiguity | the agent reads and decides, **does not ask** (SC-006) |
| **New**: unattended mandatory clarification | clarification-required outcome with `outcome: unattended` (evidence state `BLOCKED`), no invented value (SC-002) |
| **New**: long multi-file task | token efficiency where resend cost dominates |
| **New**: repeated task in one project | fixed N = 6 sequence (tasks 1–3 vs 4–6): mandatory clarifications and user corrections both lower in the learned window, no outcome regression; rediscovery reported as a secondary diagnostic (SC-021) |
| **New**: naive full-resend baseline | the comparison denominator for SC-011 |

### Reporting rule

Token and quality figures are published **in one table**. A token figure without
its outcome rate is not a result (FR-076, Constitution XXI). The judge-honesty
rules already written into `bench/README.md` apply to every new task: a `careful`
or `find` task must turn on something the repository cannot answer, and must have
at least one line whose correct value is a path, a name or a number.

---

## Test Strategy

All deterministic. No sleeps. Every guard mutation-checked: the test must fail
when the guard is removed and pass when restored (SC-025).

| # | Behaviour | Approach | Phase |
| --- | --- | --- | --- |
| 1 | Missing required info triggers clarification | Fake provider; repository with the fact absent; assert form raised before any write | 2 |
| 2 | Repository evidence prevents unnecessary clarification | Same request, fact present; assert no form, decision stated with evidence | 2 |
| 3 | Every multiple-choice question carries the custom row | Property test over generated forms, including adversarial model-authored "Other" | 3 |
| 4 | Custom answer accepted | Drive the reducer and the Python decode path; assert free text reaches the tool result | 3 |
| 5 | Execution waits for clarification | Controlled bus; assert no mutating tool ran before resolution — by state, not timing | 3 |
| 6 | Reconnect preserves pending clarification | Snapshot round-trip with `PendingInteraction` | 3 |
| 7 | Duplicate / stale answers handled | Two answers race the claim; assert exactly one applied, none applied to another question | 3 |
| 8 | Non-interactive returns clarification-required | Bus with no listener; assert distinct outcome, no default | 3 |
| 9 | Unsupported assumptions not inserted | Ledger assertion: no `UNKNOWN` promoted to a value without a transition | 2 |
| 10 | Learned corrections reused | Correct, then re-request; assert applied without restatement | 5 |
| 11 | Unverified model claims not learned | Model proposes an unsupported fact; assert admission gate refuses | 5 |
| 12 | Stale learning invalidated | Change the source; assert fingerprint mismatch excludes the item | 5 |
| 13 | Project learning does not leak | Two project scopes; assert no cross-application | 5 |
| 14 | Context deduplication works | Same content twice; assert one copy in the assembled request | 4 |
| 15 | Unchanged context not resent | Assert stable portion byte-identical across turns | 4 |
| 16 | Token metrics accurate enough | Compare estimate against provider-reported usage within calibration tolerance | 1 |
| 17 | Optimization does not change results | Benchmark outcome rates before/after each optimization | 4, 7 |
| 18 | Permissions intact | Existing permission suite unchanged and green | every phase |
| 19 | Renderer behaviour deterministic | Bun renderer tests at widths 160/120/100/80/60 | 3 |

---

## PR #39 — Overlap Audit

**Status**: open, base `main`, reported mergeable, last updated 2026-09-07.

**Files** (13): `src/comodor/trading/` ×9, `tests/test_trading_domain.py`,
`tests/test_trading_market.py`, `tests/test_trading_orders.py`,
`docs/trading.md`, `docs/README.md`.

**Finding: no material overlap.** None of the twenty audited areas is touched by
PR #39. Compared against this plan's intervention points:

| This feature touches | PR #39 touches | Conflict |
| --- | --- | --- |
| `agent/`, `learning/`, `tools/`, `session/`, `providers/`, `questions.py`, `schemas/protocol/`, `packages/`, `bench/` | `src/comodor/trading/` only | **None** |
| `tests/` (new modules, distinct names) | `tests/test_trading_*.py` | **None** — disjoint filenames |
| `docs/` (feature docs) | `docs/trading.md`, `docs/README.md` | **Textual only** on `docs/README.md` |

- **Abstractions**: no shared abstraction. The trading package imports none of
  the agent, learning, context or question machinery.
- **Likely merge conflicts**: one, in `docs/README.md`, where both add an index
  entry. Ordinary textual merge.
- **Integration order**: immaterial — either may land first. If PR #39 lands
  first, this feature rebases with at most that one-line documentation merge.

**This is not recorded as a blocking integration decision.** The PR decision is
not resolved here and PR #39 is not merged, closed, rebased, modified or depended
upon (FR-083, FR-085).

**Note**: a `src/comodor/trading/` directory exists in the working tree
containing only `__pycache__`. It is untracked build residue from a prior
checkout, not source.

---

## Phasing

Each phase is independently validatable and revertable (Constitution V). **No
phase begins before its predecessor's gate is green on the exact commit.**

**Numbering**: the phases below are **plan phases (0–8)**. The executable task
list in [tasks.md](./tasks.md) uses its own **task phases (1–11)**, and the two
do not coincide (plan Phase 5 = learning = tasks Phase 6; plan Phase 7 =
benchmark = tasks Phase 9). The normative mapping is the crosswalk table at the
top of tasks.md; cross-artifact references use `plan Phase N` / `tasks Phase N`.

| Plan phase | Name | Delivers | Gate |
| --- | --- | --- | --- |
| **0** | Research | Resolve open technical unknowns → `research.md` | All unknowns resolved or explicitly deferred |
| **1** | Foundation & baseline measurement | Per-turn/per-task token record; benchmark extended with paired reporting; **naive full-resend baseline published** | Baseline exists; SC-036 satisfied; estimator validated against provider usage (test 16) |
| **2** | Grounded uncertainty contract | Evidence ledger on `ToolContext` (IP-1); the complete closed `EvidenceState` set from data-model.md §2; materiality test; **no user-visible change yet** | Tests 1, 2, 9; full suite green; zero behaviour change observable |
| **3** | Interactive clarification enforcement | IP-2 + IP-3; answered / cancelled-declined / expired / unattended clarification lifecycles; `clarification_required` outcome (FR-082 enforcement); additive protocol fields; renderer tests | Tests 3–8, 19; protocol codegen `--check` green; old client unaffected |
| **4** | Token accounting & context optimization | IP-5; budget manager, dedup, delta, references, log summarisation | Tests 14, 15, 17; **no outcome-rate fall vs Phase 1 baseline** |
| **5** | Progressive-learning hardening | IP-6; provenance, admission gate, supersession, fingerprint invalidation | Tests 10–13; caps unchanged |
| **6** | Cross-surface integration | IP-4 completion gate; CLI/API/ACP/Web/channel wiring of the clarification-required outcome (FR-082 surface wiring); docs; capability map; bundle rebuild (T141) | Surface impact table complete with evidence; the one behaviour change release-noted |
| **7** | Regression & performance benchmark | Full paired benchmark; SC-011 threshold set from Phase 1 data | Paired report published; no regression |
| **8** | Full validation | Complete baseline on exact final HEAD, all three platforms | Every gate green; nothing claimed unverified |

**Dependency note (plan-phase numbering)**: plan Phase 4 cannot start before
plan Phase 1 (no baseline, no optimization — Constitution XXI). Plan Phase 3
depends on plan Phase 2 (the ledger decides *when* to ask). Plan Phase 6 depends
on plan Phases 2–5.

---

## Surface Impact

Canonical classification for this feature (Constitution XI). Exactly ten rows,
in canonical order; exactly one of the three allowed statuses per row. Every
REQUIRED row names at least one implementation/characterization task, at least
one validation task, and concrete file evidence. Phase references use the
[tasks.md crosswalk](./tasks.md) (`plan Phase N` / `tasks Phase N`).

| Surface | Status | Affected plan/task phases | Evidence / validation |
| --- | --- | --- | --- |
| TUI | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10 | Existing question overlay in `apps/tui/src/App.tsx` and the shared reducer in `packages/questions/src/index.ts` render the new optional `reason` / `evidence_consulted` (T052); deterministic keyboard/input behaviour and the custom-answer row characterized at widths 160/120/100/80/60 (T008) and re-run (T163); committed bundle rebuilt (T141) and verified against source (T166); frontend lint/typecheck/tests/build (T162) |
| Web UI | REQUIRED | plan Phase 1 / tasks Phase 1 (characterization); plan Phase 6 / tasks Phase 8 (wiring, verification); plan Phase 8 / tasks Phase 10 | Live browser question surface: `src/comodor/web/session.py` carries question forms to the page (`request.meta["questions"]`) and routes a dismissal as `CANCELLED` into `tools/ask.py`; `src/comodor/web/ui.js` renders options including the core-appended `free: true` row (`drawOwn`). Characterized before any change — question round-trip, option order, custom-answer row, single/multi-choice, header binding, current dismissal path (T006, `tests/test_web.py`); outcome wiring and regression — `clarification_required` never shown as completion, `clarification.outcome` preserved for cancelled/expired/unattended, dismissal ≠ turn cancellation, custom answer survives, no duplicate free row (T133); Phase 8 gate requires the Web clarification cases green alongside the permission suite (T146); full suite (T160) |
| CLI / Headless | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8 | Today's no-listener behaviour pinned (T009); `comodor run --json` reports `stopped = "clarification_required"` with the nested `clarification` payload (T130, contracts §C3); distinct non-zero exit code ≠ error code (T131); non-interactive blocking test (T044); `docs/cli.md` (T143) |
| API / Protocols | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10 | Additive optional `QuestionField` properties and the negotiated clarification-required capability in `schemas/protocol/v2.json` (T046, T048); artifacts regenerated and `--check` green (T047, T164); old-client compatibility (T136); `api/server.py` never maps the outcome to `finish_reason: "stop"` (T132); session bridge (T133); ACP (T134); capability honesty and mode authority (T138, T139); capability map (T140, T165) |
| Desktop | NOT APPLICABLE | — | No desktop application/client exists: `docs/desktop-architecture.md` opens "Planned, not built. Nothing in this document exists in the repository"; there is no `src-tauri/`, `apps/desktop/` or desktop client package. The existing `src/comodor/desktop/` package is the computer-use **tool's** screen-capture/pointer backend (consumed by `tools/computer.py`, gated in `tools/registry.py`), not a client or runtime: it renders no questions and reads no turn outcome (`grep -rn question\|stopped src/comodor/desktop/` finds only the guard's own `Stopped` refusal). As a tool it is covered by the permission gates (T011, T167), not by this row |
| Channels / Integrations | REQUIRED | plan Phase 3 / tasks Phase 3 (FR-121 blocking); plan Phase 6 / tasks Phase 8 | Non-interactive blocking applies to every channel (FR-121, T044); channel integrations under `src/comodor/channels/` report a needed decision instead of a result or a crash (T135); existing channel suites `tests/test_channel_service.py`, `tests/test_telegram.py`, `tests/test_slack.py`, `tests/test_whatsapp.py` stay green in T160; quickstart Web/channel checks |
| Docker / Packaged Runtime | REQUIRED | plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10 | **Docker configuration unchanged; packaged runtime artifact REQUIRED and verified.** `Dockerfile` / `docker-compose.yml` are not edited by any task (T169 scope review); the packaged terminal-interface bundle that the wheel, sdist and container ship is affected by the TS changes and is rebuilt (T141) and verified to match source (T166); existing Docker/packaging/release validation stays green (T160, T168, T170 confirms no release action) |
| Persistence / Shared State | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 5 / tasks Phase 6; plan Phase 6 / tasks Phase 8 | Learning records gain provenance, status, fingerprint, supersession in `src/comodor/learning/store.py` (T099, T110, T111, T112, T117); session pending-interaction round-trip characterized (T007) and an outstanding form persisted/restored across reconnect with full lifecycle in transcript/export (`src/comodor/session/store.py`, T050, T051); pre-change sessions and stored knowledge remain readable (T137); ledger never persisted (T026) |
| Security / Authorization | REQUIRED | every task phase that touches questions, ASK, modes, tool advertisement, session interaction, orchestration or protocol | Permission and mode enforcement characterized first (T011, `tests/test_baseline_permissions.py`; T012 capability advertisement); per-phase permission regression gates T028, T060, T069, T098, T119, T129, T146 and final T167; unknown modes fail closed and advertised capabilities stay mode-authoritative (T138, T139); the ledger holds fingerprints, never secrets, and is never persisted (T026); clarification never becomes a route to a forbidden action (plan §Explicit non-goal) |
| Tests / Documentation | REQUIRED | all task phases; plan Phase 8 / tasks Phase 10 | Characterization suite T001–T013; mutation-checked regression tests for every guard (SC-025) across Phases 2–8; benchmark scenarios and integrity (T147–T158); `docs/questions.md` (T142), `docs/cli.md` (T143), `docs/learning.md` (T144); `CHANGELOG.md` unreleased note stating the one intended behaviour change (T145); full validation on the exact final HEAD, three platforms (T159–T170) |

Traceability rule: every plan phase that changes a surface is traceable to this
table — plan Phase 3 (TUI, CLI, API, Channels, Persistence, Security), plan
Phase 5 (Persistence), plan Phase 6 (TUI, Web UI, CLI, API, Channels, Docker /
Packaged Runtime, Persistence, Tests / Documentation), plan Phase 1 (Web UI
characterization, Tests), plan Phases 7–8 (Tests / Documentation).

---

## Project Structure

### Documentation (this feature)

```text
specs/002-grounded-agent-quality/
├── plan.md              # This file
├── spec.md              # 174 requirements: 130 FR, 44 SC
├── research.md          # plan Phase 0 output
├── data-model.md        # plan Phase 1 output
├── quickstart.md        # plan Phase 1 output
├── contracts/           # plan Phase 1 output
│   ├── evidence-ledger.md
│   ├── clarification.md
│   └── learning-record.md
├── checklists/
│   └── requirements.md
└── tasks.md             # NOT created by /speckit-plan
```

### Source Code (repository root)

Existing layout; this feature adds one product/runtime module, two
benchmark-harness helpers, and extends eleven product modules.

```text
src/comodor/
├── agent/
│   ├── evidence.py          # NEW — the ledger and its transition table
│   ├── loop.py              # EXTEND — IP-3, IP-4
│   ├── context.py           # EXTEND — IP-5, the single render funnel
│   ├── tokens.py            # EXTEND — per-task record
│   ├── claims.py            # EXTEND — widen to unresolved work
│   ├── verify.py            # EXTEND — request-vs-delivery
│   └── staleness.py         # reuse
├── tools/
│   ├── ask.py               # EXTEND — IP-2, answered vs non-answer lifecycles
│   ├── base.py              # EXTEND — ToolContext carries the ledger
│   └── overflow.py          # EXTEND — dedup, log summarisation
├── learning/
│   ├── store.py             # EXTEND — provenance, status, fingerprint
│   ├── memory.py            # EXTEND — admission gate, invalidation
│   └── curator.py           # EXTEND — fingerprint staleness
├── session/store.py         # EXTEND — pending clarification
├── questions.py             # reuse — invariant already central
├── web/
│   ├── session.py           # VERIFY/EXTEND minimally — browser question round-trip, outcome (T006, T133)
│   └── ui.js                # VERIFY — renders options incl. the core-appended free row; adjust only if T133 proves it necessary
├── api/session_map.py       # EXTEND — bridge carries the outcome (T133)
└── safety/modes.py          # reuse — read, never modified

schemas/protocol/v2.json     # EXTEND — additive, negotiated
packages/questions/          # EXTEND — optional new fields
apps/tui/                    # EXTEND — render reason/evidence; rebuild bundle
bench/
├── integrity.py             # NEW (harness only) — scenario fingerprinting / tamper detection (T013, T154)
├── baseline.py              # NEW (harness only) — deliberately naive full-resend comparison strategy (T014)
├── report.py                # EXTEND — paired reporting
├── runner.py                # EXTEND — explicit learning mode
└── tasks/                   # EXTEND — new scenarios
tests/                       # NEW — ~20 deterministic modules; tests/test_web.py EXTENDED
```

**Structure Decision**: Existing repository layout retained unchanged. The single
new **product/runtime** file is `src/comodor/agent/evidence.py`, placed in
`agent/` because the ledger's lifetime is the agent turn and its only consumers
are the loop, the ask tool and the completion gate — all of which already live
there or call into it. The two new files under `bench/` are benchmark-harness
helpers: development/measurement infrastructure that is **never imported by the
production runtime** (`src/comodor/`), creates no agent/context/learning
subsystem, and is permitted only because each carries a distinct benchmark
responsibility (see Complexity Tracking). No further benchmark helper module may
be added without a new specification decision.

---

## Complexity Tracking

One product/runtime addition requires justification under Constitution XVIII.
Two benchmark-harness helpers are recorded alongside it so that "one new module"
is read precisely: one new **product/runtime** module, not one new Python file.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| New module `agent/evidence.py` | FR-001 requires classifying every consequential premise into one of its information-provenance categories, and the feature additionally requires a deterministic runtime lifecycle over the closed `EvidenceState` set (data-model.md §2). No existing module owns epistemic state: `claims.py` inspects answer text after the fact, `ToolContext.note_read` records only reads, and `learning/` is about durable knowledge across turns, not within one | **Extending `claims.py`** rejected: it is a post-hoc text inspector with a deliberately high firing bar; the ledger must be populated during the turn by tool results, and conflating them would make one module both a bookkeeper and a heuristic. **Extending `ToolContext`** rejected for the transition table only — the context *does* carry the ledger (IP-1), but a frozen-lifetime context object holding a state machine mixes transport with policy. **Reusing `learning/store.py`** rejected: durable cross-session knowledge and within-turn epistemic state have different lifetimes, different persistence rules (the ledger is never persisted) and different security properties |

**Benchmark-harness helpers (not product/runtime subsystems)**

| File | Why a separate file | Boundary |
| --- | --- | --- |
| `bench/integrity.py` (T013, T154) | Scenario fingerprinting and tamper detection have a separate lifecycle from scenario execution (`runner.py`) and reporting (`report.py`): fingerprints are taken before any change and checked after, and a weakened scenario must be detectable independently of the run that used it | Harness only; never imported by `src/comodor/` |
| `bench/baseline.py` (T014) | The deliberately naive full-resend comparison strategy must stay isolated from the optimized production context path (`agent/context.py`), so benchmark code cannot accidentally become runtime behaviour and the baseline cannot silently inherit an optimization it is meant to measure against | Harness only; never imported by `src/comodor/` |

Validation: a deterministic test asserts that no module under `src/comodor/`
imports `bench.integrity` or `bench.baseline` (owned by T154; enforced again in
T169's scope review). No other new subsystem. Every remaining change extends a
module that already owns the behaviour, as recorded in the Architecture Audit.

---

## Constitution Re-Check (post-design)

Re-evaluated after the plan Phase 1 design artifacts below.

- **XVIII (extend, don't duplicate)**: one new module, justified above; the audit
  names an existing owner for all twenty areas. **PASS**
- **VIII (security)**: the ledger stores fingerprints and sources, never secret
  values, and is never persisted into snapshots, journals or checkpoints. Mode
  policy is read, never written. **PASS**
- **VI (boundaries)**: the ledger lives in the core; frontends render what the
  protocol carries. The protocol change goes through the schema and codegen.
  **PASS**
- **I (compatibility)**: all protocol additions are optional and negotiated; the
  one intended behaviour change (FR-082) is isolated to plan Phase 3
  (enforcement) / Phase 6 (surface wiring) and release-noted.
  **PASS**
- **XXI (paired measurement)**: enforced structurally — plan Phase 4 (tasks
  Phase 5) cannot begin before plan Phase 1 (T015) publishes the baseline. **PASS**

**Gate result after design: PASS.** No unjustified complexity.
