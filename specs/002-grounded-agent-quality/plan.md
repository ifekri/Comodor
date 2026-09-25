# Implementation Plan: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Branch**: `002-grounded-agent-quality` | **Date**: 2026-09-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-grounded-agent-quality/spec.md` (130 functional requirements, 44 success criteria — 174 in total; 18 clarification decisions resolved through 2026-09-24)

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

**Testing**: `pytest` under `tests/` (`-n auto --dist loadfile`, `performance` marker excluded by default); Bun renderer tests for the terminal interface; `bench/` for quality-and-cost measurement.

**Target Platform**: Windows, Linux, macOS — equally supported (Constitution II).

**Project Type**: Cross-platform terminal coding agent with a browser interface, a headless command line, an API/ACP protocol surface, channel integrations and a packaged container.

**Performance Goals**: No regression in the existing performance ceilings (`pytest -m performance`). Recall stays off the critical path between Enter and first token — the existing in-memory index exists precisely for that. Context assembly must not add a model call.

**Constraints**: No new runtime dependency. No change to the cached system-prompt prefix mid-task (worth ~99% prefix-cache retention, measured; larger than anything this feature could recover). Protocol v2 stays compatible; any addition is negotiated. Secrets never enter state, snapshots, journals, checkpoints, logs or fixtures.

**Scale/Scope**: 174 requirements (130 FR, 44 SC) across the original 8 delivery phases plus 2 explicit convergence/acceptance phases added after the final specification review. Estimated surface: ~11 Python modules extended, **one new product/runtime module** (`src/comodor/agent/evidence.py`), **two new benchmark-harness helper modules** (`bench/integrity.py`, `bench/baseline.py` — measurement infrastructure, never imported by `src/comodor/`), 1 schema addition, 1 shared TS package touched, the browser question surface (`src/comodor/web/`) characterized and verified, ~20 new deterministic test modules, benchmark harness extended.

---

## Constitution Check

*GATE: evaluated before plan Phase 0 and re-evaluated after plan Phase 1 design (below).*

Checked against `.specify/memory/constitution.md` **v1.1.0** (21 principles).

| Principle | Gate | Status |
| --- | --- | --- |
| I — Backward compatibility | FR-082 enumerates three intended user-visible changes; only removal of self-resolving mandatory non-answers is backward-incompatible/regression-by-design and release-noted, while completion correction/annotation and same-decision re-raise suppression are additive | **PASS** — FR-082; plan Phase 3 (enforcement) / Phase 6 (surface wiring) — tasks Phase 3 / tasks Phase 8 |
| II — Three platforms | Every phase validated on the CI matrix; no platform-conditional logic introduced | **PASS** |
| III — Fix the invariant | No sleeps, no raised timeouts, no weakened assertions; clarification waiting uses the existing claim-and-expire primitive, not timing | **PASS** — see Clarification Architecture |
| IV — Deterministic regression tests | Every guard gets a mutation-checked test (SC-025); Phase-gated | **PASS** |
| V — Narrow scope | Bounded phases, including explicit D4/D9 convergence and final acceptance phases, each independently validatable and revertable | **PASS** |
| VI — Architectural boundaries | Evidence ledger lives in the core; frontends render it. Protocol change goes through the schema and codegen, never hand-edited | **PASS** |
| VII — Reproducible artifacts | Terminal-interface bundle rebuilt and committed if TS changes | **PASS** — TS/TUI-affecting work lands in plan Phase 3 (clarification enforcement: protocol fields, overlay) and plan Phase 6 (surface wiring); the committed bundle rebuild is owned by T141 (tasks Phase 8), verified by T166 |
| VIII — Security not weakened | Mode policy untouched; clarification never becomes a route to a forbidden action; no secret enters the ledger | **PASS** — explicit non-goal below |
| IX — Release infra is production code | No release action in this initiative at all | **N/A** — FR-084 |
| X — Quality gates mandatory | Full baseline runs per phase on the exact commit | **PASS** |
| XI — Specifications name surfaces | `spec.md` owns the normative ten-surface table using REQUIRED / UNCHANGED BUT VERIFIED / NOT APPLICABLE; this plan mirrors it and adds implementation/task evidence without overriding it | **PASS** — the table below is a convergence view of the authoritative spec classification; Web UI is REQUIRED and the planned desktop application is NOT APPLICABLE |
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

## 2026-09-24 Plan Convergence

The committed specification at `d911e3f` (specification quality gate 131/131)
is authoritative. Most of Feature 002 is implemented and validated. This
convergence closes what the final specification added or sharpened. It extends
the existing owners; it adds no clarification subsystem, no decision store, and
no persisted evidence ledger. Task IDs for the work below are derived later by
`/speckit.tasks`; this plan names the work, its owner and its gate.

### A. The three intended user-visible changes (FR-082)

| # | Change | Class | Requirements | Delivered by |
| --- | --- | --- | --- | --- |
| 1 | A mandatory clarification no longer resolves itself on a non-answer; non-interactive runs report `clarification_required` | **Backward-incompatible — the only regression-by-design**, release-noted | FR-019, FR-035, FR-121 to FR-123 | plan Phases 3 and 6 (implemented) |
| 2 | Completion claims are checked: unresolved work is annotated; a contradicted claim is corrected; an unsupported claim is never delivered as completed | **Additive** — adds a notice or correction, removes nothing a caller had | FR-036, FR-037, FR-124 to FR-127 | plan Phase 6 (implemented); FR-127's unsupported-claim rule re-verified in plan Phase 9 |
| 3 | A cancelled mandatory question is not re-raised within the same decision attempt | **Additive** — adds a report, removes nothing | FR-129 | plan Phase 3 (implemented) |

Everything else in this feature is compatibility-preserving: every protocol
addition is optional and negotiated (FR-080), and no existing message changes
meaning (FR-079). No fourth user-visible change is intended.

### B. Stable `decision_ref` and later resumption (D4, D9)

**Repository facts** (inspected at `d911e3f`):

- `agent/evidence.py::EvidenceLedger.open_decision` mints `OpenDecision.id` as
  `f"d{n}"` from a per-ledger counter shared with evidence-entry ids. A new
  ledger restarts it every turn, so `d1` recurs in every turn of a session. It
  **cannot** serve as the semantic `decision_ref`: an answer keyed by it could
  resolve the wrong turn's decision, which is exactly the heuristic matching
  FR-129 forbids.
