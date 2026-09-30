# Quickstart: Validating the Grounded Agent

**Feature**: 002-grounded-agent-quality | **Date**: 2026-09-14, revised 2026-09-29 for D14–D17

How to prove each phase works. This is a validation guide, not an implementation
guide — entity details are in [data-model.md](./data-model.md), interface rules
in [contracts/](./contracts/).

---

## Prerequisites

```bash
# Python core
python -m pip install -e ".[dev]"

# Frontend / terminal interface
npm ci
```

**Every check below is deterministic.** Model responses are scripted
(`providers/fake.py`); no check calls a provider, needs a credential or spends a
token (D14; Constitution 2.0.0). A manual check is a convenience for a person,
never an acceptance gate.

---

## Production token-usage accounting

```bash
python -m pytest -q tests/test_token_accounting.py tests/test_baseline_tokens.py \
    tests/test_metrics_locality.py tests/test_metrics_overhead.py \
    tests/test_metrics_redaction.py tests/test_insights.py
```

Expected: per provider call and per task, input, output, cached and
cache-written tokens with the provider's figure as the truth and any estimate
labelled; the task's outcome and counts beside them; no credential in any
field; nothing sent off the machine. `comodor run --json` carries `usage` and
`measurement`. No figure is presented as a saving.

---

## Per-phase validation

Headings below use **plan-phase** numbering from [plan.md](./plan.md); the
matching **task phase** is given in each heading, per the crosswalk at the top
of [tasks.md](./tasks.md).

### Plan Phase 2 (tasks Phase 2) — evidence ledger (no user-visible change)

```bash
python -m pytest tests/test_evidence_ledger.py -q
python -m pytest -q                            # nothing else may change
```

Expected: ledger tests pass; **the full suite is unchanged**. This phase is
deliberately invisible — if behaviour moved, something was wired too early.

### Plan Phase 3 (tasks Phase 3) — clarification enforcement

```bash
python -m pytest tests/test_clarification_required.py tests/test_questions_invariant.py -q
python tools/protocol-codegen.py --check       # schema and generated artifacts agree
npm test                                       # shared question reducer
```

Renderer, at the widths that matter:

```bash
npm run test:renderer                          # widths 160/120/100/80/60
```

Manual check — the custom-answer row:

1. Ask Comodor something genuinely ambiguous.
2. Confirm the form appears **before** any change that depends on the decision.
   A change that is demonstrably independent of it may already have happened;
   that is permitted, not a failure (SC-002).
3. Confirm every question's last row is the write-your-own row, and that the
   model did not author a second one.
4. Select it, type an answer, and confirm that text shapes the work.

Manual check — the clarification-required outcome (unattended):

```bash
echo "do the ambiguous thing" | comodor run --json
```

Expected: `"stopped": "clarification_required"`, `"ok": false`, a `clarification`
block naming the decision and its candidates and carrying
`"outcome": "unattended"`, and **no invented value anywhere in the output**.
Exit code non-zero and distinct from the error code.

#### The lifecycle checks

All five exercise the same setup: a request containing a genuinely **material**
ambiguity — one that passes the FR-007 materiality test — where the repository
cannot settle it. Use the repository's deterministic clock and controlled bus
rather than real-time waiting; no step below requires a sleep.

**A. An answer resumes the work** *(SC-042)*

1. Trigger the material clarification.
2. Before answering, confirm **no dependent mutation has run** — no write, no
   shell invocation, no external call that depends on the open decision.
3. Answer with a real option, then repeat with a custom-row value.
4. Confirm dependent execution resumes and uses **that exact answer**.
5. Confirm no substitute or default value was introduced along the way.

**B. Cancel** *(SC-037, SC-041)*

1. Trigger the material clarification.
2. Cancel it.
3. Confirm dependent work does **not** run.
4. Confirm no default, assumption, selected option or fabricated value appears in
   the output.
5. Confirm the run reports `stopped = "clarification_required"` with
   `clarification.outcome = "cancelled"`, naming the decision that stayed open —
   **not** `stopped = "cancelled"`, which means the whole turn was cancelled.

**C. Decline / dismiss** *(SC-038, SC-041)*

1. Trigger the material clarification.
2. Exercise the decline/dismiss path where the surface distinguishes it from
   cancellation; where it does not, record that the surface treats them as one
   path rather than assuming a second exists.
3. Confirm the decision remains unresolved.
4. Confirm zero dependent mutation.
5. Confirm zero fabricated or default answer.
6. Confirm the run reports `stopped = "clarification_required"` with
   `clarification.outcome = "cancelled"` — decline and dismissal share the
   cancelled clarification outcome.

**D. Expiry** *(SC-039, SC-041)*

Drive expiry through the repository's deterministic/fake-clock mechanism — **not
by waiting out the real timeout**.

1. Trigger the material clarification and advance the controlled clock past the
   wait.
2. Confirm the question expires and the expiry is published, so no client is left
   showing a live card.
