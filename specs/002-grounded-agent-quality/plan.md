# Implementation Plan: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Branch**: `002-grounded-agent-quality` | **Date**: 2026-09-14, re-planned 2026-09-29 for D14–D17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-grounded-agent-quality/spec.md` (174 identifiers — 130 FR, 44 SC — of which FR-076, FR-077, SC-001, SC-011, SC-012, SC-021, SC-026 and SC-036 are retired by D14, leaving 166 active: 128 FR, 38 SC; 28 clarification decisions resolved through 2026-09-29)

---

## Summary

The specification's 166 active requirements (128 FR, 38 SC) map onto an existing product that already
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

**Testing**: `pytest` under `tests/` (`-n auto --dist loadfile`, `performance` marker excluded by default); Bun renderer tests for the terminal interface. Every test in an acceptance gate is deterministic and uses scripted model responses (`providers/fake.py`) wherever a model is involved; no gate calls a provider or needs a credential (D14; Constitution 2.0.0).

**Target Platform**: Windows, Linux, macOS — equally supported (Constitution II).

**Project Type**: Cross-platform terminal coding agent with a browser interface, a headless command line, an API/ACP protocol surface, channel integrations and a packaged container.

**Performance Goals**: No regression in the existing performance ceilings (`pytest -m performance`). Recall stays off the critical path between Enter and first token — the existing in-memory index exists precisely for that. Context assembly must not add a model call.

**Constraints**: No new runtime dependency. No change to the cached system-prompt prefix mid-task (worth ~99% prefix-cache retention, measured; larger than anything this feature could recover). Protocol v2 stays compatible; any addition is negotiated. Secrets never enter state, snapshots, journals, checkpoints, logs or fixtures.

**Scale/Scope**: 166 active requirements (128 FR, 38 SC) across the original 8 delivery phases, the convergence phase (plan Phase 9) and the acceptance-scope convergence (plan Phase 11, D14–D17). Estimated surface: ~11 Python modules extended, **one new product/runtime module** (`src/comodor/agent/evidence.py`), 1 schema addition, 1 shared TS package touched, the browser question surface (`src/comodor/web/`) characterized and verified, ~20 new deterministic test modules. Plan Phase 11 adds no module.

---

## Constitution Check

*GATE: evaluated before plan Phase 0 and re-evaluated after plan Phase 1 design (below).*

First checked against `.specify/memory/constitution.md` v1.1.0 on 2026-09-14.
Re-checked on 2026-09-29, before the D14–D17 design, against **v2.0.0** (21
principles), as amended in this pull request: Principle XXI, the context-change
gate and the Development Workflow rule now make every acceptance gate
deterministic, with scripted model responses and no provider calls or paid
tokens.

| Principle | Gate | Status |
| --- | --- | --- |
| I — Backward compatibility | FR-082 enumerates four intended user-visible changes. Only the removal of self-resolving mandatory non-answers is backward-incompatible/regression-by-design, and it is release-noted. Completion correction/annotation and same-decision re-raise suppression are additive. One form per decision point (D18, D19) removes no question. It is **breaking** for callers that count forms or script one entry per form, and it is release-noted with D19's migration path. D17 removes two settings that were never offered to a person; a configuration file that still carries either key keeps loading, because unknown keys are ignored (`config._apply`) | **PASS** — FR-082; plan Phase 3 (enforcement) / Phase 6 (surface wiring) — tasks Phase 3 / tasks Phase 8; plan Phase 11 (§G.3) |
| II — Three platforms | Every phase validated on the CI matrix; no platform-conditional logic introduced | **PASS** |
| III — Fix the invariant | No sleeps, no raised timeouts, no weakened assertions; clarification waiting uses the existing claim-and-expire primitive, not timing | **PASS** — see Clarification Architecture |
| IV — Deterministic regression tests | Every guard gets a mutation-checked test (SC-025), including the re-raise suppression SC-044 measures (§G.4) | **PASS** |
| V — Narrow scope | Bounded phases, including explicit D4/D9 convergence (plan Phase 9) and the D14–D17 acceptance-scope convergence (plan Phase 11), each independently validatable and revertable; plan Phase 11 adds no module, store or subsystem | **PASS** |
| VI — Architectural boundaries | Evidence ledger lives in the core; frontends render it. Protocol change goes through the schema and codegen, never hand-edited | **PASS** |
| VII — Reproducible artifacts | Terminal-interface bundle rebuilt and committed if TS changes | **PASS** — TS/TUI-affecting work lands in plan Phase 3 (clarification enforcement: protocol fields, overlay) and plan Phase 6 (surface wiring); the committed bundle rebuild is owned by T141 (tasks Phase 8), verified by T166; plan Phase 11 changes TUI source for D19 (T240), rebuilds the committed bundle, and re-runs the staleness check (§J) |
| VIII — Security not weakened | Mode policy untouched; clarification never becomes a route to a forbidden action; no secret enters the ledger; no gate needs a credential | **PASS** — explicit non-goal below |
| IX — Release infra is production code | No release action in this initiative at all; the lint path in the release workflow changes with the CI one and is proved by the same CI run | **PASS** — FR-084 |
| X — Quality gates mandatory | Full deterministic baseline per phase on the exact commit; every gate is deterministic and calls no provider | **PASS** |
| XI — Specifications name surfaces | `spec.md` owns the normative ten-surface table using REQUIRED / UNCHANGED BUT VERIFIED / NOT APPLICABLE; this plan mirrors it and adds implementation/task evidence without overriding it | **PASS** — the table below is a convergence view of the authoritative spec classification; Web UI is REQUIRED and the planned desktop application is NOT APPLICABLE |
| XII — Done means everything agrees | Phase not complete until implementation, tests, docs and evidence agree; plan Phase 11 ends with the neutral-wording sweep (§I, I-7) | **PASS** |
| XIII — Quality-first | The whole feature | **PASS** |
| XIV — Evidence before assumption | Evidence ledger is the mechanism; every retained criterion names its deterministic evidence (§G) | **PASS** |
| XV — Clarification a product invariant | Phases 2–3; non-interactive blocking implements XV directly | **PASS** |
| XVI — Token efficiency | Production token-usage accounting kept (§Production Token-Usage Accounting); optimizations accepted on deterministic tests of their mechanism (plan Phase 4 / tasks Phase 5, §G.2) | **PASS** |
| XVII — Progressive learning | plan Phase 5 (tasks Phase 6) | **PASS** |
| XVIII — Extend, don't duplicate | Audit below names the existing owner of every behaviour; one new product/runtime module total (`agent/evidence.py`), justified in Complexity Tracking | **PASS** |
| XIX — Grounded tool use | Evidence ledger + completion gate | **PASS** |
| XX — User control | No merge, tag, publish, deploy or provider call | **PASS** — FR-084, FR-085 |
| XXI — Quality and tokens measured together (2.0.0) | Acceptance is deterministic, with scripted model responses, and needs no provider calls or paid tokens (D14, D15); the context-change gate is met by the deterministic tests in §G.2; the feature claims no token reduction and no quality improvement; production accounting is kept | **PASS** |

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

