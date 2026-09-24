---

description: "Dependency-ordered implementation tasks for the grounded high-quality agent"
---

# Tasks: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Input**: Design documents from `/specs/002-grounded-agent-quality/`

**Prerequisites**: [spec.md](./spec.md) (130 FR, 44 SC) · [plan.md](./plan.md) (6 intervention points) · [research.md](./research.md) · [data-model.md](./data-model.md) · [contracts/](./contracts/) · [quickstart.md](./quickstart.md) · `.specify/memory/constitution.md` v1.1.0

**Revision**: regenerated 2026-09-14 against the remediated specification. Closes every CRITICAL, HIGH and MEDIUM finding from the prior `/speckit.analyze`.

**Convergence (2026-09-24)**: reconciled against the final specification at `d911e3f` (specification quality gate 131/131) and the converged plan (plan Phases 9–10). Tasks T001–T171 keep their history and evidence. Wording that the final specification changed has been corrected in T009, T145, T155 and T156 (T156's own threshold-writing condition is now satisfied). T172–T207 are new: specification convergence (tasks Phases 12–17) and final acceptance (tasks Phase 18). They are derived from the converged plan as repaired after `/speckit.analyze` — one shared turn entry `run_turn` for all six application / surface turn-entry families, carrying `images` and delegate `decisions` through unchanged, a continuation bound to its workspace and mode, and a fresh vs resumed persistence lifecycle. Provisional task IDs drafted before the plan converged were not carried over.

**Tests**: Required, not optional. SC-025 mandates a deterministic, mutation-checked regression test for every guard.

## Format

```text
- [ ] T### [P?] [US#] Objective in `exact/path`
  - **Req** · **Dep** · **Evidence** · **Done when**
```

Token-optimization tasks additionally carry **Baseline · Metric · Invalidation · Correctness · Rollback**.
Learning tasks additionally carry **Provenance · Scope · Invalidation · Reject**.
Clarification tasks additionally carry **Materiality · Waiting · Outcomes · Dependent work**.

- **[P]** — parallelizable: different files, no dependency on an incomplete task
- **[US#]** — the spec user story served

## User story map

| Label | Story | Priority | Task phases |
| --- | --- | --- | --- |
| US1 | The agent asks instead of inventing | P1 | 2, 3 |
| US2 | "Done" means done, never claimed falsely | P1 | 7 |
| US3 | The same work costs materially fewer tokens | P2 | 4, 5 |
| US4 | It stops asking what it has already been told | P2 | 6 |
| US5 | When it cannot do the thing, it says so | P3 | 2, 7 |
| US6 | The improvement is measurable, not asserted | P3 | 1, 9 |

## Standing constraints

- **Extend, never duplicate.** One new **product/runtime** module only: `src/comodor/agent/evidence.py`. Benchmark-only helpers `bench/integrity.py` and `bench/baseline.py` are permitted by the plan ([plan.md §Complexity Tracking](./plan.md)) and must remain outside production runtime imports (`src/comodor/` never imports them — asserted by T154); no further benchmark helper without a new specification decision.
- **Never alter the cached prompt head** — `build_system_prompt` output stays byte-identical across turns within a task (FR-050, FR-091).
- **No release action of any kind** — no tag, workflow dispatch, publish or deploy (FR-084).
- **PR #39 is read-only** (FR-085); no unrelated work (FR-128).
- **No sleep-based correctness** in product or test (SC-025).
- **A mandatory clarification is never self-resolved** — cancel, decline, expiry and absence are lifecycle outcomes, never information outcomes (FR-018, FR-019, FR-022, FR-035, FR-129, FR-130).

## Plan-phase → task-phase crosswalk (normative)

Two phase numberings exist on purpose and **do not coincide**. [plan.md §Phasing](./plan.md) numbers the architecture/implementation plan **0–10**; this file numbers the executable task phases **1–18**. A bare `Phase N` in one artifact is ambiguous in another, so every cross-artifact reference is written as `plan Phase N` or `tasks Phase N`. Within this file, an unqualified `Phase N` below this table means a **task** phase. The mapping is derived from task contents, not from the numbers:

| Plan phase | Plan responsibility | Task phase(s) | Task IDs / notes |
| --- | --- | --- | --- |
| plan Phase 0 | Research — resolve or explicitly defer technical unknowns | *(none)* | Delivered as [research.md](./research.md). Its three deferred items are closed: T131 (CLI exit code `3`), T111 (fingerprint granularity), T156 (SC-011 threshold recorded in spec.md). R9–R14 record the convergence decisions |
| plan Phase 1 | Foundation & baseline measurement — characterization (including the Web UI question round-trip), per-turn/per-task token record, paired baseline | tasks Phase 1, tasks Phase 4 | T001–T015 (characterization — T006 covers the shared question flow **and the Web UI round-trip** in `tests/test_web.py`; naive strategy; T015 baseline) · T061–T069 (token record, metrics tests, learning switch, benchmark learning mode). The T015 hard gate is the plan Phase 1 → plan Phase 4 gate |
| plan Phase 2 | Grounded uncertainty contract — evidence ledger, materiality, escalation; no user-visible change | tasks Phase 2 | T016–T028 |
| plan Phase 3 | Interactive clarification enforcement — lifecycles, `clarification_required`, additive protocol fields, renderer tests, delegates | tasks Phase 3 | T029–T060. Protocol schema/codegen T046–T048 and the overlay TS change T052 live here; the resulting bundle rebuild is T141 (tasks Phase 8) |
| plan Phase 4 | Token accounting & context optimization behind IP-5 | tasks Phase 5 | T070–T098 (**token-efficient context**). Hard-blocked by T015. Not to be confused with tasks Phase 4 (observability), which belongs to plan Phase 1 |
| plan Phase 5 | Progressive-learning hardening — provenance, admission gate, supersession, fingerprint invalidation | tasks Phase 6 | T099–T119. Fingerprint granularity decision: T111. Not to be confused with tasks Phase 5 (token-efficient context) |
| plan Phase 6 | Cross-surface integration — IP-4 completion gate; CLI/API/ACP/Web/channel wiring of the clarification-required outcome; docs; capability map; bundle | tasks Phase 7, tasks Phase 8 | T120–T129 (**completion gate**) · T130–T146 (surfaces — T131 exit code, **T133 API and Web session bridges**, T141 bundle rebuild, docs, release note; **T146 gate requires the Web clarification cases green**) |
| plan Phase 7 | Regression & performance benchmark (historical) — paired reports, SC-011 threshold | tasks Phase 9 | T147–T158. T156 recorded the SC-011 threshold (D5); SC-011/SC-012 **acceptance** is T198/T199 in tasks Phase 18. Not to be confused with tasks Phase 7 (completion gate) |
| plan Phase 8 | Full validation on the exact final HEAD, three platforms | tasks Phase 10, tasks Phase 11 | T159–T170 (validation) · T171 (PR #39 read-only audit) |
| plan Phase 9 | Specification convergence — stable `decision_ref`, the shared turn entry `run_turn`, continuation binding and lifecycle, surfaces, D7, FR-127, re-verification | tasks Phases 12–17 | T172–T175 (identity and index) · T177–T179 (output and protocol) · T180, T200, T176, T181, T201 (shared turn entry) · T182–T189, T202–T207 (surface adapters and cross-surface proofs) · T190–T195 (D7, FR-127, security, re-verification, docs) · T196 (exact-HEAD gates) |
| plan Phase 10 | Final live acceptance on the exact frozen candidate | tasks Phase 18 | T197 (provider qualification) · T198 (SC-011) · T199 (SC-012) |

**Reading rule**: `plan Phase 5` = learning hardening = tasks Phase 6; `tasks Phase 5` = token-efficient context = plan Phase 4; `plan Phase 7` = benchmark = tasks Phase 9; `tasks Phase 7` = completion gate = plan Phase 6; `plan Phase 9` = convergence = tasks Phases 12–17; `plan Phase 10` = final acceptance = tasks Phase 18. A phrase such as "deferred to Phase 5" without a `plan`/`tasks` qualifier is non-conforming and must be read against this table.

---

## Phase 1: Baseline and Architecture Inventory

**Purpose**: pin current behaviour executably before anything changes. Characterization only — **no behaviour change in this phase**.

**⚠️ Hard gate**: tasks Phase 5 (token-efficient context; plan Phase 4) may not begin until T015 publishes the paired baseline (SC-036, Constitution XXI).

- [X] T001 [P] [US6] Characterize prompt-head stability in `tests/test_baseline_prompts.py`
  - **Req**: FR-050, FR-091, SC-015 · **Dep**: none · **Evidence**: assembled head byte-identical across three turns with differing recall · **Done when**: passes against unmodified `src/comodor/agent/prompts.py`
- [X] T002 [P] [US6] Characterize context assembly and compaction boundaries in `tests/test_baseline_context.py`
  - **Req**: FR-049, FR-051 · **Dep**: none · **Evidence**: `Conversation.render()` shape pinned; no orphaned tool call after `safe_cut`; original request always retained · **Done when**: current boundary rules are locked
- [X] T003 [P] [US6] Characterize token-estimator calibration in `tests/test_baseline_tokens.py`
  - **Req**: FR-055, SC-011 · **Dep**: none · **Evidence**: estimate vs recorded provider `Usage` within a tolerance constant that the test defines and justifies · **Done when**: tolerance is explicit, not implicit
- [X] T004 [P] [US6] Characterize superseded-read removal in `tests/test_baseline_staleness.py`
  - **Req**: FR-045, FR-046, SC-013 · **Dep**: none · **Evidence**: newest read and reads of unedited files are never rewritten · **Done when**: `src/comodor/agent/staleness.py` rules pinned
- [X] T005 [P] [US4] Characterize learning-cycle ordering and caps in `tests/test_baseline_learning.py`
  - **Req**: FR-063, FR-065 · **Dep**: none · **Evidence**: recall precedes storing the user message; at-cap add refuses and lists contents rather than evicting · **Done when**: ordering pinned
- [X] T006 [P] [US1] Characterize the shared question/ASK flow and Web UI question round-trip in `tests/test_baseline_questions.py` and `tests/test_web.py`
  - **Req**: FR-016, FR-017, FR-020, FR-021, FR-079, FR-082 · **Dep**: none · **Evidence (shared flow)**: `questions.py::_options()` appends the free row and strips model-authored escape hatches; answers match by header; single- and multi-choice both round-trip · **Evidence (Web UI, against the UNMODIFIED implementation, extending the existing authoritative suite `tests/test_web.py` rather than a new Web test subsystem)**: (1) a core question reaches the page intact through `src/comodor/web/session.py` (`request.meta["questions"]` on the pending-request payload); (2) option ordering survives transport; (3) the centrally appended `free: true` custom-answer row survives into the Web form as rendered by `src/comodor/web/ui.js` (`drawOwn`), and the page adds none of its own; (4) single-choice and multi-choice answers round-trip through `web/session.py` `decode_answers`; (5) answers bind by stable `header`, not by position; (6) today's dismissal path — the page answering `CANCELLED` into `tools/ask.py`'s current "sensible defaults" branch — is pinned exactly as it behaves now, so the plan Phase 3 change is measurable; (7) current browser behaviour is captured, not fixed · **Done when**: existing invariants locked for both the shared flow and the Web round-trip, with zero behaviour change in this phase
- [X] T007 [P] [US1] Characterize session pending-interaction round-trip in `tests/test_baseline_session.py`
  - **Req**: FR-023, FR-081, SC-024 · **Dep**: none · **Evidence**: snapshot with a pending question serialises and restores intact; fixtures written by the current version remain readable · **Done when**: reconnect path pinned
- [X] T008 [P] [US1] Characterize question-overlay rendering at widths 160/120/100/80/60 in `apps/tui/test/bun/renderer.test.tsx`
  - **Req**: FR-031, SC-008 · **Dep**: none · **Evidence**: free row visible and outstanding-question markers present at every width; full keyboard operability · **Done when**: all five widths pass
- [X] T009 [P] [US1] Characterize today's no-listener behaviour in `tests/test_baseline_headless.py`
  - **Req**: FR-033, FR-082, FR-121 · **Dep**: none · **Evidence**: record the current "choose sensible defaults, carry on" result as the documented **starting point for FR-082's backward-incompatible change 1** · **Done when**: the behaviour being removed is captured before removal
- [X] T010 [P] [US2] Characterize model-orchestration completion guards in `tests/test_baseline_loop.py`
  - **Req**: FR-038, FR-039, FR-040, FR-041, FR-043 · **Dep**: none · **Evidence**: project check runs once, only when a file changed, bounded, and an unrunnable check never converts a good turn into a failure · **Done when**: `_iterate` guards pinned
- [X] T011 [P] [US1] Characterize permission and mode enforcement in `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: none · **Evidence**: existing `tests/test_protocol_permissions.py` green; mode policy table read-only; unknown mode denies everything · **Done when**: this file becomes the per-phase permission gate referenced by T028, T060, T069, T098, T119, T129, T146
- [X] T012 [P] [US1] Characterize capability advertisement per mode in `tests/test_baseline_capabilities.py`
  - **Req**: FR-117, FR-118, FR-120 · **Dep**: none · **Evidence**: write tools are not advertised in plan mode; advertisement and enforcement both derive from `src/comodor/safety/modes.py` · **Done when**: current filtering pinned
- [X] T013 [P] [US6] Fingerprint every existing benchmark scenario in `bench/integrity.py`
  - **Req**: SC-026, FR-077 · **Dep**: none · **Evidence**: record a content fingerprint of each `bench/tasks/*/task.md`, `check.py` and `repo/` tree so later weakening is detectable · **Done when**: fingerprints stored and a check command reports any drift
- [X] T014 [US6] Implement the naive full-resend comparison strategy in `bench/baseline.py`
  - **Req**: SC-011, SC-036 · **Dep**: T003 · **Evidence**: resends full history, full file contents and full tool output every turn, selectable by flag · **Done when**: runs the existing suite end to end
- [X] T015 [US6] Publish the paired quality-and-cost baseline into `bench/results/` via `bench/report.py`
  - **Req**: SC-036, FR-076 · **Dep**: T003, T013, T014 · **Evidence**: per task — outcome rate over three attempts, input/output/cached tokens, model turns, tool calls — for both current and naive strategies · **Done when**: report exists and is cited by `spec.md` §SC-011 as the threshold source

**Checkpoint**: behaviour is executable, baseline published, nothing changed.

---

## Phase 2: Grounding and Uncertainty Contract

**Purpose**: the smallest shared mechanism separating resolved, unresolved-required, clarification-required and blocked. **Deliberately invisible** — no user-facing change.

- [X] T016 [US1] Write the evidence state-transition tests first in `tests/test_evidence_ledger.py`
  - **Req**: FR-001, FR-002 · **Dep**: none · **Evidence**: every legal transition in [data-model.md §2](./data-model.md) passes; every illegal one is rejected; a `DERIVED` entry resting on `UNKNOWN` is refused · **Done when**: tests exist and fail
- [X] T017 [US1] Create the ledger and its closed transition table in `src/comodor/agent/evidence.py`
  - **Req**: FR-001, FR-002, [contracts/evidence-ledger.md](./contracts/evidence-ledger.md) · **Dep**: T016 · **Evidence**: the complete closed `EvidenceState` set defined in [data-model.md §2](./data-model.md) — including `UNRESOLVED` — with its transition table; no model call, no network, no new dependency · **Done when**: T016 passes
- [X] T018 [US1] Carry the ledger on `ToolContext` in `src/comodor/tools/base.py`
  - **Req**: FR-001, plan IP-1 · **Dep**: T017 · **Evidence**: created and discarded with the turn; never serialised; existing `note_read` writes a `VERIFIED` entry · **Done when**: full suite unchanged
- [X] T019 [US1] Record `VERIFIED` entries from tool results in `src/comodor/agent/loop.py`
  - **Req**: FR-004, [contracts/evidence-ledger.md §E2](./contracts/evidence-ledger.md) · **Dep**: T018 · **Evidence**: read, search and shell each produce an entry with source and fingerprint; unclassifiable results stay `UNKNOWN` · **Done when**: no user-observable change
- [X] T020 [US1] Implement the materiality test against the closed FR-007 list in `src/comodor/agent/evidence.py`
  - **Req**: FR-007, FR-122 · **Dep**: T017 · **Materiality**: the eleven FR-007 classes, table-driven · **Evidence**: fixed decision table, each row classified; immaterial decisions never become `REQUIRES_CLARIFICATION` · **Done when**: classification is deterministic, not heuristic prose
- [X] T021 [US1] Confine agent discretion to non-material decisions in `src/comodor/agent/evidence.py`
  - **Req**: FR-130, FR-003, FR-011, FR-012, SC-004 · **Dep**: T020 · **Materiality**: material ⇒ assumption path unreachable · **Evidence**: mutation-checked — a decision passing the materiality test can never reach the assumption path; zero proceed-on-assumption cases involve a material decision; where readings compete the decision is treated as material · **Done when**: guard fails when removed
- [X] T022 [US1] Make the evidence-first duty mode-aware by reading `src/comodor/safety/modes.py`
  - **Req**: FR-009, FR-010, FR-032 · **Dep**: T020 · **Evidence**: with `may_use_read_tools=False` an empty `evidence_consulted` is accepted and no inspection claim is made; the mode table is read, never written · **Done when**: both modes covered
- [X] T023 [US5] Implement low-confidence escalation in `src/comodor/agent/evidence.py`
  - **Req**: FR-115, SC-033 · **Dep**: T020 · **Materiality**: low confidence on a material decision escalates to clarification · **Evidence**: four cases — (a) low confidence alone never licenses fabricated certainty; (b) material uncertainty raises a clarification; (c) non-material uncertainty is reported or handled by discretion; (d) **hedging language cannot substitute for escalation** · **Done when**: case (d) is mutation-checked
- [X] T024 [US5] Implement the insufficient-information outcome in `src/comodor/agent/evidence.py`
  - **Req**: FR-113 · **Dep**: T017 · **Evidence**: names what is missing; is not fabricated success, not a generic failure that hides the missing decision, and not a default assumption · **Done when**: all three negative forms are asserted against
- [X] T025 [P] [US5] Implement conflict and partial-access reporting in `src/comodor/agent/evidence.py`
  - **Req**: FR-069, FR-070 · **Dep**: T019 · **Evidence**: contradictory evidence surfaced rather than silently resolved; uninspected areas named · **Done when**: both cases tested
- [X] T026 [US1] Assert ledger security boundaries in `tests/test_evidence_ledger_boundaries.py`
  - **Req**: FR-074, [contracts/evidence-ledger.md §E4](./contracts/evidence-ledger.md), Constitution VIII · **Dep**: T018 · **Evidence**: mutation-checked — prompt head unchanged, entries hold fingerprints not content, ledger never persisted to snapshot/journal/checkpoint · **Done when**: guard restored after mutation
- [X] T027 [US1] Assert ledger failure degrades safely in `tests/test_evidence_ledger_resilience.py`
  - **Req**: FR-002, [contracts/evidence-ledger.md §E5](./contracts/evidence-ledger.md) · **Dep**: T017 · **Evidence**: an internal ledger error leaves entries `UNKNOWN` and never kills the turn · **Done when**: test passes
- [X] T028 **Permission regression gate — Phase 2** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 2 · **Evidence**: the existing permission suite is green after this phase, not only in Phase 10 · **Done when**: suite green on the phase commit

**Checkpoint**: ledger populated; **full test suite unchanged**. If behaviour moved, something was wired too early.

---

## Phase 3: Interactive Clarification

**Purpose**: enforce asking at material boundaries, forbid self-resolution on every non-answer path, and keep the agent from over-asking. Reuses the existing question transport.

### Option grounding and the custom-answer invariant

- [X] T029 [P] [US1] Property-test the custom-answer invariant in `tests/test_questions_invariant.py`
  - **Req**: FR-017, SC-005 · **Dep**: T006 · **Evidence**: adversarial forms where the model authors "Other", "None of the above", "Custom" — exactly one free row survives, appended centrally · **Done when**: mutation-checked
- [X] T030 [P] [US1] Test custom-answer entry and carry-back in `tests/test_questions_custom_answer.py` and `packages/questions/test/`
  - **Req**: FR-017, SC-005 · **Dep**: T006 · **Evidence**: free text reaches the tool result bound to that question's header, in both the Python decode path and the TS reducer · **Done when**: both covered
- [X] T031 [US1] Enforce grounded candidate options in `src/comodor/tools/ask.py`
  - **Req**: FR-015, FR-016 · **Dep**: T020 · **Evidence**: every option traces to user input, verified repository evidence, project configuration, trustworthy learned knowledge, or deterministic derivation; a model-invented alternative is rejected rather than presented as grounded · **Done when**: option provenance is checkable per option
- [X] T032 [P] [US1] Test the empty-candidate and invariant-preservation cases in `tests/test_questions_grounding.py`
  - **Req**: FR-015, FR-016, FR-017 · **Dep**: T031 · **Evidence**: an empty candidate list is permitted when no alternative can be grounded, and the mandatory custom-answer row is still appended centrally in that case · **Done when**: both cases pass

### When to ask, and when not to

- [X] T033 [US1] Wire the ask decision to the ledger's open decisions in `src/comodor/tools/ask.py`
  - **Req**: FR-008, FR-009, FR-013 · **Dep**: T020, T022 · **Materiality**: only FR-007 classes escalate · **Waiting**: the form is raised before any dependent mutating action · **Evidence**: an unsettled material decision raises a form; a settled one does not · **Done when**: both directions tested
- [X] T034 [P] [US1] Test anti-over-asking in `tests/test_clarification_restraint.py`
  - **Req**: FR-008, FR-011, FR-012, SC-006 · **Dep**: T033 · **Evidence**: **zero forms raised** when the question is settled by (a) repository evidence, (b) project configuration, (c) trustworthy learned knowledge, (d) safe implementation discretion, or (e) an established obvious default — measured in a mode permitted to inspect · **Done when**: all five cases pass; this guards against "never guess" regressing into "ask about everything"
- [X] T035 [US1] Test that clarification is never used for permission or plan confirmation in `tests/test_clarification_restraint.py`
  - **Req**: FR-011 · **Dep**: T033, T034 (same test file — not parallel with T034) · **Evidence**: no form asks to proceed or to have a plan confirmed back · **Done when**: mutation-checked

### The non-answer paths — no material decision may become an assumption

- [X] T036 [US1] Remove self-resolution from every no-answer path in `src/comodor/tools/ask.py`
  - **Req**: FR-019, FR-033, FR-035, plan IP-2, research R1 · **Dep**: T033 · **Outcomes**: all three report `stopped: "clarification_required"`, distinguished by `clarification.outcome` — cancelled/declined → `cancelled`; expiry → `expired` (recover the flag `bus.resolve()` already returns, currently discarded at `ask.py:170`); nobody listening → `unattended`. **`stopped: "cancelled"` is NOT used — it stays reserved for turn-level cancellation** · **Dependent work**: does not run under any of them · **Evidence**: the "choose sensible defaults, carry on" instruction is gone from **all** paths; presence read from the bus's `listening` · **Done when**: no path returns a result that lets the model supply the missing answer, and a dismissed question is never reported as a cancelled turn
- [X] T037 [US1] Add the `clarification_required` terminal state to `TurnResult` in `src/comodor/agent/loop.py`
  - **Req**: FR-123, plan IP-3, [contracts/clarification.md §C3, §C6](./contracts/clarification.md) · **Dep**: T036 · **Evidence**: `ok` is false; partial `steps`/`tool_calls` still reported; payload carries decision, candidates and `evidence_consulted`, plus the optional `prior_changes` when the turn changed files before the decision became known (contracts §C6) · **Done when**: distinguishable from both success and failure
- [X] T038 [US1] Make only a valid answer resume dependent work in `src/comodor/agent/loop.py` and `src/comodor/tools/ask.py`
  - **Req**: FR-018, SC-042 · **Dep**: T036 · **Waiting**: dependent work paused while outstanding · **Outcomes**: answer resumes; cancel/decline/expiry leaves unresolved or terminates · **Evidence**: replay test — an answer supplied after cancellation produces the same result as a first-time answer · **Done when**: cancellation demonstrably does not satisfy the information requirement
- [X] T039 [US1] Enforce zero fabricated values on all four non-answer outcomes in `tests/test_clarification_no_fabrication.py`
  - **Req**: FR-019, SC-037, SC-038, SC-039, SC-040 · **Dep**: T036 · **Evidence**: cancelled, declined, expired and unattended each assert no invented value, no option selected, no default applied, no assumption substituted — each independently mutation-checked · **Done when**: all four guards fail when removed
- [X] T040 [US1] Block dependent mutating actions after any non-answer outcome in `src/comodor/agent/loop.py`
  - **Req**: FR-018, SC-041, SC-043 · **Dep**: T038 · **Dependent work**: zero dependent writes, shell invocations or external calls **from the moment the dependency is open**; mutations completed before it became known are preserved and disclosed, not rolled back (contracts §C6) · **Evidence**: continued work is proven independent of the open decision; **uncertain dependency is treated as dependent** · **Done when**: mutation-checked
- [X] T041 [US1] Suppress re-raising a cancelled mandatory question in `src/comodor/tools/ask.py`
  - **Req**: FR-129, SC-044 · **Dep**: T036 · **Evidence**: zero repeat forms for a cancelled decision within the same decision attempt; the unresolved decision is reported instead; a later explicit user request may resume it · **Done when**: both halves tested
- [X] T042 [US1] Test the full lifecycle matrix in `tests/test_clarification_lifecycle.py`
  - **Req**: FR-018, FR-019, FR-022, FR-024, FR-025, FR-026, SC-010 · **Dep**: T036, T038 · **Outcomes**: eight separately-asserted cases — answered, unanswered, explicit cancellation, explicit decline/dismiss, expiry, unattended/no-listener, stale answer, duplicate answer · **Evidence**: each distinguishable in the reported outcome, asserted at the **transport layer** — clarification cancellation, decline, expiry and unattended each yield `stopped == "clarification_required"` with `clarification.outcome` of `cancelled`, `cancelled`, `expired` and `unattended` respectively; **turn cancellation still yields `stopped == "cancelled"`, and clarification cancellation never does**; **none of the seven non-answer cases resolves a material decision**; duplicates resolve through the existing atomic claim, not timing · **Done when**: all eight pass with no timing dependency, and the turn-vs-question cancellation assertion is mutation-checked
- [X] T043 [P] [US1] Test execution pause by state in `tests/test_clarification_pause.py`
  - **Req**: FR-013, FR-018, SC-002 · **Dep**: T038 · **Evidence**: asserted by state, never by timing — no mutating tool ran before resolution; independent work not blocked · **Done when**: deterministic with a controlled bus
- [X] T044 [US1] Test non-interactive blocking in `tests/test_clarification_required.py`
  - **Req**: FR-033, FR-121, SC-002 · **Dep**: T037 · **Evidence**: with no bus subscriber a material clarification ends the turn in `clarification_required` and **no invented value appears anywhere in the output** · **Done when**: mutation-checked
- [X] T045 [P] [US1] Test expiry observability in `tests/test_clarification_expiry.py`
  - **Req**: FR-027 · **Dep**: T042 · **Evidence**: expiry publishes its event so no client keeps showing a settled request; expiry is not an answer · **Done when**: no client left with a live card

### Protocol, persistence and surfaces of the interaction

- [X] T046 [P] [US1] Add optional `reason`, `evidence_consulted`, `decision_ref`, `outcome` and `prior_changes` to the question/clarification shapes in `schemas/protocol/v2.json`
  - **Req**: FR-080, FR-022, FR-035, research R8, [contracts/clarification.md §C1, §C2](./contracts/clarification.md) · **Dep**: none · **Evidence**: all optional; `outcome` constrained to `cancelled` \| `expired` \| `unattended`, carried in the clarification payload and never in the turn outcome; `prior_changes` is an optional array of bounded strings (contracts §C6); a client ignoring them behaves identically · **Done when**: schema edited at source only — generated files never hand-edited
- [X] T047 [US1] Regenerate protocol artifacts with `python tools/protocol-codegen.py` and verify `--check`
  - **Req**: FR-080, Constitution VI · **Dep**: T046 · **Evidence**: `src/comodor/protocol/_generated.py` and `packages/protocol/src/generated.ts` regenerate cleanly · **Done when**: `--check` green
- [X] T048 [US1] Register the clarification-required outcome capability in `schemas/protocol/v2.json` `x-capabilities`
  - **Req**: FR-080, SC-023, [contracts/clarification.md §C2](./contracts/clarification.md) · **Dep**: T046 · **Evidence**: a client not advertising it never receives the outcome · **Done when**: negotiation test proves an old client is unaffected
- [X] T049 [P] [US1] Populate `reason` and `evidence_consulted` on every raised form in `src/comodor/tools/ask.py`
  - **Req**: FR-034 · **Dep**: T046 · **Evidence**: the user is never asked to repeat inspection the agent already did · **Done when**: both fields present on every form
- [X] T050 [US1] Persist and restore an outstanding form across reconnect in `src/comodor/session/store.py`
  - **Req**: FR-023, SC-009 · **Dep**: T046 · **Evidence**: snapshot round-trip restores the pending interaction with its new optional fields · **Done when**: reconnect test passes
- [X] T051 [US1] Represent the full question lifecycle in transcript and export in `src/comodor/session/store.py`
  - **Req**: FR-030 · **Dep**: T042, T050 · **Evidence**: question text, grounded options, the custom-answer row, the user's answer, cancellation/decline, and final resolution state all appear correctly in session history and in exports, with secrets redacted · **Done when**: every one of the six elements is asserted
- [X] T052 [P] [US1] Render `reason` and `evidence_consulted` in the overlay in `apps/tui/src/App.tsx` and `packages/questions/src/index.ts`
  - **Req**: FR-031, FR-034, SC-008 · **Dep**: T046 · **Evidence**: renderer tests at all five widths; keyboard operability unchanged; **no timing dependency introduced** · **Done when**: renderer suite green
- [X] T053 [P] [US1] Test model switching during an outstanding form in `tests/test_clarification_model_switch.py`
  - **Req**: FR-028 · **Dep**: T042 · **Evidence**: the form survives; the answer applies to the work, not the model that raised it · **Done when**: test passes

### Delegated and background clarification

- [X] T054 [US1] Route delegate clarifications through the same mechanism in `src/comodor/agent/background.py`
  - **Req**: FR-029 · **Dep**: T036 · **Evidence**: a delegate's clarification reaches the same user-facing form via the existing `ScopedBus`, carrying origin/work attribution · **Done when**: attribution present and the mechanism is not duplicated
- [X] T055 [US1] Ensure a delegate clarification is never injected into another active turn in `src/comodor/agent/background.py`
  - **Req**: FR-029 · **Dep**: T054 · **Evidence**: completions and questions land at turn boundaries only; the parent's stream and cached prefix are untouched · **Done when**: mid-stream injection is asserted impossible
- [X] T056 [US1] Pause only the dependent delegated work in `src/comodor/agent/background.py`
  - **Req**: FR-029, FR-018 · **Dep**: T054 · **Dependent work**: the delegate that raised it pauses; siblings and the parent continue if independent · **Evidence**: asserted by state · **Done when**: independence proven per delegate
- [X] T057 [US1] Apply the anti-assumption rules to delegate clarifications in `src/comodor/agent/background.py`
  - **Req**: FR-029, FR-019, SC-037 to SC-040 · **Dep**: T054, T039 · **Outcomes**: identical to the parent's — no fabricated value on cancel, decline, expiry or absence · **Done when**: the four cases pass for a delegate-raised question
- [X] T058 [P] [US1] Test delegate clarification cancellation and reconnect in `tests/test_delegate_clarification.py`
  - **Req**: FR-029, FR-022, FR-023 · **Dep**: T054, T050 · **Evidence**: cancelling a delegate's question leaves its decision unresolved; a reconnect restores it with its origin intact; a crashed delegate is reported `lost`, never pretended alive · **Done when**: all three pass
- [X] T059 [P] [US1] Test clarification availability across modes in `tests/test_clarification_modes.py`
  - **Req**: FR-032, FR-010 · **Dep**: T022 · **Evidence**: every real mode may ask; a conversation-only mode asks without claiming it inspected the repository · **Done when**: both assertions pass
- [X] T060 **Permission regression gate — Phase 3** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 3 · **Evidence**: this phase changes questions, ASK behaviour, session interaction and protocol, so the permission suite is re-run and green here, not only in Phase 10 · **Done when**: suite green on the phase commit

**Checkpoint**: the agent asks when it must, never self-resolves a material decision, never over-asks, and old clients are unaffected.

---

## Phase 4: Token Observability

**Purpose**: measure before optimizing. Lightweight instrumentation that leaks nothing.

- [X] T061 [US3] Record per-turn input, output and cached tokens in `src/comodor/agent/tokens.py`
  - **Req**: FR-055, FR-072 · **Dep**: T003 · **Evidence**: provider-reported `Usage` is the source of truth; the estimator fills in only where a provider figure is absent · **Done when**: three figures separated per turn
- [X] T062 [US3] Aggregate per-task measurements in `src/comodor/agent/tokens.py`, surfaced via `src/comodor/insights.py`
  - **Req**: FR-072, FR-073 · **Dep**: T061 · **Evidence**: model turns, tool calls, retries, clarifications raised/answered, corrections, knowledge hits and stale rate recorded · **Done when**: aggregation reads records the product already writes
- [X] T063 [US3] Record assembled context size at the render funnel in `src/comodor/agent/context.py`
  - **Req**: FR-051, FR-072 · **Dep**: T002 · **Evidence**: recorded per request without a second render pass · **Done when**: gauge and request agree
- [X] T064 [US3] Test metrics redaction in `tests/test_metrics_redaction.py`
  - **Req**: FR-074 · **Dep**: T062 · **Evidence**: mutation-checked — no credential, no prompt body, no file content in any recorded field; counts, sizes and identifiers only · **Done when**: guard restored after mutation
- [X] T065 [P] [US3] Test measurement locality in `tests/test_metrics_locality.py`
  - **Req**: FR-075 · **Dep**: T062 · **Evidence**: this feature introduces no outbound transmission · **Done when**: no new network path exists
- [X] T066 [P] [US3] Bound instrumentation overhead in `tests/test_metrics_overhead.py` under the `performance` marker
  - **Req**: SC-022 · **Dep**: T062 · **Evidence**: recall stays off the critical path; no added model call; existing ceilings hold · **Done when**: `pytest -m performance` green
- [X] T067 [US6] Make learning explicitly switchable off in `src/comodor/config.py` and `src/comodor/learning/memory.py`
  - **Req**: FR-064 · **Dep**: T005 · **Provenance**: n/a — this governs whether admission runs at all · **Scope**: process-wide · **Evidence**: an explicit, documented switch; with learning off, no durable write occurs from any path including reflection and review · **Reject**: a silent or incidental disable is not acceptable · **Done when**: the switch is explicit, not inferred
- [X] T068 [US6] Make benchmark learning mode explicit and deterministic in `bench/runner.py`
  - **Req**: FR-064, SC-026 · **Dep**: T067 · **Evidence**: learning-enabled and learning-disabled benchmark modes are both selectable and both deterministic; **reproduction does not depend on undocumented incidental behaviour**; isolation of workspace and `COMODOR_HOME` asserted · **Done when**: two runs of the same mode produce the same measurement inputs
- [X] T069 **Permission regression gate — Phase 4** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 4 · **Evidence**: this phase touches agent orchestration; permission suite green here · **Done when**: suite green on the phase commit

**Checkpoint**: every benchmark figure is measurable; nothing sensitive is recorded; benchmark modes are explicit.

---

## Phase 5: Token-Efficient Context

**Purpose**: each optimization is its own task with baseline, metric, invalidation rule, correctness rule and rollback condition. All intervene behind `Conversation.render()` (plan IP-5). None may alter the cached head.

**⚠️ Hard gate**: blocked until T015 exists.

**Universal rollback** (applies to every task in this phase): if any benchmark task's outcome rate falls against the T015 baseline, revert the optimization. A saving never justifies an outcome loss (FR-044, SC-012).

**Universal correctness rule**: a cached, summarised, referenced or deduplicated representation **must never survive an invalidation event that makes it incorrect**.

- [X] T070 [US3] Implement the context budget manager in `src/comodor/agent/context.py`
  - **Req**: FR-096 · **Dep**: T015, T063 · **Baseline**: T015 per-turn context sizes · **Metric**: assembled tokens per turn · **Invalidation**: budget recomputed each turn; withheld set never carried across turns · **Correctness**: what was withheld is determinable and retrievable · **Rollback**: universal · **Done when**: budget respected on a fixed conversation
- [X] T071 [US3] Implement relevance ranking in `src/comodor/agent/context.py` reusing `src/comodor/learning/bm25.py`
  - **Req**: FR-097 · **Dep**: T070 · **Baseline**: T015 · **Metric**: assembled tokens per turn · **Invalidation**: ranking recomputed whenever the request, the working set or any ranked item's fingerprint changes; a stale ranking is never reused · **Correctness**: never removes the current request or an outstanding tool result; demoted material remains retrievable via T075 · **Rollback**: universal · **Done when**: fixed corpus yields a deterministic ranking
- [X] T072 [US3] Implement content-hash deduplication in `src/comodor/agent/context.py`
  - **Req**: FR-099, SC-028 · **Dep**: T070 · **Baseline**: T015 · **Metric**: duplicate bytes eliminated · **Invalidation**: **content change ⇒ new hash ⇒ new entry**; a hash is invalidated by source-file change, tool-output change, and branch or worktree state change · **Correctness**: identical content only; near-duplicates handled separately and conservatively · **Rollback**: universal · **Done when**: zero duplicate-bearing requests and a changed source never resolves to the stale copy
- [X] T073 [US3] Implement unchanged-content referencing in `src/comodor/agent/context.py`
  - **Req**: FR-101 · **Dep**: T072 · **Baseline**: T015 · **Metric**: retransmission avoided · **Invalidation**: a reference is invalidated when its target's fingerprint changes, when the file is edited, or when the branch/worktree moves; an invalidated reference resolves to a re-read, never to stale bytes · **Correctness**: a reference resolves to exactly the content it names · **Rollback**: universal · **Done when**: round-trip and invalidation both tested
- [X] T074 [US3] Implement delta context in `src/comodor/agent/context.py`
  - **Req**: FR-100 · **Dep**: T073 · **Baseline**: T015 · **Metric**: restatement avoided · **Invalidation**: a delta is invalid once its base is evicted or its base fingerprint changes; the full form is sent instead · **Correctness**: delta plus base reconstructs the original exactly · **Rollback**: universal · **Done when**: round-trip and base-evicted fallback pass
- [X] T075 [US3] Implement selective expansion in `src/comodor/agent/context.py`
  - **Req**: FR-098 · **Dep**: T073 · **Baseline**: T015 · **Metric**: detail not carried pre-emptively · **Invalidation**: expansion always reads current state, never a cached copy · **Correctness**: expansion returns the referenced content unchanged · **Rollback**: universal · **Done when**: expansion test passes
- [X] T076 [US3] Implement canonical summaries with provenance in `src/comodor/agent/context.py`
  - **Req**: FR-086, FR-102, SC-030 · **Dep**: T070 · **Baseline**: T015 · **Metric**: history bytes replaced · **Invalidation**: a summary is invalidated when any source it summarises changes; the original request is never summarised away · **Correctness**: every summary names what it replaced and from where · **Rollback**: universal · **Done when**: 100% of summaries carry provenance
- [X] T077 [US3] Implement evidence references in `src/comodor/agent/evidence.py`
  - **Req**: FR-103 · **Dep**: T019, T073 · **Baseline**: T015 · **Metric**: evidence bytes not resident · **Invalidation**: a citation is invalidated when the cited material's fingerprint changes or the underlying repository fact is superseded; the entry returns to `UNKNOWN` rather than citing stale evidence · **Correctness**: a citation always resolves to re-examinable material · **Rollback**: universal · **Done when**: invalidation path tested
- [X] T078 [US3] Implement bounded history in `src/comodor/agent/context.py`
  - **Req**: FR-049 · **Dep**: T002, T070 · **Baseline**: T015 · **Metric**: window occupancy · **Invalidation**: cut point recomputed per turn against the current outstanding-tool set · **Correctness**: no cut leaves a tool request without its result; original request preserved · **Rollback**: universal · **Done when**: orphaned-tool-call assertion passes
- [X] T079 [US3] Implement tool-result deduplication and compaction in `src/comodor/tools/overflow.py`
  - **Req**: FR-047, FR-089, SC-014 · **Dep**: T072 · **Baseline**: T015 · **Metric**: result bytes resident · **Invalidation**: a spilled pointer is invalidated if its backing file is pruned; the result then re-reports rather than pointing at nothing · **Correctness**: nothing discarded — head, tail and exact pointer; on-disk files pointed at in place, never copied · **Rollback**: universal · **Done when**: full recoverability proven
- [X] T080 [US3] Implement failure-preserving log summarisation in `src/comodor/tools/overflow.py`
  - **Req**: FR-090, SC-027 · **Dep**: T079 · **Baseline**: T015 · **Metric**: passing-log bytes eliminated · **Invalidation**: a summarised outcome is invalidated by any re-run of that command · **Correctness**: a passing run collapses to its outcome; **a failing run retains the failing case, its location and its message and is never reduced to a flag** · **Rollback**: universal · **Done when**: failure recoverable from the carried form in 100% of failing runs
- [X] T081 [US3] Implement diff-as-representation in `src/comodor/agent/context.py`
  - **Req**: FR-088 · **Dep**: T004, T070 · **Baseline**: T015 · **Metric**: file bytes avoided · **Invalidation**: a diff is invalidated by a further edit to the same path; superseded diffs follow the staleness rule · **Correctness**: the model sees the change that actually happened · **Rollback**: universal · **Done when**: correctness test passes
- [X] T082 [US3] Implement partial-file carriage in `src/comodor/agent/context.py`
  - **Req**: FR-087 · **Dep**: T075 · **Baseline**: T015 · **Metric**: file bytes resident · **Invalidation**: any write to the file invalidates the carried region · **Correctness**: withheld regions remain retrievable · **Rollback**: universal · **Done when**: retrieval of a withheld region works
- [X] T083 [US3] Implement incremental repository understanding in `src/comodor/agent/evidence.py`
  - **Req**: FR-104 · **Dep**: T019 · **Baseline**: T015 · **Metric**: repeat-discovery calls avoided · **Invalidation**: an accumulated fact is invalidated by a change to its source fingerprint, by a branch/worktree change, or by supersession of the underlying repository fact · **Correctness**: nothing is carried forward that a change has falsified · **Rollback**: universal · **Done when**: rediscovery count falls on a fixed multi-file task with no stale carry-forward
- [X] T084 [US3] Implement content-change invalidation of verified facts in `src/comodor/agent/evidence.py`
  - **Req**: FR-105, SC-029 · **Dep**: T083 · **Baseline**: T015 · **Metric**: redundant re-verification calls · **Invalidation**: **the source changing is the only cause; the passage of turns is not** · **Correctness**: a falsified fact returns to `UNKNOWN` rather than being relied upon · **Rollback**: universal · **Done when**: zero redundant re-verifications and zero stale reliances
- [X] T085 [US3] Carry project instructions once in a stable position in `src/comodor/agent/context.py`
  - **Req**: FR-091, FR-050, SC-015 · **Dep**: T001, T070 · **Baseline**: T015 prompt-head and per-turn sizes · **Metric**: restatement avoided; cache-hit rate from provider `Usage` · **Invalidation**: only a genuine instruction change invalidates, and never mid-task · **Correctness**: stable portion byte-identical across turns · **Rollback**: universal, plus revert if cache-hit rate falls · **Done when**: byte-identity assertion passes
- [X] T086 [US3] Reuse stored conversation on resume in `src/comodor/session/store.py`
  - **Req**: FR-095, FR-054 · **Dep**: T007, T070 · **Baseline**: T015 resume payload size · **Metric**: resume payload tokens · **Invalidation**: stored records are invalidated only by a newer record for the same message · **Correctness**: nothing re-derived; the resumed conversation is the stored one · **Rollback**: universal · **Done when**: resume sends no re-derived context
- [X] T087 [US3] Avoid verbatim restatement of established content in `src/comodor/agent/context.py`
  - **Req**: FR-052 · **Dep**: T073 · **Baseline**: T015 · **Metric**: restated bytes eliminated · **Invalidation**: the reference is invalidated if the established content is compacted away or changes · **Correctness**: a reference suffices only while the referent is still present and current; otherwise the content is re-sent · **Rollback**: universal · **Done when**: no verbatim restatement remains where a live reference exists
- [X] T088 [US3] Return delegate conclusions rather than read material in `src/comodor/tools/delegate.py`
  - **Req**: FR-053, FR-094 · **Dep**: T077 · **Baseline**: T015 on a delegate-using task · **Metric**: parent-conversation bytes attributable to delegate reading · **Invalidation**: the conclusion's supporting evidence references invalidate with their sources (T077) · **Correctness**: the conclusion travels with citations, so correctness-critical evidence stays recoverable · **Rollback**: universal · **Done when**: delegate reading does not persist in the parent
- [X] T089 [US3] Bound recalled-knowledge injection in `src/comodor/learning/memory.py`
  - **Req**: FR-092, FR-062 · **Dep**: T005 · **Baseline**: T015 recall block size · **Metric**: recall tokens per turn · **Invalidation**: recall recomputed per turn; stale and superseded items excluded · **Correctness**: the budget does not grow as the store grows · **Rollback**: universal · **Done when**: recall stays within the cap at 10× store size
- [X] T090 [US3] Avoid restating established content across repeated turns in `src/comodor/agent/context.py`
  - **Req**: FR-093 · **Dep**: T087 · **Baseline**: T015 multi-turn task · **Metric**: repeated-turn bytes · **Invalidation**: as T087 · **Correctness**: content established in an earlier turn is referenced, not repeated, and is re-sent if the reference dies · **Rollback**: universal · **Done when**: repeated-turn restatement eliminated on a fixed task
- [X] T091 [P] [US3] Verify zero superseded copies in `tests/test_context_no_superseded.py`
  - **Req**: FR-045, SC-013 · **Dep**: T004, T081 · **Evidence**: **zero superseded file copies present in any assembled request across a full benchmark run** · **Done when**: mutation-checked
- [X] T092 [P] [US3] Verify deduplication in `tests/test_context_dedup.py`
  - **Req**: FR-099, SC-028 · **Dep**: T072 · **Evidence**: zero duplicate-bearing requests; a changed source is never served from a stale hash · **Done when**: both assertions pass
- [X] T093 [P] [US3] Verify stable-prefix integrity in `tests/test_context_stable_prefix.py`
  - **Req**: FR-050, SC-015 · **Dep**: T085 · **Evidence**: zero mid-task changes to the stable portion · **Done when**: mutation-checked
- [X] T094 [P] [US3] Verify invalidation across every optimization in `tests/test_context_invalidation.py`
  - **Req**: FR-105, FR-101, FR-102, FR-103 · **Dep**: T072, T073, T076, T077, T083, T084 · **Evidence**: for each of content-hash change, source-file change, branch/worktree change, tool-output change, superseded repository fact and stale learned fact, assert **no cached or summarised representation survives the event** · **Done when**: all six events tested per applicable optimization
- [X] T095 [P] [US3] Verify evidence recoverability in `tests/test_context_recoverability.py`
  - **Req**: FR-044, FR-047, FR-090, FR-098 · **Dep**: T079, T080, T075 · **Evidence**: for every optimization, correctness-critical evidence remains recoverable — nothing is lost, only relocated · **Done when**: recoverability asserted per optimization
- [X] T096 [US3] Verify optimization neutrality in `tests/test_context_optimization_neutrality.py`
  - **Req**: FR-044, SC-012 · **Dep**: all of Phase 5 · **Evidence**: run the benchmark with each optimization toggled; **no task's outcome rate falls** · **Done when**: every Phase 5 task has a recorded paired comparison
- [X] T097 [US3] Verify no optimization weakens validation in `tests/test_context_no_validation_loss.py`
  - **Req**: FR-044 · **Dep**: all of Phase 5 · **Evidence**: no optimization suppresses a clarification, skips relevant inspection, or truncates critical evidence · **Done when**: mutation-checked
- [X] T098 **Permission regression gate — Phase 5** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 5 · **Evidence**: this phase changes agent orchestration and context assembly; permission suite green here · **Done when**: suite green on the phase commit

**Checkpoint**: tokens measurably lower, no outcome rate moved, every cache has an invalidation rule.

---

## Phase 6: Progressive Learning

**Purpose**: harden the existing learning subsystem. No second store, no raised caps.

- [X] T099 [US4] Add provenance columns in `src/comodor/learning/store.py`
  - **Req**: FR-057, [contracts/learning-record.md §L2](./contracts/learning-record.md) · **Dep**: T005 · **Provenance**: `provenance`, `source_ref`, `fingerprint`, `confidence`, `established_at`, `status`, `superseded_by` · **Scope**: existing project/user scope retained · **Invalidation**: columns carry what later invalidation needs · **Reject**: a record missing provenance is not storable · **Evidence**: additive migration; records written by the current version remain readable (FR-081, SC-024) · **Done when**: round-trip on pre-existing fixture data passes
- [X] T100 [US4] Implement the admission gate in `src/comodor/learning/memory.py`
  - **Req**: FR-056, [contracts/learning-record.md §L1](./contracts/learning-record.md) · **Dep**: T099 · **Provenance**: exactly the six admissible classes · **Scope**: set at admission · **Invalidation**: n/a at admission · **Reject**: anything whose only origin is an unverified model assertion · **Evidence**: the gate is the single entry point to durable storage · **Done when**: no caller can bypass it
- [X] T101 [US4] Route model-driven proposals through the gate in `src/comodor/learning/reflect.py` and `src/comodor/learning/review.py`
  - **Req**: FR-056, SC-018 · **Dep**: T100 · **Provenance**: a proposal is admissible only once corroborated into one of the six classes · **Reject**: uncorroborated proposals · **Evidence**: mutation-checked · **Done when**: reflection and review cannot write directly
- [X] T102 [P] [US4] Test refusal of unverified claims in `tests/test_learning_admission.py`
  - **Req**: FR-056, SC-018 · **Dep**: T101 · **Evidence**: after a full benchmark run with learning enabled, **zero items exist whose only origin is a model assertion** · **Done when**: mutation check confirms the gate is load-bearing
- [X] T103 [US4] Refuse untrusted content as durable knowledge in `src/comodor/learning/memory.py`
  - **Req**: FR-066, [contracts/learning-record.md §L5](./contracts/learning-record.md) · **Dep**: T100 · **Provenance**: untrusted text may become a `tool_confirmed` fact about *what a file contains*, never a belief about the world · **Scope**: unchanged · **Invalidation**: follows its source fingerprint · **Reject**: any item whose sole authority is text that appeared in retrieved content, a file, tool output, repository text or web content · **Evidence**: existing injection checks in `src/comodor/learning/facts.py` preserved · **Done when**: the distinction is enforced at the gate
- [X] T104 [US4] Test prompt-injection resistance of learning in `tests/test_learning_untrusted.py`
  - **Req**: FR-066, SC-018 · **Dep**: T103 · **Evidence**: instructional text embedded in a read file, a web page, a tool result and a channel message — each attempting to install a durable fact or rule — **cannot become durable learning without an independently admissible provenance signal**; each case mutation-checked · **Done when**: all four vectors refused
- [X] T105 [P] [US4] Capture corrections with provenance in `src/comodor/learning/signals.py`
  - **Req**: FR-109, SC-016 · **Dep**: T100 · **Provenance**: `user_correction` · **Scope**: project unless the correction is about the person · **Invalidation**: superseded by a later contradicting correction · **Reject**: a correction inferred rather than observed · **Evidence**: rewrite, undo and refusal each produce an item; detection stays deterministic with no model call · **Done when**: the correction is in force on the next turn without restatement
- [X] T106 [P] [US4] Capture settled decisions in `src/comodor/learning/memory.py`
  - **Req**: FR-109, SC-017 · **Dep**: T100, T042 · **Provenance**: `settled_decision` from an answered form · **Scope**: project · **Invalidation**: superseded by a later answer to the same decision · **Reject**: a decision that was cancelled, declined, expired or unattended — **an unresolved decision is never learned as settled** · **Evidence**: the same decision is not re-asked within the project · **Done when**: zero repeat forms for a settled decision and zero learned items from non-answers
- [X] T107 [US4] Learn project-specific terminology in `src/comodor/learning/rules.py` and `src/comodor/learning/store.py`
  - **Req**: FR-106 · **Dep**: T100 · **Admission signal**: the user's own repeated usage, or a definition counted from the repository · **Provenance**: `user_statement` or `counted_convention` · **Scope**: project only · **Persistence**: within the existing fact caps · **Retrieval**: relevance-ranked, status-filtered, inside the recall budget · **Supersession/invalidation**: superseded by a newer contradicting usage; stale when the source fingerprint changes · **Reject**: a term the model coined · **Evidence**: regression test in `tests/test_learning_terminology.py` · **Done when**: a term used consistently is applied without re-asking, and a redefinition supersedes it
- [X] T108 [US4] Learn stable architectural decisions in `src/comodor/learning/rules.py`
  - **Req**: FR-107 · **Dep**: T100 · **Admission signal**: a decision the user settled, or a structural convention counted across the repository · **Provenance**: `settled_decision` or `counted_convention` · **Scope**: project only · **Persistence**: within existing caps · **Retrieval**: as T107 · **Supersession/invalidation**: **marked stale when the structure it describes changes** (fingerprint mismatch) · **Reject**: a structure the model inferred from a single file · **Evidence**: regression test in `tests/test_learning_architecture.py` · **Done when**: moving the described structure invalidates the item
- [X] T109 [US4] Learn recurring instructions in `src/comodor/learning/signals.py`
  - **Req**: FR-108 · **Dep**: T100 · **Admission signal**: the same instruction given repeatedly across tasks · **Provenance**: `user_statement` · **Scope**: project or user, per the instruction's subject · **Persistence**: within existing caps · **Retrieval**: as T107 · **Supersession/invalidation**: superseded by a contradicting instruction · **Reject**: **a one-off instruction scoped to a single task is never made durable** · **Evidence**: regression test in `tests/test_learning_recurring.py` proving a repeated instruction is applied unasked while a one-off does not leak into later tasks · **Done when**: SC-031 satisfied
- [X] T110 [US4] Implement deterministic supersession in `src/comodor/learning/store.py`
  - **Req**: FR-059 · **Dep**: T099 · **Invalidation**: newer `established_at` governs; older retained with `superseded_by` set · **Reject**: silent deletion · **Evidence**: contradictory-correction test · **Done when**: no superseded item vanishes
- [X] T111 [US4] Implement fingerprint staleness at recall in `src/comodor/learning/memory.py`
  - **Req**: FR-060, FR-114, SC-032 · **Dep**: T099, research R5 · **Granularity (owned here, decided from evidence)**: research R5 deliberately defers whether a repository-derived item's fingerprint covers the whole source file or the specific region/rule it was counted from; this task makes that decision and no artifact pre-selects it · **Invalidation**: source fingerprint mismatch marks the item stale and excludes it · **Evidence**: the contradiction is surfaced rather than silently resolved; an answer already resting on it in that turn is corrected before completion · **Done when**: (1) real `src/comodor/learning/rules.py` observation shapes and the existing learning-record shapes in `store.py` have been inspected; (2) whole-file versus region/rule-level granularity is chosen from that evidence, not in advance; (3) the chosen granularity and its rationale are recorded in [data-model.md §5](./data-model.md) under `fingerprint`; (4) its invalidation implications are defined there — what change marks an item stale, and what change does not; (5) tests for the chosen granularity exist (a change inside the fingerprinted scope marks stale; a change outside it does not, where the granularity makes that distinction) and are mutation-checked · **Revised after review (repository-owner decision)**: for a counted convention the sample **membership is part of the evidence identity**, and the staleness check rebuilds the current bounded sample with the same deterministic sampler (a new, removed, renamed or changed eligible file is a manifest change) rather than rehashing only the recorded paths; a path-narrowed check uses the current sampler domain, so a newly added relevant path is not ignored · **Revised again after review 4042406579 (repository-owner decision, Option A)**: configuration-derived rules (`python.tests`, `python.lint`, `python.format`, `js.*`, `build.make`) carry their **own** evidence identity — a detector-specific configuration-source manifest (`rules.configuration_manifest`: detector, version, sorted candidate membership, per-source fingerprints; `source_ref = configuration:<detector>:<version>:<members>`) — never the source-code sample; a manifest mismatch re-runs the detector and the rule is refreshed or staled; the path-narrowed check routes a configuration path to the rules whose configuration domain contains it; rules persisted with the sample manifest under a configuration key are migrated or staled on the next check; the decision, rationale and invalidation implications are recorded in data-model.md §5 and regression-tested in `tests/test_learning_configuration.py` (25 cases, mutation-checked)
- [X] T112 [US4] Extend the curator with fingerprint staleness in `src/comodor/learning/curator.py`
  - **Req**: FR-112 · **Dep**: T111 · **Invalidation**: deterministic pass, nothing hard-deleted that the user did not ask to delete · **Evidence**: curator report lists fingerprint-stale items; they stay inspectable · **Done when**: report includes the new class
- [X] T113 [P] [US4] Test cross-project isolation in `tests/test_learning_scope.py`
  - **Req**: FR-058, SC-019 · **Dep**: T099 · **Evidence**: two project scopes; **zero cross-application** · **Done when**: mutation-checked
- [X] T114 [US4] Implement retrieval policy in `src/comodor/learning/memory.py`
  - **Req**: FR-110, FR-062 · **Dep**: T111 · **Retrieval**: relevance, scope, status exclusion, budget · **Evidence**: stale and superseded items never recalled; recall stays within the cap · **Done when**: recall-budget assertion passes
- [X] T115 [P] [US4] Surface provenance and status in `src/comodor/learning/journey.py` and `src/comodor/tools/memory.py`
  - **Req**: FR-061, FR-111, SC-020 · **Dep**: T099 · **Evidence**: every item listable with origin, scope and status, individually deletable; what was recalled into a turn is attributable afterwards · **Done when**: 100% coverage of stored items
- [X] T116 [US4] Assert learned knowledge never overrides current evidence in `tests/test_learning_vs_evidence.py`
  - **Req**: FR-114, FR-067 · **Dep**: T111, T084 · **Evidence**: where a learned item contradicts a freshly verified repository fact, the verified fact governs and the item is marked stale · **Done when**: mutation-checked
- [X] T117 [US4] Assert storage caps and at-cap behaviour in `tests/test_learning_caps.py`
  - **Req**: FR-065 · **Dep**: T099 · **Evidence**: reaching a cap produces an explicit refusal listing current contents; **never a silent eviction**; caps unchanged by this feature · **Done when**: refusal asserted
- [X] T118 [US4] Measure repeated-work efficiency in `tests/test_learning_reuse.py`
  - **Req**: FR-067, SC-021 · **Dep**: T105, T106, T114 · **Sequence**: the fixed **N = 6** comparable-task sequence in one project defined by SC-021 — tasks 1–3 the initial window, tasks 4–6 the learned window; the same sequence and the same metric definitions as T152 · **Primary metrics (SC-021)**: total mandatory clarifications raised per window; total user corrections received per window · **Secondary diagnostics**: repository rediscovery / knowledge-hit counts, reported but never substituted for either primary metric · **Evidence**: learned-window clarifications < initial-window clarifications **and** learned-window corrections < initial-window corrections **and** no task's outcome success regresses; a lower count produced by a skipped required question, a guess, reduced task quality or a weakened scenario is a failure; incomparable window inputs make the run invalid rather than passing · **Done when**: the fixed six-task sequence is measured with a deterministic fake provider and the first-three vs last-three comparison is produced for both primary metrics
- [X] T119 **Permission regression gate — Phase 6** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 6 · **Evidence**: this phase changes agent orchestration inputs; permission suite green here · **Done when**: suite green on the phase commit

**Checkpoint**: learning is provenanced, bounded, inspectable, injection-resistant and invalidating.

---

## Phase 7: Quality Completion Gate

**Purpose**: evidence-based completion. Annotate by default; block only a contradicted completion claim.

- [X] T120 [US2] Implement request-versus-delivery comparison in `src/comodor/agent/verify.py`
  - **Req**: FR-036, FR-037 · **Dep**: T019 · **Evidence**: requested elements matched against delivered work using ledger entries; unresolved elements named individually with what blocked each · **Done when**: a three-requirement request with two delivered names the third
- [X] T121 [US2] Extend the unverified-claim notice to unresolved work in `src/comodor/agent/claims.py`
  - **Req**: FR-005, FR-006, FR-124, SC-003 · **Dep**: T120 · **Evidence**: the existing four-condition firing bar preserved; hedged, negated and instruction sentences still do not fire; no new false positives on the existing fixture set · **Done when**: fixture set clean
- [X] T122 [US2] Implement the single blocking condition in `src/comodor/agent/loop.py`
  - **Req**: FR-125, FR-126 · **Dep**: T120 · **Evidence**: blocks only when the answer explicitly claims completion and evidence contradicts it; an honest partial answer is never withheld · **Done when**: both cases tested
- [X] T123 [US2] Bound blocking with an annotation fallback in `src/comodor/agent/loop.py`
  - **Req**: FR-127 · **Dep**: T122 · **Evidence**: at most one additional correction turn; a gate that cannot reach a verdict annotates rather than withholding indefinitely · **Done when**: fallback path tested
- [X] T124 [US2] Refuse completion while a required clarification is unresolved in `src/comodor/agent/loop.py`
  - **Req**: FR-013, FR-036, SC-041 · **Dep**: T037, T040 · **Dependent work**: none runs · **Outcomes**: the turn ends in `clarification_required` (with `clarification.outcome` naming which non-answer occurred), never `done` · **Evidence**: a turn with an open blocking decision cannot report success · **Done when**: mutation-checked
- [X] T125 [US5] Prevent a failed required tool call being reported as success in `src/comodor/agent/loop.py`
  - **Req**: FR-068, FR-116 · **Dep**: T024 · **Evidence**: the answer distinguishes what was established from what the failure left unknown; a failed validation is reported as failure with its evidence, never re-characterised, retried until green, or omitted · **Done when**: all three negative forms asserted against
- [X] T126 [P] [US2] Assert assumptions are stated and never material in `tests/test_completion_assumptions.py`
  - **Req**: FR-003, SC-004 · **Dep**: T021, T120 · **Evidence**: 100% of proceed-on-assumption cases are labelled as assumptions, and **zero involve a decision that passed the materiality test** · **Done when**: both halves asserted
- [X] T127 [P] [US2] Assert validation proportionality in `tests/test_completion_gate_proportionality.py`
  - **Req**: FR-042, FR-043 · **Dep**: T010, T120 · **Evidence**: a read-only turn triggers no project check; a turn touching one surface does not trigger unrelated validation · **Done when**: mutation-checked
- [X] T128 [P] [US5] Assert failure-state reporting in `tests/test_failure_states.py`
  - **Req**: FR-068, FR-069, FR-070, FR-113, FR-115, FR-116 · **Dep**: T023, T024, T025 · **Evidence**: tool failure, conflicting evidence, partial access, insufficient information, low confidence and failed validation each report the real limitation with no synthesised result · **Done when**: all six covered
- [X] T129 **Permission regression gate — Phase 7** via `tests/test_baseline_permissions.py`
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T011, all of Phase 7 · **Evidence**: this phase changes agent orchestration; permission suite green here · **Done when**: suite green on the phase commit

**Checkpoint**: "done" is truthful; an honest partial answer is never withheld.

---

## Phase 8: Cross-Surface Integration

**Purpose**: wire the outcomes to every affected surface. Backward compatibility preserved except for the single specified change.

- [X] T130 [US1] Report the clarification outcome in the headless JSON in `src/comodor/cli.py`
  - **Req**: FR-121, FR-123, [contracts/clarification.md §C3](./contracts/clarification.md) · **Dep**: T037 · **Outcomes**: `stopped: "clarification_required"` with `ok: false` and a `clarification` block carrying `outcome` (`cancelled` | `expired` | `unattended`); **`stopped: "cancelled"` is never emitted for a dismissed question — it keeps its turn-level meaning** · **Evidence**: partial `steps`/`tool_calls` preserved · **Done when**: output matches the contract, partial `steps`/`tool_calls` are preserved, and a **regression assertion** proves a dismissed clarification is not indistinguishable from the user cancelling the whole turn
- [X] T131 [US1] Assign a distinct non-zero exit code for an unresolved decision in `src/comodor/cli.py`
  - **Req**: FR-123, research R3 · **Dep**: T130 · **Evidence**: distinguishable from both the error exit code and success · **Done when**: the chosen code is documented in `docs/cli.md`
- [X] T132 [US1] Map the clarification-required outcome correctly in `src/comodor/api/server.py`
  - **Req**: FR-123, SC-023, [contracts/clarification.md §C4](./contracts/clarification.md) · **Dep**: T037 · **Evidence**: the OpenAI-compatible envelope uses **only standard `finish_reason` values** — a clarification-required turn maps to `finish_reason: "stop"` — while the distinct core state rides the existing `comodor` extension block (`comodor.stopped = "clarification_required"` and `comodor.clarification`, including `clarification.outcome`), so a standard OpenAI-compatible client that does not understand the extension retains its existing behaviour · **Done when**: a clarification-required turn is never reported as normal completion by a Comodor-aware client, and no OpenAI-compatible response Comodor emits contains a custom `finish_reason` value
- [X] T133 [P] [US1] Carry clarification outcomes through the API and Web session bridges in `src/comodor/api/session_map.py`, `src/comodor/web/session.py` and, only if proven necessary, `src/comodor/web/ui.js`
  - **Req**: FR-016, FR-022, FR-035, FR-079, FR-082, FR-121, FR-123 · **Dep**: T132, T006 · **Evidence (API bridge)**: the turn outcome, the nested `clarification.outcome` and the optional `prior_changes` (contracts §C6) all survive `api/session_map.py` intact and un-collapsed; bridge-level `timeout`/`busy` untouched · **Evidence (Web)**: first determine whether the page already consumes the corrected core outcome unchanged — if it does, change no Web source and add regression coverage only; if not, make the smallest change necessary. Regression cases in `tests/test_web.py` prove: (1) `stopped = "clarification_required"` is never rendered or interpreted as normal completion; (2) `clarification.outcome` survives unchanged for `cancelled`, `expired` and `unattended`; (3) a dismissed Web clarification is never confused with cancellation of the whole agent turn (`stopped = "cancelled"`); (4) the final custom-answer row remains present; (5) a manually entered custom answer survives the Web round-trip; (6) Web dismissal cannot make the model choose a default; (7) when the page/session disappears so nobody can answer a required material clarification, the core result is the approved `unattended` clarification-required outcome, never fabricated continuation; (8) existing answered-question behaviour stays backward compatible; (9) no Web code reimplements `questions.py::_options()` or appends its own duplicate free row · **Done when**: bridge test passes for all three clarification outcomes on the API bridge, and all nine Web cases pass with the Web UI recorded as verified in [plan.md §Surface Impact](./plan.md)
- [X] T134 [P] [US1] Handle the outcome in `src/comodor/acp/agent.py`
  - **Req**: FR-121, FR-035 · **Dep**: T037 · **Evidence**: structured outcome preserving `clarification.outcome`; no default selected · **Done when**: ACP test passes for all three clarification outcomes
- [X] T135 [P] [US1] Report a needed decision in channel integrations under `src/comodor/channels/`
  - **Req**: FR-121 · **Dep**: T037 · **Evidence**: a message naming the decision and which clarification outcome occurred (`cancelled`, `expired` or `unattended`); no invented value on any channel that runs turns · **Done when**: covered per channel
- [X] T136 [P] [US1] Test old-client compatibility in `tests/test_protocol_backcompat.py`
  - **Req**: FR-079, FR-080, SC-023 · **Dep**: T048 · **Evidence**: a client that negotiates no new capability behaves exactly as today; existing protocol conformance tests run unchanged; no existing message changes meaning · **Done when**: mutation-checked
- [X] T137 [P] [US1] Test pre-change persistence readability in `tests/test_persistence_backcompat.py`
  - **Req**: FR-081, SC-024 · **Dep**: T099 · **Evidence**: sessions and brain records written before the change remain readable after it, in 100% of fixture cases · **Done when**: fixture suite green
- [X] T138 [P] [US1] Test that a capability is never claimed when unavailable in `tests/test_capability_honesty.py`
  - **Req**: FR-120, SC-034 · **Dep**: T012, T022 · **Evidence**: **zero claims or attempts of a capability not advertised in the current mode**, across plan-mode and conversation-only tasks; the mode is reported as the reason when an action is unavailable · **Done when**: mutation-checked
- [X] T139 [P] [US1] Test that mode filtering stays authoritative in `tests/test_capability_authority.py`
  - **Req**: FR-117, FR-118 · **Dep**: T012 · **Evidence**: advertisement and enforcement derive from one rule in `src/comodor/safety/modes.py` and cannot disagree; a forbidden capability is never offered; **an unknown mode remains fail-closed**; **question capability does not imply any tool capability** · **Done when**: all four assertions pass
- [X] T140 [US1] Register any new capability and verify `python tools/capability-map.py --check`
  - **Req**: FR-119, SC-035 · **Dep**: T048 · **Evidence**: inventory regenerates from code, never hand-edited · **Done when**: `--check` green
- [X] T141 [US1] Rebuild and commit the terminal-interface bundle from `apps/tui/`
  - **Req**: FR-031, FR-078, SC-022 (Constitution VII governs artifact reproducibility) · **Dep**: T052 · **Evidence**: bundle reproducible from source; the build alters nothing outside its own path; the committed artifact is what installed users run on all three platforms · **Done when**: committed artifact matches its source
- [X] T142 [P] [US1] Update `docs/questions.md` for the new clarification semantics
  - **Req**: FR-030, FR-082 · **Dep**: T051 · **Evidence**: answered, cancelled, declined, expired and unattended documented with their outcomes; no stale "proceed with assumptions" claim remains · **Done when**: docs match implemented behaviour
- [X] T143 [P] [US1] Update `docs/cli.md` for the new outcome and exit code
  - **Req**: FR-082, FR-123 · **Dep**: T131 · **Evidence**: the exit code and JSON shape documented · **Done when**: documented
- [X] T144 [P] [US4] Update `docs/learning.md` for provenance, staleness and the learning switch
  - **Req**: FR-057, FR-064, FR-082 · **Dep**: T099, T067 · **Evidence**: provenance classes, invalidation and the off switch documented · **Done when**: documented
- [X] T145 [US1] State FR-082's backward-incompatible change (change 1) in the release notes source
  - **Req**: FR-082 · **Dep**: T130 · **Evidence**: "a material clarification can no longer be resolved by default, assumption or invented value when the required information was not supplied" — written as the sole behavioural regression-by-design. **No tag, release or publication is created by this task** · **Done when**: the note exists in `CHANGELOG.md` unreleased section
- [X] T146 **Permission regression gate — Phase 8** via `tests/test_baseline_permissions.py`, plus the Web clarification regression cases
  - **Req**: FR-019, FR-118, FR-079, FR-082, SC-022 · **Dep**: T011, T133, all of Phase 8 · **Evidence**: this phase changes protocol behaviour, session interaction and tool advertisement; the permission suite is green here; **and** the Web clarification regression cases owned by T006/T133 in `tests/test_web.py` are green on the same commit — permission tests are not replaced by Web tests, both must pass · **Done when**: permission suite green **and** Web clarification cases green on the phase commit; Phase 8 is not green while either fails

**Checkpoint**: every surface reports a needed decision truthfully; old clients unaffected.

---

## Phase 9: Benchmarks

**Purpose**: prove the claims with paired measurement. **Scenarios are never weakened to improve a score.**

- [X] T147 [P] [US6] Add the repository-settled-ambiguity scenario in `bench/tasks/careful-repo-settles-it/`
  - **Req**: SC-006, FR-008 · **Dep**: T034 · **Evidence**: the agent must read and decide, **not** ask; the judge scores a line whose correct value is a path, a name or a number · **Done when**: a reference solution passes and `tests/test_bench.py` still passes
- [X] T148 [P] [US6] Add the unattended-mandatory-clarification scenario in `bench/tasks/careful-unattended/`
  - **Req**: SC-002, SC-040 · **Dep**: T044 · **Evidence**: run with no listener; passing requires the clarification-required outcome with `clarification.outcome = "unattended"` and zero invented values · **Done when**: the judge refuses the shortcut the task invites
- [X] T149 [P] [US6] Add the cancelled-mandatory-clarification scenario in `bench/tasks/careful-cancelled/`
  - **Req**: SC-037, SC-038, SC-041, SC-044 · **Dep**: T039, T041 · **Evidence**: the user cancels; passing requires zero fabricated values, zero dependent mutating actions, and no re-raise within the attempt · **Done when**: judge scores an exactly-readable line
- [X] T150 [P] [US6] Add the expiry and answer-resumption scenario in `bench/tasks/careful-expired-then-answered/`
  - **Req**: SC-039, SC-042 · **Dep**: T038 · **Evidence**: expiry fabricates nothing; a later answer resumes the dependent work to the same result as a first-time answer · **Done when**: both halves scored
- [X] T151 [P] [US6] Add the long multi-file scenario in `bench/tasks/refactor-many-files/`
  - **Req**: SC-011 · **Dep**: T015 · **Evidence**: resend cost dominates, so efficiency is measurable · **Done when**: baseline recorded
- [X] T152 [P] [US6] Add the repeated-task-in-one-project scenario in `bench/tasks/learning-repeat/`
  - **Req**: SC-021, SC-031 · **Dep**: T118 · **Sequence**: the **same N = 6** comparable-task sequence as T118 (tasks 1–3 initial window, tasks 4–6 learned window), with comparability of the six inputs asserted so an incomparable window invalidates the run · **Primary metrics (SC-021)**: mandatory clarifications raised and user corrections received, per window, using exactly the metric definitions T118 uses; rediscovery / knowledge-hit counts emitted only as secondary diagnostics · **Evidence**: the scenario emits both window totals for both primary metrics plus outcome success per task, so the SC-021 comparison is mechanical · **Done when**: the six-task sequence is reproducible (T157) and emits the same metric definitions used by T118
- [X] T153 [US6] Extend per-task reporting with the full paired record in `bench/report.py`
  - **Req**: FR-076 · **Dep**: T062 · **Evidence**: task, category, result, correctness, input/output/cached/total tokens, model turns, tool calls, clarifications, corrections and validation outcome in **one table** · **Done when**: a token figure cannot be published without its outcome rate
- [X] T154 [US6] Enforce benchmark scenario integrity in `bench/integrity.py`
  - **Req**: SC-026, FR-077 · **Dep**: T013 · **Evidence**: a check that **fails the run** if any existing scenario's prompt, judge, starting repository or step/time budget has been weakened, deleted, simplified, shortened or re-labelled relative to its recorded fingerprint; **a lower token result obtained by weakening the benchmark is invalid and reported as such** ; additionally a deterministic test asserts that no module under `src/comodor/` imports `bench.integrity` or `bench.baseline` (harness-only boundary, plan §Complexity Tracking) · **Done when**: tampering with any existing scenario fails the check, and the production-import guard passes
- [X] T155 [US6] Produce the before/after comparison in `bench/report.py`
  - **Req**: SC-011, SC-012, FR-077 · **Dep**: T015, T096, T153, T154 · **Evidence**: per-task deltas for both cost and quality; any outcome-rate fall flagged as a regression; the integrity check must have passed · **Done when**: comparison published
  - **Published**: `bench/results/paired-baseline-2026-09-20.{json,md}` — the final 13-task × 3-try paired run at candidate HEAD `be9cf6f`, token-accounting version 2 (provider/model sanitized per repository policy). `as_paired_markdown` now carries an explicit **Regression** column (FR-077). Measured: current 30/39 attempts at 55,440 mean total tokens vs naive 33/39 at 50,750; the comparison flags `feature-retry-decorator` and `careful-unknowable`. **SC-011 is not satisfied by this measurement** — current uses more total tokens and its outcome rate is lower. *(2026-09-24: the SC-011 threshold has since been recorded in spec.md (D5), closing T156's writing condition; SC-011 acceptance itself remains open as T198.)*
- [X] T156 [US6] Set the SC-011 numeric threshold from measured data and record it in `spec.md`
  - **Req**: SC-011, SC-036 · **Dep**: T155 · **Evidence**: threshold derived from T015 and T155, **never chosen in advance** · **Done when**: `spec.md` §SC-011 names the figure and its baseline
  - **Recorded** (owner decision D5, committed spec `d911e3f`): SC-011 passes only when current mean total tokens ≤ 0.90 × naive in one comparable paired run **and** every task's current outcome rate ≥ naive. §SC-011 names the figure, and its baselines are the T015 and T155 runs in the Benchmark evidence record. This closes the **threshold-writing** condition only. SC-011 is **not satisfied**; its acceptance is T198.
- [X] T157 [P] [US6] Assert benchmark reproducibility in `tests/test_bench_reproducibility.py`
  - **Req**: SC-026, FR-064 · **Dep**: T068 · **Evidence**: per-attempt isolation, explicit learning mode, results reported as rates across repeated attempts rather than single booleans · **Done when**: two identical runs agree on their measurement inputs
- [X] T158 [P] [US6] Assert new scenarios meet the judge-honesty rules in `tests/test_bench.py`
  - **Req**: SC-026 · **Dep**: T147 to T150 · **Evidence**: each new `careful`/`find` task turns on something the repository cannot answer and has at least one line whose correct value is a path, a name or a number; each judge refuses the shortcut its task invites · **Done when**: existing bench guard test extended and green

**Checkpoint**: claims measured, paired, tamper-evident.

---

## Phase 10: Regression and Validation

**Purpose**: every gate green on the exact commit under review. Evidence from an earlier commit is not evidence.

- [X] T159 [P] Run `python -m ruff check src tests bench tools`
  - **Req**: SC-022 · **Dep**: Phases 2–9 · **Evidence**: clean · **Done when**: exit zero
- [X] T160 [P] Run `python -m pytest -q`
  - **Req**: SC-022, SC-025 · **Dep**: Phases 2–9 · **Evidence**: full suite green, including every mutation-checked guard · **Done when**: exit zero
- [X] T161 [P] Run `python -m pytest -m performance -n 0 -q`
  - **Req**: SC-022 · **Dep**: T066 · **Evidence**: performance ceilings hold · **Done when**: exit zero
- [X] T162 [P] Run `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`
  - **Req**: SC-022 · **Dep**: T052 · **Evidence**: frontend gates green, including the shared question reducer · **Done when**: all four exit zero
- [X] T163 [P] Run the renderer suite at widths 160/120/100/80/60
  - **Req**: FR-031, SC-008, SC-022 · **Dep**: T052 · **Evidence**: deterministic rendering at every width, no timing dependency · **Done when**: suite green
- [X] T164 [P] Run `python tools/protocol-codegen.py --check`
  - **Req**: FR-080, SC-022 · **Dep**: T047 · **Evidence**: schema and generated artifacts agree · **Done when**: exit zero
- [X] T165 [P] Run `python tools/capability-map.py --check`
  - **Req**: FR-119, SC-035 · **Dep**: T140 · **Evidence**: inventory matches the code · **Done when**: exit zero
- [X] T166 Verify the committed terminal bundle matches its source
  - **Req**: FR-078, SC-022 (Constitution VII governs) · **Dep**: T141 · **Evidence**: rebuild produces no diff outside the artifact path · **Done when**: `git status` clean after rebuild
- [X] T167 [P] Run the full permission suite a final time
  - **Req**: FR-019, FR-118, SC-022 · **Dep**: T028, T060, T069, T098, T119, T129, T146 · **Evidence**: green on the final commit, confirming the per-phase gates held · **Done when**: exit zero
- [X] T168 [P] Run the cross-platform matrix on Windows, Linux and macOS
  - **Req**: FR-078, SC-022 · **Dep**: T159 to T167 · **Evidence**: green on all three for every changed surface · **Done when**: matrix green on the exact final HEAD
  - **Matrix green**: the exact-HEAD CI at `971372e` passed Linux, Windows and macOS (py3.11/3.12/3.13, TUI renderer on all three, installed package on all three, Frontend, Lint, Capability Map, Surface Contract). The macOS renderer job hit the known frame-predicate flake once and passed on a single rerun; no code differs between that commit and the documentation-only closure that carries this line.
- [X] T169 [P] Run `git diff --check` and review the diff against the scope rule
  - **Req**: FR-128 · **Dep**: Phases 2–9 · **Evidence**: the diff contains only work required by a requirement in this specification; no drive-by refactor, cleanup, formatting churn or dependency bump · **Done when**: exit zero and the diff reviewed
- [X] T170 Confirm no release action was taken anywhere in the branch
  - **Req**: FR-084, FR-085 · **Dep**: Phases 2–9 · **Evidence**: no tag created or moved, no release workflow dispatched, no package published, no deployment, no pending pull request merged, closed, rebased or incorporated · **Done when**: asserted against the branch history

**Checkpoint**: every gate green on the exact final HEAD.

---

## Phase 11: PR #39 Compatibility Audit (strictly read-only)

- [X] T171 Audit implemented changes against open PR #39 (`feat/trading-core-foundation`) — **read-only**
  - **Req**: FR-083, FR-085, [plan.md §PR #39](./plan.md) · **Dep**: Phase 10 complete
  - **Objective**: compare this branch's changed paths against PR #39's thirteen paths and report conflicting files, conflicting abstractions, likely merge conflicts and a recommended integration order
  - **Evidence**: the path and abstraction comparison, recorded in the final report
  - **Prohibited**: merge · close · rebase · edit · checkout-and-modify its branch · enable auto-merge · import unmerged trading code into this initiative
  - **Done when**: the audit is recorded and, if a conflict exists, **reported to the user as their decision** — never resolved inside this feature

---

## Phase 12: Stable Decision Identity and the Continuation Index

**Purpose**: a stable semantic `decision_ref` for every mandatory decision, carried into questions and form records, and an exact index from a ref to its continuation (plan §2026-09-24 Plan Convergence B; data-model §3, §Stateless-run continuation; research R9, R10, R14, R16).

- [ ] T172 [P] [US1] Add a minted semantic `ref` to `OpenDecision` in `src/comodor/agent/evidence.py`
  - **Req**: FR-020, FR-129, D4; data-model §3 · **Dep**: none · **Evidence**:
    - `EvidenceLedger` takes an injectable minting function; the default mints an opaque, collision-resistant random token (e.g. from `secrets`).
    - `ref` is minted **once**, when a decision first enters `REQUIRES_CLARIFICATION`, and is immutable afterwards. `OpenDecision.id` stays the ledger-local `d#` and is never the semantic identity. A decision re-raised for resumption accepts and keeps its original `ref`.
    - Tests extend `tests/test_evidence_decisions.py`: two ledgers (two turns) mint distinct refs; one decision keeps its ref across cancelled, expired and unattended endings; an injected minter makes refs deterministic; no ref is derived from wording, position or the counter.
    **Done when**: tests pass, and replacing the minter with the `d#` counter fails the distinctness test (mutation-checked)
- [ ] T173 [US1] Carry the minted `ref` as the question's `decision_ref` in `src/comodor/tools/ask.py`
  - **Req**: FR-020 · **Dep**: T172 · **Evidence**: `question.decision_ref = decision.ref` replaces `decision.id`, so form records (`form_record`) persist the semantic ref; a re-raised decision's question carries its original ref · **Done when**: `tests/test_clarification_protocol.py` asserts the question and its form record carry the ref, never a `d#` value
- [ ] T174 [P] [US1] Add the optional `SessionMeta.continuation` object and the listing filter in `src/comodor/session/store.py`
  - **Req**: FR-081, FR-129, Constitution I and XI; data-model §Stateless-run continuation · **Dep**: none · **Evidence**:
    - **Field.** `continuation` is an object `{decision_refs, mode}`, **"Present only on continuations"**. `save_meta` omits it on every ordinary session, so an ordinary meta file keeps today's exact key set.
    - **Contents.** `decision_refs` holds every ref the continuation has **ever** issued ("a ref is **never removed** on resolution"). `mode` is the effective safety mode at the stop. `SessionMeta.cwd` stays the workspace binding and `provider` / `model` stay provenance; none is duplicated inside the object.
    - **Listing.** `list_sessions()` excludes any meta that has `continuation` by default; an explicit opt-in parameter includes them for internal lookup only.
    - **Tests** in `tests/test_protocol_sessions.py` (the existing `SessionStore` suite): (1) an ordinary session's meta file has exactly the pre-change keys, byte for byte for a fixed fixture; (2) a continuation's meta carries the object; (3) `list_sessions()` never returns a continuation; (4) meta written before this change still loads and still lists; (5) through the **previous** `SessionMeta` / `load_meta` from `d911e3f`, a continuation meta is skipped rather than listed, and ordinary sessions still load. The compatibility claim is tested, not assumed.
    **Done when**: all five pass, and writing the field on ordinary sessions fails (1) (mutation-checked). If (5) cannot hold as planned, stop and report the design issue rather than weakening compatibility
- [ ] T175 [US1] Implement the exact continuation lookup and the open / stale / unknown derivation in `src/comodor/session/store.py`
  - **Req**: FR-024, FR-026, FR-129, D9; plan §B "Exact continuation lookup" · **Dep**: T173, T174 · **Evidence**:
    - `find_continuation(decision_ref)` returns the single continuation whose `continuation.decision_refs` contains the ref, **by equality**. No match → unknown; more than one → unresolvable (rejected, never "pick one").
    - A derivation over a session's form records (`message.meta["question"]`, carrying T173's refs) classifies a ref as **open** (latest record ended `cancelled` / `expired` / `unattended`, no later `answered`), **stale** (an `answered` record exists) or **unknown**. There is no tombstone store.
    - Tests: open; stale; unknown; a deleted continuation's ref → unknown; duplicate membership → unresolvable; two continuations where the most recent is irrelevant to the result.
    **Done when**: tests pass, and replacing equality with a prefix match or a most-recent fallback fails them (mutation-checked)

**Checkpoint**: every mandatory decision has a stable ref that reaches its form record, and a ref resolves to one continuation or to nothing.

---

## Phase 13: Clarification Output and Protocol

**Purpose**: surface the `decision_ref` in the structured outcome, additively (plan §B; contracts/clarification.md §C2; research R12). Order: schema → generated artifacts → runtime emission → compatibility tests.

- [ ] T177 [P] [US1] Add optional `decision_ref` to `ClarificationRequired` and `ClarificationDecision` in `schemas/protocol/v2.json`
  - **Req**: FR-034, FR-080; research R12 · **Dep**: none · **Evidence**: additive optional properties only. `ClarificationDecision.id` stays required; no required field, enum, `finish_reason` value or protocol version changes · **Done when**: the schema diff is purely additive
- [ ] T178 [US1] Regenerate protocol artifacts and extend compatibility tests
  - **Req**: FR-080, SC-023, Constitution VI · **Dep**: T177 · **Evidence**: `python tools/protocol-codegen.py` regenerates `src/comodor/protocol/_generated.py` and `packages/protocol/src/generated.ts` (never hand-edited). `tests/test_protocol_backcompat.py` proves a client that negotiates nothing sees an unchanged payload with `decisions[].id` present · **Done when**: `python tools/protocol-codegen.py --check` is clean and the tests pass
- [ ] T179 [US1] Emit `decision_ref` in `src/comodor/tools/ask.py::payload_for`
  - **Req**: FR-034, FR-035, FR-013 · **Dep**: T173, T178 · **Evidence**: a top-level `decision_ref` (first open decision) and one `decision_ref` per `decisions[]` entry, each entry's `id` carrying the same value. `outcome` and `prior_changes` unchanged; no new turn-level `stopped` value · **Done when**: `tests/test_clarification_required.py` asserts all three for cancelled, expired and unattended outcomes

**Checkpoint**: the outcome names every open decision by its stable ref; old clients are unaffected.

---

## Phase 14: The Shared Turn Entry `run_turn`

**Purpose**: one owner, immediately above `AgentLoop.run()`, for everything that crosses an invocation (plan §B "Shared turn entry", §B.1, §B.2; research R15, R16). `AgentLoop` keeps everything within a turn and never loads or writes session files.

- [ ] T180 [US1] Implement `run_turn` in `src/comodor/application/__init__.py` with the complete turn contract
  - **Req**: FR-024, FR-026, FR-029, FR-018, FR-129, SC-042, D9; plan §B "Shared turn entry", §B.1; data-model §DecisionAnswer · **Dep**: T172, T173, T175, T179 · **Evidence**:
    - **Contract.** `run_turn` never narrows `AgentLoop.run(user_text, images, decisions)`. It accepts `user_text`, `images` and `decisions`, passing all three through **unchanged**, plus one new input, `decision_answers`. It also takes the agent loop and, for a stateless caller, the session store and its execution binding. It returns the ordinary `TurnResult`.
    - **Two different inputs.** `decisions` are **open** clarification payloads carried into the turn — today from background delegates. They stay unresolved, never trigger a continuation lookup, and are never treated as answers. `decision_answers` (`{decision_ref, chosen?, written?}`, the existing `Answer` semantics) are explicit later-invocation answers, and only they trigger resolution and validation.
    - **Validation**, in plan §B.1's fixed order, stopping at the first failure: parse → shape → exact resolution of every ref (T175) → one continuation, or the live session, for the whole batch → each decision open → binding (T200) → answer content.
    - **Application.** Only then: restore a continuation's transcript into the loop's conversation; append an `answered` form record per ref; seed each answer exactly as a live-form answer is seeded (caller-provided → `KNOWN`); call `AgentLoop.run(user_text, images, decisions)`.
    - **Rejection.** Any failure applies zero answers, makes no model call, runs no tool or dependent mutation, leaves every open decision unchanged — carried `decisions` included, which are never consumed or settled — and returns a structured rejection naming what failed.
    - **Not in scope.** No recency, position, question-text, most-recent-form, first-unresolved or similarity path; no persistence code inside `AgentLoop`.
    - **Pass-through tests** in `tests/test_decision_resumption.py`, with a recording loop double: `user_text`, `images` and `decisions` each reach `AgentLoop.run` unchanged, including when `decision_answers` are also given. Plus three cases:
      - **A** — `decisions=[open delegate clarification]` alone: no continuation lookup, no answer applied, and the decision still open at the loop.
      - **B** — a valid `decision_answers` batch: the exact lookup and validation path runs.
      - **C** — an invalid `decision_answers` batch with carried `decisions`: rejected before the model, with the carried decisions neither consumed nor settled.
    **Done when**: the pass-through tests and cases A–C pass, T181 passes, and making `run_turn` drop `images` or `decisions`, or route `decisions` into validation, fails them (mutation-checked)
- [ ] T200 [US1] Enforce the continuation's workspace and mode binding in `run_turn` (`src/comodor/application/__init__.py`)
  - **Req**: FR-129, FR-028, Constitution VIII; plan §B.1; research R16 · **Dep**: T174, T180 · **Evidence**:
    - For a stateless caller, before any answer is applied or any model is called: the invocation's canonical workspace (resolved absolute path) must equal the continuation's canonical `SessionMeta.cwd`, and its effective mode must equal `continuation.mode`. Otherwise the whole batch is rejected, with no silent re-pointing and no mode upgrade or downgrade.
    - Provider and model are never compared.
    - Tests in `tests/test_decision_resumption.py`: same workspace and mode → resumes; different workspace → rejected before the model; different mode → rejected before the model; changed model, and changed provider, with the same workspace and mode → the ref stays valid and resumes.
    **Done when**: tests pass, and removing either check fails its test (mutation-checked)
- [ ] T176 [US1] Implement the continuation persistence lifecycle in `run_turn` via `SessionStore`
  - **Req**: FR-129, FR-030, FR-074; plan §B.2 · **Dep**: T174, T180 · **Evidence**:
    - **Fresh stateless run.** Ending normally or with an error, it persists nothing. Ending `clarification_required`, it writes its transcript once through the existing `SessionStore` — form records with refs, outcome and `prior_changes` — with `continuation = {decision_refs, mode}` and a canonical `cwd`.
    - **Resumed run.** It appends its whole turn to the **same** continuation, whatever it ends in: success, error or another clarification. The fresh-run rule does not apply to it.
    - **Re-stop.** A resumed run that stops again keeps the same continuation id and record: the new form is appended, new refs are minted and **added** to `decision_refs`, the old refs are kept, and the earlier answered refs remain stale. No second continuation is created.
    - Tests in `tests/test_decision_resumption.py` cover each case, including: a successful fresh run and an error fresh run leave the store untouched; the continuation is absent from `list_sessions()`; and it is exportable with `SessionStore.export_markdown` / `export_json` by the id `find_continuation` returns.
    **Done when**: tests pass
- [ ] T181 [US1] Add deterministic, mutation-checked tests for `run_turn` validation in `tests/test_decision_resumption.py`
  - **Req**: FR-024, FR-026, FR-129 · **Dep**: T180, T200, T176 · **Evidence**:
    - **Rejection classes.** One test per class: missing, malformed, unknown, stale, cross-continuation and empty answer, plus workspace and mode mismatch.
    - **Order.** A test per step proves that a failure there leaves the continuation byte-identical, applies zero answers and makes zero provider calls (fake-provider call counter), and that later steps never run.
    - **Atomicity.** One bad answer among three applies none.
    - **Stale vs unknown.** A stale ref is reported stale, and a never-minted or deleted-continuation ref unknown.
    **Done when**: all pass, and adding a most-recent-decision fallback or partial application fails them (mutation-checked)
- [ ] T201 [US4] Route a resumed answer into the existing settled-decision learning path
  - **Req**: FR-109, SC-017, FR-056; L3 · **Dep**: T180 · **Evidence**:
    - A valid resumed answer is seeded where the loop's existing answered-form handling (`src/comodor/agent/loop.py`, which calls `LearningMemory.settle_decision` in `src/comodor/learning/memory.py`) already sees live answers. No resumption-specific memory path exists.
    - Tests in `tests/test_learning_reuse.py`: a valid resumed answer produces a `settled_decision` item with its provenance; a rejected batch (invalid, stale or unknown) learns nothing; the same decision is not re-asked later in the project; learning switched off learns nothing.
    **Done when**: tests pass

**Checkpoint**: one function validates, binds, restores, seeds, runs and persists; the loop is unchanged in role.

---

## Phase 15: Surface Adapters

**Purpose**: each of the six application / surface turn-entry families calls `run_turn` instead of the loop, passing through the inputs it already supports, and each surface translates its native input into it (plan §B facts "Turn entry — six families"; §B rows). Delegate child loops (`tools/delegate.py`, `agent/background.py`) are internal execution, not turn entries, and are left as they are. The global `--resume` and `--interactions` contracts are unchanged; nothing moves onto `CoreService`.

- [ ] T202 [P] [US1] Route `web/session.py::Session.send` through `run_turn` (a session-backed caller)
  - **Req**: FR-129, FR-079, FR-029 · **Dep**: T180 · **Evidence**:
    - `Session.send` calls `run_turn` with its live conversation instead of `self.agent.run(...)`. It passes through the inputs it already supports — `text`, `images` and `decisions` — unchanged, and adds `decision_answers` only when a caller supplies them.
    - This covers the Web UI, the OpenAI-compatible API (`api/session_map.py`), Telegram, Slack, WhatsApp and Discord, plus the Web session's own completion delivery, which already re-enters through `Session.send`. A turn without decision answers behaves exactly as before.
    - Tests in `tests/test_web.py`: the existing Web suite stays green; an image turn and a carried-decision turn reach the loop unchanged; a decision answer arriving through `Session.send` resumes or is rejected exactly as `run_turn` decides.
    **Done when**: tests pass
- [ ] T203 [P] [US1] Route `CoreService.send` in `src/comodor/application/__init__.py` through `run_turn` (the TUI user turn, session-backed)
  - **Req**: FR-129, FR-079 · **Dep**: T180 · **Evidence**:
    - `CoreService.send` runs its turn through `run_turn` with the handle's live conversation, as an adapter only: no resumption logic lives in `CoreService`.
    - Busy state, turn ids, the journal, event ordering, the persistence boundary, cancellation and every client-visible behaviour are unchanged.
    - `send` accepts no images or carried decisions today, so none are invented for it. No new client→core message is added; protocol clients answer live forms through `question.answer`.
    - `tests/test_protocol_sessions.py` and the existing protocol suites stay green.
    **Done when**: tests pass
- [ ] T207 [US1] Route `CoreService._deliver_completions` in `src/comodor/application/__init__.py` through `run_turn`, preserving carried delegate decisions
  - **Req**: FR-029, FR-018, FR-019, FR-129; plan §B facts "Turn entry — six families" (family 3) · **Dep**: T180, T203 (same file, `application/__init__.py`) · **Evidence**:
    - The background-completion turn — a separate entry path from `send` — calls `run_turn(..., user_text=text, decisions=carried or None)` instead of `handle.assembly.agent.run(...)`.
    - `carried` stays exactly what it is today: each finished delegate record's `clarification` payload. No payload is dropped, rewritten or converted into a `decision_answers` entry.
    - A regression test in `tests/test_session_delegates.py` (or `tests/test_delegate_clarification.py`), with a scripted fake provider:
      1. a background delegate stops for a mandatory decision;
      2. its completion is delivered;
      3. the parent turn reaches `run_turn` with that payload in `decisions`;
      4. at the loop the decision is still open and attributed to the delegate's origin;
      5. no answer is supplied or invented, and no continuation lookup happens because of it;
      6. work that depends on it does not run, while demonstrably independent work is unaffected.
    **Done when**: the regression passes, and dropping `decisions` in this path, or passing them as `decision_answers`, fails it (mutation-checked)
- [ ] T182 [P] [US1] Add `--decision-answers` to `comodor run` and route `run_headless` through `run_turn` in `src/comodor/cli.py`
  - **Req**: FR-129, FR-123; research R14 · **Dep**: T176, T180, T200 · **Evidence**:
    - **Option.** `--decision-answers PATH` (`-` = stdin) takes a JSON DecisionAnswer list and makes the positional task optional; a task given alongside rides the resumed turn as the caller's message.
    - **Routing.** `run_headless` calls `run_turn` as a stateless caller, passing the session store and its binding: the canonical workspace, and the effective mode from the invocation's configuration and flags.
    - **Rejection.** No model call; the refs or the binding mismatch are named on stderr; exit `1`; `--json` gains an additive `error` object. No new exit code.
    - **Unchanged.** The global `--resume` keeps its interactive meaning; `--interactions` still scripts live forms within one run.
    - **Tests** in `tests/test_headless.py`: a full round trip (exit `3` → answers file → resumed run finishes the same work); stdin input; each rejection class; a batch spanning two continuations rejected; a stale ref after a successful resume rejected; `--interactions` and `--resume` unchanged.
    **Done when**: tests pass
- [ ] T184 [P] [US1] Route ACP turns through `run_turn` and accept decision answers in `src/comodor/acp/agent.py`
  - **Req**: FR-129 · **Dep**: T180 · **Evidence**: the ACP agent calls `run_turn` with its session's live conversation instead of `self.loop.run(...)`. A prompt's extension metadata may carry `decision_answers`. An invalid batch returns a JSON-RPC invalid-params error naming what failed; no ACP-specific decision state exists. Tests in `tests/test_acp.py` · **Done when**: tests pass
- [ ] T204 [P] [US1] Route `cron/runner.py::run_job` (scheduled jobs and webhook events) through `run_turn` as a stateless caller
  - **Req**: FR-121, FR-129, FR-123 · **Dep**: T176, T180, T200 · **Evidence**:
    - `run_job` calls `run_turn` with the session store and its binding (the job's workspace, and its effective mode — for a webhook, plan unless the subscription sets `allow_writes`).
    - Tests in `tests/test_cron.py` and `tests/test_webhook.py`:
      - a scheduled run that completes creates no continuation;
      - a scheduled run that ends `clarification_required` creates one hidden continuation;
      - a later unrelated scheduled invocation does not resume it;
      - a webhook event that ends `clarification_required` creates one hidden continuation;
      - a later unrelated webhook event does not resume it;
      - an explicit valid batch through `comodor run --decision-answers` resumes it;
      - a workspace mismatch is rejected, and a mode mismatch is rejected.
    - No cron-specific decision logic exists.
    **Done when**: tests pass
- [ ] T183 [US1] Accept `comodor.decision_answers` on the OpenAI-compatible API in `src/comodor/api/schema.py`, `src/comodor/api/server.py` and `src/comodor/api/session_map.py`
  - **Req**: FR-123, FR-129, FR-080, SC-023 · **Dep**: T202 · **Evidence**:
    - `decision_answers` rides the existing request-side `comodor` block within the session named by `X-Comodor-Session`, and reaches `run_turn` through `Session.send`.
    - Rejection returns HTTP 400 with the existing OpenAI-style error body (`type: invalid_request_error`) naming the refs, with no model call. No `finish_reason` value is added, and a request without `decision_answers` behaves exactly as before.
    - Tests in `tests/test_api.py`: valid resume; each invalid class; batch atomicity; unchanged plain clients.
    **Done when**: tests pass
- [ ] T185 [US1] Name the open decisions' refs in the core's needed-decision text in `src/comodor/agent/loop.py` and `src/comodor/application/__init__.py`
  - **Req**: FR-121, FR-129 · **Dep**: T179 · **Evidence**: the existing "Stopped: a decision is needed …" text — which every channel, including Discord and the webhook's `reply_url` delivery, relays — lists each open decision's `decision_ref`; no channel formats it separately. `tests/test_channel_clarification.py` asserts the ref appears · **Done when**: test passes
- [ ] T186 [P] [US1] Resume by explicit reference on Telegram in `src/comodor/telegram/bot.py` and `src/comodor/telegram/keyboard.py`
  - **Req**: FR-129; plan §B "Channels" · **Dep**: T185, T202 · **Evidence**: a command (the existing `_on_command` path) or an inline-keyboard callback carrying the `decision_ref` becomes a decision answer passed through `Session.send` → `run_turn`; free text stays a new request, never matched to a decision. Tests in `tests/test_telegram.py` · **Done when**: tests pass
- [ ] T187 [P] [US1] Resume by explicit reference on Slack in `src/comodor/slack/bot.py` and `src/comodor/slack/blocks.py`
  - **Req**: FR-129 · **Dep**: T185, T202 · **Evidence**: a block action whose `action_id` / value carries the `decision_ref` becomes a decision answer through `Session.send` → `run_turn`; free text stays a new request. Tests in `tests/test_slack.py` · **Done when**: tests pass
- [ ] T188 [P] [US1] Resume by explicit reference on WhatsApp in `src/comodor/whatsapp/bot.py`, `src/comodor/whatsapp/menu.py` and `src/comodor/whatsapp/webhook.py`
  - **Req**: FR-129 · **Dep**: T185, T202 · **Evidence**:
    - An interactive reply (button or list) whose id carries the `decision_ref` becomes a decision answer through `Session.send` → `run_turn`; free text stays a new request.
    - **Discord** (plain messages only) and the **webhook** (one-shot events, outbound `reply_url`) get no resumption route: they report the decision and its ref (T185), and no interaction system is added for them.
    - Tests in `tests/test_whatsapp.py`, and a Discord case in `tests/test_channel_clarification.py` proving free text there never resumes a decision.
    **Done when**: tests pass
- [ ] T189 [US1] Prove the live pending-form path is unchanged, and that a re-raised decision keeps its ref, in `tests/test_clarification_lifecycle.py` and `tests/test_web.py`
  - **Req**: FR-020, FR-023, FR-024, FR-129, FR-079 · **Dep**: T173, T202, T203 · **Evidence**: a live form is still answered through `question.answer` and the bus's atomic claim; an answer to an expired or cancelled form is still ignored (FR-024) even though its question carries a `decision_ref`; a later explicit request re-raises the same decision with the same `decision_ref`; the Web question round-trip is unchanged · **Done when**: tests pass
- [ ] T205 [US1] Prove every application / surface primary-turn entry routes through `run_turn` — behaviourally
  - **Req**: FR-129, FR-029; H1, N1; Constitution XVIII · **Dep**: T182, T184, T202, T203, T204, T207 · **Evidence**:
    - **Behavioural proof, the primary evidence**, in `tests/test_decision_resumption.py`: for each of the six entry functions, replace `run_turn` with a recording double, drive the real entry function, and assert the double was reached with the expected semantic inputs. The six are:
      - (A) `web/session.py::Session.send` — text, images and carried decisions as passed;
      - (B) `CoreService.send` — the user text;
      - (C) `CoreService._deliver_completions` — `decisions` equal to the carried delegate clarification payloads, not converted into `decision_answers`;
      - (D) `cli.py::run_headless` — task text, plus decision answers and binding when `--decision-answers` is given;
      - (E) the ACP agent's prompt entry;
      - (F) `cron/runner.py::run_job`.
    - **No structural source scan** is used as proof. `run_turn` itself must call `AgentLoop.run`, and the delegate child loops in `tools/delegate.py` and `agent/background.py` legitimately run their own loops; they are outside this invariant.
    - If a structural check is added at all, it must be call-target-aware (AST), limited to the bodies of those six entry functions, and assert only that none of them calls the primary agent loop's `run` directly.
    **Done when**: all six behavioural cases pass, and restoring a direct loop call in any one entry function fails its case (mutation-checked)
- [ ] T206 [US1] Prove SC-042 with a deterministic replay in `tests/test_decision_resumption.py`
  - **Req**: SC-042, FR-129 · **Dep**: T176, T181, T182 · **Evidence**:
    - Two runs with the same workspace, mode, provider and model (a scripted fake provider).
    - **A**: the decision is answered during the original wait.
    - **B**: `clarification_required` → hidden continuation → explicit later `--decision-answers` with the same `decision_ref` → resumed work.
    - The test asserts the same semantic decision is resolved in both, and compares the observable requested result — files and their contents, the outcome — not the prose byte for byte.
    **Done when**: the replay passes, and seeding a different decision's answer fails it (mutation-checked)

**Checkpoint**: every surface resumes through one path, or reports the decision where it has no structured route; the six families are provably unified, and delegate-carried decisions still reach the parent turn unresolved.

---

## Phase 16: D7, FR-127, Security, Re-Verification and Documentation

**Purpose**: close the remaining specification-convergence items (plan §C, §D).

- [ ] T190 [US1] Complete the D7 / SC-002 cases in `tests/test_clarification_pause.py` and `tests/test_mutation_preflight.py`
  - **Req**: SC-002, FR-013, FR-018, FR-123 · **Dep**: none · **Evidence**:
    - First audit what the existing suites already prove: they assert that the **specific dependent artifact** is absent (e.g. `db.py`, `postcodes.csv`).
    - Add only the missing cases: (a) a demonstrably independent write is permitted and does not fail; (b) an uncertain dependency is withheld; (c) late discovery keeps the earlier change, lists it in `prior_changes`, and runs nothing dependent afterwards; (d) no work is started merely to stay active.
    - No existing assertion is weakened.
    **Done when**: each of (a)–(d) is covered by an existing or new test, recorded in the task evidence
- [ ] T191 [P] Audit the `careful-*` benchmark judges in `bench/tasks/*/check.py` for a blanket "no write before asking" rule
  - **Req**: SC-002, SC-026, FR-077 · **Dep**: none · **Evidence**:
    - The judges inspected so far assert specific fabricated or dependent artifacts: `careful-unattended` (no target written) and `careful-only-what-was-asked` (scope).
    - Record each judge's rule. If one asserts that nothing at all was written, report it as a finding. Judges are fingerprinted by `bench/integrity.py` and are **not** edited or weakened by this task.
    **Done when**: the audit is recorded, with any finding reported
- [ ] T192 [US2] Verify, and if needed implement, FR-127's unsupported-claim rule in the existing completion path (`src/comodor/agent/claims.py`, `src/comodor/agent/verify.py`, `src/comodor/agent/loop.py`)
  - **Req**: FR-125, FR-127, FR-036 · **Dep**: none · **Evidence**:
    - First establish current behaviour: when the gate cannot reach a verdict, or the one correction turn still produces an explicit completion claim, is the claim delivered marked as not confirmed, with the outstanding work named? Plan inspection found no such marking.
    - If present: record where, and add a deterministic test if none exists.
    - If absent: add the narrowest annotation in the existing path — no second gate — so the delivered answer does not report the task complete (FR-036).
    - Tests in `tests/test_completion_gate.py`.
    **Done when**: behaviour is evidenced by a mutation-checked test
- [ ] T193 [P] Validate continuation privacy and the security boundaries in `tests/test_decision_resumption.py` and `tests/test_baseline_permissions.py`
  - **Req**: FR-074, FR-117, FR-118, FR-120, Constitution VIII · **Dep**: T176, T182, T200 · **Evidence**:
    - **Privacy.** A hidden continuation gets **the same established redaction as an ordinary stored session**, and no more is claimed: a known or configured secret redacted at the tool layer (`ctx.redact`, the `Redactor` in `agent/loop.py`) is absent from the continuation file exactly as it is from an ordinary session's. `continuation` metadata holds only refs and a mode name, and refs carry no secret.
    - **Security.** A decision answer supplies information, never permission. Resuming in plan or conversation-only mode grants no tool the mode forbids; act stays permission-controlled; an unknown mode still fails closed; a changed provider or model does not bypass the mode binding; an invalid batch authorises no dependent work.
    - FR-074 is re-checked for the new measurement and diagnostic records (rejection records hold no credential). The permission suite is green (this phase's permission gate).
    **Done when**: tests pass
- [ ] T194 Re-verify the requirements the 2026-09-24 sessions sharpened, against the code
  - **Req**: FR-099, FR-100, FR-101, FR-105, FR-018, FR-123; plan §D · **Dep**: none · **Evidence**: one deterministic assertion each —
    - near-duplicates are never collapsed on similarity alone, and exact duplicates only on content identity (`tests/test_context_dedup.py`);
    - a delta or reference whose base cannot be validated falls back to the full authoritative form (`tests/test_context_invalidation.py`);
    - every reuse mechanism invalidates on a source change (`tests/test_context_invalidation.py`);
    - a non-interactive run starts no speculative work before its stop (`tests/test_clarification_pause.py`).
    A gap found here is fixed in the owning module, with a test, before T196.
    **Done when**: each assertion exists and passes, with any fix recorded
- [ ] T195 [P] [US1] Document the convergence in `docs/cli.md`, `docs/questions.md`, `docs/telegram.md`, `docs/slack.md` and `CHANGELOG.md`
  - **Req**: FR-082, FR-129, FR-030 · **Dep**: T182, T183, T186, T187, T188, T204 · **Evidence**:
    - `decision_ref` and exact later resumption; `--decision-answers` with its JSON shape and the exit `1` rejection; the workspace and mode binding.
    - The API's `comodor.decision_answers` and HTTP 400; explicit-reference replies on Telegram, Slack and WhatsApp, with Discord and the webhook reporting only.
    - That a stopped CLI run, scheduled job or webhook event keeps an unlisted continuation, exportable by id.
    - `CHANGELOG.md` unreleased entries marked additive; FR-082's change 1 note from T145 is unchanged.
    **Done when**: the docs match the implemented behaviour

**Checkpoint**: D7, FR-127 and the sharpened requirements are evidenced; continuations match ordinary-session privacy and grant no permission; documentation matches.

---

## Phase 17: Convergence Validation

- [ ] T196 Run every deterministic gate on the exact convergence HEAD
  - **Req**: SC-022, SC-023, SC-025, SC-035; Constitution VII · **Dep**: Phases 12–16 · **Evidence**:
    - `python -m ruff check src tests bench tools`; `python -m pytest -q`; `python -m pytest -m performance -n 0 -q`.
    - `python tools/protocol-codegen.py --check`; `python tools/capability-map.py --check`; `python -m bench.integrity`; `git diff --check`.
    - `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`; the renderer suite.
    - The committed terminal bundle is rebuilt whenever **any bundle input** changed — TUI source, or any package it bundles, including the regenerated `packages/protocol/src/generated.ts` — and verified to match its source as in T166.
    - The CI matrix is green on the exact HEAD on all three platforms.
    **Done when**: every gate is green on one recorded HEAD

---

## Phase 18: Final Acceptance

**Purpose**: settle SC-011 and SC-012 on the exact frozen candidate. Historical runs (T015, T155) are evidence but **do not** pass either criterion. The threshold is fixed (D5) and never adjusted after seeing results; timeouts, retries, judges, assertions and sample sizes are not weakened to obtain a pass.

- [ ] T197 [US6] Qualify the acceptance provider and model on the exact frozen candidate with `python -m bench.health`
  - **Req**: SC-026 · **Dep**: T196 · **Evidence**: the health gate passes as defined, with no raised timeout or selective retry, and the provider and model are recorded (sanitized per repository policy) · **Done when**: qualification is recorded for the frozen HEAD
- [ ] T198 [US6] Run the final comparable paired measurement and decide SC-011
  - **Req**: SC-011, SC-036, FR-076, FR-077 · **Dep**: T197 · **Evidence**:
    - One fresh paired run (`python -m bench --paired --provider <provider> --model <model> --tries 3`), with the same provider, model, task set, attempts, token-accounting version, counterbalancing and candidate semantics for both strategies; the result is published in `bench/results/`.
    - SC-011 **passes only if** current mean total tokens ≤ 0.90 × naive **and** every task's current outcome rate ≥ naive; otherwise it is reported as failing.
    **Done when**: the result is published, and the checkbox is marked only if SC-011 passes
- [ ] T199 [US6] Decide SC-012 from the same run against the immediately preceding published baseline
  - **Req**: SC-012, FR-077 · **Dep**: T198 · **Evidence**: each task's outcome rate is compared with the immediately preceding published baseline; any fall attributable to the efficiency change is reported as a regression and blocks acceptance · **Done when**: the comparison is published, and the checkbox is marked only if no task's outcome rate fell

**Final checkpoint**: Feature 002 is acceptance-complete only when T172–T207 are complete, the exact-HEAD gates are green, and SC-011 and SC-012 pass on fresh evidence.

---

## Requirement Coverage

Every implementation-relevant FR and SC maps to at least one task. The requirements below intentionally carry **no separate task**, each with its evidence-based justification — they are constraints enforced by other tasks rather than units of work.

| Requirement | Why no separate task | Enforced by |
| --- | --- | --- |
| FR-014 (all decisions in one form) | The existing `ask` tool is already one call for the whole set; there is nothing to build | T006 characterizes it; T033 preserves it |
| FR-020 (stable identity, match by header) | Already implemented in `questions.py` and the protocol schema | T006, T042 |
| FR-021 (single- and multi-choice) | Already implemented | T006 |
| FR-046 (never rewrite newest/unedited reads) | A constraint on T081/T091, not separate work | T004, T091 |
| FR-048 (point at on-disk files in place) | A correctness rule inside overflow handling | T079 |
| FR-071 (cancellation takes effect at the next existing cooperative step/tool boundary) | Existing cooperative cancellation preserved; this feature adds no new blocking path, polling or timer — T042 asserts turn cancellation still yields `stopped == "cancelled"` at the transport layer; T160 keeps the existing cancellation suite green | T042, T160 |
| FR-085 (no PR mutation) | A prohibition, verified rather than built | T170, T171 |
| FR-128 (no unrelated work) | A prohibition on the diff | T169 |
| SC-001, SC-005, SC-007 | Measured by benchmark and property tests rather than built | T029, T147–T150, T153 |
| SC-016, SC-017, SC-018, SC-019, SC-020 | Each is the acceptance measure of a named learning task | T102, T105, T106, T113, T115 |
| SC-025 (mutation checks) | A standard applied to every guard task, not a task itself | Every task marked mutation-checked |

**No coverage percentage is reported in place of this table.** Every requirement is either listed above with a justification or referenced by at least one task.

---

## Dependencies & Execution Order

*Task-phase numbering throughout this section and the rest of this file; see the crosswalk above for plan-phase equivalents.*

```text
Phase 1 (baseline) ──┬─────────────────────────────► Phase 5 (optimization) ──┐
   T015 hard gate ───┘                                        │               │
      │                                                       │               │
      ▼                                                       │               │
Phase 2 (ledger) ──► Phase 3 (clarification) ─────────────────┤               │
      │                     │                                 │               ▼
      │                     │                    Phase 4 (observability)  Phase 9
      ▼                     ▼                                 │          (benchmark)
Phase 7 (completion gate) ◄─┴─────────────────────────────────┘               │
      │                                                                       │
      └───────► Phase 6 (learning) ──► Phase 8 (surfaces) ────────────────────┤
                                                                              ▼
                                                                   Phase 10 (validation)
                                                                              │
                                                                              ▼
                                                                   Phase 11 (PR #39, read-only)
                                                                              │
                                              (specification convergence, 2026-09-24)
                                                                              ▼
       Phase 12 (identity + index) ──► Phase 13 (output + protocol) ──► Phase 14 (run_turn)
                                                                              │
                                                                              ▼
                                                    Phase 15 (surface adapters, six families)
                                                                              │
                                  Phase 16 (D7, FR-127, security, re-verify, docs) ┤
                                                                              ▼
                                                   Phase 17 (exact-HEAD deterministic gates)
                                                                              │
                                                                              ▼
                                                       Phase 18 (final acceptance: SC-011, SC-012)
```

- **Phase 5 is hard-blocked by T015.** No optimization before the baseline (Constitution XXI).
- **Phase 3 depends on Phase 2** — the ledger decides when to ask.
- **Phase 7 depends on Phases 2 and 3** — the gate reads ledger entries and must respect unresolved decisions.
- **Phase 8 depends on Phases 3, 6 and 7.**
- **Resumption chain**: T172 → T173 → T175 (with T174) → T179 → T180 → T200 / T176 → T181. The open/stale derivation (T175) needs refs in form records (T173); `run_turn` (T180) needs the lookup (T175) and the emitted refs (T179); the SC-042 replay (T206) runs only after persistence (T176), the validation tests (T181) and the CLI adapter (T182) exist.
- **Phase 15** depends on Phase 14. T183 depends on T202; T186–T188 depend on T185 and T202; T205 depends on every family adapter (T182, T184, T202, T203, T204, T207).
- **Phase 16** items are independent of Phase 15, except T193 (T176, T182, T200) and T195 (the surfaces it documents).
- **Phase 18 depends on Phase 17**: no acceptance measurement before every deterministic gate is green on the frozen HEAD.
- **A permission gate closes every phase that touches questions, ASK, modes, tool advertisement, session interaction, orchestration or protocol**: T028, T060, T069, T098, T119, T129, T146, confirmed finally by T167.

### Parallel opportunities

- **Phase 1**: T001–T013 all `[P]` — thirteen independent characterization modules
- **Phase 3**: T029/T030/T032 · T045 · T053 · T058/T059 · T049 (T034 and T035 share `tests/test_clarification_restraint.py`, so only T034 is `[P]`)
- **Phase 5**: T070–T090 are **deliberately not `[P]`** — they touch overlapping regions of `context.py` and each needs an isolated token comparison against T015. Verification tasks T091–T095 are `[P]`
- **Phase 6**: T102, T105, T106, T113, T115 are `[P]`
- **Phase 8**: T133–T139, T142–T144 are `[P]`
- **Phase 9**: T147–T152, T157, T158 are `[P]`
- **Phase 10**: all but T166 are `[P]`
- **Phase 12**: T172 and T174 are `[P]` (no dependency, different files); **Phase 13**: T177 is `[P]` with Phase 12
- **Phase 15**: T202, T182, T184 and T204 are `[P]` once Phase 14 is done (different modules); T203 is `[P]` with those; T207 edits the same file as T203 (`application/__init__.py`), so it follows T203 and is not `[P]`; T186–T188 are `[P]` once T185 and T202 are done
- **Phase 16**: T191, T193 and T195 are `[P]`; T190, T192 and T194 touch shared agent modules and run in sequence

---

## Implementation Strategy

### MVP scope

**Phases 1 → 2 → 3** (T001–T060). Delivers User Story 1 — the agent asks instead of inventing, and no non-answer path ever supplies the missing information. Independently testable and shippable without any token or learning work.

### Incremental delivery

1. **Phases 1–3** → US1 complete. The agent stops guessing, and stops over-asking. *(MVP)*
2. **Phase 7** → US2 and US5 complete. "Done" becomes truthful.
3. **Phases 4–5** → US3 complete. Tokens fall, measured against the baseline, every cache invalidating correctly.
4. **Phase 6** → US4 complete. It stops re-asking what it was told, and cannot be taught by untrusted text.
5. **Phases 8–10** → every surface consistent, every gate green.
6. **Phase 11** → PR #39 audited, decision handed to the user.
7. **Phases 12–17** → specification convergence: stable `decision_ref`, the shared turn entry `run_turn`, continuation binding and lifecycle, six turn-entry families, D7, FR-127, gates green on one HEAD.
8. **Phase 18** → final acceptance on the frozen candidate: SC-011 and SC-012 decided on fresh evidence.

---

## Notes

- `[P]` = different files, no dependency on an incomplete task
- Write the test before or with the behaviour change; every guard must be mutation-checked — the test fails when the guard is removed and passes when restored (SC-025)
- Commit per task or logical group; keep each phase revertable on its own (Constitution V)
- **Nothing in this list creates a tag, dispatches a release workflow, publishes, or deploys.** Excluded by FR-084 and reserved to the repository owner
- **Nothing in this list mutates PR #39.** T171 is read-only and reports; the integration decision is the user's