3. Confirm the decision is unresolved.
4. Confirm dependent mutation does not run.
5. Confirm no answer or default is fabricated.
6. Confirm the run reports `stopped = "clarification_required"` with
   `clarification.outcome = "expired"`, distinguishable from `cancelled` — an
   expired form reported as cancelled is a failure of this check (FR-022).

**E. A cancelled question is not immediately re-raised** *(SC-044)*

Within the same decision attempt:

1. Cancel the material clarification.
2. Confirm the agent **reports the unresolved decision**.
3. Confirm it does **not** immediately ask the identical mandatory question
   again.
4. Confirm a later explicit user action can still resume or answer it, and that
   doing so resumes the dependent work.

**What every one of A–E must show in common**: the decision is either answered or
it stays open. Cancellation, decline and expiry are outcomes about the
*conversation*, never about the *information* — none of them may hand the agent
permission to fill the gap itself.

### Plan Phase 4 (tasks Phase 5) — context optimization

```bash
python -m pytest -q tests/test_context_budget.py tests/test_context_dedup.py \
    tests/test_context_optimization_neutrality.py tests/test_context_no_validation_loss.py \
    tests/test_context_recoverability.py tests/test_context_no_superseded.py \
    tests/test_context_stable_prefix.py
python -m pytest -m performance -n 0 -q        # ceilings hold
```

Expected: with each optimization switched off inside the test, the same
scripted task delivers the same work; failing evidence survives every setting;
nothing withheld is lost; the request head stays byte-identical within a turn.
This is the constitution's context-change gate (plan §G.2). No token saving is
claimed (D14).

### Plan Phase 5 (tasks Phase 6) — learning hardening

```bash
python -m pytest tests/test_learning_admission.py tests/test_learning_fingerprint.py tests/test_learning_lifecycle.py -q
```

Manual check — a correction is reused:

1. Ask for something; correct what comes back.
2. Ask for the next thing in the same project.
3. Confirm the correction is already in force without restating it.

Manual check — nothing unverified was learned:

```bash
comodor journey show
```

Expected: every entry shows what it is, where it came from, and its scope, and
can be deleted individually. No entry whose only origin is a model assertion.

### Plan Phase 6 (tasks Phases 7–8) — cross-surface integration

```bash
python -m pytest tests/ -q -k "cli or api or acp or channel or web"
python tools/capability-map.py --check
```

Confirm on each surface that a clarification-required turn is reported as
needing a decision, never as success and never as a crash.

**Web UI** (REQUIRED — normative in [spec.md §Surface classification](./spec.md), implementation detail in [plan.md §Surface Impact](./plan.md); T006, T133, T146):

```bash
python -m pytest tests/test_web.py -q -k "question or clarification"
```

Manual check in the browser, on the served page:

1. Ask for something ambiguous so a question opens in the browser.
2. The custom / manual-answer row is present as the last option, exactly once.
3. Answer normally: the dependent action resumes and completes.
4. Dismiss or cancel the question: the agent does **not** invent an answer; the
   run reports a needed decision (`clarification.outcome = "cancelled"`).
5. An expired or unattended material clarification is never shown as a
   successful completion (`stopped = "clarification_required"` with
   `clarification.outcome = "expired"` / `"unattended"`). Drive expiry through
   the harness's fake clock / controlled event delivery — no real-time sleeps.
6. The page distinguishes a clarification-required result from an ordinary turn
   cancellation (`stopped = "cancelled"`, the stop button).
7. Existing non-clarification Web behaviour — permission prompts, streaming,
   mode changes — still works (`python -m pytest tests/test_web.py -q`).

### Plan Phase 8 (tasks Phases 10–11) — full validation

```bash
python -m ruff check src tests tools
python -m pytest -q
python -m pytest -m performance -n 0 -q
python tools/capability-map.py --check
python tools/protocol-codegen.py --check
git diff --check

npm run lint && npm run typecheck && npm test && npm run build
```

All of it on the **exact commit under review**, on Windows, Linux and macOS.
Evidence from an earlier commit is not evidence.

---

## What "done" means here

| Claim | Accepted only with |
| --- | --- |
| A context change is safe | Its deterministic tests with scripted responses — neutrality, no validation loss, recoverability (plan §G.2); no token-reduction claim is made (D14) |
| Clarification works | The clarification-required outcome (`outcome: unattended`) observed on a surface with no listener, plus the custom row present on every generated form — TUI and Web |
| Learning is reused | A correction or a settled decision applied on the next relevant turn without restatement (SC-016, SC-017), shown deterministically |
| Nothing regressed | The full baseline green on the exact final HEAD, all three platforms |
| A guard holds | Its test fails when the guard is removed and passes when restored |

Anything not demonstrated this way is reported as **NOT VERIFIED**, which is an
acceptable and expected answer.

### Plan Phase 9 — convergence