### A. The four intended user-visible changes (FR-082)

| # | Change | Class | Requirements | Delivered by |
| --- | --- | --- | --- | --- |
| 1 | A mandatory clarification no longer resolves itself on a non-answer; non-interactive runs report `clarification_required` | **Backward-incompatible — the only regression-by-design**, release-noted | FR-019, FR-035, FR-121 to FR-123 | plan Phases 3 and 6 (implemented) |
| 2 | Completion claims are checked: unresolved work is annotated; a contradicted claim is corrected; an unsupported claim is never delivered as completed | **Additive** — adds a notice or correction, removes nothing a caller had | FR-036, FR-037, FR-124 to FR-127 | plan Phase 6 (implemented); FR-127's unsupported-claim rule re-verified in plan Phase 9 |
| 3 | A cancelled mandatory question is not re-raised within the same decision attempt | **Additive** — adds a report, removes nothing | FR-129 | plan Phase 3 (implemented) |
| 4 | Questions outstanding at one decision point arrive as one form, even when one model reply raises them through several calls (D18) | **Breaking for form-count and scripted consumers** — no question, answer or decision association is lost, but the number of forms and the moment each question is presented change; a multi-entry `--interactions` script must name its headers. Release-noted with D19's migration path | FR-014, SC-007, FR-079, SC-023 | plan Phase 11 (§G.5; not yet implemented) |

Everything else in this feature is compatibility-preserving: every protocol
addition is optional and negotiated (FR-080), and no existing message changes
meaning (FR-079), apart from the changes above. No fifth user-visible change is intended.

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
discovery. Validation measures SC-002 as narrowed by D16 — the clause that the agent
asks in 100% of attempts is model behaviour and is not claimed — per attempt,
never as a blanket "no write before asking" rule:

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
discovery with prior changes).

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

### E. FR-082 — the headless continuation is not a user-visible change

Headless later resumption is FR-129's own requirement, and its CLI
representation (`--decision-answers`) and the `decision_ref` fields are that
requirement's surface. The continuation that makes it safe is internal: it is
written only when a stateless run (`comodor run`, a scheduled job or a webhook
event) already ends needing a decision, it never
appears in any session list, UI or insights, it leaves the global `--resume`
contract untouched, and it leaves ordinary sessions' stored files unchanged. No
behaviour a user sees today changes beyond the FR-082 changes, so no
specification clarification is needed.

### F. Acceptance (D14–D16)

Acceptance is deterministic. It needs no model call other than scripted
responses, no paid tokens and no provider credential (D14;
Constitution 2.0.0, Principle XXI and the Development Workflow rule). It rests
on:

- the gates of §J, run on the exact final HEAD, on Windows, Linux and macOS;
- the per-criterion evidence of §G;
- the constitution's context-change gate, met by the deterministic tests of
  §G.2.

The retired identifiers — FR-076, FR-077, SC-001, SC-011, SC-012, SC-021,
SC-026, SC-036 and User Story 6 — are neither measured nor marked passed. The
feature claims no token reduction and no quality improvement. It keeps
production token-usage accounting (§Production Token-Usage Accounting).

### G. Retained success criteria and their deterministic evidence (D16)

Every retained criterion is measured by deterministic tests that use scripted
model responses. The counts are test functions at the PR #61 head `7361c50`
and come from the spec's D16 audit. Criteria outside that audit take their
evidence from the test modules that cite them at `7361c50`. Plan Phase 11
re-confirms every row on the final HEAD (§I, I-2). A row whose evidence covers
less than the criterion's wording has been narrowed in the spec (D16); it is
never claimed beyond its tests.