- `tools/ask.py` sets `Question.decision_ref = decision.id`. Questions already
  carry the field (`questions.py`, protocol `QuestionField.decision_ref`), but
  with the turn-local value.
- `tools/ask.py::payload_for` emits `decisions[].id` only. In
  `schemas/protocol/v2.json`, `ClarificationDecision` requires `id` and
  `decision`, and `ClarificationRequired` has no `decision_ref`.
- The form lifecycle is already persisted. `ask.form_record` — written for
  model-raised, preflight-raised (`origin="mutation_preflight"`) and unattended
  forms — is stored by `agent/loop.py` on the tool message as
  `message.meta["question"]`, appended to the session JSON Lines by
  `session/store.py`, and rendered in exports (`_question_lines`).
- CLI: `comodor run --json` emits the `clarification` block and exits `3`.
  **A headless run is stateless**: `cli.py::run_headless` never touches
  `SessionStore`, and nothing of a finished headless run is persisted. The
  global `--resume` flag belongs to the interactive session path, and
  `run_headless` never reads it. API: `api/server.py` reads a request-side
  `comodor` block (today `mode`) and the `X-Comodor-Session` header, and
  returns `comodor.clarification`. ACP: `acp/agent.py` sends a
  `clarification_required` session update. Channels have no
  clarification-specific code; they run turns through the application layer.
- No surface accepts an answer keyed by `decision_ref`.
- **Turn entry — six families, one loop.** Every application or surface path
  that starts a primary turn ends in `AgentLoop.run(user_text, images,
  decisions)`, but not through one caller:
  1. `web/session.py::Session.send` (it builds its own `AgentLoop`) serves the
     Web UI, the OpenAI-compatible API (`api/session_map.py`), Telegram, Slack,
     WhatsApp and Discord. It passes `images` and `decisions`; the Web
     session's own completion delivery re-enters through `Session.send`.
  2. `application/__init__.py::CoreService.send` starts a normal TUI user turn.
  3. `application/__init__.py::CoreService._deliver_completions` starts the
     turn that delivers finished background delegates to the parent session.
     It collects each record's `clarification` and passes them as
     `decisions=carried or None`, so a delegate's open decision reaches the
     parent turn unresolved (FR-029, FR-018). It is a separate call path from
     `send`.
  4. `cli.py::run_headless` calls `assemble()` and then `agent.run(task)`.
  5. `acp/agent.py` calls `assemble()` and then `self.loop.run(text)`.
  6. `cron/runner.py::run_job` builds its own `AgentLoop` for scheduled jobs,
     and the webhook channel runs every event through it.
- **Internal child loops are not turn entries.** `tools/delegate.py` and
  `agent/background.py` run a delegate's own child loop (`loop.run(brief)`).
  They take no cross-invocation answer; when a child stops for a decision, its
  clarification returns to the parent — through the completion delivery above,
  or through the delegate tool's result.
- **Channel reply capabilities** (verified in source):
  - **Telegram** — inline-keyboard callbacks (`telegram/keyboard.py`,
    `callback_query` in `telegram/bot.py`) and bot commands (`_on_command`).
  - **Slack** — block actions whose `action_id` / value come back in the
    interaction payload (`slack/blocks.py`, `slack/bot.py`).
  - **WhatsApp** — interactive reply buttons and lists (`whatsapp/menu.py`),
    parsed as `type == "interactive"` in `whatsapp/webhook.py`.
  - **Discord** — plain messages only; no component or interaction handling in
    `discord/`.
  - **Webhook** — inbound signed events run as one-shot templated jobs through
    `cron/runner.py`, and the answer is delivered outbound to a `reply_url`;
    there is no inbound reply route.
- Sessions: `session/store.py::SessionMeta` is loaded as `SessionMeta(**json)`,
  and a `TypeError` returns `None`, so an older reader silently skips a meta
  file carrying a field it does not know. `SessionStore.list_sessions()` is the
  single listing owner. Its callers are `application/__init__.py` (the
  protocol's `session.list` — the TUI's resume list), `web/session.py`,
  `acp/agent.py` and `insights.py`. Exports are
  `SessionStore.export_markdown` / `export_json`, keyed by session id. No
  session has a retention or prune policy; a session lives until it is
  deleted.

**Design — each concern stays with its existing owner:**