**Current behaviour at `d911e3f`**: the clarification-required outcome carries
`decisions[].id` — a turn-local value such as `d1` — and no top-level
`decision_ref`, and no surface accepts an answer keyed by `decision_ref`. The
checks below describe what plan Phase 9 had to make true (plan.md §2026-09-24
Plan Convergence; contracts/clarification.md §C7). Plan Phase 9 has since
delivered them, and plan §G maps SC-042 and SC-043 to the tests that pin
them.

**Cross-turn resumption (D4/D9)** — deterministic, no provider:

```bash
python -m pytest -q tests/test_clarification_protocol.py tests/test_clarification_required.py tests/test_headless.py tests/test_api.py tests/test_acp.py
python tools/protocol-codegen.py --check
```

Expected once implemented:

- a `decision_ref` stays the same across cancel, expiry and unattended endings
  and across a later turn, and differs between decisions;
- a valid answer resolves only its own decision and resumes the dependent work
  to the same result as a first-time answer;
- a missing, malformed, unknown, stale or cross-session ref is rejected before
  any model call, changes no decision and runs no dependent work — on the CLI
  with exit `1` and the refs named, on the API with HTTP 400, on ACP with an
  invalid-params error;
- headless: a run that ends normally leaves no stored session; one that ends
  `clarification_required` leaves exactly one continuation, which appears in no
  session list; `comodor run --decision-answers answers.json` resumes it by ref
  alone; a second use of an answered ref is rejected as stale;
- a resumed run's transcript is appended to the same continuation whatever it
  ends in; if it stops again, the same continuation carries the new refs and
  keeps the old ones;
- resuming from another workspace, or in another mode, is rejected before any
  model call; resuming with a different provider or model is accepted;
- every surface reaches the loop through the one shared turn entry, so the same
  rejection holds on the CLI, API, ACP and channels;
- a live pending form still answers through its existing path;
- an old client sees no change.

**SC-002 dependency semantics (D7)** — deterministic:

- up-front ambiguity: the specific dependent artifact is never written before
  the clarification;
- an uncertain dependency is withheld;
- a demonstrably independent change may happen and does not fail the check;
- late discovery: the earlier change persists, appears in `prior_changes`, and
  nothing dependent runs afterwards.

### Plan Phase 11 — acceptance-scope convergence (D14–D17)

Deterministic; no provider is called.

**SC-044 — a cancelled mandatory question is not asked again in the same
attempt** (plan §G.4):

```bash
python -m pytest -q tests/test_clarification_lifecycle.py
```

Expected:
- **Tool level**: a second `ask` for a cancelled question raises no form and
  reports the decision as unresolved.
- **Loop level**: one batch that asks the same question twice after a
  cancellation raises exactly one form; the dependent write does not run; the
  turn ends `clarification_required` / `cancelled`, carrying the same
  `decision_ref`.
- **Mutation**: with the repeat-preventing layers disabled inside the tests, a
  second form appears and the tests fail (plan §G.4).

**SC-007 — one form per decision point** (plan §G.5):

```bash
python -m pytest -q tests/test_clarification_one_form.py
```

Expected:
- Every decision a batch raises reaches the person in one logical form. That
  includes two `ask` calls in one batch, and an `ask` beside a mutation whose
  preflight finds another missing decision.
- On the TUI and the Web, a form of more than four questions is one request
  and one submission. The Web page shows it in pages of at most four; the TUI
  shows each question's position in the form.
- On the OpenAI-compatible API and ACP, the same set is one
  clarification-required payload, resumed through `decision_answers` keyed by
  `decision_ref`, in parts if needed.
- An invalid set of calls is refused atomically, with sibling mutations
  withheld.
- A scripted `--interactions` entry that does not match its form, or is left
  over, ends the run with exit `1` and a clear error. That includes an
  unkeyed `answer` for a form of several questions. A bare `answer`, with no
  value, is rejected before the run starts, with exit `1`, even for a
  one-question form. A keyed `answer` leaves omitted questions open, and an
  explicit `value` naming the first option selects exactly that option.
- A new form appears only at a new decision point (D18, D19).

**D17 — settings removed, coverage kept** (plan §G.3):

```bash
python -m pytest -q tests/test_context_optimization_neutrality.py \
    tests/test_context_no_validation_loss.py tests/test_context_no_superseded.py
```

Expected:
- the same assertions as before, with optimizations switched off inside the
  tests only;
- a configuration file that still carries either removed key loads, and the
  key has no effect.

**Every retained criterion**: run each module plan §G names, on the exact
final HEAD; a criterion without passing evidence is reported, never assumed.

**Final gates**: plan §J, on the exact final HEAD, on Windows, Linux and macOS:

```bash
python -m ruff check src tests tools
python -m pytest -q
python -m pytest -m performance -n 0 -q
python tools/capability-map.py --check
python tools/protocol-codegen.py --check
git diff --check
npm ci && npm run lint && npm run typecheck && npm test && npm run build
bun test apps/tui/test/bun/renderer.test.tsx
bun test apps/tui/test/bun/orphan.test.ts
bun tools/build-tui-distribution.ts && git status --porcelain   # prints nothing
```
