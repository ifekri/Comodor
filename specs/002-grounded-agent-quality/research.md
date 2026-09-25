# Plan Phase 0 Research: Grounded High-Quality Agent

**Feature**: 002-grounded-agent-quality | **Date**: 2026-09-14

Every unknown below was resolved by reading the repository, not by assumption.
Where a question could not be settled from source, it is marked deferred with the
phase that will settle it — an unknown left visible rather than filled in, which
is the behaviour this feature exists to build.

---

## R1 — How is "nobody is there to answer" detected?

**Decision**: Use the event bus's existing `listening` property. No new
heuristic, no TTY probing, no surface-specific flag.

**Rationale**: `EventBus.listening` already answers exactly this question, and
its docstring already names the defect this feature fixes:

> *"A question needs somewhere to be answered. The bus existing is not the same
> as somebody being there, and a request published into an empty room waits for
> its full timeout before defaulting to no."*

The property is `bool(self._subscribers) and not self._closed` under the bus
lock — a fact the system already maintains, not an inference. `ScopedBus`
delegates to the parent, so a background delegate reports the parent's presence
correctly with no extra work.

**Alternatives considered**:
- *`sys.stdin.isatty()`* — rejected: wrong for the API and channel surfaces,
  where a person is present but not on a terminal, and wrong for a TUI driven
  through a pipe in tests.
- *A per-surface `interactive` config flag* — rejected: duplicates a fact the bus
  already holds, and two sources of one truth eventually disagree (the failure
  `safety/modes.py` was written to prevent).
- *Waiting for the timeout and treating expiry as absence* — rejected: it is the
  current behaviour, it costs 1800 seconds of a scheduled job's life, and expiry
  genuinely means something different (a person who never returned).

---

## R2 — Is the custom-answer invariant already centrally guaranteed?

**Decision**: Yes. Build nothing; add tests.

**Rationale**: `questions.py::_options()` appends the write-your-own row to every
question after validating the model's options, and `_is_an_escape_hatch()` strips
model-authored equivalents ("other", "something else", "none of the above", and
nine more) before appending. The comment states the reason: *"A model that offers
its own escape hatch would give the user two of them, one of which does not
work."*

This is precisely the "enforce the invariant in one shared layer so every caller
receives it automatically" the request asked for, and precisely the "do not
duplicate the custom option inside model-generated choices" rule. It already
holds. The `free: true` flag then travels through the protocol's
`QuestionOption`, and `packages/questions` renders it distinctly.

**Alternatives considered**: none needed — the requirement is already satisfied.
The risk is not absence but silent regression, which is what the property test in
plan Phase 3 / tasks Phase 3 (test 3; T029) guards.

**Consequence for the plan**: this removes a substantial block of anticipated
work. What remains is adversarial testing, including a model that authors its own
"Other" row.

---

## R3 — Can the clarification-required outcome ride the existing turn result?

**Decision**: Yes. Add one value to `TurnResult.stopped`; it propagates to every
surface through paths that already exist.

**Rationale**: `stopped` is already the turn's outcome channel and already
carries `done | max_steps | budget | cancelled | error`. Tracing its consumers:

- `cli.py:358` puts `stopped` verbatim into the headless JSON.
- `api/server.py:354` maps it to an OpenAI `finish_reason`, with anything
  unrecognised falling through to `"stop"`.
- `api/session_map.py` carries it through the session bridge.
- `TurnResult.ok` is `stopped in ("done", "max_steps")`.

So a new value `clarification_required` is reported by the headless JSON for free
and makes `ok` false — correct, since a clarification-required run is not a
success. The one place needing a deliberate edit is the `finish_reason` mapping,
which must not silently report a clarification-required turn as a normal stop.

**Alternatives considered**:
- *A separate exception type* — rejected: the loop already converts exceptional
  paths into `stopped` values, and a new exception would bypass the accumulated
  partial result (`steps`, `tool_calls`) that the loop deliberately fills in as
  it goes.
- *A new protocol event only* — rejected: it would leave the headless command
  line, which has no protocol client, with no way to see the outcome.

**Deferred to T131 (tasks Phase 8; plan Phase 6 surface wiring of the plan
Phase 3 outcome)**: the exact CLI exit code. It must be non-zero and distinct
from the error code; the specific number is a one-line decision better made
against `cli.py`'s existing return conventions than guessed here.

---

## R4 — Where can context optimization intervene without breaking the cache?

**Decision**: Behind `Conversation.render()`, and nowhere else.

**Rationale**: `render()` is `[Message.system(system_prompt), *self.messages]` —
the single funnel every request passes through, called from `_stream_once` and
from the token accounting. Anything that shapes what the model sees can therefore
be implemented in one place, with one test surface.