| Criterion | Deterministic evidence | Basis |
| --- | --- | --- |
| SC-002 | `tests/test_clarification_pause.py` (19, including the withheld-check mutation check and the three D7 cases); `tests/test_clarification_required.py` (6) | narrowed, D16 |
| SC-003 | `tests/test_claims.py` (11); `tests/test_baseline_loop.py::test_an_unverified_pass_claim_is_noticed_but_not_blocked` | narrowed, D16 |
| SC-004 | `tests/test_completion_assumptions.py`; `tests/test_evidence_decisions.py` (the assumption-path mutation check) | kept |
| SC-005 | `tests/test_questions_invariant.py` (property test, mutation-checked); `tests/test_questions_custom_answer.py`; `packages/questions` tests | kept |
| SC-006 | `tests/test_clarification_restraint.py` (10, including two mutation checks) | narrowed, D16 |
| SC-007 | `tests/test_clarification_one_form.py` (to be added, §G.5); one case fails today and is fixed in `agent/loop.py` | kept; test and fix required |
| SC-008 | Bun renderer tests (`apps/tui/test/bun/renderer.test.tsx`) at widths 160/120/100/80/60 | kept |
| SC-009 | `tests/test_clarification_persistence.py`; `tests/test_baseline_session.py` | kept |
| SC-010 | `tests/test_clarification_lifecycle.py` cases 7 and 8 and its ended-form reference tests | kept |
| SC-013 | `tests/test_context_no_superseded.py` (3, including the sweep mutation check); `tests/test_baseline_staleness.py` | narrowed, D16; §G.3 seam |
| SC-014 | `tests/test_context_recoverability.py`; `tests/test_overflow.py` | kept |
| SC-015 | `tests/test_context_stable_prefix.py`: the three head tests, including the read-once mutation check | narrowed, D16 |
| SC-016 | `tests/test_learning_corrections.py` | kept |
| SC-017 | `tests/test_learning_lifecycle.py`; `tests/test_learning_reuse.py` | kept |
| SC-018 | `tests/test_learning_admission.py` (31); `tests/test_learning_untrusted.py` (9), both with mutation checks | narrowed, D16 |
| SC-019 | `tests/test_learning_scope.py` | kept |
| SC-020 | `tests/test_learning_surfacing.py` | kept |
| SC-022 | the full gate set of §J | kept |
| SC-023 | `tests/test_protocol_backcompat.py`; `tests/test_clarification_protocol.py` | kept |
| SC-024 | `tests/test_persistence_backcompat.py`; `tests/test_baseline_session.py`; the configuration-compatibility test of §G.3 | kept |
| SC-025 | the mutation check of every guard in this table, SC-044 included | kept |
| SC-027 | `tests/test_context_recoverability.py`; `tests/test_context_no_validation_loss.py::test_a_failing_log_keeps_its_failure_under_every_setting` | kept; §G.3 seam |
| SC-028 | `tests/test_context_dedup.py` (14) | narrowed, D16; §G.3 seam |
| SC-029 | `tests/test_context_invalidation.py`: its three ledger tests | narrowed, D16 |
| SC-030 | `tests/test_context_budget.py` | kept |
| SC-031 | `tests/test_learning_recurring.py` (7, including the recurrence-guard mutation check) | measurement rewritten, D16 |
| SC-032 | `tests/test_learning_fingerprint.py`; `tests/test_learning_configuration.py` | kept |
| SC-033 | `tests/test_evidence_decisions.py`: its four confidence tests; `tests/test_failure_states.py`: its two low-confidence tests | narrowed, D16 |
| SC-034 | `tests/test_capability_honesty.py` (3) | narrowed, D16 |
| SC-035 | `python tools/capability-map.py --check`; `tests/test_capability_map.py` | kept |
| SC-037 to SC-040 | `tests/test_clarification_no_fabrication.py`, parametrised over the four non-answer outcomes, with a guard mutation check per outcome | kept, D16 |
| SC-041 | `tests/test_clarification_pause.py` (its dismissed-batch and turn-ends tests); `tests/test_clarification_lifecycle.py` cases 3 to 6 | kept, D16 |
| SC-042 | `tests/test_decision_resumption.py`; `tests/test_clarification_required.py::test_a_later_answer_in_the_next_turn_resumes_the_work` | kept, D16 |
| SC-043 | `tests/test_clarification_pause.py`: its independent-work and D7 tests | kept, D16 |
| SC-044 | **to be added** (§G.4) | kept, D16; test required |

#### G.1 FR-064

FR-064 keeps its first clause: learning can be switched off entirely. Evidence:
`tests/test_learning_switch.py`.

#### G.2 The context-change gate (Constitution 2.0.0)

The feature changes what is sent to a model through IP-5 (budget, dedup,
delta, ranking, summary provenance), log summarisation and the superseded-read
sweep. The gate is met by deterministic tests that run a scripted task and show
that no change omits evidence an answer depends on or weakens validation:

- `tests/test_context_optimization_neutrality.py`: the same scripted task
  delivers the same work with each optimization switched off;
- `tests/test_context_no_validation_loss.py`: failing evidence survives every
  setting, and forms are never deduplicated or withheld;
- `tests/test_context_recoverability.py`: nothing withheld is lost;
- `tests/test_context_no_superseded.py`, `tests/test_context_dedup.py`,
  `tests/test_context_stable_prefix.py`, `tests/test_context_budget.py`.

No token or quality claim is made beyond what these tests show.

#### G.3 D17 — the two settings are removed; tests switch optimizations off internally

**Runtime change** (behaviour-preserving for every configuration a person
could reach, because neither setting was ever offered):

- `AgentConfig` loses both fields.
- `agent/context.py`: `Optimizer.from_config` is removed. The
  `Conversation` default — every optimization on — is the product.
- `agent/loop.py`: the loop no longer overwrites `conversation.optimizer` from
  the configuration. `_maybe_compact` loses its alternative branch, so picture
  pruning, the superseded-read sweep and budget withholding always run.
- `tools/overflow.py`: the settings read is removed; log summarisation always
  runs.

**Test-internal seams** (no new production parameter, environment variable or
hidden setting):

- Optimizations inside the funnel: construct `Conversation(optimizer=
  Optimizer(enabled))` — the existing constructor parameter already used by
  `tests/test_context_budget.py` and `tests/test_context_dedup.py` — or assign
  `loop.conversation.optimizer = Optimizer(enabled)` after the loop is built.
  `OPTIMIZATIONS` stays the named inventory the tests iterate.
- Log summarisation: switched off inside a test by monkeypatching the
  module-level summariser in `tools/overflow.py`.

**Tests migrated to the seams**:

- `tests/test_context_no_superseded.py` (the setting at ~92);
- `tests/test_context_no_validation_loss.py` (~46–47, ~120);
- `tests/test_context_optimization_neutrality.py` — its settings-driven tests.

**Compatibility test (added)**: a configuration file that still carries either
key loads without error, and the key has no effect, because `config._apply`
ignores unknown keys (Constitution I; SC-024).

**Mutation sensitivity is kept**: each migrated test still fails when its guard
is removed, and still passes when the guard is restored.

#### G.4 SC-044 — cancelled mandatory question, not re-raised in the same attempt

**The guards**, as found at `7361c50`. A decision attempt is the turn that
raised the form. After a non-answer, the turn ends `clarification_required`
once the current batch finishes, so a repeat can only come from a sibling call
in that same batch. Two independent layers stop it:

1. `agent/loop.py::_withheld_by` withholds every non-read-only call, `ask`
   included, while a decision is `unresolved`, `blocked` or `asked`.
