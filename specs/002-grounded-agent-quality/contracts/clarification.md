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
  "decision_ref": "opaque-stable-id", // semantic id of the first open decision
  "decision": "string",               // what must be decided
  "candidates": [                      // may be empty; never invented
    { "label": "string", "description": "string" }
  ],
  "evidence_consulted": ["string"],    // what was already checked
  "reason": "string",                  // materiality class (FR-007)
  "outcome": "cancelled",              // optional: cancelled | expired | unattended
  "decisions": [
    {
      "id": "opaque-stable-id",        // kept (still required by the schema); same value as decision_ref
      "decision_ref": "opaque-stable-id",
      "decision": "string",
      "candidates": ["string"],
      "evidence_consulted": ["string"],
      "reason": "string"
    }
  ]
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
    "decision_ref": "opaque-stable-id",
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
- Exit code is **3** for `clarification_required`, distinct from success (`0`), generic error (`1`) and turn cancellation (`130`), matching the current `cli.py` contract.
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
| Form id ≠ decision id | Form/question lifecycle identity is not the semantic open-decision identity. An expired or cancelled form id stays stale even though the underlying decision may remain resumable by its `decision_ref` (FR-020, FR-024, FR-129) |
| Semantic resumption matches by `decision_ref` | A later cross-turn answer resolves only the exact unresolved decision named by `decision_ref`; missing, malformed, unknown, stale or unresolvable refs are rejected, applied to no decision and authorize no dependent work (FR-026, FR-129) |
| No heuristic resumption | Recency, position, textual similarity, most-recent-question and first-unresolved fallbacks are forbidden. Surface adapters map to one common core decision-answer path rather than implementing their own matcher |
| Expiry is observable | Expiry publishes its event (`Kind.REQUEST_EXPIRED`) so no client keeps showing a request that is no longer live (FR-027). **Publishing that event is not the whole of expiry semantics**: the run must also report `stopped = "clarification_required"` with `clarification.outcome = "expired"`, leave the decision unresolved, and withhold dependent work (FR-018, FR-022, FR-035) |
| Reconnect restores | An outstanding form returns via the snapshot's pending interaction (FR-023) |
| Delegates attribute | A clarification from background work is origin-tagged and never injected mid-turn (FR-029) |
| Mode-aware | Every real mode may ask; a conversation-only mode must not claim it inspected the repository (FR-010) |

---

## C6. Late discovery — a decision that becomes known after work was done

A material unknown can surface only after investigation, and the investigation
may already have changed files. The temporal boundary is therefore explicit:

- **From the moment the dependency is open**, no further mutation that may
  depend on it runs. The withheld check and the turn stop are unchanged
  (FR-018).
- **Mutations completed before the dependency became known are not
  retroactively claimed to have never happened.** They stay in place. Feature
  002 does not roll them back: some operations are not perfectly reversible,
  and an automatic rollback could itself destroy valid work or create new side
  effects. A future transaction/checkpoint feature may offer stronger
  semantics; it is out of scope here.
- The turn reports `stopped = "clarification_required"` with the usual
  `clarification.outcome`, and it **MUST NOT** say or imply that the workspace
  is unchanged, or that "nothing dependent was done", when a mutation actually
  occurred earlier in the turn.

**Structured disclosure.** The clarification payload gains an optional,
additive `prior_changes` array: files a writer changed, and bounded names of
shell operations that changed the filesystem, deduplicated and in stable
order. It is absent when nothing was changed before the decision. It carries a
bounded description only — never file contents, command text or credentials —
and it does **not** claim an earlier change was decision-dependent, only that
it happened before the decision became known.

`prior_changes` rides the existing clarification capability and the existing
`comodor` extension; it is additive and needs no protocol version change. A
client that does not know the field ignores it.

This applies to every way the clarification can end — answered later,
cancelled, expired or unattended. Only a valid answer permits dependent work to
resume.


---

## C7. Cross-turn semantic resumption

*Planned in plan Phase 9 (plan.md §2026-09-24 Plan Convergence B). At
`d911e3f` the outcome carries `decisions[].id` (a turn-local value) and no
surface accepts an answer keyed by `decision_ref`. This section is the
contract that work must meet; it does not describe current behaviour.*

A pending interactive form and an unresolved semantic decision are related but
not identical lifecycles. The existing pending-interaction slot remains
authoritative while a form is live, and supports reconnect (FR-023). When
cancellation, expiry or unattended execution ends a form without an answer, the
per-turn evidence ledger still dies. The decision stays resolvable through the
form record that the session transcript already stores. That record carries each
question's `decision_ref` and the lifecycle outcome, so no new store is needed.