The hard constraint is the cached prefix. `providers/caching.py` documents the
measured stakes: the resend cost grows with the square of the step count, every
major provider discounts a byte-identical prefix by 50–90%, and the condition is
unforgiving — *"the request must begin with bytes the provider has seen
before."* The architecture already honours this by ordering the system prompt
identity → environment → mode → playbook, and — crucially — by attaching recalled
memory to the **user message** (`Message.user(..., briefing=playbook)`) rather
than the system prompt, so the head never changes between turns.

Therefore: optimizations operate on the **tail** (messages), never the head, and
never rewrite a message a provider has already cached unless the saving exceeds
the cache loss. `staleness.py` already documents this exact trade-off and applies
a threshold for it.

**Alternatives considered**:
- *Intervening in `_stream_once`* — rejected: it would bypass `used_tokens()`,
  which also calls `render()`, so the gauge and the request would disagree.
- *Intervening per provider adapter* — rejected: three adapters, three copies of
  one policy.

---

## R5 — How should repository-derived learning become stale?

**Decision**: Store a fingerprint of the derivation source on the record; compare
at recall; mismatch marks the item stale and excludes it.

**Rationale**: The curator already performs deterministic staleness marking for
decayed and duplicate items and already has the principle that *nothing is
hard-deleted that the user did not ask to delete*. Fingerprint invalidation slots
into that existing pass rather than creating a second maintenance path.

Recall is the right comparison point because it is where the cost of being wrong
is paid, and because `learning/hotindex.py` already holds the corpus in memory
for exactly this path — the check adds a comparison, not a query.

**Alternatives considered**:
- *Modification time* — rejected: unreliable across checkouts, clones, and the
  three supported platforms; a `git checkout` rewrites mtimes without changing
  content.
- *A file watcher* — rejected: a new runtime mechanism, a new failure mode, and
  it cannot see changes made while Comodor was not running.
- *Re-deriving the fact on every recall* — rejected: that is the rediscovery cost
  the feature exists to remove.

**Deferred to T111 (tasks Phase 6; plan Phase 5 learning hardening)**: the
fingerprint's granularity (whole file versus the specific region a convention
was counted from). Both are defensible; the choice should be made against real
`rules.py` observations rather than in advance. T111's completion condition
requires the decision, its rationale and its invalidation implications to be
recorded in `data-model.md` §5 with tests for the chosen granularity.

---

## R6 — Does the provider layer already report what the benchmark needs?

**Decision**: Yes. `Usage` carries it; no adapter change required.

**Rationale**: `providers/base.py::Usage` already exposes `input_tokens`,
`output_tokens`, `prompt_tokens`, `total`, `cache_hit_rate` and `merge`.
`agent/tokens.py` already calibrates its estimate against the real
`usage.input_tokens` on every reply. So the paired benchmark reports
provider-truth for cost and uses the estimator only where a provider figure does
not exist — which is the anti-gaming rule the plan states.

**Alternatives considered**: *Adding a tokenizer dependency* — rejected outright.
The Python core has exactly one runtime dependency (`rich`), `tokens.py`
documents why a compiled tokenizer was refused, and it would still be wrong for
every non-OpenAI model.

---

## R7 — Does the evidence ledger need to be persisted?

**Decision**: No. It lives and dies with the turn.

**Rationale**: Three reasons, each independently sufficient. **Security**: a
persisted ledger is another place secret-adjacent material could land, and
Constitution VIII lists snapshots, journals and checkpoints as forbidden
destinations. **Lifetime**: `ToolContext` already has exactly the turn lifetime
the ledger needs. **Simplicity**: what deserves to outlive a turn is a *learned
fact*, and `learning/` already owns that with caps, provenance and user
inspection.

The one thing that must survive is an **open decision** that blocked a turn — and
that is already handled by a different, existing mechanism: the pending question
in the session snapshot.

**Alternatives considered**: *Persisting the ledger for post-hoc audit* —
rejected: it duplicates the session journal, which already records what was read
and what was run, and it would turn a bookkeeping aid into a retention question.

---

## R8 — Does the protocol change need a new negotiated capability?

**Decision**: New optional fields on existing question shapes need no new
capability. The non-interactive clarification-required outcome does.

**Rationale**: The handshake's contract is explicit: *"A name absent from the
list means not supported; a name present that the other side does not know is
ignored. Neither side may assume a capability it did not see."* JSON Schema
objects with optional properties are ignored by a client that does not read them,
so `reason`, `evidence_consulted` and `decision_ref` are safe additions to
`QuestionField`/`QuestionRequest`.