2. `tools/ask.py::AskTool.run` returns `_unresolved(..., repeated=True)`
   without posting a form when a question matches (`_same`) a material
   decision already `unresolved` or `blocked`.

A probe at `7361c50` showed that disabling `_same` alone leaves one form in a
loop-level batch, because layer 1 withholds the sibling first. A single-layer
mutation is therefore not decisive at loop level, and the test is built per
layer.

**Required tests**, extending `tests/test_clarification_lifecycle.py` with its
existing scripted `Script` provider and controlled `EventBus`. Each case
cancels with `forms.CANCELLED` — a cancellation, not a decline.

- **Tool level (layer 2).**
  - Steps: `Ask().run` is answered `CANCELLED`; `Ask().run` is then called
    again for the same question, varied only in case and whitespace.
  - Asserts: exactly one form; the second result is the unresolved report
    ("asked again"), with outcome `cancelled` and the same `decision_ref`; the
    decision stays `UNRESOLVED`.
  - Mutation: with `_same` monkeypatched never to match, a second form appears
    and the test fails. Restored, it passes.
- **Loop level (the layers together, and whatever T218 adds).**
  - Steps: one model batch holds `ask` X and a sibling `ask` X′ (the same
    question), followed by a dependent write; the first form is cancelled.
  - Asserts:
    - exactly one form for X reaches the bus;
    - the dependent write does not run;
    - the turn ends `clarification_required`, with outcome `cancelled` and the
      same `decision_ref`;
    - the scripted provider is not called again in that turn.
  - Mutation: with every repeat-preventing layer disabled at once, a second
    form appears and the test fails. Each layer's own mutation is also
    asserted: disabling any one layer alone still yields one form. That
    records that the layers are independent.

**Scope**:

- The attempt boundary is already covered by
  `test_a_later_explicit_request_raises_the_same_decision_with_the_same_ref`
  and `tests/test_decision_resumption.py`. After an explicit user resumption,
  the decision is raised or resolved again under the same `decision_ref`.
- A declined-only variant does not satisfy SC-044 (D16). If one is added, it is
  asserted separately.

#### G.5 SC-007 — one form per decision point (U-1)

**Finding.** No test covered SC-007. The previous coverage note ("the `ask`
tool is already one call for the whole set") holds for one `ask` call only. A
probe at `7361c50` found:

| Case | Forms |
| --- | --- |
| one model batch, two `ask` calls for two decisions, first form **answered** | **2** — SC-007 is not met |
| same decision in two calls, first answered | 1 (`Ledger.settled`) |
| same decision, first cancelled | 1 (§G.4 layers) |

SC-007 is therefore testable, and it currently fails in one case. It is
neither narrowed nor retired. The work is:

- A deterministic test, `tests/test_clarification_one_form.py`, covers:
  - C1 — one `ask` with several questions;
  - C2 — two `ask` calls for two decisions in one batch;
  - C3 — the same decision twice;
  - C4 — cancellation;
  - C5 — an `ask` with a mutation whose scripted preflight finds another
    missing decision, in one batch;
  - C6 — successive model calls, where a new form at a new decision point is
    allowed.
- A fix in `agent/loop.py`, through the existing shared clarification path:
  all decisions a batch raises reach the person as **one logical form**, with no
  upper bound on its length (D19).
  - Clients page it in groups of at most four, and it is answered once.
  - The per-call input rule (`forms.MAX_QUESTIONS`, 4 per `ask` call) stays.
  - An invalid set of calls is refused atomically, with every sibling
    non-read-only call withheld.
  - Headers stay unique within the form, and every call gets its own result.
- Client paging: the Web page shows pages of at most four; the TUI shows its
  position in the form; neither is a protocol change.
- The OpenAI-compatible API and ACP have no live form. A decision point there
  ends in one clarification-required payload listing every decision, resumed
  through `decision_answers` keyed by `decision_ref`.
- Headless scripted interactions:
  - an entry matches its form by header, and headers are optional only in a
    single-entry script;
  - an `answer` without headers is valid only for a one-question form;
  - a bare `answer` (no `value`, no keyed `values`) is invalid on every form,
    and is rejected before the run starts, with exit `1`; no option is ever
    selected implicitly;
  - a keyed `answer` never fills omitted questions and never spreads one value;
  - an unmatched or leftover entry ends the run with exit `1` and a clear
    error.
- The same decision under two headers is shown once, under the first header,
  and each call is answered under its own header.
- D18 records the fix as FR-082's fourth intended user-visible change. It
  lists the preserved and changed behaviour, the per-form cap, the outcomes,
  and the deterministic coverage required across every existing client
  surface.

## I. Implementation sequence (plan Phase 11)

Each step leaves the full deterministic suite green before the next begins.
Nothing is committed, pushed or merged without the owner's instruction.

| Step | Work | Leaves green |
| --- | --- | --- |
| I-0 | Preflight: record HEAD; audit the worktree's uncommitted spec, plan and constitution changes; leave the owner's own checkout untouched | — |
| I-1 | SC-007 (§G.5): the test first, then the loop fix (D18, D19), then the client paging and the scripted-interaction matching. SC-044 (§G.4): the tool-level and loop-level tests with their mutation checks | `pytest -q`; Bun tests; bundle rebuilt |
| I-2 | Re-confirm every §G row on HEAD: run each named module, record the counts, and treat any gap as a finding | the named modules |
| I-3 | D17 (§G.3): remove the settings and branches; migrate the tests to the seams; add the configuration-compatibility test; re-run the context, overflow, loop and performance suites | `pytest -q`; `pytest -m performance -n 0 -q` |
| I-4 | Clean-up of tests, after the coverage rule (tasks Phase 22) | `pytest -q` |
| I-5 | Clean-up of files and configuration (tasks Phase 22) | ruff over `src tests tools`; `pytest -q` |
| I-6 | Comments, test prose, documentation and changelog (tasks Phase 22) | ruff; `pytest -q`; Bun tests |
| I-7 | Neutral-wording sweep, then the reviewer's checklist cleanup (T232, T233) | the reference gates, run from copies kept outside the tree |
| I-8 | Final gates (§J) on the exact final HEAD | §J |

Each step can be reverted on its own (Constitution V). I-3 and I-4 are
separate because I-3 changes runtime behaviour for no reachable configuration,
while I-4 removes only tests.

## J. Final verification gates

**Where**: run on the exact final HEAD, in a clean detached worktree with an
isolated virtual environment (`pip install -e ".[dev]"`, because
`comodor/_version.py` is generated at install time).

**Python**

```bash
python -m ruff check src tests tools
python -m pytest -q
python -m pytest -m performance -n 0 -q
python tools/capability-map.py --check
python tools/protocol-codegen.py --check
git diff --check
```

**Frontend**

```bash
npm ci
npm run lint && npm run typecheck && npm test && npm run build
bun test apps/tui/test/bun/renderer.test.tsx
bun test apps/tui/test/bun/orphan.test.ts
bun tools/build-tui-distribution.ts && git status --porcelain   # must print nothing
```

**Tree**

- the reference gate and the retired-ID gate, run from copies kept outside the
  tree, report nothing.

**CI**

- Every check of the workflow matrix — Windows, Linux and macOS — is green on
  the same exact SHA.
- No workflow reads a provider secret.

**Per-criterion evidence**: every §G row is re-run on the exact final HEAD, and
its result is recorded against its criterion. A criterion without passing
evidence blocks acceptance.

**Counts** are recorded, not predicted. At `7361c50`:

- `pytest -q`: 6110 passed, 49 skipped;
- `pytest -m performance -n 0 -q`: 36;
- `npm test`: 188; Bun renderer: 175; Bun orphan: 3.

The final `pytest -q` count falls by the removed tests and rises by the added
ones. The performance count must not fall, because no performance test is
removed.

**Owner's completion rule** (outside this plan's authority): after the owner
authorises the push, the review bot reviews the exact final PR HEAD. Nothing
here is merged, auto-merged or approved on the owner's behalf.

