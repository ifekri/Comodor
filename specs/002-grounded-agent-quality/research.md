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

## Open items carried forward

| Item | Why not resolved now | Settled in |
| --- | --- | --- |
| CLI exit code number for a clarification-required turn | Better decided against `cli.py`'s existing return conventions than guessed | T131 (tasks Phase 8; plan Phase 6) |
| Fingerprint granularity for repository-derived learning | Should follow real `rules.py` observation shapes | T111 (tasks Phase 6; plan Phase 5) |
| SC-011 numeric token threshold | Resolved by user decision: set from the plan Phase 1 baseline (T015), never in advance | T015 (tasks Phase 1; plan Phase 1) → T156 (tasks Phase 9; plan Phase 7) |

No other `NEEDS CLARIFICATION` remains. The three specification-level
clarifications were resolved with the user on 2026-09-14 and are recorded in
`spec.md`.