A clarification-required turn outcome is different in kind: a client that does
not understand it would misread such a run as a completed one. That must be
negotiated.

**Alternatives considered**: *Bumping the protocol to v3* — rejected: nothing here
is incompatible, and a version bump would break every existing client for an
additive change (Constitution I, VI).

---

## R9 — Can `OpenDecision.id` serve as the stable `decision_ref`?

**Decision**: No. Add a separately minted `ref` to `OpenDecision`, and keep `id`
ledger-internal.

**Rationale**: `EvidenceLedger.open_decision` mints `id = f"d{n}"` from a
per-ledger counter, and a new ledger per turn restarts it, so `d1` recurs in
every turn of a session. Using it as the resumption key would let an answer meant
for one turn's decision resolve another's — the positional matching FR-129
forbids. The `ref` is minted once, when a decision first becomes a mandatory
clarification, by a function the ledger takes as a parameter. Production uses an
opaque random token; tests inject a deterministic sequence, so no test depends
on randomness (Constitution IV).

**Alternatives considered**:
- *Compose the turn id with the ledger id* — rejected: the core loop has no turn
  identity (the application layer mints turn ids), and threading one down only
  to build a key crosses the layering for no gain.
- *Hash the decision text* — rejected: two different decisions with the same
  wording would collide, and matching by wording is the textual-similarity
  fallback FR-129 forbids.

## R10 — Where does an unresolved decision live between invocations?

**Decision**: In the session transcript that already exists. The unresolved set
is derived from the form records every form already leaves
(`tools/ask.py::form_record` → `message.meta["question"]` → session JSON
Lines). A ref resolves only within its own session.