## K. Open issues and reviewer-owned cleanup

**Open issues**

- **U-1 — SC-007.** Resolved as a finding, not by narrowing: SC-007 is
  testable, and one case fails today (§G.5). The test and the fix are tasked.
  **U-5**: resolved by D18 and D19 (2026-09-29). One logical form per
  decision point, paged in groups of at most four, is FR-082's fourth intended
  user-visible change. It is breaking for form-count and scripted consumers,
  and it is release-noted with change 1 and D19's migration path.
- **U-2 — the spec's own wording.** The owner approved neutral wording for
  D14–D17 on 2026-09-29, with no remaining references, and T232 applied it.
- **U-3 — task history.** D14 says completed task history is not rewritten,
  and that the final tree carries no reference. This plan reads that as:
  - retired tasks become ID-only stubs;
  - completion marks on tasks that remain are not changed;
  - Git history is the record.

  The owner confirms this reading.
- **U-4 — the constitution checklist item.** Resolved: the reviewer
  re-judges it, like every checklist item, from the file contents at the time
  of judging — the constitution text in the tree — not from commit or push
  state.

**Reviewer-owned checklist cleanup**: done by the reviewer at T233, which
re-judges every item from the files' contents.

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

**Acceptance is deterministic.** Each optimization is accepted on tests that
exercise its mechanism with scripted model responses and show that it neither
omits evidence an answer depends on nor weakens validation (Constitution 2.0.0,
context-change gate; §G.2). The column "What it avoids resending" describes each
mechanism's purpose, not a measured saving: this feature claims no token
reduction (D14).

| # | Optimization | Exists? | What it avoids resending | Information at risk | What prevents correctness loss | Invalidation | Test |
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

**Accounting rule.** Token figures come from providers' reported `usage`
(already carried on every reply and already used to calibrate the counter); the
estimator is used only where a provider reports nothing, and is marked as an
estimate. No figure is presented as a saving (Constitution XXI).

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

## Production Token-Usage Accounting

Kept unchanged by D14 (Constitution XVI, XXI; FR-072 to FR-075). It is product
behaviour:

- `agent/tokens.py` — `TurnRecord` per provider call (input, output, cached and
  cache-written tokens, context size, whether estimated) and `TaskMeasurement`
  per task (turns, tool calls, retries, clarifications raised and answered,
  corrections, knowledge hits and stale items, preflight calls and tokens,
  outcome, validation outcome).
- `comodor run --json` carries `usage` and `measurement` beside the outcome.
- The brain's episode record keeps `measurement`; `insights.py` aggregates it
  locally.
- Rules: provider-reported figures are the truth, the estimate is labelled;
  no credential in any field (FR-074); nothing leaves the machine unless the
  user chooses (FR-075).

Deterministic evidence: `tests/test_token_accounting.py`,
`tests/test_baseline_tokens.py`, `tests/test_metrics_locality.py`,
`tests/test_metrics_overhead.py`, `tests/test_metrics_redaction.py`,
`tests/test_insights.py`.

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
| 17 | Optimization does not change results | Scripted task delivers the same work with each optimization switched off inside the test (§G.3 seam); failing evidence survives every setting | 4, 11 |
| 18 | Permissions intact | Existing permission suite unchanged and green | every phase |
| 19 | Renderer behaviour deterministic | Bun renderer tests at widths 160/120/100/80/60 | 3 |
| 20 | A cancelled mandatory question is not re-raised in the same attempt (SC-044) | Scripted `ask` twice in one turn; controlled bus cancels the first; assert one form, the unresolved report, no dependent write; mutation-checked (§G.4) | 11 |

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
| `agent/`, `learning/`, `tools/`, `session/`, `providers/`, `questions.py`, `schemas/protocol/`, `packages/` | `src/comodor/trading/` only | **None** |
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
coincide (plan Phase 5 = learning = tasks Phase 6). Plan Phase 9 was added by
the 2026-09-24 convergence and plan Phase 11 by the 2026-09-28 acceptance-scope
decisions; their task phases and task IDs are derived by `/speckit.tasks`. Plan
Phases 7 and 10 are retired (D14). The normative mapping is the crosswalk table at the top of
tasks.md; cross-artifact references use `plan Phase N` / `tasks Phase N`.