| Concern | Owner (extended, not replaced) | Design |
| --- | --- | --- |
| Semantic identity | `agent/evidence.py` (`OpenDecision`) | Add a `ref`: an opaque id minted **once**, when a decision first enters `REQUIRES_CLARIFICATION`, by a minting function the ledger takes as a parameter (default: a random opaque token; tests inject a deterministic sequence, so no test depends on randomness). Never derived from wording, list position or a turn counter. A decision re-raised for resumption carries its original `ref` rather than a new one. `OpenDecision.id` stays ledger-internal. |
| Lifetime | the session that raised the decision | A `decision_ref` resolves for the life of that session — for a stateless run, its continuation (below). It becomes **stale** once an answered record for it is persisted. A ref from any other session is **unknown**. There is no new retention policy: like every session, a continuation lives until it is deleted, and deleting one makes its refs unknown. There is no global tombstone store. |
| Persistence | existing session transcript (`form_record` → `message.meta["question"]`) | No new store. The form record already carries each question's `decision_ref` and the lifecycle `outcome`. The session layer derives the **unresolved set**: refs whose latest record ended `cancelled`, `expired` or `unattended` with no later `answered` record. The evidence ledger stays turn-local and unpersisted. |
| Stateless-run continuation | `session/store.py` (`SessionStore`, `SessionMeta`), written through the shared turn entry | A **stateless** run — `comodor run`, a scheduled job, a webhook event — persists nothing unless it ends `stopped = "clarification_required"`. Only then does it write its transcript through the existing `SessionStore`: the same JSON Lines records (form records included) and meta as any session. `SessionMeta` gains **one** optional field, `continuation`, a small object `{decision_refs: [...], mode: "..."}`, **written only on continuations**; every ordinary session's meta file is byte-for-byte unchanged, and an older Comodor, which rejects unknown fields, skips a continuation. `SessionMeta.cwd` (existing) is the workspace binding; `SessionMeta.provider` / `model` (existing) are provenance only. `list_sessions()` excludes any meta that has `continuation`, so a continuation never appears in the TUI resume list, the Web UI, ACP or insights. |
| Exact continuation lookup | `SessionStore` | One exact lookup, `decision_ref` → continuation: the single continuation whose `continuation.decision_refs` contains the ref, by equality. No match → unknown; more than one → unresolvable. `decision_refs` keeps **every** ref the continuation has ever issued, answered ones included — a ref is never removed on resolution. The transcript's form records then decide open vs stale. Never recency, list order, workspace proximity, question text or first-unresolved order. |
| `clarification_required` serialization | `tools/ask.py::payload_for`; `agent/loop.py` carries it | Add top-level `decision_ref` (the first open decision) and `decision_ref` on every `decisions[]` entry. Keep `decisions[].id`, set to the same value, so there is one identity with a compatibility alias. |
| Protocol | `schemas/protocol/v2.json` → `tools/protocol-codegen.py` | Optional `decision_ref` on `ClarificationRequired` and `ClarificationDecision`. No change to required fields, no version bump; regenerate `src/comodor/protocol/_generated.py` and `packages/protocol/src/generated.ts`. No new client→core message in this phase: interactive clients answer a live form through `question.answer`, and a later explicit request re-raises the form with the same `decision_ref`. |
| Shared turn entry (one owner) | `application/__init__.py` — one function, `run_turn`, sitting immediately above `AgentLoop.run()` | The single operation all six turn-entry families call **instead of** calling the loop directly: `Session.send` (Web, API, Telegram, Slack, WhatsApp, Discord), `CoreService.send` (TUI user turn), `CoreService._deliver_completions` (background-completion turn), `run_headless` (CLI), ACP and `run_job` (cron, webhook). **Inputs**: it never narrows `AgentLoop.run`'s contract. `user_text`, `images` and `decisions` pass through unchanged, and `decision_answers` is the one new input. `decisions` are **open** clarification payloads carried into the turn — today from background delegates — and stay unresolved; they never trigger a continuation lookup and are never treated as answers. `decision_answers` are explicit later-invocation answers, and only they trigger resolution and validation. It owns, in this order: accepting an optional DecisionAnswer batch; resolving the continuation a stateless caller's batch names; validating the whole batch (§B.1); refusing before any model call; restoring a continuation's conversation into the loop; seeding valid answers exactly as live-form answers are seeded; calling `AgentLoop.run(user_text, images, decisions)` with the carried inputs unchanged; persisting a stateless run's continuation (§B.2); and returning the ordinary `TurnResult`. A session-backed caller (Session, CoreService, ACP) passes its live conversation, which *is* its session. A stateless caller passes the session store and its execution binding (canonical workspace, effective mode). It is a function over the existing loop, conversation and store — not a second loop, clarification engine or persistence layer. Adapters only translate their native input into it. |
| Invalid-reference rejection | common path | Missing, malformed, unknown, stale or unresolvable refs are rejected. The rejection names the refs that failed, changes no decision, authorises no dependent work, and never falls back to recency, position, textual similarity, most-recent-question or first-unresolved order (FR-026, FR-129). |
| CLI / headless | `cli.py` (`run` parser, `run_headless` → `run_turn`) | A dedicated `run` option, `--decision-answers PATH` (`-` = stdin), carrying a JSON DecisionAnswer list — the headless representation of FR-129's structured resumption input. The global interactive `--resume` is **not** reused, because its contract is reopening interactive sessions. With `--decision-answers`, the positional task is optional; if given, it rides the resumed turn as the caller's message. The refs alone locate the continuation (exact lookup); all refs in a batch must resolve to the same continuation; the invocation's canonical workspace and effective mode must match the continuation's (§B.1). On rejection: no model call; the refs, or the binding mismatch, are named on stderr; exit code `1`; `--json` output carries an additive `error` object. No new exit code. `--interactions` is unchanged: it scripts a **live** form within one run, in order — the pending-form path — and never resolves a decision in a later invocation. |
| API | `api/server.py`, `api/schema.py`, `api/session_map.py` | `decision_answers` inside the existing request-side `comodor` block, with `X-Comodor-Session`. On rejection: HTTP 400 with the existing OpenAI-style error body (`type: invalid_request_error`), naming the refs. The response envelope is otherwise unchanged. |
| ACP | `acp/agent.py` | Decision answers ride the prompt request's extension metadata. On rejection: a JSON-RPC invalid-params error naming the refs. |
| Channels / integrations | channel adapters → `Session.send` → `run_turn` | A message reporting a needed decision shows its `decision_ref` (the core's needed-decision text). Resumption only through an existing structured route that can carry the ref: a Telegram callback or command, a Slack block action, a WhatsApp interactive reply. **Discord** and the **webhook** have no inbound structured reply route: they report the decision and its ref and offer no resumption there; no new interaction system is added for Feature 002. A webhook event, like a scheduled job, is a stateless run, so its stopped run leaves a continuation resumable with `comodor run --decision-answers`. Ordinary free text on every channel is a new request, never matched to a decision. |
| Delegated work | `agent/background.py` (`ScopedBus`) | A delegate's decision gets its `ref` from the same minting path and is recorded in the parent session, so resumption is the same path. |
| Live pending forms | unchanged (`question.answer`, the bus's atomic claim) | A live form keeps its lifecycle identity; the core already knows its decision association (FR-020, FR-024). |
| Backward compatibility | every surface | A client that neither sends decision answers nor reads `decision_ref` sees identical behaviour. `decisions[].id` remains, and every new field is optional. |

**Layering.** `AgentLoop` stays the one execution loop. Within a turn it owns
the evidence lifecycle, the mutation preflight, clarification, completion
verification, and tool and model execution. `run_turn` (application layer)
owns everything that crosses an invocation: loading a continuation, validating
decision answers against it, restoring its conversation, and persisting a
stateless run's continuation. Session persistence never moves into model
iteration.

#### B.1 Execution binding and validation order

A continuation is bound to the conditions under which its decision was
created:

- **Workspace — binding.** `SessionMeta.cwd`, stored canonical (resolved
  absolute path), is authoritative. A resumption whose invocation resolves to
  a different canonical workspace is rejected. The continuation is never run
  against the caller's current directory and never re-pointed to it.
- **Mode — binding.** `continuation.mode` is the effective safety mode the run
  stopped in. A resumption whose effective mode differs is rejected: no
  automatic upgrade or downgrade, and act capability is never granted to work
  that stopped in another mode.
- **Provider and model — provenance, not identity.** They do not bind. A
  changed provider or model neither makes a valid `decision_ref` unknown nor
  stale (FR-028: an outstanding form stays valid across a model change). After
  workspace, mode and answer validation succeed, the resumed work runs on the
  invocation's configured provider and model.

`run_turn` validates a resumption in exactly this order, and rejects the whole
batch at the first failure:

1. Parse the DecisionAnswer input.
2. Validate its structural shape.
3. Resolve every `decision_ref` exactly.
4. Require the whole batch to resolve to one continuation (for a stateless
   caller) or to the live session (for a session-backed caller).
5. Verify every referenced decision is open (not stale).
6. Verify the canonical workspace matches (stateless callers).
7. Verify the effective mode matches (stateless callers).
8. Validate each answer's `chosen` / `written` content.
9. Apply the answers.
10. Invoke `AgentLoop.run()`.

On any failure: zero answers applied, no model call, no tool or dependent
mutation, and every unresolved decision unchanged. The caller is told what
failed. A session-backed caller's binding is its own live session, so steps 6
and 7 are satisfied by construction there; the loop's mode enforcement governs
the resumed turn as it governs every turn.

#### B.2 Stateless-run continuation lifecycle

- **Fresh run, ends normally or with an error**: nothing is persisted; this
  feature adds no persistence here.
- **Fresh run, ends `clarification_required`**: its whole resumable transcript
  — form records with their `decision_ref`s, outcome and any `prior_changes` —
  is written once through `SessionStore` as a continuation, whose
  `continuation` holds its refs and mode, with `cwd` its canonical workspace.
  The same redaction applies as to any stored session: tool output is redacted
  at the tool layer before it enters the conversation.
- **Resumed run** (a valid batch): no longer a fresh run — it is
  continuation-backed. The continuation's transcript is loaded, the answers are
  appended as `answered` form records through the common clarification
  semantics, and the resumed turn runs in that same continuation. Its
  transcript is **appended to that continuation whatever it ends in**:
  success, error or another clarification. The fresh-run "persist only on
  `clarification_required`" rule does not apply to a resumed run.
- **Resumed run stops again**: the same continuation is kept. The new form and
  outcome are appended, the new decisions get newly minted refs, and those refs
  are **added** to `decision_refs` — every earlier ref stays. The new
  `clarification_required` outcome is returned. No second continuation is
  created. One continuation is one resumable chain of work.
- **After resolution**: the answered ref stays in `decision_refs` and in the
  transcript, so reusing it is rejected as **stale**. When every decision is
  resolved and the work completes, the continuation is kept, still unlisted,
  under the existing retention rule.
- **Deleted**: a continuation removed through the existing delete path makes
  its refs **unknown**, because the authority was intentionally removed.
- **Transcript and export (FR-030)**: the continuation is an ordinary transcript
  in the existing format, exportable through `SessionStore.export_markdown` /
  `export_json` by the id its refs resolve to. It is only kept out of the
  listing.

**SC-042.** A real later answer resumes the dependent work through the same
semantic decision, and produces the same requested result as answering during
the original wait. The deterministic replay test holds everything else
constant, provider and model included, and varies only "answered during the
original wait" against "clarification stop → persisted continuation → explicit
later answer". It compares the observable requested result, not the model's
prose byte for byte.

**Gate for this work (plan Phase 9)**: deterministic, mutation-checked tests
prove:

- `decision_ref` is stable across cancel, expiry and unattended endings and
  across a later turn, and distinct across turns;
- a valid answer resolves only its own decision and resumes the dependent work
  to the same result as a first-time answer (SC-042);
- each invalid class — missing, malformed, unknown, stale, cross-session — is
  rejected before any model call, with no decision changed and no dependent
  work run;
- a fresh stateless run that ends normally persists nothing; one that ends
  `clarification_required` persists exactly one continuation, which
  `list_sessions()` does not return, which an older-format reader skips, and
  which a later `comodor run --decision-answers` resumes by ref alone;
- a resumed run appends its transcript to the same continuation whatever it
  ends in; a resumed run that stops again keeps the same continuation and adds
  its new refs without dropping the old ones; an answered ref is then rejected
  as stale, and a deleted continuation's ref as unknown;
- a resumption from a different canonical workspace, or in a different
  effective mode, is rejected before any model call with no decision changed;
  a changed provider or model is not a rejection;
- every application or surface path that starts a primary turn — all six
  families — goes through `run_turn`. This is proved behaviourally, by driving
  each family's entry function and observing that `run_turn` was reached, and
  not by forbidding loop calls in source text. `run_turn` itself calls the
  loop, and delegate child loops legitimately call their own;
- `images` and carried `decisions` reach `AgentLoop.run` unchanged through
  `run_turn`; a delegate's open decision delivered by
  `CoreService._deliver_completions` is still unresolved in the parent turn and
  still blocks dependent work;
- an ordinary session's meta file is unchanged byte for byte;
- no fallback path exists (a mutation that adds one fails a test);
- old clients are unaffected (SC-023).

Protocol codegen `--check` and the capability map stay green.

### C. SC-002 and dependency semantics (D7) — validation model

The mechanisms already exist: the dependent-work guard in `agent/loop.py`, the
mutation preflight in `agent/preflight.py`, and `prior_changes` for late
discovery. Validation measures SC-002 as written, per attempt, never as a
blanket "no write before asking" rule:

| Scenario class | What a deterministic test asserts |
| --- | --- |
| Up-front ambiguity (the decision is identifiable before any dependent mutation) | Zero dependent writes, shell invocations or external calls before the clarification; the specific dependent artifact does not exist. |
| Uncertain dependency | The mutation is withheld, as if dependent. |
| Demonstrably independent work | It **may** run, does not fail SC-002, and is not required. No work is started merely to stay active. |
| Late discovery | Changes made before discovery persist and appear in `prior_changes`; zero potentially dependent mutations run after discovery; nothing claims the workspace is unchanged. |

The existing clarification suites (`test_clarification_lifecycle.py`,
`test_clarification_pause.py`, `test_clarification_required.py`,
`test_mutation_preflight.py`) assert that the **specific dependent artifact**
is absent, not that nothing at all was written — consistent with D7. Plan
Phase 9 adds the missing positive cases (independent work permitted; late
discovery with prior changes), and audits the benchmark judges in
`bench/tasks/careful-*` for a blanket no-write assertion without weakening any
of them.

### D. Requirements sharpened by the 2026-09-24 sessions — re-verification

Each is re-verified against the code by a deterministic test in plan Phase 9;
a gap becomes a task rather than an assumption:

- **FR-127**: an unsupported completion claim is marked unconfirmed and never
  delivered as completed. No "not confirmed" annotation was found in
  `agent/claims.py`, `agent/verify.py` or `agent/loop.py` at `d911e3f`, so this
  is a probable gap.
- **FR-099**: exact duplicates collapse only on content identity; near-duplicates
  only when the difference is proven irrelevant.
- **FR-100 / FR-101**: full authoritative fallback when a base or referent
  cannot be validated.
- **FR-105**: one invalidation rule across every reuse mechanism.
- **FR-018 / FR-123**: bounded independent work before a non-interactive stop;
  no speculative work.

### E. FR-082 — the headless continuation adds no fourth user-visible change

Headless later resumption is FR-129's own requirement, and its CLI
representation (`--decision-answers`) and the `decision_ref` fields are that
requirement's surface. The continuation that makes it safe is internal: it is
written only when a stateless run (`comodor run`, a scheduled job or a webhook
event) already ends needing a decision, it never
appears in any session list, UI or insights, it leaves the global `--resume`
contract untouched, and it leaves ordinary sessions' stored files unchanged. No
behaviour a user sees today changes beyond the three FR-082 changes, so no
specification clarification is needed.

### F. Acceptance

SC-011 passes only when current mean total tokens ≤ 0.90 × naive in one
comparable paired run **and** every task's current outcome rate ≥ naive. Both
historical runs fail it. SC-012 has no final passing evidence. Both are settled
only in plan Phase 10, on the exact frozen candidate, after plan Phase 9. SC-011
is unchanged by §G. SC-012 is decided by §G's per-task reference rule.

### G. SC-012 comparability and baseline provenance (D10–D12, 2026-09-25)

**Repository facts** (inspected at `77b765b`):

- `bench/integrity.py::fingerprint(directory)` is the one scenario
  fingerprint: the hashes of `task.md` and `check.py`, the `repo/` and
  `hidden/` trees, and the declared budgets, with line endings normalised.
  `fingerprint_all(root)` applies it to every scenario under a root, and
  `FINGERPRINTS.json` is its committed record.
- `bench/runner.py::_paired_header` already computes `fingerprint_all()` once
  at the start of a paired run and binds it into the checkpoint, and a resume
  is refused if it moved. `python -m bench` refuses to run on a drifted suite.
- `bench/report.py::as_paired_json` publishes, per task, `current` and `naive`
  records carrying `passed` and `tries`, and a top-level short `commit`. It
  records **no** fingerprint. The 2026-09-20 baseline
  (`bench/results/paired-baseline-2026-09-20.json`, `commit: "be9cf6f"`) has
  none either.
- `commit` comes from `git rev-parse --short HEAD`, with no dirty-tree
  marker. Recorded fingerprints (D12) remove the dependence on it for future
  results.
- Recomputing `fingerprint_all()` over `bench/tasks` at `be9cf6f` and at HEAD
  gives 19 scenarios each, of which exactly two differ:
  `careful-cannot-be-done` (`check.py`, `task.md`) and `careful-unknowable`
  (`check.py`). This is **current evidence only**. Nothing names these tasks;
  the rule below is fingerprint-driven.

**Design:**

| Concern | Owner (extended, not replaced) | Design |
| --- | --- | --- |
| Scenario fingerprint (D11) | `bench/integrity.py` | The canonical producer stays `fingerprint(directory)`, with no second algorithm. Two additions. `fingerprint_at(commit)` extracts `bench/tasks` from that commit (`git archive`) into a temporary directory and applies the **current** `fingerprint_all` to it, so both sides are hashed by one algorithm. It fails if the commit cannot be resolved (`git cat-file -e <commit>^{commit}`). `digest(fingerprint)` is the SHA-256 of the fingerprint's canonical JSON (`sort_keys`, compact separators), a fixed-length identity for evidence. Two fingerprints are equal exactly when their digests are equal. Harness code outside the fingerprint (`runner.py`, `task.py`, `report.py`) is not part of a scenario and never makes a task changed. |
| Baseline provenance (D12) | `bench/runner.py`, `bench/report.py` | Captured **once, at run start**: the `fingerprint_all()` result the paired header already computes, verified unchanged on resume, is passed to `write_paired` / `as_paired_json`. There is no second computation at write time. Stored per task in the published paired JSON as an additive key `"scenario_fingerprint"`, holding the full fingerprint (the same shape as a `FINGERPRINTS.json` entry), inside the task's entry beside `current` and `naive`. Both arms of a task come from one run and one fingerprint. The Markdown report gains no column. Only the paired baseline kind (`kind: "paired-baseline"`) is a published baseline for SC-012 and SC-036. The single-strategy and blocked-ablation reports are unchanged. |
| Reading provenance | `bench/report.py` | One reader, `scenario_fingerprints(report)`. It returns `(per-task fingerprints, source)`. It uses the recorded `scenario_fingerprint` values when **every** task carries one (source `recorded`). Otherwise it reconstructs from the report's own `commit` via `fingerprint_at` (source `reconstructed:<commit>`). A report with no usable commit and no recorded values is undecidable. It never mixes: fingerprints come either from the file or from that file's own commit, never another commit, and never partly each. Historical artifacts are read, never rewritten. |
| SC-012 comparison (D10) | `bench/report.py`, CLI in `bench/__main__.py` | `sc012_comparison(candidate, baseline)` over two paired reports. For every task in the candidate: **UNCHANGED** when `digest(candidate fp) == digest(baseline fp)` for that task. The reference is then the baseline's `current` rate, kind `PUBLISHED_BASELINE`, and the reference fingerprint is the baseline's. Otherwise **CHANGED**: the reference is the candidate's own `naive` rate from the same run, kind `SAME_RUN_NAIVE`, and the reference fingerprint is the candidate's. A candidate task absent from the baseline is CHANGED. The per-task result is `PASS` when `Fraction(passed, tries)` of the candidate `current` is at least the reference's, `FAIL` otherwise. The selection is fixed: no option, parameter or file can choose a reference, exclude a task or supply fingerprints. |
| Fail-closed (undecidable) | `bench/report.py` | The overall result is `UNDECIDABLE`, never PASS, when: either document is not `kind: "paired-baseline"`; fingerprints cannot be obtained for either side; a baseline task is missing from the candidate (the task set may not shrink to hide a fall; the tasks are listed); a candidate `current` arm has `tries == 0`; or the selected reference arm is missing or has `tries == 0`. The overall result is otherwise `FAIL` if any task fails, else `PASS`. The denominator is every task in the candidate. |
| Output (T199 evidence) | `bench/report.py`, `bench/results/` | `python -m bench --sc012 <candidate.json> --against <baseline.json> [--label NAME]` writes `bench/results/sc012-<label>.json` and `.md`. It needs no provider or model, calls none, and exits `0` PASS, `1` FAIL, `2` UNDECIDABLE. The JSON has `kind: "sc012-comparison"`; `candidate` and `baseline` objects (file, commit, fingerprint source); `result`; `baseline_only_tasks`; and one entry per candidate task with: `task`, `candidate_fingerprint` and `reference_fingerprint` (digests), `scenario_status` (`CHANGED` or `UNCHANGED`), `reference_kind` (`PUBLISHED_BASELINE` or `SAME_RUN_NAIVE`), `candidate_rate` and `reference_rate` (`passed`, `tries`), `result` (`PASS`, `FAIL` or `UNDECIDABLE`) and `reason`. The Markdown shows the same table. |

**Execution order.** The D12 recording and the comparator are benchmark-only
changes, implemented and tested before T196. The candidate HEAD therefore
already carries them when:
- T196 runs its gates;
- T197 qualifies the provider;
- T198 runs the full paired suite (`python -m bench --paired`, no `--only`),
  producing both arms for every task under one set of recorded fingerprints;
- T199 runs `python -m bench --sc012 <T198 artifact> --against
  bench/results/paired-baseline-2026-09-20.json`, publishes the result, and
  marks SC-012 only on `PASS`.

No new baseline run is required. The 2026-09-20 artifact is not rewritten; its
fingerprints are reconstructed from `be9cf6f`, which requires a full-history
checkout (the CI workflow already fetches with `fetch-depth: 0`).

**What this prevents.**
- A changed task compared with its old published rate: selection is by digest
  only.
- An excluded task: a missing arm or a shrunken task set is `UNDECIDABLE`.
- A manually chosen reference: no override exists.
- Fingerprints from a different commit: each report is read from itself or its
  own commit.
- A naive result under a different scenario: both arms and the fingerprint
  come from the same paired document and run.

**Gate for this work** (deterministic, no model, mutation-checked):
- `tests/test_bench_integrity.py`:
  - `fingerprint_at(commit)` on a temporary git repository equals
    `fingerprint_all` of the same tree;
  - an unresolvable commit raises;
  - `digest` is order-independent and changes when any fingerprint part
    changes.
- `tests/test_bench_baseline.py`, recording:
  - a paired report records a `scenario_fingerprint` per task equal to the
    run-start fingerprint;
  - one computation feeds both the checkpoint header and the report.
- `tests/test_bench_baseline.py`, reading:
  - a report whose tasks all carry `scenario_fingerprint` reads as
    `recorded`;
  - one without reads as `reconstructed:<commit>` through `fingerprint_at`;
  - one with neither is undecidable.
- `tests/test_bench_baseline.py`, comparison:
  - an unchanged task is compared with the published `current` rate;
  - a changed task with the same-run `naive` rate;
  - a task new to the candidate is CHANGED;
  - equal rates pass and a lower rate fails;
  - PASS only when every task passes;
  - each UNDECIDABLE condition is reported, and none can yield PASS;
  - every evidence field is present;
  - `--sc012` exits `0` / `1` / `2` and needs no provider.
- Mutations that must fail these tests:
  - selecting `PUBLISHED_BASELINE` for a changed task;
  - excluding a task whose reference is missing;
  - reading recorded fingerprints from one file and the baseline from another
    commit;
  - comparing with `>` instead of at least;
  - treating a candidate-only task as UNCHANGED.

### Constitution re-check (post-clarification, 2026-09-25)

| Principle | Result |
| --- | --- |
| IV — Deterministic regression tests | Comparator, reader and recording tested offline on fixtures and a temporary git repository; the listed mutations are required to fail. **PASS** |
| X / XII — Gates and agreement | Spec SC-012 (D10–D12), this section, research R17, data-model §9 and quickstart agree; tasks follow via `/speckit.tasks`. **PASS** |
| XIV — Evidence before assumption | The two changed scenarios were computed, not assumed; the rule is fingerprint-driven, not name-driven. **PASS** |
| XVIII — Extend, never duplicate | One fingerprint algorithm (`bench/integrity.py`), reused for recording, reconstruction and comparison; no new module (the standing benchmark-helper limit holds). **PASS** |
| XXI — Paired measurement | SC-011 unchanged; SC-012's reference for a changed scenario is the same-run paired arm, so quality is never compared across two decision functions. **PASS** |
| XX — User control | No run, push, merge or release is part of this planning; T197–T199 remain the owner's paid runs. **PASS** |

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
| **`decision_ref`** | **new** | the decision's stable semantic `ref` (not the turn-local `OpenDecision.id`), so an answer — live, or a later one — closes exactly that decision (plan §2026-09-24 Plan Convergence B) |

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
         payload: decision_ref, decision, candidates, evidence_consulted, reason, outcome
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

**Numbering**: the phases below are **plan phases (0–10)**. The executable task
list in [tasks.md](./tasks.md) uses its own **task phases**, and the two do not
coincide (plan Phase 5 = learning = tasks Phase 6; plan Phase 7 = the historical
benchmark phase = tasks Phase 9). Plan Phases 9 and 10 were added by the
2026-09-24 convergence; their task phases and task IDs are derived by
`/speckit.tasks`. The normative mapping is the crosswalk table at the top of
tasks.md; cross-artifact references use `plan Phase N` / `tasks Phase N`.

| Plan phase | Name | Delivers | Gate |
| --- | --- | --- | --- |
| **0** | Research | Resolve open technical unknowns → `research.md` | All unknowns resolved or explicitly deferred |
| **1** | Foundation & baseline measurement | Per-turn/per-task token record; benchmark extended with paired reporting; **naive full-resend baseline published** | Baseline exists; SC-036 satisfied; estimator validated against provider usage (test 16) |
| **2** | Grounded uncertainty contract | Evidence ledger on `ToolContext` (IP-1); the complete closed `EvidenceState` set from data-model.md §2; materiality test; **no user-visible change yet** | Tests 1, 2, 9; full suite green; zero behaviour change observable |
| **3** | Interactive clarification enforcement | IP-2 + IP-3; answered / cancelled-declined / expired / unattended clarification lifecycles; `clarification_required` outcome (FR-082 enforcement); additive protocol fields; renderer tests | Tests 3–8, 19; protocol codegen `--check` green; old client unaffected |
| **4** | Token accounting & context optimization | IP-5; budget manager, dedup, delta, references, log summarisation | Tests 14, 15, 17; **no outcome-rate fall vs Phase 1 baseline** |
| **5** | Progressive-learning hardening | IP-6; provenance, admission gate, supersession, fingerprint invalidation | Tests 10–13; caps unchanged |
| **6** | Cross-surface integration | IP-4 completion gate; CLI/API/ACP/Web/channel wiring of the clarification-required outcome (FR-082 surface wiring); docs; capability map; bundle rebuild (T141) | Surface impact table complete with evidence; the backward-incompatible FR-082 change is release-noted and the two additive visible changes are documented |
| **7** | Regression & performance benchmark (historical) | Full paired benchmark reports (tasks-phase-1 baseline T015; candidate run T155); the SC-011 threshold derived from them and recorded in spec.md (D5) | Paired reports published; threshold recorded. SC-011 and SC-012 acceptance moved to plan Phase 10 — both historical runs fail SC-011 |
| **8** | Full deterministic validation | Complete local/CI baseline on the integrated candidate, all three platforms | Every deterministic gate green; nothing claimed unverified |
| **9** | Specification convergence (D4/D7/D9 and re-verification) | Stable semantic `decision_ref` minted in the evidence owner; unresolved set derived from the existing session form records; common DecisionAnswer path in the application layer; additive protocol fields; CLI/API/ACP/channel adapters; D7 validation cases; re-verification of FR-099/100/101/105/127/018/123 (§2026-09-24 Plan Convergence B–D) | The §B gate: invalid refs fail closed before any model call, no heuristic path, stable and distinct refs, SC-042 replay, old clients unaffected; D7 cases green; every re-verification either passes or has become a task; protocol codegen, capability map and full deterministic suite green |
| **10** | Final live acceptance | Provider qualification, then a fresh comparable paired run on the exact frozen candidate, recording its scenario fingerprints; then the SC-012 comparison against the 2026-09-20 baseline (§G) | SC-011 (≤ 0.90 × naive mean total tokens **and** no task-level outcome-rate fall) has fresh passing evidence; SC-012 is `PASS` in the published `python -m bench --sc012` result, with every task compared against its fingerprint-selected reference (D10–D12) |

**Dependency note (plan-phase numbering)**: plan Phase 4 cannot start before
plan Phase 1 (no baseline, no optimization — Constitution XXI). Plan Phase 3
depends on plan Phase 2 (the ledger decides *when* to ask). Plan Phase 6 depends
on plan Phases 2–5. Plan Phase 9 follows the final specification review and
closes D4/D9 before any final provider acceptance; plan Phase 10 depends on
plan Phase 9 and on exact-head deterministic validation.

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
| CLI / Headless | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 9 | Today's no-listener behaviour pinned (T009); `comodor run --json` reports `stopped = "clarification_required"` with the nested `clarification` payload (T130, contracts §C3); distinct exit code 3 ≠ generic error/cancellation (T131); non-interactive blocking test (T044); `docs/cli.md` (T143); exact-`decision_ref` resumption via `comodor run --decision-answers` through `run_turn` (the global `--resume` is not reused); invalid refs and workspace or mode mismatches refused before any model call with exit `1` (plan Phase 9, §B, §B.1) |
| API / Protocols | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10; plan Phase 9 | Additive optional `QuestionField` properties and the negotiated clarification-required capability in `schemas/protocol/v2.json` (T046, T048); artifacts regenerated and `--check` green (T047, T164); old-client compatibility (T136); `api/server.py` maps the OpenAI-compatible envelope to standard `finish_reason: "stop"` while preserving the distinct Comodor state in `comodor.stopped` and `comodor.clarification` (T132); session bridge (T133); ACP (T134); capability honesty and mode authority (T138, T139); capability map (T140, T165); optional `decision_ref` on `ClarificationRequired` / `ClarificationDecision`, codegen, API `comodor.decision_answers` and ACP resumption (plan Phase 9, §B) |
| Desktop | NOT APPLICABLE | — | No desktop application/client exists: `docs/desktop-architecture.md` opens "Planned, not built. Nothing in this document exists in the repository"; there is no `src-tauri/`, `apps/desktop/` or desktop client package. The existing `src/comodor/desktop/` package is the computer-use **tool's** screen-capture/pointer backend (consumed by `tools/computer.py`, gated in `tools/registry.py`), not a client or runtime: it renders no questions and reads no turn outcome (it imports none of the question, clarification or turn-outcome machinery; its uses of the words "question" and "stopped" are prose and the guard's own `Stopped` refusal). As a tool it is covered by the permission gates (T011, T167), not by this row |
| Channels / Integrations | REQUIRED | plan Phase 3 / tasks Phase 3 (FR-121 blocking); plan Phase 6 / tasks Phase 8; plan Phase 9 | Non-interactive blocking applies to every channel (FR-121, T044); channel integrations under `src/comodor/channels/` report a needed decision instead of a result or a crash (T135); existing channel suites `tests/test_channel_service.py`, `tests/test_telegram.py`, `tests/test_slack.py`, `tests/test_whatsapp.py` stay green in T160; quickstart Web/channel checks; a later answer counts only as an explicit structured reply naming the `decision_ref`, routed through the common path; any other reply is a new request (plan Phase 9, §B) |
| Docker / Packaged Runtime | REQUIRED | plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10 | **Docker configuration unchanged; packaged runtime artifact REQUIRED and verified.** `Dockerfile` / `docker-compose.yml` are not edited by any task (T169 scope review); the packaged terminal-interface bundle that the wheel, sdist and container ship is affected by the TS changes and is rebuilt (T141) and verified to match source (T166); existing Docker/packaging/release validation stays green (T160, T168, T170 confirms no release action) |
| Persistence / Shared State | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 5 / tasks Phase 6; plan Phase 6 / tasks Phase 8; plan Phase 9 | Learning records gain provenance, status, fingerprint, supersession in `src/comodor/learning/store.py` (T099, T110, T111, T112, T117); session pending-interaction round-trip characterized (T007) and an outstanding form persisted/restored across reconnect with full lifecycle in transcript/export (`src/comodor/session/store.py`, T050, T051); pre-change sessions and stored knowledge remain readable (T137); ledger never persisted (T026); the unresolved-decision set is derived from the form records the session transcript already stores (`message.meta["question"]`) — no new store, and the ledger is still never persisted; a headless run persists only when it ends `clarification_required`, as a `SessionStore` continuation marked by the optional `SessionMeta.continuation` object (`decision_refs`, `mode`), written only on continuations and excluded from `list_sessions()`; a resumed run appends to it whatever it ends in (plan Phase 9, §B, §B.2) |
| Security / Authorization | REQUIRED | every task phase that touches questions, ASK, modes, tool advertisement, session interaction, orchestration or protocol | Permission and mode enforcement characterized first (T011, `tests/test_baseline_permissions.py`; T012 capability advertisement); per-phase permission regression gates T028, T060, T069, T098, T119, T129, T146 and final T167; unknown modes fail closed and advertised capabilities stay mode-authoritative (T138, T139); the ledger holds fingerprints, never secrets, and is never persisted (T026); clarification never becomes a route to a forbidden action (plan §Explicit non-goal) |
| Tests / Documentation | REQUIRED | all task phases; plan Phase 8 / tasks Phase 10 | Characterization suite T001–T013; mutation-checked regression tests for every guard (SC-025) across Phases 2–8; benchmark scenarios and integrity (T147–T158); `docs/questions.md` (T142), `docs/cli.md` (T143), `docs/learning.md` (T144); `CHANGELOG.md` unreleased note for the one backward-incompatible regression-by-design and documentation of the two additive visible changes in FR-082 (T145); full validation on the exact final HEAD, three platforms (T159–T170); benchmark provenance and the SC-012 comparator — per-task scenario fingerprints recorded in published paired baselines and a fingerprint-driven comparison (§G, D10–D12), tested offline |

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

**Plan Phase 9 (convergence) extends, and adds nothing new**:
`agent/evidence.py` (minted `ref` on `OpenDecision`), `tools/ask.py`
(`payload_for`, question `decision_ref`), `session/store.py` (the unresolved
set derived from stored form records; the optional `SessionMeta.continuation`
index, the listing filter and the exact ref lookup), `application/__init__.py`
(`run_turn`, the shared turn entry above `AgentLoop.run()`), its six callers
— `web/session.py` (`Session.send`), `CoreService.send`,
`CoreService._deliver_completions`, `cli.py` (`--decision-answers`),
`acp/agent.py`, `cron/runner.py` — `api/server.py` / `api/schema.py` /
`api/session_map.py`, `acp/agent.py`, `agent/background.py`, and
`schemas/protocol/v2.json` with its regenerated artifacts. No new module, store
or subsystem.

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
T169's scope review). No other new subsystem. The SC-012 provenance and
comparison work (§G) adds no benchmark file: it extends `integrity.py`,
`runner.py`, `report.py` and `__main__.py`. Every remaining change extends a
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
  one backward-incompatible regression-by-design in FR-082 is isolated to plan
  Phase 3 (enforcement) / Phase 6 (surface wiring) and release-noted; the two
  other intended visible changes are additive and documented.
  **PASS**
- **XXI (paired measurement)**: enforced structurally — plan Phase 4 (tasks
  Phase 5) cannot begin before plan Phase 1 (T015) publishes the baseline. **PASS**

**Gate result after design: PASS.** No unjustified complexity.

### Constitution Re-Check (post-convergence, 2026-09-24)

Re-evaluated against the converged plan and the specification at `d911e3f`.

| Principle | Check | Status |
| --- | --- | --- |
| I — Backward compatibility | Exactly one backward-incompatible change (FR-082 #1), release-noted. The new `decision_ref` fields and resumption inputs are optional, and `decisions[].id` is kept. `SessionMeta.continuation` is written only on continuations, so ordinary session files are unchanged and older readers skip continuations. The global `--resume` contract is untouched | **PASS** |
| III — Fix the invariant | The turn-local id is replaced as semantic identity by a minted `ref`, not patched with matching heuristics; no sleeps, timeouts or retries | **PASS** |
| IV — Deterministic regression tests | The ref minting function is injectable; every new guard (rejection classes, no-fallback, D7 cases) is mutation-checked | **PASS** |
| V — Narrow scope | Plan Phase 9 is limited to the spec's D4/D7/D9 deltas and the named re-verifications; no surface is moved onto `CoreService`; one function is added above the loop, and the six existing callers switch to it; delegate child loops are left as they are | **PASS** |
| VI — Boundaries and protocol contracts | Identity lives in the core evidence owner; cross-invocation resumption lives in `run_turn` (application), in-turn behaviour stays in `AgentLoop`; adapters only translate input; schema → codegen | **PASS** |
| VII — Reproducible artifacts | Generated protocol TS/Python regenerated; the committed terminal bundle is rebuilt only if TUI source changes | **PASS** |
| VIII — Security | A decision answer is caller input, validated before any tool; refs carry no secrets; mode policy is untouched; a continuation is bound to its workspace and mode and fails closed on a mismatch, so resumption can neither redirect mutations to another directory nor change mode; persistence follows the same redaction as any stored session | **PASS** |
| X — Quality gates | Full deterministic baseline plus exact-HEAD CI at the plan Phase 9 gate | **PASS** |
| XI — Surfaces | The spec owns the ten-row table; the Surface Impact table here mirrors its statuses and adds only implementation detail | **PASS** |
| XII — Done means everything agrees | data-model, contracts, quickstart and research updated with this plan (including the H1/H2/M1/L2 repair); tasks follow via `/speckit.tasks` | **PASS** |
| XIV — Evidence before assumption | The design rests on inspected code (§B facts); FR-127 is flagged as a probable gap rather than assumed done | **PASS** |
| XV — Interactive clarification | Only an explicit answer bound to its `decision_ref` resolves a decision; invalid input changes nothing; channels without a structured reply route report the decision instead of guessing | **PASS** |
| XVI / XXI — Token efficiency measured with quality | No context change in plan Phase 9; SC-011/SC-012 remain paired acceptance in plan Phase 10 | **PASS** |
| XVII — Progressive learning | Unchanged; a resumed answer is a `settled_decision` only when it is a real answer | **PASS** |
| XVIII — Extend, never duplicate | No new store, subsystem or matcher: the evidence owner, `SessionStore` (one optional meta field, a listing filter, an exact lookup) and existing request extensions are extended; `run_turn` removes the duplication six direct loop calls would otherwise force, while carrying `images` and delegate `decisions` through unchanged | **PASS** |
| XIX — Grounded tool use | Unchanged | **PASS** |
| XX — User control | No merge, tag, publish or deploy | **PASS** |

**Gate result after convergence: PASS.**
