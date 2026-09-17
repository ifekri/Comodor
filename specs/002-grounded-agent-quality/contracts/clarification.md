# Contract: Clarification

**Feature**: 002-grounded-agent-quality | Protocol: v2 (additive, no version bump)

Comodor exposes clarification on four external surfaces: the protocol (terminal
and browser clients), the headless command line, the API/ACP bridge, and channel
integrations. This contract states what each must honour.

---

## C1. Protocol additions — all optional

Added to `schemas/protocol/v2.json`, regenerated through
`tools/protocol-codegen.py` into `src/comodor/protocol/_generated.py` and
`packages/protocol/src/generated.ts`. **Generated files are never hand-edited.**

### `QuestionField` — three optional properties

```jsonc
{
  "header": "string",            // exists — the stable match key
  "prompt": "string",            // exists
  "options": [ /* QuestionOption */ ],  // exists
  "multiple": true,              // exists

  "reason": "string",            // NEW, optional
  "evidence_consulted": ["string"], // NEW, optional
  "decision_ref": "string"       // NEW, optional
}
```

A client that does not read these renders exactly as it does today. This is
guaranteed by the handshake's own rule: *a name present that the other side does
not know is ignored*.

### `QuestionOption` — unchanged

```jsonc
{ "id": "string", "label": "string", "description": "string", "free": true }
```

**Invariant (already enforced, must not regress)**: the last option of every
question has `free: true`. It is appended by the core, and model-authored
escape-hatch labels are stripped before appending so the user never sees two.

---

## C2. Clarification-required turn outcome — negotiated capability

Unlike C1, this **must** be negotiated: a client that misread it would report a
clarification-required run as a completed one.

**Terminology.** `clarification_required` is the **turn** stop category for
*all* mandatory non-answer clarification outcomes (cancelled, expired,
unattended). `EvidenceState.BLOCKED` (data-model.md §2) is specifically the
**unattended / no-listener** evidence state; cancelled and expired map to
`UNRESOLVED`. "Blocked" is therefore never used in this feature as a synonym
for the whole `clarification_required` category.

- Capability name added to `x-capabilities.core`.
- A client that does not advertise it never receives the outcome; for that client
  behaviour is unchanged.

**Payload**

```jsonc
{
  "kind": "clarification_required",
  "decision": "string",              // what must be decided
  "candidates": [                    // may be empty; never invented
    { "label": "string", "description": "string" }
  ],
  "evidence_consulted": ["string"],  // what was already checked
  "reason": "string",                // materiality class (FR-007)
  "outcome": "cancelled"             // NEW, optional: "cancelled" | "expired" | "unattended"
}
```

**`outcome` — the clarification lifecycle discriminator.** This is the layer that
distinguishes *clarification* lifecycle from *turn* lifecycle, and it is the only
place that distinction is carried.

| Clarification ended by | `outcome` |
| --- | --- |
| Explicit question cancellation or decline/dismissal | `cancelled` |
| Question expiry | `expired` |
| Nobody present / no listener | `unattended` |

- It is **additive and optional**, carried inside this payload under the same
  negotiated capability as the rest of C2. A client that does not negotiate the
  capability never receives it and keeps its existing semantics unchanged
  (FR-080).
- Its value set is scoped to the clarification lifecycle. It is **not** a turn
  outcome and must never be read as one.
- An **answered** clarification produces no payload at all: the answer resolves
  the decision and dependent execution resumes. `outcome` therefore has no
  "answered" value — its absence is not a fourth state, it means no clarification
  stopped the run.

---

## C3. Headless command line

`comodor run --json` already emits `stopped`, whose value set today is
`done | max_steps | budget | cancelled | error`.

**Where each `stopped` value comes from (repository truth) — two layers.**