| Plan phase | Name | Delivers | Gate |
| --- | --- | --- | --- |
| **0** | Research | Resolve open technical unknowns → `research.md` | All unknowns resolved or explicitly deferred |
| **1** | Foundation & token accounting | Per-turn/per-task token record; characterization suite | Estimator validated against provider usage (test 16) |
| **2** | Grounded uncertainty contract | Evidence ledger on `ToolContext` (IP-1); the complete closed `EvidenceState` set from data-model.md §2; materiality test; **no user-visible change yet** | Tests 1, 2, 9; full suite green; zero behaviour change observable |
| **3** | Interactive clarification enforcement | IP-2 + IP-3; answered / cancelled-declined / expired / unattended clarification lifecycles; `clarification_required` outcome (FR-082 enforcement); additive protocol fields; renderer tests | Tests 3–8, 19; protocol codegen `--check` green; old client unaffected |
| **4** | Token accounting & context optimization | IP-5; budget manager, dedup, delta, references, log summarisation | Tests 14, 15, 17, all deterministic with scripted responses |
| **5** | Progressive-learning hardening | IP-6; provenance, admission gate, supersession, fingerprint invalidation | Tests 10–13; caps unchanged |
| **6** | Cross-surface integration | IP-4 completion gate; CLI/API/ACP/Web/channel wiring of the clarification-required outcome (FR-082 surface wiring); docs; capability map; bundle rebuild (T141) | Surface impact table complete with evidence; the backward-incompatible FR-082 change is release-noted and the two additive visible changes are documented |
| **7** | *Retired (D14)* | — | — |
| **8** | Full deterministic validation | Complete local/CI baseline on the integrated candidate, all three platforms | Every deterministic gate green; nothing claimed unverified |
| **9** | Specification convergence (D4/D7/D9 and re-verification) | Stable semantic `decision_ref` minted in the evidence owner; unresolved set derived from the existing session form records; common DecisionAnswer path in the application layer; additive protocol fields; CLI/API/ACP/channel adapters; D7 validation cases; re-verification of FR-099/100/101/105/127/018/123 (§2026-09-24 Plan Convergence B–D) | The §B gate: invalid refs fail closed before any model call, no heuristic path, stable and distinct refs, SC-042 replay, old clients unaffected; D7 cases green; every re-verification either passes or has become a task; protocol codegen, capability map and full deterministic suite green |
| **10** | *Retired (D14)* | — | — |
| **11** | Acceptance-scope convergence (D14–D17) | Deterministic evidence confirmed for every retained criterion (§G); the SC-044 regression test (§G.4); D17's settings removed with test-internal seams (§G.3); clean-up (tasks Phase 22); the neutral-wording sweep and checklist re-judgement (§I, I-7) | §J on the exact final HEAD, all three platforms |

**Dependency note (plan-phase numbering)**: plan Phase 4 builds on plan
Phase 1's accounting. Plan Phase 3 depends on plan Phase 2 (the ledger decides
*when* to ask). Plan Phase 6 depends on plan Phases 2–5. Plan Phase 9 follows the
final specification review and closes D4/D9. Plan Phase 11 follows plan Phase 9
and its order is fixed in §I.

---

## Surface Impact

Canonical classification for this feature (Constitution XI). Exactly ten rows,
in canonical order; exactly one of the three allowed statuses per row. Every
REQUIRED row names at least one implementation/characterization task, at least
one validation task, and concrete file evidence. Phase references use the
[tasks.md crosswalk](./tasks.md) (`plan Phase N` / `tasks Phase N`).