**Identity and lifetime.** A `decision_ref` is opaque, minted once when the
decision first becomes a mandatory clarification, and never derived from
wording, position or a turn counter. It resolves only within the session that
raised it, and becomes **stale** once an `answered` record for it exists. A
decision re-raised at the user's explicit request keeps its `decision_ref`.

**Stateless runs** (`comodor run`, scheduled jobs, webhook events). A fresh
stateless run keeps nothing when it succeeds or fails. When it ends
`clarification_required`, its transcript — the form records included — is kept
through the existing session store as a **continuation**: an ordinary
transcript that is excluded from every session list, and found only by an exact
`decision_ref`. A resumed run appends to the same continuation whatever it ends
in. If it stops again, the same continuation gains the new refs and keeps the
old ones. After resolution a continuation is kept, so a reused ref is reported
stale rather than unknown; deleting it makes its refs unknown.

**Binding.** A continuation is bound to its canonical workspace and to the
safety mode it stopped in. A resumption from another workspace, or in another
effective mode, is rejected before any model call, and nothing changes. The
provider and model are provenance: changing them neither invalidates a
`decision_ref` nor blocks a resumption (FR-028).

**Validation order** (owned by the shared turn entry, plan §B.1): shape →
exact resolution of every ref → one continuation (or the live session) for the
batch → each decision open → workspace → mode → answer content → apply → run.
Any failure rejects the whole batch with zero effect.

A later invocation may supply one or more **DecisionAnswer**s:
`{ "decision_ref": "...", "chosen": [...], "written": "..." }`, the existing
answer shape keyed by `decision_ref` instead of a form header. The common
application/session path validates the whole input against the session's
unresolved set **before any model call or tool**, all-or-nothing.

- **Valid** — every ref names an unresolved decision of this session and every
  answer carries real input. Each answer resolves only its own decision, is
  recorded as `answered`, and enters the new turn's ledger as caller-provided
  `KNOWN`. Any decision left unanswered stays open; if dependent work still
  needs it, the turn ends in `clarification_required` again, naming it.
- **Invalid** — a ref that is missing where required, malformed, unknown,
  stale, from another session, or otherwise unresolvable, or an answer with no
  real input. The whole input is rejected. Nothing is recorded as answered,
  every open decision stays unchanged, no dependent work runs, and the caller
  is told which references could not be resolved.

**Per-surface transport** (all additive; no new `stopped` value, no new exit
code, no new protocol enum):

| Surface | Resumption input | Rejection |
| --- | --- | --- |
| CLI / headless | `comodor run --decision-answers PATH` (`-` = stdin): a JSON DecisionAnswer list. The refs alone locate the headless continuation — which exists only because the earlier run ended `clarification_required`, and which is never listed as a session. All refs in a batch must belong to one open continuation. The positional task is optional here; if given, it accompanies the resumed turn. The global interactive `--resume` is not involved | No model call; the refs are named on stderr; exit `1`; `--json` output carries an `error` object naming the unresolved refs |
| OpenAI-compatible API | `comodor.decision_answers` in the existing request-side `comodor` block, with `X-Comodor-Session` | HTTP 400 with the existing OpenAI-style error body (`type: invalid_request_error`) naming the refs |
| ACP | Decision answers in the prompt request's extension metadata | JSON-RPC invalid-params error naming the refs |
| Channels / integrations | Telegram (callback or command), Slack (block action) and WhatsApp (interactive reply) — only an explicit structured reply carrying the `decision_ref`. Discord and the webhook have no inbound structured reply route: they report the decision and its ref, and offer no resumption there (a stopped webhook event is a stateless run, resumable with `comodor run --decision-answers`). Any other reply is an ordinary new request | A reply naming the refs that could not be resolved |
| Protocol clients (TUI, Web) | A live form is answered through `question.answer`, which already carries the association; a later explicit request re-raises the form with the same `decision_ref` | — (no new client→core message in this phase) |

Every surface translates its native input into the same DecisionAnswer path —
the shared turn entry `run_turn`, which every turn-entry family calls instead of
the loop — and none has a matcher of its own. `run_turn` does not narrow the
turn: `images` and carried `decisions` (open clarifications from background
delegates) pass through unchanged. A carried decision is never an answer and
never triggers resumption; only `decision_answers` do. No surface may guess the intended decision
from prose, recency, most-recent question, list position, textual similarity or
first-open order. A client that neither sends decision answers nor reads
`decision_ref` behaves exactly as today (FR-080, SC-023).
