# Quickstart: Validating the Grounded Agent

**Feature**: 002-grounded-agent-quality | **Date**: 2026-09-14

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

A benchmark run needs a provider key in the environment or in a `.env` beside the
source. The benchmark never reads your own Comodor configuration: every attempt
gets its own workspace, its own `COMODOR_HOME`, and learning switched off.

**Model rule**: where a test genuinely requires a live model, use only the model
the project designates for that purpose. Deterministic fakes cover every case
listed below except the benchmark itself.

---

## The baseline everything else is measured against

**Run this first. Context optimization — plan Phase 4 / tasks Phase 5 — must
not begin until it exists** (SC-036, Constitution XXI).

```bash
python -m bench --dry-run                     # list the suite, run nothing
python -m bench --provider <provider> --model <model> --tries 3
```

Expected: a report in `bench/results/` carrying, per task, the outcome rate
across three attempts **and** its token cost. A token figure without its outcome
rate is not a result.

Record the naive full-resend comparison alongside it. The SC-011 threshold is set
from these numbers and never chosen in advance.

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
2. Confirm the form appears **before** any file is written.
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
python -m pytest tests/test_context_budget.py tests/test_context_dedup.py -q
python -m pytest -m performance -n 0 -q        # ceilings hold
python -m bench --provider <provider> --model <model> --tries 3
```

Expected: token figures fall against the plan Phase 1 baseline (T015) and **no task's outcome
rate falls**. A drop in any outcome rate is a regression and blocks the change,
however large the saving.

### Plan Phase 5 (tasks Phase 6) — learning hardening

```bash
python -m pytest tests/test_learning_admission.py tests/test_learning_staleness.py -q
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

**Web UI** (REQUIRED — [plan.md §Surface Impact](./plan.md); T006, T133, T146):

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

### Plan Phases 7–8 (tasks Phases 9–11) — full validation

```bash
python -m ruff check src tests bench tools
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
| Tokens went down | A paired report showing outcome rates did not |
| Clarification works | The clarification-required outcome (`outcome: unattended`) observed on a surface with no listener, plus the custom row present on every generated form — TUI and Web |
| Learning improved things | Clarifications and corrections trending down over a repeated series, reported only where the sample supports a trend |
| Nothing regressed | The full baseline green on the exact final HEAD, all three platforms |
| A guard holds | Its test fails when the guard is removed and passes when restored |

Anything not demonstrated this way is reported as **NOT VERIFIED**, which is an
acceptable and expected answer.