| Surface | Status | Affected plan/task phases | Evidence / validation |
| --- | --- | --- | --- |
| TUI | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10 | Existing question overlay in `apps/tui/src/App.tsx` and the shared reducer in `packages/questions/src/index.ts` render the new optional `reason` / `evidence_consulted` (T052); deterministic keyboard/input behaviour and the custom-answer row characterized at widths 160/120/100/80/60 (T008) and re-run (T163); committed bundle rebuilt (T141) and verified against source (T166); frontend lint/typecheck/tests/build (T162) D18, D19: one logical form per decision point, paged in groups of at most four, answered once (T216, T218, T237, T239–T241). |
| Web UI | REQUIRED | plan Phase 1 / tasks Phase 1 (characterization); plan Phase 6 / tasks Phase 8 (wiring, verification); plan Phase 8 / tasks Phase 10 | Live browser question surface: `src/comodor/web/session.py` carries question forms to the page (`request.meta["questions"]`) and routes a dismissal as `CANCELLED` into `tools/ask.py`; `src/comodor/web/ui.js` renders options including the core-appended `free: true` row (`drawOwn`). Characterized before any change — question round-trip, option order, custom-answer row, single/multi-choice, header binding, current dismissal path (T006, `tests/test_web.py`); outcome wiring and regression — `clarification_required` never shown as completion, `clarification.outcome` preserved for cancelled/expired/unattended, dismissal ≠ turn cancellation, custom answer survives, no duplicate free row (T133); Phase 8 gate requires the Web clarification cases green alongside the permission suite (T146); full suite (T160) D18, D19: one logical form per decision point, paged in groups of at most four, answered once (T216, T218, T237, T239–T241). |
| CLI / Headless | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 9 | Today's no-listener behaviour pinned (T009); `comodor run --json` reports `stopped = "clarification_required"` with the nested `clarification` payload (T130, contracts §C3); distinct exit code 3 ≠ generic error/cancellation (T131); non-interactive blocking test (T044); `docs/cli.md` (T143); exact-`decision_ref` resumption via `comodor run --decision-answers` through `run_turn` (the global `--resume` is not reused); invalid refs and workspace or mode mismatches refused before any model call with exit `1` (plan Phase 9, §B, §B.1) D18, D19: one logical form per decision point, paged in groups of at most four, answered once (T216, T218, T237, T239–T241). |
| API / Protocols | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10; plan Phase 9 | Additive optional `QuestionField` properties and the negotiated clarification-required capability in `schemas/protocol/v2.json` (T046, T048); artifacts regenerated and `--check` green (T047, T164); old-client compatibility (T136); `api/server.py` maps the OpenAI-compatible envelope to standard `finish_reason: "stop"` while preserving the distinct Comodor state in `comodor.stopped` and `comodor.clarification` (T132); session bridge (T133); ACP (T134); capability honesty and mode authority (T138, T139); capability map (T140, T165); optional `decision_ref` on `ClarificationRequired` / `ClarificationDecision`, codegen, API `comodor.decision_answers` and ACP resumption (plan Phase 9, §B) D18, D19: a protocol v2 interactive client receives one live paged form, answered once. The OpenAI-compatible API and ACP return one clarification-required payload listing every decision, resumed through `decision_answers` keyed by `decision_ref`, in parts if needed (T216, T218, T237). |
| Desktop | NOT APPLICABLE | — | No desktop application/client exists: `docs/desktop-architecture.md` opens "Planned, not built. Nothing in this document exists in the repository"; there is no `src-tauri/`, `apps/desktop/` or desktop client package. The existing `src/comodor/desktop/` package is the computer-use **tool's** screen-capture/pointer backend (consumed by `tools/computer.py`, gated in `tools/registry.py`), not a client or runtime: it renders no questions and reads no turn outcome (it imports none of the question, clarification or turn-outcome machinery; its uses of the words "question" and "stopped" are prose and the guard's own `Stopped` refusal). As a tool it is covered by the permission gates (T011, T167), not by this row |
| Channels / Integrations | REQUIRED | plan Phase 3 / tasks Phase 3 (FR-121 blocking); plan Phase 6 / tasks Phase 8; plan Phase 9 | Non-interactive blocking applies to every channel (FR-121, T044); channel integrations under `src/comodor/channels/` report a needed decision instead of a result or a crash (T135); existing channel suites `tests/test_channel_service.py`, `tests/test_telegram.py`, `tests/test_slack.py`, `tests/test_whatsapp.py` stay green in T160; quickstart Web/channel checks; a later answer counts only as an explicit structured reply naming the `decision_ref`, routed through the common path; any other reply is a new request (plan Phase 9, §B) D18, D19: one logical form per decision point, paged in groups of at most four, answered once (T216, T218, T237, T239–T241). |
| Docker / Packaged Runtime | REQUIRED | plan Phase 6 / tasks Phase 8; plan Phase 8 / tasks Phase 10; plan Phase 11 | **Docker configuration unchanged; packaged runtime artifact REQUIRED and verified.** `Dockerfile` / `docker-compose.yml` are not edited by any task (T169 scope review); the packaged terminal-interface bundle that the wheel, sdist and container ship is affected by the TS changes and is rebuilt (T141) and verified to match source (T166); existing Docker/packaging/release validation stays green (T160, T168, T170 confirms no release action); plan Phase 11 leaves the wheel and container contents unchanged, the sdist ships fewer test modules, and the bundle staleness check is re-run (§J) D19 changes TUI source (T240), so the committed bundle is rebuilt and T234 checks that it is not stale. |
| Persistence / Shared State | REQUIRED | plan Phase 3 / tasks Phase 3; plan Phase 5 / tasks Phase 6; plan Phase 6 / tasks Phase 8; plan Phase 9 | Learning records gain provenance, status, fingerprint, supersession in `src/comodor/learning/store.py` (T099, T110, T111, T112, T117); session pending-interaction round-trip characterized (T007) and an outstanding form persisted/restored across reconnect with full lifecycle in transcript/export (`src/comodor/session/store.py`, T050, T051); pre-change sessions and stored knowledge remain readable (T137); ledger never persisted (T026); the unresolved-decision set is derived from the form records the session transcript already stores (`message.meta["question"]`) — no new store, and the ledger is still never persisted; a headless run persists only when it ends `clarification_required`, as a `SessionStore` continuation marked by the optional `SessionMeta.continuation` object (`decision_refs`, `mode`), written only on continuations and excluded from `list_sessions()`; a resumed run appends to it whatever it ends in (plan Phase 9, §B, §B.2) |
| Security / Authorization | REQUIRED | every task phase that touches questions, ASK, modes, tool advertisement, session interaction, orchestration or protocol | Permission and mode enforcement characterized first (T011, `tests/test_baseline_permissions.py`; T012 capability advertisement); per-phase permission regression gates T028, T060, T069, T098, T119, T129, T146 and final T167; unknown modes fail closed and advertised capabilities stay mode-authoritative (T138, T139); the ledger holds fingerprints, never secrets, and is never persisted (T026); clarification never becomes a route to a forbidden action (plan §Explicit non-goal) |
| Tests / Documentation | REQUIRED | all task phases; plan Phase 8 / tasks Phase 10; plan Phase 11 | Characterization suite T001–T012; mutation-checked regression tests for every guard (SC-025) across Phases 2–8 and 11, including the SC-044 test (§G.4); `docs/questions.md` (T142), `docs/cli.md` (T143), `docs/learning.md` (T144); `CHANGELOG.md` unreleased note for the one backward-incompatible regression-by-design and documentation of the two additive visible changes in FR-082 (T145), and of change 4 (D18; T231, T238); full validation on the exact final HEAD, three platforms (T159–T170, and §J for plan Phase 11); the retained-criterion evidence map (§G); the D14 clean-up and neutral-wording sweep across tests, CI configuration, documentation, the changelog and the Spec Kit artifacts (§I) |

Traceability rule: every plan phase that changes a surface is traceable to this
table — plan Phase 3 (TUI, CLI, API, Channels, Persistence, Security), plan
Phase 5 (Persistence), plan Phase 6 (TUI, Web UI, CLI, API, Channels, Docker /
Packaged Runtime, Persistence, Tests / Documentation), plan Phase 1 (Web UI
characterization, Tests), plan Phase 8 (Tests / Documentation), plan Phase 11
(Docker / Packaged Runtime, Tests / Documentation).

---

## Project Structure

### Documentation (this feature)

```text
specs/002-grounded-agent-quality/
├── plan.md              # This file
├── spec.md              # 174 identifiers; 166 active: 128 FR, 38 SC
├── research.md          # plan Phase 0 output
├── data-model.md        # plan Phase 1 output
├── quickstart.md        # plan Phase 1 output
├── contracts/           # plan Phase 1 output
│   ├── evidence-ledger.md
│   ├── clarification.md
│   └── learning-record.md
├── checklists/
│   ├── requirements.md
│   └── spec-gate.md
└── tasks.md             # NOT created by /speckit-plan
```