**Rationale**: those records already carry each question's `decision_ref`,
prompt, grounded options, reason, consulted evidence, the answers and the
lifecycle outcome — everything a later answer needs, for model-raised,
preflight-raised and unattended forms alike. Deriving from them adds no store,
keeps a single source of truth (FR-030's transcript is the same record), and
keeps the evidence ledger unpersisted (R7). Session scope makes a ref from
another conversation unknown by construction, and a ref goes stale once an
`answered` record is appended.

**Alternatives considered**:
- *A new unresolved-decisions table or file* — rejected: a second store for
  state the transcript already holds, which can disagree with it
  (Constitution XVIII).
- *Persisting the evidence ledger* — rejected for the reasons in R7.
- *Global (cross-session) refs* — rejected: they would let an answer cross
  conversations, and nothing in the specification needs it.

## R14 — How does a headless run make its decision resumable?

**Decision**: Persist a continuation **only** when a headless run ends
`stopped = "clarification_required"`. It is written through the existing
`SessionStore`, marked by an optional `SessionMeta.continuation` object (the
refs it holds and the mode it stopped in; R16), and excluded from
`list_sessions()`. This applies to every stateless run: `comodor run`, a
scheduled job and a webhook event (R15). The headless input is a dedicated
`run` option, `--decision-answers`, carrying the DecisionAnswer list; the refs
alone locate the continuation.

**Rationale**: FR-129 requires a later headless invocation to resume by
`decision_ref` and to reject unknown and stale refs. That is only possible if
something remembers which refs exist and whether they are still open. Writing
only on `clarification_required` confines the new persistence to the runs that
need it. Using `SessionStore` keeps one store, one transcript format and the
existing redaction and export paths. Writing the marker only when non-empty
leaves every ordinary session's meta file unchanged, and an older Comodor —
which rejects unknown meta fields — skips continuations instead of listing
them. Excluding continuations from `list_sessions()`, the single listing owner,
keeps them out of the TUI resume list, the Web UI, ACP and insights with one
filter.

**Alternatives considered**:
1. *Persist every headless run* — rejected: much broader persistence than FR-129
   needs, and every scripted run would become a stored conversation — an
   observable behaviour expansion.
2. *Persist the clarification-required continuation only* — **selected**, with
   the invariant that it is never listed as an ordinary session.
3. *Stateless caller replay (the caller sends the earlier outcome back)* —
   rejected: with no stored state, an unknown or stale `decision_ref` cannot be
   told apart from a valid one, so D9's fail-closed rule could not be enforced.
4. *Headless resumption only through the API or ACP* — rejected: it contradicts
   FR-129's explicit headless requirement.
5. *Reuse the global `--resume` for `comodor run`* — rejected: `--resume`
   reopens interactive sessions, and giving it a second meaning on `run` would
   couple two lifecycles and change an existing CLI contract for no gain.
6. *A separate directory or store for continuations* — rejected: a second store
   only to hide records the existing store can mark.

## R15 — Who owns the turn entry that resumption needs?

**Decision**: One function in the application layer, `run_turn`, immediately
above `AgentLoop.run()`. All six existing turn-entry families call it instead
of the loop: `web/session.py::Session.send` (Web UI, OpenAI-compatible API,
Telegram, Slack, WhatsApp, Discord), `CoreService.send` (TUI user turn),
`CoreService._deliver_completions` (the background-completion turn),
`cli.py::run_headless`, `acp/agent.py`, and `cron/runner.py::run_job`
(scheduled jobs, webhook events). It keeps `AgentLoop.run`'s inputs whole:
`user_text`, `images` and `decisions` — open clarifications carried from
background delegates — pass through unchanged. `decision_answers` is the one
new input, and only it triggers resumption. It owns decision-answer acceptance,
continuation resolution, whole-batch validation, refusal before any model call,
continuation restore, answer seeding, the loop call, and a stateless run's
continuation persistence.

**Rationale**: the surfaces do not share a turn entry today — six callers
reach `AgentLoop.run()` by different paths. Putting resumption in one function
over the existing loop, conversation and store gives it exactly one owner
without moving any surface onto new infrastructure. `AgentLoop` keeps
everything that happens within a turn. `run_turn` takes only what crosses an
invocation, so persistence never enters model iteration.

**Alternatives considered**:
- *Validate and seed in each surface* — rejected: six copies of the rules
  that decide whether dependent work may run, which diverge — the exact failure
  Constitution XVIII exists to prevent.
- *Move every surface onto `CoreService`* — rejected: a broad refactor of the
  Web session, channels, API, ACP, CLI and cron runner that Feature 002 does
  not need, and outside its scope (Constitution V).
- *Route delegate child loops (`tools/delegate.py`, `agent/background.py`)
  through `run_turn` too* — rejected: they run a delegate's own work, take no
  cross-invocation answer, and hand any clarification back to the parent, which
  already reaches `run_turn` through the completion turn or the delegate tool's
  result. Forcing them through an application-layer, continuation-aware entry
  would couple internal delegation to session persistence for no behaviour.
- *Fold carried `decisions` into `decision_answers`* — rejected: a carried
  decision is an **open** question from delegated work, not an answer. Treating
  it as one would settle it without the user (FR-019), or drop it (FR-029).
- *Put resumption inside `AgentLoop`* — rejected: the loop would load and write
  session files and know about continuations and bindings, coupling model
  iteration to persistence and business policy.

## R16 — What binds a continuation, and what does not?

**Decision**: The canonical workspace (existing `SessionMeta.cwd`) and the
effective safety mode (`continuation.mode`) bind a continuation; a resumption
that differs in either is rejected before any model call. The provider and
model (existing `SessionMeta.provider` / `model`) are provenance only.

**Rationale**: resuming in another directory would run the dependent mutation
on the wrong workspace, and resuming in another mode would change what the work
is permitted to do. Both are safety boundaries, so a mismatch fails closed
rather than being silently re-pointed, upgraded or downgraded
(Constitution VIII). A decision, by contrast, is about the user's product
intent, not the model that asked it: the specification keeps an outstanding
form valid across a model change (FR-028), so a changed provider or model must
neither stale nor orphan a `decision_ref`.

**Alternatives considered**:
- *Bind provider and model too* — rejected: it would over-bind the decision to
  incidental runtime state, against FR-028.
- *Adopt the caller's workspace or mode on resume* — rejected: it silently
  redirects or re-permissions work.
- *Duplicate `cwd` / provider / model inside `continuation`* — rejected: they
  already live on `SessionMeta`; only the mode is new.

## R17 — How is SC-012 compared across a scenario change, and where does provenance live?

**Decision**:
- The per-task scenario fingerprint is `bench/integrity.py::fingerprint`
  (D11). It is reused for recording, reconstruction and comparison, with no
  second hashing algorithm.
- A paired run records the run-start fingerprints, already computed for the
  checkpoint header, into each task's entry of the published JSON as
  `scenario_fingerprint` (D12).
- A historical report without them is read by reconstructing from its own
  recorded `commit` with the current algorithm (`fingerprint_at`).
- `sc012_comparison` selects each task's reference mechanically: the published
  `current` rate when the digests match, otherwise the same run's `naive`
  rate (D10).
- It fails closed as `UNDECIDABLE` when comparability cannot be established.
- It is exposed as `python -m bench --sc012 … --against …`, in existing modules
  only.

**Rationale**:
- One algorithm on both sides makes "changed" a byte-level fact, not a
  reviewer's call.
- Capturing at run start ties the recorded fingerprints to the scenarios
  actually judged. The drift check and the checkpoint binding already
  guarantee that.
- Reconstructing from the report's own commit is the only way to read the
  2026-09-20 baseline without rewriting it.
- A fail-closed comparator makes a shrunken task set or a missing arm visible
  instead of silently passing.

**Alternatives considered**:
- *A second, reporting-only hash*: rejected. Two definitions of "changed"
  could disagree.
- *Recomputing fingerprints at write time*: rejected. It could differ from
  what the run was judged with if the tree changed mid-run.
- *Hashing the whole `bench/` tree*: rejected by D11. Harness changes would
  make every task changed.
- *A new `bench/compare.py`*: rejected under the standing limit on new
  benchmark helpers; `report.py` already owns comparison output.
- *Rewriting the 2026-09-20 artifact to add fingerprints*: rejected, because
  historical artifacts are never altered (as with token accounting).
- *Manual reference override flags*: rejected. Selection must be mechanical
  (D10–D11).

## R11 — How does a later invocation deliver the answer?

**Decision**: One common DecisionAnswer path, owned by the shared turn entry
`run_turn` (R15). Each surface adapts its existing input
channel: the headless `--decision-answers` option (R14); `decision_answers` in the API's
existing request-side `comodor` block, with `X-Comodor-Session`; ACP prompt
extension metadata; and, on channels, only an explicit structured reply naming
the ref.

**Rationale**: validation and seeding happen once, before any model call, so no
surface has its own matcher. The answer shape is the existing `Answer`
(`chosen` / `written`) keyed by `decision_ref` instead of a form header. A seeded
answer enters the new turn exactly as a live-form answer does, so the evidence
and learning paths need no new branch.

**Alternatives considered**:
- *Let each surface match answers itself* — rejected: several matchers diverge,
  and the specification forbids surface-specific heuristics.
- *Infer the decision from a free-text follow-up* — rejected: FR-129 forbids
  textual and recency matching.
- *A new protocol client→core message for TUI/Web* — deferred as unneeded: a
  live form is answered through `question.answer`, and a later explicit request
  re-raises the form with the same ref.

## R12 — Does the protocol need a version change?

**Decision**: No. Add optional `decision_ref` to `ClarificationRequired` and
`ClarificationDecision`, and keep `decisions[].id` — still required by the
schema — carrying the same value as a compatibility alias.

**Rationale**: an optional property is ignored by a client that does not read
it (R8), and keeping `id` means an existing reader sees the same shape. The
change goes through `schemas/protocol/v2.json` and `tools/protocol-codegen.py`,
never a hand edit (Constitution VI).

## R13 — How does an invalid reference fail?

**Decision**: Closed, before any work, all-or-nothing, and through each
surface's existing error form: CLI exit `1` with the refs named (and an additive
`error` object under `--json`), HTTP 400 with the existing OpenAI-style error
body, and a JSON-RPC invalid-params error on ACP. No new `stopped` value, exit
code or protocol enum.