| Layer | Producer | `stopped` values | This feature |
| --- | --- | --- | --- |
| **Core run loop** | `src/comodor/agent/loop.py` (`TurnResult.stopped`) | `done`, `max_steps`, `budget`, `cancelled`, `error` — plus the planned `clarification_required` | Adds exactly `clarification_required` (research R3); all existing meanings unchanged |
| **API/session bridge** | `src/comodor/api/session_map.py` | `timeout` ("the turn outlived its patience" — the bridge's own wait expired), `busy` (the session is already running a turn) | Untouched. These are bridge-produced outcomes, **not part of the core loop's native stopped set**, and this contract does not extend them |

`clarification_required` propagates from the core loop to the bridge through the
existing path (T133). Nothing here adds or renames a wire value.

**Two different concepts that both mention time.** `clarification.outcome =
"expired"` means *the clarification request expired* — a person did not answer
within the form's wait — and is a clarification-lifecycle value nested inside
the payload. The bridge/runtime `stopped = "timeout"` means *the runtime or
session timed out* and is a turn-level bridge outcome. They are different
lifecycles at different layers, and neither is ever reported in place of the
other.

**`stopped` gains exactly one value: `clarification_required`.** Every mandatory
clarification that ends without the required answer reports that single
top-level category. The precise clarification lifecycle is carried **inside the
clarification payload**, never in `stopped`.

| Clarification ended by | `stopped` | `clarification.outcome` | `ok` |
| --- | --- | --- | --- |
| Explicit cancellation or decline/dismissal | `clarification_required` | `cancelled` | `false` |
| Expiry | `clarification_required` | `expired` | `false` |
| Nobody present / no listener | `clarification_required` | `unattended` | `false` |
| An actual answer | *(no clarification stop)* | *(no payload)* | per the turn's own result |

```jsonc
{
  "text": "...",
  "ok": false,
  "stopped": "clarification_required",
  "clarification": {
    "kind": "clarification_required",
    "decision": "...",
    "candidates": [ /* … */ ],
    "evidence_consulted": [ /* … */ ],
    "reason": "...",
    "outcome": "expired"              // "cancelled" | "expired" | "unattended"
  },
  "steps": 3,
  "tool_calls": 5,
  "usage": { "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0 }
}
```

**Rules**

- **`stopped = "cancelled"` keeps its existing meaning exclusively: the whole
  agent turn was cancelled or interrupted** — the person pressed stop, or a newer
  message took over (`cancel_reason` of `"stop"` or `"interrupt"`). It MUST NOT
  be reused for a dismissed question. A turn-level cancellation and a
  question-level dismissal are different events and remain separately reportable.
- No `clarification_cancelled` or `clarification_expired` value is added to
  `stopped`. The clarification payload is the layer that distinguishes
  clarification lifecycle from turn lifecycle.
- `ok` is `false` for all three clarification outcomes. None is a success, and
  none reports success for the dependent operation — the dependent work did not
  run.
- All three MUST remain machine-distinguishable from each other via
  `clarification.outcome`, because the sensible next action differs: re-ask later,
  re-ask with a longer wait, or route to a human.
- `stopped` distinguishes them from `error`, so a caller can tell "needs a
  decision" from "something broke".
- Exit code is non-zero and distinct from the error code. *(Exact number
  deferred per research R3 to T131 — tasks Phase 8, plan Phase 6 surface
  wiring — decided against `cli.py`'s existing return conventions.)*
- Partial work already done in the turn is still reported (`steps`,
  `tool_calls`) — the loop fills the result as it goes, and that must not
  regress.

**Expiry is not a runtime timeout.** `clarification.outcome = "expired"` means
*the clarification request expired* — the person did not answer within the
form's wait. Existing turn and runtime timeout semantics, including the
API/session bridge's `stopped = "timeout"` ("the turn outlived its patience",
produced by `api/session_map.py`, not by the core loop), remain separate and
unchanged. The two are different lifecycles at different layers and neither is
reported in place of the other.

**Where the discriminator comes from.** The core already distinguishes expiry:
`EventBus.resolve()` returns `(choice, expired)` and publishes
`Kind.REQUEST_EXPIRED` on the claim. The asking tool currently **discards** that
flag — recovering it is the specific change the implementation makes, and it
feeds `clarification.outcome`. Absence of a listener is read from the bus's
`listening`. No new core mechanism is invented; what is new is only the optional
payload field that surfaces the distinction to callers.

---

## C4. API bridge

`api/server.py` maps the core `stopped` value to an OpenAI-compatible
`finish_reason`. The OpenAI-compatible envelope uses **only standard
`finish_reason` values**; Comodor never invents a value in a field whose enum
belongs to the OpenAI protocol.

**Required mapping.** A clarification-required turn maps to
`finish_reason = "stop"`. The distinct core state is not lost: it travels in
the existing `comodor` extension block, which is where non-standard
information already goes so that a standard client is untouched:

```jsonc
{
  "choices": [ { "finish_reason": "stop", /* … */ } ],
  "comodor": {
    "stopped": "clarification_required",
    "clarification": { "kind": "clarification_required", /* … */ }
  }
}
```

Rules:

- The core `TurnResult.stopped = "clarification_required"` is unchanged and
  remains authoritative inside Comodor; only the compatibility envelope is
  remapped.
- A standard client that does not read the `comodor` block sees an ordinary
  `stop` and is unaffected.
- A Comodor-aware client **MUST** read `comodor.stopped` (and
  `comodor.clarification`) to tell an ordinary completion from a
  clarification-required stop. `finish_reason` alone does not carry that
  distinction.
- No OpenAI-compatible response Comodor emits contains a custom
  `finish_reason` value.
- The same mapping applies to non-streaming responses, streaming final
  chunks and the session/API bridge path.
- `max_steps`/`budget`/`timeout` continue to map to `"length"`; a normal
  completion continues to map to `"stop"`.

---

## C5. Behaviour contract — every surface

| Rule | Requirement |
| --- | --- |
| No auto-selection | No surface may choose an option on the user's behalf (FR-019) |
| Four distinct lifecycle classes | **Only an answer resolves the information dependency.** Answered → no clarification stop; the decision is resolved and dependent work resumes. The other three all report `stopped = "clarification_required"` and are told apart by `clarification.outcome`: cancelled/declined → `cancelled`; expiry → `expired`; nobody present → `unattended`. Under all three the decision remains unresolved, no dependent work runs, and no invented value, selected option, default or stated assumption is produced (FR-018, FR-019, FR-022, FR-035) |
| Clarification lifecycle ≠ turn lifecycle | `clarification.outcome` carries the clarification lifecycle. `stopped = "cancelled"` carries the **turn** lifecycle and keeps its existing meaning exclusively — the turn was cancelled or interrupted. A dismissed question MUST NOT be reported as a cancelled turn, and a cancelled turn MUST NOT be reported as a dismissed question |
| Expiry is not cancellation | An expired form MUST NOT be reported with `outcome: "cancelled"`. The two are separate outcomes with separate next actions, and FR-022 requires the system to report which occurred |
| Only an answer resumes | Dependent work stays paused or terminates on cancel/decline/expiry, and resumes only when a valid answer arrives (FR-018). Work continues meanwhile only where it is demonstrably independent of the open decision |
| No re-raise within an attempt | A cancelled mandatory question is not re-asked during the same decision attempt; the unresolved decision is reported instead (FR-129) |
| Assumptions are for non-material decisions only | FR-003, FR-011 and FR-012 govern discretion over non-material details and may never settle or downgrade a decision that passes the materiality test (FR-130) |
| Presence is a fact | Determined from the event bus's `listening`, not from a TTY check or a per-surface flag |
| Materiality gates blocking | Only a decision passing FR-007 blocks; routine automation is unaffected (FR-122) |
| Answers match by header | Never by position (FR-020) |
| One claim wins | Duplicate answers resolve through the existing atomic claim, not timing (FR-025) |
| Stale answers ignored | An answer to an expired, cancelled or answered form is discarded and never applied to another question (FR-024) |
| Expiry is observable | Expiry publishes its event (`Kind.REQUEST_EXPIRED`) so no client keeps showing a request that is no longer live (FR-027). **Publishing that event is not the whole of expiry semantics**: the run must also report `stopped = "clarification_required"` with `clarification.outcome = "expired"`, leave the decision unresolved, and withhold dependent work (FR-018, FR-022, FR-035) |
| Reconnect restores | An outstanding form returns via the snapshot's pending interaction (FR-023) |
| Delegates attribute | A clarification from background work is origin-tagged and never injected mid-turn (FR-029) |
| Mode-aware | Every real mode may ask; a conversation-only mode must not claim it inspected the repository (FR-010) |