### Source Code (repository root)

Existing layout; this feature adds one product/runtime module and extends
eleven product modules.

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
there or call into it.

---

## Complexity Tracking

One product/runtime addition requires justification under Constitution XVIII.

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| New module `agent/evidence.py` | FR-001 requires classifying every consequential premise into one of its information-provenance categories, and the feature additionally requires a deterministic runtime lifecycle over the closed `EvidenceState` set (data-model.md §2). No existing module owns epistemic state: `claims.py` inspects answer text after the fact, `ToolContext.note_read` records only reads, and `learning/` is about durable knowledge across turns, not within one | **Extending `claims.py`** rejected: it is a post-hoc text inspector with a deliberately high firing bar; the ledger must be populated during the turn by tool results, and conflating them would make one module both a bookkeeper and a heuristic. **Extending `ToolContext`** rejected for the transition table only — the context *does* carry the ledger (IP-1), but a frozen-lifetime context object holding a state machine mixes transport with policy. **Reusing `learning/store.py`** rejected: durable cross-session knowledge and within-turn epistemic state have different lifetimes, different persistence rules (the ledger is never persisted) and different security properties |

No other new subsystem. Every remaining change extends a module that already
owns the behaviour, as recorded in the Architecture Audit.

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
  Phase 3 (enforcement) / Phase 6 (surface wiring) and release-noted; changes 2
  and 3 are additive and documented; change 4 (D18, D19, plan Phase 11) is breaking for form-count and scripted consumers, has a migration path, and changes the
  number of forms and when questions are presented, and is release-noted.
  **PASS**
- **XXI (2.0.0)**: every optimization is accepted on deterministic tests of its
  mechanism with scripted responses (§G.2); no token-reduction claim is made.
  **PASS**

**Gate result after design: PASS.** No unjustified complexity.

### Constitution Re-Check (post-convergence, 2026-09-24)

Re-evaluated against the converged plan and the specification at `d911e3f`.

| Principle | Check | Status |
| --- | --- | --- |
| I — Backward compatibility | Exactly one backward-incompatible change (FR-082 #1), release-noted. FR-082 #4 (D18, D19, added later) removes no question; it is named breaking for form-count and scripted consumers, and it carries a migration path and a release note. The new `decision_ref` fields and resumption inputs are optional, and `decisions[].id` is kept. `SessionMeta.continuation` is written only on continuations, so ordinary session files are unchanged and older readers skip continuations. The global `--resume` contract is untouched | **PASS** |
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
| XVI / XXI — Token efficiency measured with quality | No context change in plan Phase 9; acceptance is deterministic (D14, Constitution 2.0.0) | **PASS** |
| XVII — Progressive learning | Unchanged; a resumed answer is a `settled_decision` only when it is a real answer | **PASS** |
| XVIII — Extend, never duplicate | No new store, subsystem or matcher: the evidence owner, `SessionStore` (one optional meta field, a listing filter, an exact lookup) and existing request extensions are extended; `run_turn` removes the duplication six direct loop calls would otherwise force, while carrying `images` and delegate `decisions` through unchanged | **PASS** |
| XIX — Grounded tool use | Unchanged | **PASS** |
| XX — User control | No merge, tag, publish or deploy | **PASS** |

**Gate result after convergence: PASS.**

### Constitution Re-Check (post-design, D14–D17, 2026-09-29; against 2.0.0)

Re-evaluated after the plan Phase 11 design (§F–§K) and its research, data
model and quickstart revisions.

| Principle | Check | Status |
| --- | --- | --- |
| I — Backward compatibility | No protocol, session or learning format changes. D18/D19's one logical form is FR-082 change 4: named breaking for form-count and scripted consumers, with D19's migration path and a release note. Message shapes are unchanged. The two D17 settings were never offered, and a configuration file that still carries either one loads unchanged (§G.3 compatibility test). `comodor run --json` keeps `usage` and `measurement` | **PASS** |
| II — Three platforms | §J runs on Windows, Linux and macOS on the exact final HEAD | **PASS** |
| III — Fix the invariant | The SC-044 test pins the existing suppression; no sleep, timeout or retry is added; seams replace settings without weakening an assertion | **PASS** |
| IV — Deterministic regression tests | Every retained criterion maps to deterministic tests (§G). The SC-044 test is mutation-checked. Migrated tests keep their mutation checks | **PASS** |
| V — Narrow scope | Plan Phase 11 cleans up, re-confirms evidence, adds the one-form work and its tests, and sweeps wording; §I steps are separately revertable | **PASS** |
| VII — Reproducible artifacts | D19 changes TUI source (T240); the bundle is rebuilt and its staleness check is in §J | **PASS** |
| VIII — Security | No gate needs a credential; no workflow reads a provider secret; mode policy untouched | **PASS** |
| IX — Release infrastructure | The release workflow's lint path changes with CI's and is proved by the same run | **PASS** |
| X / XII — Gates and agreement | spec (D14–D17), constitution 2.0.0, this plan, research R18–R20, data-model §6 and the quickstart agree. Tasks follow via `/speckit.tasks`, checklist notes via `/speckit.checklist` (§K), and the sweep (I-7) leaves no reference behind | **PASS** |
| XIV — Evidence before assumption | Evidence names test modules and counts found in the repository; SC-007's missing evidence and failing case are reported (U-1, §G.5), not assumed | **PASS** |
| XVI — Token efficiency | Production token-usage accounting kept and tested | **PASS** |
| XVIII — Extend, never duplicate | No module, store or subsystem added; the seams reuse `Optimizer`'s existing constructor | **PASS** |
| XX — User control | No commit, push, merge, provider call or paid token in this planning | **PASS** |
| XXI — Quality and tokens (2.0.0) | Deterministic acceptance; the context-change gate is met by §G.2; no token-reduction or quality-improvement claim | **PASS** |

**Gate result after the D14–D17 design: PASS.** No unjustified complexity; four
open issues (§K) are recorded rather than resolved by assumption.