**Rationale**: a missing, malformed, unknown, stale or cross-session reference
is a caller error, not a clarification outcome. Rejecting the whole input keeps
partial application impossible, so every open decision stays exactly as it was
and no dependent work can start (FR-026, FR-129). Reusing each surface's
existing error channel is additive, and the specification requires no new enum.

## Follow-up decisions resolved / acceptance still open

| Item | Why not resolved now | Settled in |
| --- | --- | --- |
| CLI exit code number for a clarification-required turn | Better decided against `cli.py`'s existing return conventions than guessed | T131 (tasks Phase 8; plan Phase 6) |
| Fingerprint granularity for repository-derived learning | Should follow real `rules.py` observation shapes | T111 (tasks Phase 6; plan Phase 5) |
| SC-011 numeric token threshold | Resolved by user decision: set from the plan Phase 1 baseline (T015), never in advance | T015 (tasks Phase 1; plan Phase 1) → T156 (tasks Phase 9; plan Phase 7) |

No other `NEEDS CLARIFICATION` remains. The specification records eighteen
clarification decisions (the latest on 2026-09-24) in its §Clarifications —
Resolved.


### 2026-09-24 alignment note

The three items originally carried forward are no longer open design questions: the headless clarification exit code is `3`; learning fingerprint granularity is represented by the provenance-specific evidence identities documented in `data-model.md` and implemented by the current learning rules; and SC-011 has the owner-selected 10% relative threshold plus the per-task quality conjunct. What remains open is empirical acceptance on a fresh exact candidate and implementation convergence for stable cross-turn `decision_ref` resumption (D4/D9).
