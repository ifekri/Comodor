# Feature Specification: Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning

**Feature Branch**: `002-grounded-agent-quality`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Grounded High-Quality Agent with Token-Efficient Context and Progressive Learning" — a product-quality initiative covering output quality, token efficiency, progressive learning, elimination of silent gap-filling, mandatory interactive multiple-choice clarification with a custom-answer row, a completion gate, explicit failure and uncertainty states, observability, and full cross-surface compatibility. Trading features are out of scope; PR #39 is pending external work.

---

## Context: This Is a Brownfield Initiative

Comodor is a mature product. Every goal in this initiative already has a partial
implementation in the repository. This specification therefore describes the
**gaps between what exists and what is required**, and mandates extension of the
existing machinery rather than a parallel architecture (Constitution XVIII).

A capability inventory was taken before this specification was written. It is
recorded in **Appendix A** and is the evidence base for every "extend, do not
duplicate" statement below. Three findings from that inventory shape the whole
specification and are stated here because they change what the work *is*:

**Finding 1 — the clarification path already exists end to end, and already
guarantees the custom-answer row.** A question form is a protocol primitive
(`question.requested` / `question.answer` / `question.resolved`), it is carried
in session snapshots as a pending interaction, it is rendered by the terminal
and the browser, and the mandatory write-your-own row is appended by the core
and cannot be authored or removed by the model. The gap is not the mechanism.
The gap is **when the agent chooses to use it** and **what happens when nobody
is there to answer**.

**Finding 2 — the current no-answer behaviour is precisely the behaviour this
initiative forbids.** When a question form is dismissed, times out, or is raised
where no client is listening, the agent is currently told to *"Choose sensible
defaults, carry on, and say plainly which decisions you made for them."* For a
**mandatory** clarification that is silent gap-filling on every one of those
paths, including the dismissed form: a label on an invented value does not make
it an answer. Removing that instruction from all three paths is a **deliberate,
user-visible behaviour change**, called out under Compatibility (FR-082) and
specified in FR-018, FR-019, FR-022, FR-035, FR-121 to FR-123 and FR-129. The
three paths still differ in the lifecycle outcome they report — that distinction
is preserved — but none of them may supply the missing information.

**Finding 3 — question capability is not the same as tool capability.** Every
real mode, including the conversation-only modes, permits questions, but the
conversation-only modes permit no inspection tools at all. So the rule "inspect
the repository before asking the user" (goal G) cannot be unconditional: in a
mode that may not look, the evidence-first duty is vacuous and the clarification
threshold must differ. Any requirement that ignores this produces an agent that
either refuses to ask in the one mode where it cannot check, or claims to have
checked when it could not.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The agent asks instead of inventing (Priority: P1)

A developer asks for something that a reasonable person could read two ways, or
that depends on a fact the request never states and the repository does not
settle. Instead of choosing a reading and building it, the agent gathers what
evidence it can, and if a genuine decision remains it puts a short
multiple-choice form on screen before it performs any mutation that depends on
that unresolved decision. Every question carries
a row the developer can type their own answer into. The developer answers in
seconds, and the work that follows is built to what they actually meant.

If the developer is not there — a scheduled run, a channel integration, a piped
command — the agent does not pick for them. It reports, in a form the caller can
act on, that a decision is outstanding and what the candidate answers were.

**Why this priority**: This is the difference between a tool that is
occasionally wrong in expensive, invisible ways and one that is trustworthy.
An invented assumption is not merely a defect; it is a defect that looks like a
result, and the developer finds it only after building on top of it. Every other
goal in this initiative is worth less if this one does not hold.

**Independent Test**: Can be fully tested on its own by running requests
containing a genuine unresolvable ambiguity and confirming that (a) the form
appears before any file that depends on the decision is written (SC-002), (b)
every question carries a working
custom-answer row, (c) the answer changes the work produced, and (d) on a
surface with nobody listening, a structured clarification-required outcome is
returned instead of an invented value. Delivers value with nothing else built.

**Acceptance Scenarios**:

1. **Given** a request whose required behaviour cannot be determined from the
   request, the repository, the project configuration, or trustworthy learned
   knowledge, **When** the agent begins work, **Then** it presents a
   multiple-choice form before performing any mutating action that depends on
   the decision, and no such dependent mutation runs unless a valid answer is
   received. If the form is dismissed, cancelled or expires, the decision stays
   unresolved and the dependent mutation does not run (FR-018, FR-019).
2. **Given** a question form is on screen, **When** the developer selects the
   final row and types free text, **Then** that text is carried back to the
   agent as the answer for that question and visibly shapes the resulting work.
3. **Given** a request whose ambiguity *is* settled by a file in the repository,
   **When** the agent begins work in a mode permitted to read, **Then** it reads
   that file, decides, states the decision and its evidence, and does **not**
   raise a question form.
4. **Given** a run on a surface where no client is listening, **When** a
   clarification becomes mandatory, **Then** the run ends in an explicit
   clarification-required outcome naming the open decision and its candidate
   answers, and no invented value is substituted.
5. **Given** the developer dismisses, declines or cancels a **mandatory** form,
   **When** the agent continues, **Then** the decision stays observably
   unresolved: the agent does **not** invent a value, select an option, apply a
   default or proceed on an assumption; it does not re-raise the same form
   during that decision attempt; it reports the unresolved decision; and any work
   depending on that decision does not run.
6. **Given** a mandatory form was cancelled and the developer later supplies the
   answer, **When** they do, **Then** the dependent work resumes from the
   answer — cancellation left it unresolved, not settled.
7. **Given** an ambiguity that does **not** pass the materiality test, **When**
   the agent proceeds, **Then** it may exercise implementation discretion, take a
   reasonable default, and say plainly which choice it made — this path is
   available only to non-material decisions.

---

### User Story 2 - "Done" means done, and is never claimed falsely (Priority: P1)

A developer asks for a change. The agent makes it, and before saying the work is
complete it checks its own claim with evidence proportionate to what it touched:
the project's own check where a file changed, a comparison of the request
against what was actually delivered, and an inspection of whether any part of
the request is still unaddressed. If something is unresolved, the agent says so
in its answer rather than reporting success. If it states that a suite or a
build passes, either it ran one or the answer carries a visible notice that
nothing was run.

**Why this priority**: Shares P1 with Story 1 because they are the same promise
seen from two ends — do not invent an input, do not invent an outcome. A tool
that reports work it did not do devalues every other claim it makes.

**Independent Test**: Testable on its own with tasks that contain a deliberately
unaddressable or partially-addressable element, plus tasks where the project
check fails after the edit. Confirm that completion is never claimed while a
requested element is unresolved, and that an unverified pass-claim is always
either backed by a run or visibly marked.

**Acceptance Scenarios**:

1. **Given** a turn that changed at least one file and a configured project
   check, **When** the agent reaches the end of the turn, **Then** the check
   runs once, and a failure is reported with one opportunity to correct it
   rather than being reported as success.
2. **Given** a request with three distinct requirements of which two were
   implemented, **When** the agent ends the turn, **Then** its answer names the
   third as outstanding and does not describe the task as complete.
3. **Given** an answer stating that tests or a build pass, **When** no command
   was run in that turn and files were changed, **Then** the answer carries a
   notice that nothing was run.
4. **Given** a turn that only read files and answered a question, **When** the
   turn ends, **Then** no project check is run and no verification notice is
   added.
5. **Given** the configured project check cannot be executed at all, **When**
   the turn ends, **Then** that limitation is stated once and the turn's real
   outcome is preserved — the unrunnable check never becomes the turn's failure.

---

### User Story 3 - The agent does not resend or lose what it has established (Priority: P2)

A developer works through an ordinary multi-step task. The agent does not resend
what it has already established: superseded file reads are replaced by a note
that they are stale, oversized tool output is spilled to a retrievable location
rather than pasted or truncated, stable prefixes are arranged so the provider's
cache keeps hitting, and history that has outgrown the window is compacted at a
boundary that never separates a tool call from its result. Token use is
reported by the product's own usage accounting, and no token reduction is
claimed (D15).

**Why this priority**: P2 rather than P1 because a cheaper agent that is wrong is
not a product. Efficiency is graded against a quality floor and is worthless
without Stories 1 and 2 holding.

**Independent Test**: Testable on its own with deterministic tests that drive
the agent with scripted model responses and inspect every assembled request:
the superseded-read sweep, the overflow spill, the stable head and the
compaction boundary each have their own regression tests.

**Acceptance Scenarios**:

1. **Given** a file read at an early step and edited at a later one, **When** the
   next request is assembled, **Then** the superseded copy is not resent and the
   record retains the change that superseded it plus an instruction to re-read
   if current contents are needed.
2. **Given** a tool produces output far above the per-result budget, **When** the
   result is recorded, **Then** the beginning and end are kept with an exact
   pointer to the remainder, nothing is silently discarded, and the omitted
   material remains retrievable.
3. **Given** a sequence of turns in one task, **When** requests are assembled,
   **Then** the portions of the request that did not change are byte-identical
   across turns so that provider-side caching applies.
4. **Given** history that exceeds the configured fraction of the context window,
   **When** compaction runs, **Then** the original request is preserved, the cut
   never separates a tool request from its result, and what was removed is
   represented by a summary rather than dropped.
5. **Given** any token-reducing behaviour, **When** it would omit evidence that
   changes the answer, **Then** it must not be applied — measured by the
   deterministic retention and neutrality tests, which switch optimizations
   off inside the test (D17).

---

### User Story 4 - It stops asking what it has already been told (Priority: P2)

A developer corrects the agent, states a preference, or settles a decision. Later
— in the same project, or in another one where the lesson genuinely travels —
the agent applies what it learned instead of asking again or rediscovering it.
The developer can see everything the agent believes, where each item came from,
and can delete any of it. Nothing the model merely asserted becomes a durable
fact; learning comes from corrections, validated outcomes, counted repository
conventions and explicit statements.

**Why this priority**: P2. It is the compounding value of the product and the
largest structural source of token savings over time, but the product is correct
without it and dangerous if it learns the wrong things.

**Independent Test**: Testable on its own by driving a correction, then issuing a
later request whose correct handling depends on it, and confirming the
correction is applied without re-asking. Inspectability is tested by listing what
was learned, its origin, and deleting an entry.

**Acceptance Scenarios**:

1. **Given** the developer rewrites code the agent produced, **When** the next
   turn begins, **Then** the correction is already in force without the developer
   restating it.
2. **Given** a decision the developer settled through a question form, **When**
   the same decision arises again in the same project, **Then** the stored answer
   is applied and the form is not raised again.
3. **Given** any learned item, **When** the developer inspects the agent's
   memory, **Then** each item shows what it is, where it came from, and its
   scope, and can be deleted individually.
4. **Given** a statement the model produced that no tool, correction or
   repository fact confirms, **When** learning runs, **Then** it is not stored as
   a durable fact.
5. **Given** a learned item about a repository fact, **When** that repository
   fact changes, **Then** the item stops being applied — it is superseded or
   marked stale rather than silently continuing to shape answers.
6. **Given** knowledge learned in project A, **When** the agent works in
   unrelated project B, **Then** project-scoped knowledge from A is not applied
   in B.
7. **Given** two corrections that contradict each other, **When** both are
   present, **Then** the more recent one governs and the superseded one is
   recorded as superseded rather than both being applied.

---

### User Story 5 - When it cannot do the thing, it says so (Priority: P3)

The agent hits a wall: a tool fails, a service is unreachable, the repository is
only partly accessible, a capability is not supported, or the evidence in the
project contradicts itself. It reports the actual limitation and what it did
establish, rather than producing a plausible result that conceals the wall.

**Why this priority**: P3. It generalises Stories 1 and 2 to the failure path.
Lower priority only because those two cover the highest-frequency cases.

**Independent Test**: Testable on its own by injecting each failure class and
confirming the reported outcome names the real limitation and contains no
fabricated result.

**Acceptance Scenarios**:

1. **Given** a tool call fails, **When** the agent continues, **Then** the answer
   distinguishes what was established from what the failure left unknown.
2. **Given** two sources of project evidence that contradict each other, **When**
   the contradiction bears on the decision, **Then** the agent reports the
   conflict rather than silently preferring one.
3. **Given** an external service is unavailable, **When** the task depended on
   it, **Then** that unavailability is the reported outcome — not a result
   synthesised without it.
4. **Given** a requested capability the product does not support, **When** the
   agent responds, **Then** it says so plainly instead of simulating the
   capability.
5. **Given** a destructive action whose target is ambiguous, **When** the agent
   would otherwise act, **Then** it stops and asks (Story 1) rather than picking
   a target.

---

### User Story 6 — retired (D14)

*Retired 2026-09-28 (D14).* Its telemetry-redaction scenario remains required
by FR-074.

---

### Edge Cases

**Clarification lifecycle**

- Several questions are outstanding at once: they are presented as one form in a
  single round trip, not as a sequence of interruptions. That holds even when one
  model reply raises them through several calls (D18). With more than four,
  the client shows the one form in pages of at most four, and it is answered
  once (D19). A second form is not raised while one is unanswered.
- The developer cancels or declines a mandatory form: recorded as *cancelled*,
  which is distinct from *nobody was there* and from *answered*. Cancellation
  does **not** supply the missing information, so the decision stays unresolved,
  dependent work does not run, and the agent does not re-raise the same form
  during that decision attempt. A later request from the developer may answer or
  resume it.
- The form times out: the outstanding request is closed and observably expired.
  Expiry is not an answer either — the decision stays unresolved on the same
  terms as cancellation, and no client is left showing a card for a request that
  is no longer live.
- A mandatory clarification arises where nobody is present to answer (a
  scheduled run, a channel, a piped command, an API caller with no listener):
  no form is waited out and no answer is supplied. The run ends in the
  clarification-required outcome with lifecycle outcome `unattended`, naming the
  open decision by its decision reference, and no dependent work runs
  (FR-033, FR-034, FR-121).
- A material unknown becomes known only after the turn has already changed
  files (late discovery): from that moment no further mutation that may depend
  on it runs; the earlier changes are neither denied nor silently rolled back;
  they are disclosed in the clarification-required outcome as prior changes;
  and nothing reports or implies that the workspace is unchanged (FR-013).
- The client disconnects and reconnects mid-form: the outstanding form is
  restored from the session snapshot's pending interaction so the developer sees
  it again rather than losing it.
- An answer arrives for a form that is no longer outstanding (stale, expired, or
  already answered): it is ignored, not applied, and never applied to a
  *different* question that happens to occupy the same position.
- Two answers arrive for the same form: the first to be claimed wins and the
  second is discarded; the outcome is never applied twice.
- A later resumption answer carries a decision reference that is unknown,
  malformed, stale (the decision is already resolved), or missing where one is
  required: it is rejected as invalid, applied to no decision, and never
  matched to another decision by recency, position, similarity or order. No
  dependent work is authorised, every unresolved decision stays unresolved, and
  the caller is told the reference could not be resolved (FR-026, FR-129).
- An answer names an option that does not exist, or omits a required field: it is
  rejected as invalid and the form remains outstanding rather than a malformed
  answer being coerced into a choice.
- Questions are reordered between request and answer: answers are matched by each
  question's stable name, never by position.
- The developer switches model while a form is outstanding: the form survives;
  the answer applies to the work, not to the model that raised it.
- A background or delegated agent needs a clarification: it reaches the same
  person through the same mechanism, tagged with its origin so it is not
  mistaken for the parent's own question, and it is never injected into the
  middle of the parent's turn.
- A conversation-only mode (no inspection tools) raises a clarification: it may
  ask, but it must not claim to have checked the repository first.
- The session transcript is exported: the form and its answers appear as what
  they were, so the record shows what the agent was told.

**Token efficiency**

- Compaction would have to cut between a tool request and its result: it must cut
  elsewhere; an orphaned tool call is rejected outright by providers.
- The original request would be compacted away: it is always preserved.
- A single tool result alone exceeds the whole budget: it is spilled and pointed
  at, never truncated into silence.
- A file is read twice and never edited: not rewritten, because the rewrite costs
  more cache than the duplicate costs tokens.
- An efficiency measure would alter a stable prefix mid-task: it must not, since
  the cache saving exceeds what the measure could recover.

**Learning**

- A correction contradicts a stored fact: the newer governs; the older is marked
  superseded, not deleted silently.
- Stored knowledge refers to a file that no longer exists: it stops being
  applied.
- The store reaches its cap: a further addition is refused with the current
  contents shown, rather than an existing item being silently evicted.
- Learning is switched off: no durable learning occurs and behaviour is
  reproducible.
- Untrusted text (a file, a web page, a tool result) contains something shaped
  like an instruction or a fact: it is not admitted as learned knowledge on that
  basis.

**Failure and uncertainty**

- The project check is configured but missing: reported once; the turn's real
  outcome stands.
- The repository is partly inaccessible: the answer states which parts were not
  inspected rather than implying full coverage.
- Cancellation arrives mid-turn: it takes effect at the next existing cooperative
  step/tool cancellation boundary and no partial result is reported as complete.

---

## Requirements *(mandatory)*

Requirements are written as product behaviour. Where an existing subsystem
already owns a behaviour, the requirement is to extend it; Appendix A records
which subsystem, so that "extend, do not duplicate" is checkable at review.

**Surface classification (Constitution XI).** This table is the normative
classification of the ten canonical product surfaces, in canonical order. Each
surface has exactly one of REQUIRED, UNCHANGED BUT VERIFIED or NOT APPLICABLE.
[plan.md §Surface Impact](./plan.md) may carry implementation-level detail
(tasks, files, validation), but it must agree with this table and cannot
override it.

| Surface | Status | Requirements | Evidence |
| --- | --- | --- | --- |
| TUI | REQUIRED | FR-017, FR-020, FR-031 | The terminal question overlay (`apps/tui/src/App.tsx`, shared form reducer `packages/questions`) renders every form with the system-appended custom-answer row (FR-017). Where negotiated, it shows each question's reason and the evidence consulted (FR-020). It must be fully and deterministically keyboard-operable (FR-031). The committed terminal bundle it ships as must be rebuilt to match its source (Constitution VII). D18, D19: one model reply's questions arrive as one form, shown one question at a time with its position in the form and submitted once (FR-082 change 4, breaking for form-count consumers). The overlay already pages a form this way, so D18 and D19 change no TUI source and leave the committed bundle as it is; renderer tests prove the behaviour. |
| Web UI | REQUIRED | FR-017, FR-019, FR-035, FR-079, FR-123 | The browser page (`src/comodor/web/session.py`, `src/comodor/web/ui.js`) is a live question surface. It carries forms and the custom-answer row. A dismissal there is the clarification outcome `cancelled` and never lets the agent choose a default (FR-019, FR-035). A clarification-required stop is never shown as completion or as a cancelled turn (FR-123). Existing answered-question behaviour is preserved (FR-079). D18, D19: one model reply's questions arrive as one form, shown in pages of at most four and submitted once; answers bind by header (FR-082 change 4). |
| CLI / Headless | REQUIRED | FR-033, FR-034, FR-121, FR-123, FR-129 | A piped or scheduled `comodor run` blocks on a mandatory clarification and returns the structured clarification-required outcome, with its `decision_ref`, distinct from both success and failure (FR-033, FR-034, FR-121, FR-123). A later invocation resumes the decision only through an explicit `decision_ref`; an unresolvable one is rejected (FR-129). D18, D19: a scripted `--interactions` entry applies to exactly one logical form. A multi-entry script names each entry's headers; a bare `answer` is rejected before the run; and an unmatched or leftover entry ends the run with exit `1` and a clear error — it is never applied to a later form (FR-082 change 4, breaking; migration in D19). |
| API / Protocols | REQUIRED | FR-020, FR-079, FR-080, FR-123, FR-129 | Protocol v2 gains only additive, negotiated question fields and the negotiated clarification-required outcome (FR-080), and no existing message changes meaning (FR-079). The OpenAI-compatible API keeps standard `finish_reason` values and carries the distinct state in Comodor's extension (FR-123). API and agent-to-agent resumption carries an explicit `decision_ref` (FR-129). A client that negotiates nothing behaves as today, apart from FR-082's intended changes (SC-023). D18, D19 change no message shape or meaning. A protocol v2 interactive client receives a reply's questions as one live pending question of any length, which it pages and answers once. The OpenAI-compatible API and ACP have no live form: they return one clarification-required payload listing every decision, and resume through `decision_answers` keyed by `decision_ref`, in parts if needed (FR-082 change 4; clients that assumed at most four accept more). |
| Desktop | NOT APPLICABLE | — | No desktop application exists: `docs/desktop-architecture.md` opens "Planned, not built. Nothing in this document exists in the repository", and there is no `src-tauri/` or `apps/desktop/`. `src/comodor/desktop/` is the computer-use tool's screen and pointer backend: it imports none of the question, clarification or turn-outcome machinery, and it presents no question and no turn outcome. As a tool it is governed by the Security / Authorization row. |
| Channels / Integrations | REQUIRED | FR-121, FR-123 | Channel integrations (`src/comodor/channels/`) run turns with nobody at a form. A mandatory clarification ends in a message naming the open decision and its lifecycle outcome, never in an invented value or a crash (FR-121, FR-123). D18, D19: an unattended reply ends in one clarification-required payload naming every decision and its `decision_ref`, however many questions it holds. |
| Docker / Packaged Runtime | REQUIRED | FR-078; Constitution VII | The wheel, sdist and container image ship the terminal bundle, which changes with the TUI row and must be rebuilt from source. This feature does not change the container configuration (`Dockerfile`, `docker-compose.yml`); the only `docker-compose.yml` change on this branch came from `main` with the retired-provider removal (PR #60). Everything works on Windows, Linux and macOS (FR-078). |
| Persistence / Shared State | REQUIRED | FR-023, FR-030, FR-057, FR-059, FR-081, FR-112, FR-129 | Durable learned items gain provenance, scope, status and supersession (FR-057, FR-059, FR-112). An outstanding form survives reconnect through the session's pending-interaction state (FR-023) and appears in transcripts and exports (FR-030). An unresolved decision stays resolvable by its `decision_ref` (FR-129). Sessions and knowledge written before the change stay readable (FR-081, SC-024). |
| Security / Authorization | REQUIRED | FR-066, FR-074, FR-117, FR-118, FR-120 | The authorization policy itself is preserved unchanged. Advertised and enforced capabilities derive from one rule, an unknown mode still fails closed, and clarification never becomes a route to an action the mode forbids (FR-117, FR-118, FR-120; Assumptions). The feature adds security requirements on top: untrusted text is never admitted as learned knowledge (FR-066), and recorded measurements carry no credentials (FR-074). |
| Tests / Documentation | REQUIRED | SC-022, SC-025, FR-082 | Every guard needs a deterministic, mutation-checked regression test (SC-025), and the full suite must pass on all three platforms on the exact commit under review (SC-022). User documentation must describe the new question, headless-outcome and learning behaviour, and changes 1 and 4 of FR-082 must be stated in release notes, change 4 with D19's migration path (FR-082, D18, D19). |

No surface is classified UNCHANGED BUT VERIFIED. The one NOT APPLICABLE surface
(Desktop) carries its evidence in its row.

**Operational definitions.** The terms below are normative. Every use of the
term in this specification carries the meaning given here.

- **High-quality output**: output in which every consequential claim, change
  and completion statement is supported by, and consistent with, the evidence
  classes quality is judged against: (1) the user's actual request and stated
  constraints; (2) repository evidence observed through a tool; (3) project
  conventions and configuration; (4) the applicable specification and
  contracts; (5) observable runtime behaviour; (6) tests and checks actually run
  in the session or whose results were supplied; (7) recorded validation
  evidence. Output is not high-quality merely because it compiles, because tests
  pass, or because it is stated confidently. Quality is observed through the
  success criteria: no fabricated values or unmarked pass-claims
  (SC-002 to SC-004) and clarification correctness (SC-005 to SC-010,
  SC-037 to SC-044).
- **Material / materially** (FR-007): a decision is material only when there
  are at least two plausible, grounded resolutions and choosing one instead of
  another can produce a different observable or contractual outcome in at least
  one FR-007 class. "Can materially change" means exactly that. A difference is
  **non-material** when every grounded alternative satisfies the same explicit
  user intent, compatibility contract and acceptance criteria, and differs only
  in internal implementation detail. Normally non-material, when no other
  requirement makes them material: private helper structure, local variable
  naming, equivalent internal decomposition, an equivalent implementation
  mechanism, and formatting or internal organisation that does not alter an
  interface. The class "the requested behaviour" does not make every
  implementation choice material; it applies only when the user-visible or
  requested result differs. Where the system cannot determine whether competing
  readings are materially equivalent, FR-130 applies: the decision is material
  and is clarified.
- **Implementation discretion** (FR-012): exists when **all** grounded
  alternatives satisfy the explicit request, satisfy repository and
  specification constraints, preserve compatibility, preserve security and
  persistence semantics, meet the same acceptance criteria, and do not cross the
  materiality threshold above. The agent may choose among them without asking.
- **Missing product intent** (FR-012): exists when two or more grounded
  interpretations remain, the repository, configuration and trustworthy stored
  knowledge do not settle them, and choosing between them changes a material
  outcome. It is a mandatory clarification. Where the classification itself is
  ambiguous, material wins and the clarification is raised (FR-130).
- **Relevant / relevance**: information or evidence is relevant when it can
  change, support, refute or validate an active requirement, decision,
  completion claim, or affected-surface judgement for the current task.
  Information that only repeats an already-settled fact and cannot affect the
  current decision is not relevant merely because it is topically similar.
- **Affected surface**: any behaviour, contract or canonical product surface
  whose code, configuration or data the turn changed.
- **Proportionate validation** (FR-042): the smallest set of checks that
  directly exercises the changed behaviour, the affected contracts and
  surfaces, and the repository-mandated quality gates applicable to the change.
  A repository-wide gate that project policy requires — including the project's
  own configured check of FR-038 — remains in scope even when its individual
  tests are broader than the changed file. An optional suite with no coverage of
  the change, of an affected surface, or of a mandatory repository gate is
  **unrelated**, and is not run merely for volume.
- **Trustworthy stored knowledge** (FR-008): a stored item is trustworthy for a
  decision only when it was admitted from a source FR-056 allows, is active, is
  correctly scoped to the current user or project, is neither stale nor
  superseded, is not contradicted by current repository or tool evidence, and is
  attributable to its provenance. Similarity or age alone does not make stored
  knowledge trustworthy.
- **Explicit completion claim** (FR-125): a statement in the answer that
  asserts, without qualification, that the requested task — or a named requested
  element — is done, complete, fixed, implemented or working. Hedged, negated,
  conditional and instructional sentences are not completion claims.
- **Information origin** (FR-001) and **evidence lifecycle state** are two
  separate axes and MUST NOT be conflated. The *origin* says how an item became
  known and is exactly one of FR-001's five categories: stated by the user;
  verified from the repository or a tool; established project or user
  knowledge; deterministically derived; unknown. The *lifecycle state* says
  where an item or decision stands during the turn: `KNOWN`, `VERIFIED`,
  `DERIVED`, `UNKNOWN`, `REQUIRES_CLARIFICATION`, `UNRESOLVED`, `BLOCKED`,
  `VALIDATED` or `FAILED`. An item has one origin and, at any moment, one
  lifecycle state. The two sets are not counted together, and one lifecycle
  state may be reached from more than one origin (for example, `KNOWN` from a
  user statement or from established knowledge). Lifecycle state names are never
  used as origin values.
- **VERIFIED** (lifecycle state): directly observed or established from
  evidence — a tool result, a file read, or source inspected in the session.
- **VALIDATED** (lifecycle state): checked against the delivered work or the
  relevant acceptance or check mechanism by the completion gate. Observing a
  fact (`VERIFIED`) never by itself makes the delivered work `VALIDATED`, and the
  two states are never collapsed.
- **Decision reference** (`decision_ref`): the stable identifier of one open
  material decision. It identifies the decision itself across every
  clarification lifecycle instance raised for it. A form or question request has
  its own lifecycle identifier (FR-020), which is not a substitute for the
  decision reference.

### Epistemic state and grounding

- **FR-001**: The system MUST classify every item of information it relies on for
  a consequential decision as exactly one of: stated by the user; verified from
  the repository or a tool; established project or user knowledge; deterministically
  derived from one of the preceding; or unknown. These five are
  *information-origin* categories. They are not evidence lifecycle states
  (see Operational definitions), and an item's origin is recorded separately
  from its lifecycle state.
- **FR-002**: The system MUST NOT convert an unknown into an assumed value in
  order to continue. An unknown is either resolved by evidence, resolved by
  asking, or reported as unresolved. The rule is mechanical: an item may be
  recorded as deterministically derived only when every premise it rests on is
  itself stated by the user, verified, established knowledge or deterministically
  derived — **a derivation that rests on an unknown is refused**, so an unknown
  can become usable only by being observed, stated, answered or validly derived,
  never by being needed. The non-material discretion of FR-003, FR-011 and
  FR-130 is not an exception to this rule and not a fourth way out of it: it does
  not turn an unknown premise into a fact. The unknown stays unknown, and what
  the agent records is its own choice between alternatives that the materiality
  test found equivalent, labelled as an assumption. That choice is never
  available for a material decision.
- **FR-003**: When the system proceeds on an assumption it chose itself, it MUST
  state that assumption in its answer, identifiably as an assumption rather than
  as a finding. **This applies only to decisions that do not pass the materiality
  test of FR-007.** A decision that passes that test is a mandatory
  clarification, and FR-019 forbids resolving it by assumption regardless of how
  clearly the assumption is stated. Stating an assumption is never a substitute
  for asking.
- **FR-004**: The system MUST NOT assert that a file, symbol, interface,
  command, configuration value or repository state exists unless it was observed
  through a tool, stated by the user, or read from the project.
- **FR-005**: The system MUST NOT assert that a test, build, lint or check passed
  unless that check was executed in the session or its result was supplied.
- **FR-006**: Where a claim of a passing check appears in an answer, files were
  changed in that turn, and no command was run, the answer MUST carry a visible
  notice that nothing was run. The notice MUST NOT fire where a command was run,
  where no file changed, or where the sentence is hedged, negated, or an
  instruction.

### When to ask, and when not to

- **FR-007**: Clarification MUST be treated as mandatory when unresolved
  uncertainty can materially change any of: the requested behaviour;
  architecture; data loss; security; compatibility; an API or protocol contract;
  user-visible interface behaviour; a destructive operation; a release action; an
  external side effect; or persisted state. "Can materially change" has the
  operational meaning given under **Material** in Operational definitions: at
  least two plausible, grounded resolutions whose choice changes the delivered
  behaviour or one of these eleven effects. "The requested behaviour" counts
  only when the user-visible or requested result differs, never merely because
  an internal implementation choice differs.
- **FR-008**: Clarification MUST NOT be raised for a decision that is settled by
  the request itself, by the repository, by project configuration, or by
  trustworthy stored knowledge (as defined in Operational definitions).
- **FR-009**: In a mode permitted to use inspection tools, the system MUST
  inspect the available evidence before raising a clarification, and the
  question MUST concern what that inspection could not settle.
- **FR-010**: In a mode not permitted to use inspection tools, the system MUST
  still be able to raise a clarification, and MUST NOT claim to have inspected
  evidence it was not permitted to gather.
- **FR-011**: Clarification MUST NOT be raised to request permission to proceed,
  to have a plan confirmed back, or to settle a matter with an obvious default;
  where an obvious default exists the system MUST take it and say that it did.
- **FR-012**: The system MUST distinguish implementation freedom it may exercise
  alone from missing product intent it must ask about, and MUST NOT ask about the
  former. The two are defined in Operational definitions as **Implementation
  discretion** and **Missing product intent**; a decision that fits neither
  definition cleanly is treated as missing product intent (FR-130).
- **FR-130**: FR-003, FR-011 and FR-012 govern agent discretion over
  **non-material** implementation details only. None of them may be invoked to
  settle, downgrade or bypass a decision that passes the materiality test of
  FR-007. Where the two readings compete, the decision is treated as material and
  the clarification is raised.
- **FR-013**: Where clarification is mandatory, the system MUST raise it before
  performing any mutating action that depends on the unresolved decision. Where
  the material unknown becomes known only after the turn has already changed
  files (late discovery), the rule applies from that moment on: no further
  mutation that may depend on the decision runs; mutations completed before it
  became known are neither denied nor silently rolled back; they are disclosed as
  prior changes in the clarification-required outcome; and nothing reports or
  implies that the workspace is unchanged.

### The clarification interaction

- **FR-014**: All clarifications outstanding at one decision point MUST be
  presented together as a single form in one round trip, rather than as
  successive individual questions. A client MAY show the form in pages of at
  most four questions. Pages are not separate forms, and the form is answered
  in one submission (D19).
- **FR-015**: Every question MUST present grounded candidate answers whenever
  meaningful alternatives can be enumerated, each with a label choosable at a
  glance and a description of what choosing it would mean.
- **FR-016**: Candidate answers MUST NOT be invented or misleading; each MUST be
  a realistic reading of the request or a convention observable in the project.
- **FR-017**: Every question MUST end with a final row meaning "Other — enter a
  custom answer", which the system appends and which the model can neither
  author nor remove. Selecting it MUST allow arbitrary free text, and that text
  MUST be carried back as the answer to that question.
- **FR-018**: Work that depends on an outstanding question MUST be paused while
  it is outstanding. **Only a valid answer may resume that dependent work.**
  Cancellation, decline and expiry end the wait without supplying the
  information, so the dependent path MUST remain unresolved or terminate — it
  MUST NOT continue. Work MAY continue only where it is demonstrably independent
  of the open decision; where dependency is uncertain, the work is treated as
  dependent. Independent work is **permitted, not mandatory**: an outstanding
  clarification MUST NOT by itself prohibit work that is demonstrably
  independent of the unresolved decision, but the system is not required to
  start unrelated work merely to remain active, and an unanswered clarification
  is never bypassed because independent work happened. "Independent work is not
  blocked" means it is eligible to proceed, not that it must be executed. On a
  non-interactive surface the run MAY finish already identified, bounded
  independent work before returning the clarification-required outcome
  (FR-123), and MUST NOT begin speculative unrelated work merely to delay that
  stop.
- **FR-019**: The system MUST NOT answer a question on the user's behalf. A
  required clarification that is unanswered, declined, cancelled, expired or
  unattended MUST NOT be converted into a default, an option selection, an
  invented value or a stated assumption. There is no outcome of a mandatory
  clarification, other than a real answer, that authorises the agent to supply
  the missing information itself.
- **FR-020**: Each form and each question within it MUST carry a stable
  identifier, and answers MUST be matched to questions by that identifier rather
  than by position. That identifier belongs to one clarification lifecycle
  instance. Every material decision additionally carries a stable decision
  reference (`decision_ref`, Operational definitions) that survives across
  lifecycle instances. Wherever the clarification capability is negotiated
  (FR-080), each question raised for a material decision MUST carry its
  `decision_ref`, its reason (the FR-007 materiality class that made it
  mandatory) and the evidence already consulted (FR-009), so the user is never
  asked to repeat inspection the agent already did. A client that does not
  negotiate the capability receives the question unchanged.
- **FR-021**: A form MUST be able to express both single-choice and
  multiple-choice questions, and the answer MUST record which options were chosen
  and any free text written.
- **FR-022**: Cancellation MUST be represented distinctly from "answered with
  nothing", and both MUST be distinct from expiry. **None of the three resolves
  the decision.** Cancellation is a lifecycle outcome, not an information
  outcome: the open decision it belonged to stays unresolved, and the system MUST
  be able to report which of the three occurred without any of them implying that
  the required information was obtained.
- **FR-129**: A mandatory clarification the user explicitly cancelled MUST NOT be
  re-raised during the same decision attempt. The agent MUST report the
  unresolved decision instead. A later explicit request from the user MAY resume
  or answer it. A later answer resumes a decision **only** by being explicitly
  associated with that decision's `decision_ref`. It MUST NOT be matched to an
  unresolved decision by list position, by "most recent question", by textual
  similarity, by taking the first unresolved decision, or by any other heuristic
  inference. When the original form has expired or been cancelled, its lifecycle
  identifier is stale, but the decision stays unresolved under its
  `decision_ref`. A later explicit answer associated with that `decision_ref`
  resolves it and permits dependent work to resume. Where an interactive pending
  form still exists, the existing answer path makes this association itself,
  because it already knows the `decision_ref`. On headless, API and other
  subsequent-invocation surfaces, the structured resumption input MUST carry the
  `decision_ref` explicitly. No second clarification mechanism is introduced for
  this. A resumption answer whose `decision_ref` cannot be resolved to the
  intended open decision — unknown, malformed, stale (the decision is no longer
  open), or otherwise unresolvable — is an **invalid resumption answer** under
  FR-026. It MUST be rejected and applied to no decision. It MUST NOT be matched
  to another decision by any means — the most recent decision, list position,
  textual similarity, the first unresolved decision, or any other heuristic — and
  it MUST NOT authorise dependent work. Every unresolved decision stays
  unresolved, and the caller is told that the supplied decision reference could
  not be resolved. A resumption answer with no `decision_ref`, on a surface where
  explicit resumption requires one, is invalid on the same terms. None of this
  applies to an answer given through an interactive pending form, whose existing
  transport already carries the decision association (FR-020, FR-024). How the
  rejection is represented on each surface is left to planning; no new wire-level
  error value is required by this specification.
- **FR-023**: An outstanding form MUST survive client disconnection and be
  restored to a reconnecting client from the session's pending-interaction state.
- **FR-024**: An answer to a form that has expired, been cancelled, or already
  been answered MUST be ignored, and MUST NOT be applied to any other form or
  question. An answer addressed to a form's lifecycle identifier binds only to
  that form. It never becomes a resumption answer for the decision that form
  asked about; resumption happens only through FR-129's explicit `decision_ref`
  association.
- **FR-025**: Duplicate answers to the same form MUST resolve to exactly one
  applied answer.
- **FR-026**: An answer that names an unknown option or omits a required field
  MUST be rejected as invalid without being coerced into a valid choice. This
  includes a resumption answer whose `decision_ref` is missing where one is
  required, or cannot be resolved to the intended open decision (FR-129). Such
  an answer is not redirected to any other decision.
- **FR-027**: A form MUST have a bounded wait, after which it expires; expiry
  MUST be published so no client continues to present a decision already taken.
- **FR-028**: An outstanding form MUST remain valid across a change of model
  during the wait.
- **FR-029**: A clarification raised by a background or delegated agent MUST
  reach the user through the same mechanism, MUST be attributable to its
  originating work, and MUST NOT be injected into the middle of another turn.
- **FR-030**: Questions and their answers MUST appear in the session transcript
  and in exports as what they were.
- **FR-031**: The terminal form MUST be fully operable from the keyboard —
  moving between questions and options, choosing, toggling in multiple-choice,
  entering custom text, sending, and closing — and MUST indicate which questions
  remain unanswered without requiring the user to visit each. Keyboard behaviour
  MUST be deterministic: the same key sequence applied to the same form state
  yields the same result, with no dependence on timing, delays or sleeps.
- **FR-032**: The clarification mechanism MUST remain available in every mode
  that permits questions, including conversation-only modes.

### Non-interactive surfaces

- **FR-033**: Where a mandatory clarification arises and no client can answer,
  the system MUST produce an explicit, structured clarification-required outcome
  rather than selecting an answer.
- **FR-034**: That outcome MUST identify the decision, the candidate answers, and
  what evidence was already consulted, sufficiently for the caller to answer it
  in a subsequent invocation. "Sufficiently" means that the structured outcome
  carries, at minimum, for every open decision: its `decision_ref`; the
  decision, stated so it can be answered without re-reading the request; the
  candidate answers (possibly empty, never invented); the evidence consulted;
  the reason (the FR-007 materiality class); and the clarification lifecycle
  outcome (FR-035). Where earlier mutations occurred, it also carries the prior
  changes (FR-013). A caller answers in a later invocation by supplying an
  answer explicitly associated with a `decision_ref` (FR-129).
- **FR-035**: The system MUST distinguish the **three** ways a mandatory
  clarification can end without an answer. The distinction is in the **reported
  lifecycle outcome only** — it is never a difference in permission to guess.
  All three report the **same single top-level outcome** —
  `clarification_required` — and are told apart by a clarification-lifecycle
  discriminator carried inside the structured clarification payload:
  - Explicit cancellation or decline/dismissal → clarification outcome
    `cancelled`.
  - Expiry → clarification outcome `expired`. This MUST remain distinguishable
    from cancellation/decline (FR-022).
  - Nobody present → clarification outcome `unattended`.

  An actual answer produces no clarification stop at all: it resolves the
  decision and dependent execution resumes.

  **The clarification payload is the layer that carries this distinction, never
  the turn outcome.** The turn-level cancelled outcome retains its existing
  meaning exclusively — the whole agent turn was cancelled or interrupted — and
  MUST NOT be reused for a dismissed question. A turn-level cancellation and a
  question-level dismissal are different events and remain separately reportable.

  All three are equal in every respect that matters to correctness. Under each
  one: the required information remains **unsupplied**, the open decision remains
  **unresolved**, **no dependent work runs**, and **no default, assumption,
  selected option or invented value may be produced** (FR-018, FR-019). None of
  them is an answer. Only a real answer resolves the dependency, whether it
  arrives during the original wait or later (FR-129).

  Existing representations are reused wherever they already carry the
  distinction; **no new state is introduced where an existing one already
  expresses the case unambiguously**. Where an existing representation cannot yet
  express the distinction, the gap is closed additively and under negotiation
  (FR-080), never by collapsing expiry into cancellation.
- **FR-121**: **All** non-interactive surfaces MUST block on a mandatory
  clarification — scheduled runs, channel integrations, the piped command line,
  the API and agent-to-agent invocation alike. There is no surface on which a
  material unknown may be filled with an invented value. This implements
  Constitution XV directly.
- **FR-122**: The materiality test of FR-007 is what makes a clarification
  mandatory and therefore blocking. A decision that does not meet it is not
  escalated, so blocking remains confined to decisions that genuinely change the
  outcome, and routine automation is unaffected.
- **FR-123**: A run that ends in the clarification-required outcome MUST
  terminate with a distinct, machine-readable outcome that a caller can tell
  apart from both success and failure, so a scheduler or integration can route
  it for an answer rather than retrying it as an error. On every surface that
  speaks a protocol with its own enum, the distinct outcome is carried in
  Comodor's own extension (`stopped = "clarification_required"` and the
  structured `clarification` block) rather than by inventing a value in the
  foreign enum; on the OpenAI-compatible envelope that means
  `finish_reason = "stop"` plus `comodor.stopped` and `comodor.clarification`
  (contracts §C4). Ending the run this way is consistent with FR-018: the run
  MAY first finish already identified, bounded work that is demonstrably
  independent of the open decision. It MUST NOT start speculative unrelated work
  to delay the stop, and it MUST NOT run any work that depends on the decision.

### Completion gate

- **FR-036**: Before reporting a task complete, the system MUST compare what was
  requested against what was delivered and MUST NOT report completion while a
  requested element is unresolved.
- **FR-037**: Unresolved elements MUST be named individually in the answer,
  with what blocked each.
- **FR-038**: Where a turn changed at least one file and the project defines its
  own check, that check MUST be run once before completion is reported.
- **FR-039**: A failing check MUST be handed back with one opportunity to
  correct it, and MUST NOT be retried indefinitely.
- **FR-040**: Verification MUST be bounded in time and MUST NOT be able to hang a
  turn indefinitely.
- **FR-041**: A check that cannot be executed MUST be reported as such once, and
  MUST NOT convert an otherwise successful turn into a failure.
- **FR-042**: Verification effort MUST be proportionate to what the turn touched;
  the system MUST NOT run validation unrelated to the affected surface.
  "Proportionate", "affected surface" and "unrelated" have the meanings given in
  Operational definitions. FR-042 and FR-038 therefore agree: the project's own
  configured check that FR-038 requires after a file-changing turn is a
  repository-mandated gate. It is never "unrelated" merely because it is
  repository-wide. What FR-042 excludes is an optional suite with no coverage of
  the change, of an affected surface, or of a mandatory gate.
- **FR-043**: A turn that changed nothing MUST NOT trigger project verification.
- **FR-124**: The completion gate's default authority is to **annotate**: an
  answer with unresolved work is delivered with that work named beside it, and
  the user is never denied a result the agent did produce.
- **FR-125**: The gate MUST **block** in exactly one case — the answer
  explicitly claims the task is complete and the gathered evidence contradicts
  that claim. In that case the answer MUST be corrected to state the work as
  incomplete before it is delivered. "Explicitly claims" means an **explicit
  completion claim** as defined in Operational definitions. An answer that
  reports the task, or a requested element, as done while that element is
  unresolved is contradicted by that fact alone.
- **FR-126**: An honest partial answer — one that does not claim completion —
  MUST NOT be blocked, so the gate targets the false claim rather than
  incompleteness itself.
- **FR-127**: Blocking MUST cost at most one additional correction turn, and a
  gate that cannot reach a verdict MUST fall back to annotating rather than
  withholding the answer indefinitely. The fallback never makes an unsupported
  completion statement acceptable. Where the gate cannot establish support for
  an explicit completion claim — because it cannot reach a verdict, or because
  the one correction turn still produced a completion claim — the system MUST
  NOT deliver that claim as completed. The annotation states that completion is
  not confirmed and names the outstanding or unverifiable work, so the delivered
  answer as a whole does not report the task as complete (FR-036). A failed
  correction turn never licenses a false completion claim. The answer the agent
  produced is still delivered (FR-124).

### Token efficiency

- **FR-044**: Token reduction MUST NOT be achieved by omitting information
  required for correctness, weakening validation, skipping relevant inspection,
  suppressing a warranted clarification, truncating critical evidence, or
  replacing verified content with an unsupported summary.
- **FR-045**: A file read that a later change has superseded MUST NOT be resent;
  what remains MUST record that it is stale, retain the change that superseded
  it, and state that the file can be re-read if current contents are needed.
- **FR-046**: The newest read of a file, and any read of a file nothing has
  written to, MUST NOT be rewritten.
- **FR-047**: Tool output exceeding its budget MUST be preserved in full
  somewhere retrievable and represented in the conversation by its beginning, its
  end, and an exact pointer to the remainder. It MUST NOT be silently truncated.
- **FR-048**: Output that was already a file on disk MUST be pointed at in place
  rather than copied.
- **FR-049**: Where history exceeds the configured fraction of the context
  window, it MUST be compacted at a boundary that leaves no tool request without
  its result, and the original request MUST always be preserved.
- **FR-050**: The stable portions of a request MUST remain byte-identical across
  turns within a task so provider-side prefix caching applies, and no efficiency
  measure may alter them mid-task for a smaller saving.
- **FR-051**: Context MUST be selected by relevance against an explicit budget
  rather than by inclusion of everything available.
- **FR-052**: Content already established in the conversation MUST NOT be
  re-sent verbatim merely to restate it; a reference to it MUST be sufficient.
- **FR-053**: Delegated work MUST return its conclusion rather than the material
  it read, so that reading performed for a sub-question does not enter and
  persist in the parent conversation.
- **FR-054**: Resuming a session MUST NOT re-send material the resumed
  conversation already carries.
- **FR-055**: Token consumption MUST be measurable per task and per turn,
  separated into what was sent, what was generated, and what was served from
  cache.

### Token efficiency: behaviour required per class of content

Each class below is carried differently and wastes tokens differently. A single
blanket rule would either lose evidence in one class or save nothing in another.

- **FR-086**: **Conversation history** — history that has outgrown its budget
  MUST be represented by a canonical summary that preserves the original
  request, every decision taken, and every outstanding commitment. The summary
  MUST identify what it replaced, so the user can see what was condensed.
- **FR-087**: **File contents** — a file MUST NOT be carried in full where only
  a part is relevant to the work in hand, and MUST NOT be carried at all once a
  later change has superseded it (FR-045).
- **FR-088**: **Diffs** — where a file has changed, the change itself MUST be
  the carried representation rather than the file before and the file after.
- **FR-089**: **Tool results** — results MUST be carried in a compact form that
  preserves the parts that bear on the decision, with the remainder retrievable
  (FR-047).
- **FR-090**: **Build and test logs** — a passing run MUST be represented by its
  outcome rather than its full output. A failing run MUST preserve the failure
  itself — the failing case, its location and its message — and MUST NOT be
  reduced to a pass/fail flag, because the failure is the entire reason the log
  was produced.
- **FR-091**: **Project instructions** — the project's own standing instructions
  MUST be carried once in a stable position rather than restated per turn, and
  MUST NOT be re-sent in altered form mid-task, which would break prefix
  caching (FR-050).
- **FR-092**: **Learned project knowledge** — recalled knowledge MUST be carried
  under an explicit budget (FR-062) and MUST NOT grow without bound as the store
  grows.
- **FR-093**: **Repeated model turns** — content established in an earlier turn
  of the same task MUST NOT be restated verbatim in a later one merely to keep
  it in view. This is the repeated-turn specialization of FR-052 (see FR-052);
  the overlap is intentional and both remain.
- **FR-094**: **Delegated work** — a delegate MUST return its conclusion and the
  evidence references supporting it, not the material it read (FR-053).
- **FR-095**: **Reconnect and resume** — resuming MUST reuse what the stored
  conversation already carries and MUST NOT re-derive or re-send established
  context (FR-054).

### Token efficiency: techniques the architecture must support

- **FR-096**: Context MUST be assembled against an explicit budget, with what was
  included and what was withheld both determinable.
- **FR-097**: Candidate context MUST be ranked by relevance to the work in hand,
  and selection MUST be by that ranking rather than by recency alone.
- **FR-098**: Detail MUST be retrievable on demand rather than carried
  pre-emptively; a reference to material the agent can fetch MUST be preferred
  over the material itself where the decision does not yet require it.
- **FR-099**: Content already present in the assembled context MUST NOT appear
  twice. **Exact duplicates** MUST be carried once, and may be collapsed only
  when content identity (the identity of the carried content itself, such as a
  content fingerprint) proves the two are equivalent. **Near-duplicates** may be
  collapsed only when their differences are proven irrelevant (Operational
  definitions) to every active requirement and decision. Where a difference could
  carry evidence — for example, two test runs that differ in one failing case —
  both representations remain. Semantic similarity alone is never proof of
  equivalence. This keeps FR-099 subordinate to FR-044: deduplication never
  removes evidence.
- **FR-100**: Where context changes between turns, the change MUST be
  expressible as a delta against what was already established rather than as a
  full restatement. If the base a delta rests on cannot be recovered, or cannot
  be validated as current, the system MUST fetch or carry a full authoritative
  representation before relying on the change. Missing base content is never
  reconstructed by guessing.
- **FR-101**: Material that has not changed MUST be referenceable by identity
  rather than by value, so that unchanged content need not be re-transmitted to
  be relied upon. If the referent cannot be recovered, or cannot be validated as
  current, the system MUST fetch or carry a full authoritative representation
  before relying on the reference.
- **FR-102**: A canonical summary MUST carry its provenance — what it summarises
  and from where — so a claim resting on it can be traced back to the evidence.
- **FR-103**: An assertion derived from inspected material MUST be able to cite
  that material by reference, so evidence can be re-examined without having been
  carried continuously.
- **FR-104**: Repository understanding MUST accumulate incrementally within a
  task, so that what has been established about the project is not rediscovered
  step by step.
- **FR-105**: A fact already verified in the session MUST NOT be re-verified
  without cause; a change to its underlying source is such a cause, the passage
  of turns alone is not. **Invalidation applies to every reuse mechanism in this
  specification**: references (FR-101), deltas (FR-100), deduplicated
  representations (FR-099), canonical summaries (FR-086, FR-102), verified
  session facts (this requirement) and learned items (FR-060). A representation
  becomes unusable as soon as the source identity, version or fingerprint it
  rests on no longer matches, or is known to have changed. It is then re-fetched
  or rebuilt from the authoritative source, and never relied on in its stale
  form.

### Progressive learning

- **FR-056**: Durable knowledge MUST be admitted only from: an explicit user
  correction; an explicit user statement or preference; a decision the user
  settled; a convention counted from the repository; a validated outcome; or a
  fact confirmed by a tool or by source. An unverified model assertion MUST NOT
  become durable knowledge.
- **FR-057**: Every durable item MUST record its provenance, its scope (this
  project versus this user), and, where meaningful, a confidence.
- **FR-058**: Project-scoped knowledge MUST NOT be applied in an unrelated
  project.
- **FR-059**: Contradictory items MUST resolve deterministically in favour of the
  more recent, with the superseded item retained as superseded rather than
  vanishing.
- **FR-060**: An item whose underlying repository fact has changed MUST cease to
  be applied.
- **FR-061**: Durable knowledge MUST be listable, attributable and individually
  deletable by the user, and what was recalled into a turn MUST be visible.
- **FR-062**: Recalled knowledge injected into a turn MUST be bounded by an
  explicit budget.
- **FR-063**: Learning MUST NOT occur during a turn in a way that changes that
  turn's behaviour mid-flight; persistence boundaries MUST be deterministic and
  testable.
- **FR-064**: Learning MUST be able to be switched off entirely.
- **FR-065**: Storage MUST be bounded; reaching a cap MUST produce an explicit
  refusal showing current contents rather than a silent eviction.
- **FR-066**: Text originating from untrusted content MUST NOT be admitted as
  durable knowledge on its own authority.
- **FR-067**: Learning MUST measurably reduce repeated clarifications, repeated
  rediscovery and repeated corrections over time, without introducing stale
  assumptions.

### Progressive learning: what may be learned, and how it is retrieved

- **FR-106**: The system MUST be able to learn **project-specific terminology** —
  what a name means in this project — from the user's own usage and from the
  repository, and MUST scope it to that project.
- **FR-107**: The system MUST be able to learn **stable architectural
  decisions** — where a kind of thing belongs, which layer owns a concern — from
  decisions the user settled and from conventions counted across the repository,
  and MUST treat such an item as superseded when the structure it describes
  changes.
- **FR-108**: The system MUST be able to learn **recurring instructions** — an
  instruction the user has given repeatedly — and apply it without being asked
  again. A recurring instruction MUST be distinguishable from a one-off
  instruction scoped to a single task, and only the former may become durable.
- **FR-109**: The system MUST be able to learn from **accepted decisions** and
  **validated fixes**: a decision the user adopted, or a change that was verified
  and retained, is admissible evidence; a proposal that was rejected or reverted
  is not.
- **FR-110**: Retrieval MUST select stored knowledge by relevance to the work in
  hand, MUST respect scope (FR-058), MUST exclude items marked stale or
  superseded, and MUST be bounded by the recall budget (FR-062).
- **FR-111**: What was recalled into a turn MUST be attributable after the fact,
  so that an answer shaped by a wrong item can be traced to that item and the
  item removed.
- **FR-112**: Stored knowledge MUST have a defined lifecycle — admitted,
  active, superseded or stale, removed — with every transition either
  deterministic or user-initiated, and no transition that silently discards an
  item the user did not ask to delete.

### Failure and uncertainty

- **FR-068**: On tool failure, unreachable service, partial repository access,
  unsupported capability or failed validation, the system MUST report the actual
  limitation and MUST NOT present a synthesised result in its place.
- **FR-069**: Where evidence in the project conflicts on a point that matters to
  the decision, the conflict MUST be reported rather than silently resolved.
- **FR-070**: Where the repository could only be partly inspected, the answer
  MUST say which parts were not inspected.
- **FR-071**: Cancellation MUST take effect at the next step or tool boundary at
  which the current runtime already observes cancellation — the existing
  cooperative cancellation semantics are preserved unchanged, and this feature
  adds no new blocking path, polling, timer or latency target — and no partially
  completed work may be reported as complete.
- **FR-113**: **Insufficient information** — where the information needed to
  proceed is absent and cannot be obtained, that MUST be the reported outcome,
  naming what is missing, rather than a result produced without it.
- **FR-114**: **Stale learned knowledge** — where a stored item is found to
  contradict current repository fact, it MUST stop being applied, the
  contradiction MUST be surfaced rather than silently resolved, and any answer
  already resting on it in that turn MUST be corrected before completion.
- **FR-115**: **Model uncertainty** — where the agent's own confidence in a
  consequential conclusion is low, it MUST say so and name what would settle it,
  and MUST NOT present the conclusion with the same assurance as a verified one.
  Low confidence on a decision meeting the FR-007 materiality test MUST be
  escalated to a clarification rather than reported as a hedge.
- **FR-116**: **Validation failure** — a check that fails MUST be reported as a
  failure with its evidence; it MUST NOT be re-characterised as a limitation of
  the check, retried until it passes, or omitted from the answer.

### Observability

- **FR-072**: The system MUST record, per task: input tokens, output tokens,
  cached-context tokens, context size, model turns, tool calls, retries,
  clarifications raised and answered, corrections received, task outcome, and
  validation results.
- **FR-073**: The system MUST record how often recalled knowledge was used and
  how often stored knowledge was found stale or superseded.
- **FR-074**: Recorded measurements MUST respect the product's existing redaction
  and privacy boundaries and MUST NOT contain credentials.
- **FR-075**: Measurements MUST remain local to the user's own machine unless the
  user has explicitly chosen otherwise; this initiative introduces no new
  outbound transmission of user data.
- **FR-076** *(retired 2026-09-28, D14)*.
- **FR-077** *(retired 2026-09-28, D14)*.

### Compatibility

- **FR-078**: All behaviour in this specification MUST work on Windows, Linux and
  macOS.
- **FR-079**: Existing question, permission, session, streaming, delegate and
  usage behaviour MUST be preserved, apart from the intended changes FR-082
  enumerates; no existing protocol message may change meaning.
- **FR-080**: Any new protocol surface MUST be introduced as an additive,
  negotiated capability, so that a client which does not understand it continues
  to work exactly as before.
- **FR-081**: Stored sessions and stored knowledge written by the current version
  MUST remain readable after this change.
- **FR-082**: This initiative intends exactly **four** user-visible behaviour
  changes, and no other:
  1. **A mandatory clarification no longer resolves itself on a non-answer.**
     **A material clarification can no longer be resolved by default,
     assumption or invented value when the required information was not
     actually supplied.** Today, a form that is dismissed, that expires, or that
     is raised where nobody is listening all lead the agent to choose sensible
     defaults and carry on; after this change none of them do. Cancellation or
     decline, expiry and unattended execution remain distinguishable as
     lifecycle outcomes (FR-035), and all three preserve the unresolved
     decision; non-interactive runs report the clarification-required outcome
     (FR-121 to FR-123).
  2. **Completion claims are checked.** An answer with unresolved work is
     annotated with that work named beside it, and an explicit completion claim
     that the evidence contradicts, or that the gate cannot support, is
     corrected or marked unconfirmed before delivery (FR-036, FR-037, FR-124 to
     FR-127).
  3. **A cancelled mandatory question is not re-raised** within the same
     decision attempt; the unresolved decision is reported instead (FR-129).
  4. **Questions outstanding at one decision point arrive as one form**
     (FR-014, SC-007; D18, D19). When one model reply raises questions through
     several calls, the person receives them together in one form, instead of
     one form per call. A form with more than four questions is shown in
     pages and answered once.

  Change 1 is the only one that removes behaviour an existing caller may rely
  on. It is the only behavioural regression-by-design in this initiative and
  MUST be stated in release notes. Changes 2 and 3 are additive: they add a
  notice, a correction or a report, and remove nothing a caller was given
  before.

  Change 4 removes no question, no answer and no decision association. It is
  **breaking** for callers that count forms, or that script one answer per
  form:
  - the number of forms changes, and so does the moment each question is
    presented;
  - a later call's questions, which a non-answer to the first form used to
    withhold, are now shown;
  - a multi-entry `--interactions` script must name each entry's headers.

  It MUST be stated in release notes with the migration path that D19 gives.

### Capability discovery

- **FR-117**: The set of tools advertised to the model MUST continue to be
  filtered by mode, so that a capability the mode forbids is not merely refused
  but never offered — a model that cannot see a capability does not plan around
  it, and the advertised set is also a token cost paid on every request.
- **FR-118**: Mode filtering of the advertised set and mode enforcement at the
  point of use MUST continue to derive from one rule, so the two can never
  disagree about what a mode means.
- **FR-119**: Any capability this initiative adds MUST appear in the generated
  capability inventory, and the inventory MUST remain generated from the code
  rather than maintained by hand.
- **FR-120**: The agent MUST NOT claim a capability that is not advertised to it
  in the current mode, and MUST report the mode as the reason when a requested
  action is unavailable.

### Scope exclusions

- **FR-083**: This initiative MUST NOT introduce trading functionality, MUST NOT
  depend on unmerged trading code, and MUST NOT modify the branch of PR #39.
- **FR-084**: This initiative MUST NOT create a release tag, dispatch a release
  workflow, publish a package, create a release, deploy, or modify production
  state.
- **FR-085**: This initiative MUST NOT merge, close, rebase or incorporate any
  pending pull request.
- **FR-128**: This initiative MUST NOT carry unrelated work. Refactors, cleanup,
  formatting churn, dependency bumps and architectural changes that are not
  required by a requirement in this specification MUST NOT be combined with it.
  An incidental problem discovered along the way is recorded and addressed
  separately unless the change is impossible without it, in which case the
  coupling MUST be stated explicitly in the change that carries it.

### Key Entities

- **Evidence item**: something the agent relies on. It carries what it asserts;
  its **information origin**, which is exactly one of FR-001's five categories
  (stated by the user; verified from the repository or a tool; established
  project or user knowledge; deterministically derived; unknown); its current
  **evidence lifecycle state**, a separate axis (Operational definitions); and
  what it was observed from.
- **Open decision**: an unresolved point that materially affects the work. It
  carries its stable decision reference (`decision_ref`), what must be decided,
  the candidate answers, the reason (its FR-007 materiality class), and the
  evidence already consulted.
- **Clarification form**: a set of open decisions put to the user at one time,
  with a stable identity and a bounded lifetime. **Form lifecycle** (a live,
  claimed form): outstanding → answered, cancelled/declined, or expired. This is
  distinct from the **clarification terminal outcome** the run reports
  (FR-035): answered → no clarification stop; cancelled/declined →
  `clarification.outcome = "cancelled"`; expired → `"expired"`; and
  `"unattended"`, which is the clarification-required outcome when nobody is
  available to claim or answer a mandatory clarification — it maps the open
  decision to the BLOCKED evidence state rather than pretending a user cancelled
  a live form, and is not a state of a form that was never claimed.
- **Question**: one open decision within a form, with a stable name, its
  candidate options, whether several may be chosen, and a mandatory
  custom-answer row.
- **Answer**: what came back for one question — the options chosen and any text
  written — bound to the question by name. This is the existing question
  response/answer payload (`questions.py`, protocol `QuestionRequest` reply), not
  a new runtime entity.
- **Durable knowledge item**: something learned, carrying its statement,
  provenance, scope, confidence, current status (active, superseded, stale), and
  the time it was established.
- **Completion assessment**: the comparison of requested work against delivered
  work, listing unresolved elements and the evidence gathered; a transient value
  of the existing completion verification path (data-model.md §8), never durable
  state.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

**Acceptance** (owner decisions D14 to D17, 2026-09-28). Accepting this feature
requires no model call other than scripted responses, no paid tokens and no
provider credential. It is accepted on its deterministic gates on the exact commit
under review (SC-022, SC-025, SC-035): the full test suite and its performance
ceilings, lint, type checks, code-generation and capability-inventory checks,
the frontend and renderer suites, and the three-platform matrix. SC-001,
SC-011, SC-012, SC-021, SC-026 and SC-036 are retired. A criterion whose
guarantee deterministic tests cover is kept, worded as exactly what those tests
establish (D16). No token-efficiency or quality improvement is claimed for this
feature (D15).

**Grounding and assumption prevention**

- **SC-001** *(retired 2026-09-28, D14)*.
- **SC-002**: Once a necessary material decision is open — asked by the
  agent, or recorded as unresolved because it is unavailable from every
  permitted source — the agent loop enforces the clarification safety
  invariant on every turn:
  1. From the moment the unresolved dependency is known, **zero** mutating
     actions that depend on the decision run before a valid answer. A mutation
     whose dependency on the decision is uncertain counts as dependent (FR-018).
  2. Where the material decision was identifiable before any dependent
     mutation began, **zero** dependent mutations precede the clarification
     (FR-013).
  3. Demonstrably independent work (FR-018) is not a failure of SC-002.
  4. In a legitimate late-discovery case (FR-013), mutations completed before
     the dependency became known are not an SC-002 failure merely because they
     preceded it. But **zero** potentially dependent mutations may run after
     discovery, and 100% of those earlier changes are disclosed as prior
     changes in the outcome.

  The open decision is either answered or reported as outstanding in the
  turn's outcome, and a turn fails SC-002 if any of these does not hold.
  Measured by its deterministic regression tests (D16). Whether the model
  recognises a decision as material in the first place is model behaviour and
  is not claimed.
- **SC-003**: An answer that claims tests or checks pass when no command ran
  in the turn is marked by the unverified-claim notice beside the answer, for
  the claim forms the notice recognises; a claim backed by a command that ran,
  a hedge, an instruction and a denial are not marked. Measured by its
  deterministic regression tests (D16).
- **SC-004**: Every assumption the agent takes appears in its answer as an
  assumption; measured as 100% of proceed-on-assumption cases. Separately,
  **zero** of those cases involve a decision that passed the materiality test —
  an assumption standing in for a mandatory clarification is a failure regardless
  of how it is labelled.

**Clarification quality and cost**

- **SC-005**: Every question presented carries a working custom-answer row;
  measured as 100% across all generated forms, including adversarial attempts by
  the model to author or suppress it.
- **SC-006**: When a question's answer is already settled — by repository
  evidence, project configuration, trustworthy learned knowledge, safe
  implementation discretion or an established obvious default — no form is
  raised in a mode permitted to inspect, and a permission- or
  confirmation-shaped question is refused rather than asked; an unsettled
  material decision is still asked. Measured by its deterministic regression
  tests (D16).
- **SC-007**: All decisions outstanding at one point reach the user as a single
  form, whatever its number of questions. Measured as no case of two forms
  raised for one decision point, and no decision dropped, inferred or
  misapplied, by the deterministic regression tests D18 and D19 list.
- **SC-008**: A developer can answer a full form using only the keyboard, and can
  see which questions remain outstanding without visiting each.
- **SC-009**: An outstanding form survives disconnect and reconnect and is
  presented again in 100% of reconnect cases.
- **SC-010**: Stale, duplicate and invalid answers never alter the work; measured
  as zero applied answers among them.

**Mandatory clarification is never self-resolved**

Each criterion below is measured by its deterministic regression tests (D16),
and each is independently mutation-checked.

- **SC-037**: Cancelling a mandatory question produces **zero fabricated
  values** — no invented value, no option selected on the user's behalf, no
  default applied, no stated assumption standing in for the answer.
- **SC-038**: Declining a mandatory question produces zero fabricated values, on
  the same measure as SC-037.
- **SC-039**: Expiry of a mandatory question produces zero fabricated values, on
  the same measure as SC-037.
- **SC-040**: Unattended execution reaching a mandatory question produces zero
  fabricated values, on the same measure as SC-037.
- **SC-041**: After any of SC-037 to SC-040, **zero mutating actions dependent on
  that decision execute**; measured by asserting no dependent write, shell
  invocation or external call occurred after the outcome.
- **SC-042**: A real answer supplied after a cancelled or expired mandatory
  question resumes the dependent work and produces the same result as if it had
  been answered the first time; measured by its deterministic regression tests
  (D16).
- **SC-043**: Work that continues while a mandatory clarification is outstanding
  is demonstrably independent of it; measured by asserting that every continued
  action's inputs exclude the unresolved decision. Where dependency cannot be
  established, the work is treated as dependent and does not run.
- **SC-044**: A cancelled mandatory question is not re-raised within the same
  decision attempt; measured as zero repeat forms for a cancelled decision before
  an explicit user resumption.

**Token efficiency**

- **SC-011** *(retired 2026-09-28, D14)*.
- **SC-036** *(retired 2026-09-28, D14)*.
- **SC-012** *(retired 2026-09-28, D14)*.
- **SC-013**: Once a file read is superseded — the file was edited and read
  again — no request assembled after the context sweep has run carries the
  pre-edit copy in full, and the edit is represented by its change rather than
  the whole file. Measured by its deterministic regression tests (D16).
- **SC-014**: No tool output is lost to truncation; measured as every
  over-budget result remaining retrievable in full.
- **SC-015**: Within one turn, the request head — the system prompt with the
  project instructions carried once in a fixed position — is identical on
  every model call, and a change to the project instructions saved during the
  turn takes effect from the next turn. Measured by its deterministic
  regression tests (D16).

**Progressive learning**

- **SC-016**: A correction issued once is applied on the next relevant turn
  without restatement, in 100% of tested correction cases.
- **SC-017**: A decision settled through a form is not re-asked within the same
  project; measured as zero repeat forms for a settled decision.
- **SC-018**: The learning store's admission gate refuses to persist any new
  lesson, fact or rule whose provenance is not one of the admissible classes,
  whether it arrives through the service, reflection, review, curation or a
  direct store write; a model's own assertion, assistant text and an
  instruction arriving as untrusted content are not admissible. Measured by
  its deterministic regression tests (D16).
- **SC-019**: Project-scoped knowledge is never applied in an unrelated project;
  measured as zero cross-project applications in a two-project test.
- **SC-020**: Every durable item is listable with its origin and individually
  deletable; measured as 100% coverage.
- **SC-021** *(retired 2026-09-28, D14, D16)*.

**Compatibility, determinism and regression prevention**

- **SC-022**: The full existing test suite, lint, type checks, code-generation
  freshness checks and the renderer suite pass on all three platforms on the
  exact commit under review.
- **SC-023**: A client that does not negotiate any new capability behaves as it
  does today, apart from the intended changes FR-082 enumerates. For example, a
  reply's questions reach it in one form (D18). Measured by running the
  existing protocol conformance tests unchanged.
- **SC-024**: Sessions and stored knowledge written before the change remain
  readable after it, in 100% of fixture cases.
- **SC-025**: Every behaviour in this specification that guards an invariant has
  a deterministic regression test that fails when the guard is removed and passes
  when it is restored, with no test relying on sleeps or timing for correctness.
- **SC-026** *(retired 2026-09-28, D14)*.

**Per-class efficiency and evidence retention**

- **SC-027**: A failing build or test run never loses its failure to
  compression; measured as the failing case, its location and its message being
  recoverable from the carried representation in 100% of failing runs.
- **SC-028**: Tool-result material identical to a result still resident in
  the assembled context is admitted as a reference to the call that holds it,
  never as a second full copy; a changed source is never served from a stale
  copy, and a near-duplicate is not collapsed on similarity alone. Measured by
  its deterministic regression tests (D16).
- **SC-029**: In the evidence ledger, recording an unchanged source again
  reuses the existing verified entry instead of creating a second
  verification; a change to the source returns the earlier fact to unknown and
  moves its citation; and the passage of turns alone invalidates nothing.
  Measured by its deterministic regression tests (D16).
- **SC-030**: Every canonical summary and every derived assertion can be traced
  to the material it rests on; measured as 100% of summaries carrying provenance.

**Learning coverage and honesty**

- **SC-031**: An instruction given twice becomes a rule that is applied
  without being requested again, a single mention does not, a one-off
  instruction never becomes durable, and a contradicting instruction
  supersedes the earlier rule. Measured by its deterministic regression tests
  (D16).
- **SC-032**: A stored item contradicted by current repository fact stops being
  applied, and the contradiction is surfaced; measured as zero silent
  applications of a contradicted item.
- **SC-033**: A material conclusion recorded with confidence below the
  threshold is escalated to a clarification rather than delivered, and
  hedging language in the answer does not substitute for that escalation; a
  non-material low-confidence point is reported, not asked. Measured by its
  deterministic regression tests (D16).

**Capability honesty**

- **SC-034**: In plan mode and conversation-only mode, a tool the mode does
  not advertise is refused before it runs, with the mode named as the reason,
  and no tool the mode would refuse is advertised. Measured by its
  deterministic regression tests (D16).
- **SC-035**: The generated capability inventory regenerates cleanly and its
  check passes on the exact commit under review.

---

## Clarifications — Resolved

**Twenty-eight** clarification decisions are recorded below, in nine groups.
Each decision is binding on the requirements it names:

| Group | Decisions |
| --- | --- |
| Session 2026-09-29 (one form per decision point) | 2 — D18, D19 |
| Session 2026-09-28 (acceptance scope) | 4 — D14 to D17 |
| Session 2026-09-26 | 1 — D13, superseded by D14 |
| Session 2026-09-25 | 3 — D10 to D12, superseded by D14 |
| Session 2026-09-24 (post-gate amendment) | 3 — D7 to D9 |
| Session 2026-09-24 (specification review) | 6 — D1 to D6; D5 superseded by D14 |
| Session 2026-09-14 (remediation) | 3 |
| Session 2026-09-14 (outcome encoding) | 3 |
| Original clarifications, 2026-09-14 | 3 — Q1 to Q3 |

All twenty-eight were put to, or decided by, the repository owner. Every one
lists the FR/SC requirements or Constitution principle it binds, or the later
decision that supersedes it. No unresolved
clarification markers remain in this specification.

### Session 2026-09-29 (one form per decision point)

The owner decided how questions raised through several calls in one model
reply reach the person (D18), and how a form larger than one page is
presented (D19).

- Q: When one model reply raises questions through several calls, are they
  presented as one form, and is that a user-visible change? → A: **D18.** Yes,
  and yes. It is the fourth intended user-visible change under FR-082, and it
  is required by FR-014 and SC-007.
  - **Decision point**: one model reply of one agent loop. The decisions that
    the mutation preflight finds missing for that reply's calls belong to the
    same decision point. A delegate's own replies are its own decision points.
    Decisions a delegate carries back enter the parent turn unresolved. They
    are never re-asked in the parent's form or in any later form of that turn.
  - **Preserved**:
    - every question, with its header, options, custom-answer row (FR-017),
      materiality and grounding;
    - its decision association: one `decision_ref` per decision (FR-020,
      FR-129);
    - answers bound by header to the call that asked;
    - the lifecycle outcomes (FR-035);
    - the shape and meaning of every protocol message (FR-079, FR-080).

    No question is dropped, answered by default, or merged into a different
    decision. The same decision asked by two calls in one reply appears once,
    and both calls receive its answer or outcome.
  - **Changed**:
    - The number of forms: one per decision point, instead of one per call.
    - When a question is presented. A question from a later call in the same
      reply is shown at once, beside the earlier calls' questions, instead of
      after the first form is answered.
    - Where the first form would have been cancelled, declined, expired or
      unattended, the later calls' questions were previously withheld and
      never shown. They are now shown, and they share that outcome.
    - A caller that counts forms, or that scripts one answer per form, sees the
      difference. `comodor run --interactions`, for example, applies one entry
      per form, in order: the combined form consumes one entry. D19 defines how
      entries match forms, and gives the migration path.
  - **Limit**: *superseded by D19 (2026-09-29).* A form has no upper bound;
    a client pages it in groups of at most four, and an invalid set of calls is
    refused atomically.
  - **Outcomes**:
    - A partial answer resolves the answered questions. Each unanswered
      material decision stays open and is reported once.
    - Cancellation, decline, expiry or absence of the combined form applies
      that outcome to every decision in it.
    - Each call receives its own result, naming only its own questions.
  - **Coverage** (deterministic, with scripted model responses, and
    mutation-checked):
    - one reply with several `ask` calls — answered, partially answered,
      cancelled, expired and unattended;
    - the same decision asked twice in one reply;
    - an `ask` beside a mutation whose preflight finds another missing
      decision;
    - the atomic refusal (D19);
    - successive replies, where a new form at a new decision point is allowed;
    - every existing client surface that presents, scripts or reports a form:
      - the live forms of the TUI renderer and the Web session round trip;
      - headless `--interactions`;
      - the clarification-required payload, and its later `decision_answers`
        resumption, on the OpenAI-compatible API and ACP;
      - channels (one clarification-required payload naming every decision).
  - **Release note**: stated in the release notes together with change 1,
    with D19's migration path.
  - SC-044's two-guard test design (plan §G.4) is kept.

  *Binds*: FR-014, FR-079, FR-082, SC-007, SC-023; the surface classification
  rows for TUI, Web UI, CLI / Headless, API / Protocols, Channels /
  Integrations and Tests / Documentation.
- Q: How is a decision point with more than four material questions
  presented, if a page shows at most four? → A: **D19.** As one logical form,
  shown in client-side pages of at most four questions. On a live surface — a
  protocol v2 interactive client, such as the TUI, and the Web page — it is
  delivered in one interaction and answered in one submission. FR-014 and
  SC-007 are not narrowed. D19 supersedes D18's **Limit** item (a combined form of at most
  four questions, with an overflow call refused).
  - **One logical form**:
    - Every material question outstanding at one decision point (D18) is
      carried in one form. On a live surface, that is one pending question
      request, answered by one submission.
    - The OpenAI-compatible API and ACP have no live form. The same set is one
      clarification-required payload, resumed later (see Surfaces).
    - The form has no upper bound on its number of questions.
  - **Pages**:
    - A client presents the form in pages of at most four questions. Pages are
      presentation only: never separate forms, requests or submissions.
    - Moving between pages loses nothing already entered.
    - A client that presents one question at a time, such as the TUI, meets
      the rule, and shows each question's position in the whole form.
    - A client that does not page still receives the whole form.
  - **Per-call input rule** (not a form limit): one `ask` call still carries at
    most four questions. A reply that needs more uses several calls, which the
    loop combines into one logical form (D18).
  - **Atomic refusal**:
    - If any `ask` call in a reply is refused — too many questions in the call,
      malformed input, a permission- or confirmation-shaped question, or a
      header that collides with a different question — no form is raised for
      that reply.
    - Every `ask` call in the reply receives a tool error, which says the set
      must be asked again together.
    - No decision is registered, dropped, inferred or applied.
    - Every non-read-only call in the same batch is withheld, and a mutation
      whose missing decision came from the preflight is re-assessed on the next
      reply.
    - The model may retry at its next reply, and a valid set then arrives as
      one form.
  - **Binding**:
    - Each question keeps a header that is unique within the logical form, and
      its own `decision_ref`.
    - Answers bind by header (FR-020), never by page or position, and each
      reaches the call that asked.
    - A question the same decision raises twice appears once (D18). When two
      calls name it under different headers, the form shows the first asking
      call's header, once. The answer or outcome is returned to **each** asking
      call under that call's own header.
    - A header shared by two different questions is a collision, and it is
      refused atomically (above).
  - **Partial answers**: the answered questions resolve. Each unanswered
    material decision stays open and is reported once, and the work that
    depends on it is withheld until a real answer exists (FR-018, FR-129).
  - **Non-answers**: cancellation, decline, expiry and absence apply to the
    whole logical form, and so to every decision in it, whatever page was
    showing. Entries on pages that were never submitted are discarded, never
    applied.
  - **Reconnect**: the whole form returns through the pending interaction
    (FR-023). A client may restore its page position. Unsubmitted entries are
    never assumed.
  - **Surfaces**:
    - **Protocol v2 interactive clients (the TUI)**: a live form, one question
      at a time, with its position in the form; one submission.
    - **Web**: a live form, in pages of at most four questions; one submission.
    - **OpenAI-compatible API and ACP**: no live form.
      - The turn ends `clarification_required`, with one payload listing every
        decision of the decision point, whatever their number, each with its
        `decision_ref`.
      - A later request resumes through `decision_answers`, keyed by
        `decision_ref` (FR-129), never by header or position.
      - A partial `decision_answers` resolves only the decisions it names. The
        others stay open, and their dependent work stays withheld.
    - **CLI**: see scripted interactions below.
    - **Channels**: an unattended run ends in one clarification-required
      message that names every decision and its `decision_ref`. A later
      structured reply resolves a decision only by that ref (FR-129).
  - **Scripted interactions** (`comodor run --interactions`):
    - One entry applies to exactly one logical form.
    - An entry that names headers matches a form only if every header it names
      belongs to that form. `answer` names its headers through `values` keyed
      by header; `cancel`, `expire` and `unattended` name theirs through a
      `headers` list.
    - Headers are optional only in a single-entry script. When a script has
      more than one entry, every entry must name the headers of its form, and
      that includes `cancel`, `expire` and `unattended`.
    - The whole script is validated when it is parsed, before the run starts
      and before any model call. A script is rejected there, with exit code
      `1` and an error naming the problem, when it:
      - is not valid JSON, or is not a list;
      - holds an entry with an unknown action;
      - holds an `answer` without a non-empty choice;
      - is a multi-entry script with an entry that names no headers.
    - Every `answer` states its choice. It carries either a non-empty
      `value` or non-empty keyed `values`.
      - A **bare** `answer` — no `value` and no keyed `values`, or only empty
        ones — is invalid on every form, a one-question form included.
      - The script is validated when it is parsed, before the run starts, and
        a bare `answer` is rejected there as an input error. The run exits
        with code `1`, having resolved no decision and run no dependent work.
      - No option is ever selected implicitly. To choose the first offered
        option, a script names it (`{"action": "answer", "value": "<first
        option>"}`).
    - Without headers:
      - an `answer` with a `value` is valid only for a form with exactly one
        question;
      - `cancel`, `expire` and `unattended` apply to the whole form.
    - A keyed `answer` answers exactly the headers it names. It never fills an
      omitted question — not with a first option, a default or anything else —
      and a single value is never spread across questions. An omitted question
      stays unanswered: a partial answer.
    - An entry that does not match the form it would apply to is rejected
      before anything is applied. That covers an unknown header, a missing
      header list in a multi-entry script, and an `answer` without headers for
      a form of more than one question. The run then ends with exit code `1` and an
      error naming the entry and why it did not match; `--json` carries the
      error, and any clarification payload that was reached.
    - A mismatch can only be found once the form has appeared, which is
      after the model has raised it. The run then aborts, and the pending
      interaction is closed internally without applying any answer:
      - it is closed as `unattended`, the outcome a run with no script
        reaches, and never reported as a user cancellation;
      - no dependent work runs;
      - the run exits `1` with the error.
    - Entries left over when the run ends are rejected the same way. A
      scripted entry is never applied to an unrelated later form.
  - **FR-082 change 4 is breaking** for callers that count forms, or that
    script one entry per form. The migration path:
    1. Count decision points, not calls. There is one form per decision point,
       and its length is its number of questions.
    2. In an `--interactions` script with more than one entry, give each entry
       the headers of its form (`values` keyed by header for `answer`,
       `headers` for the other actions), one entry per decision point. A
       single-entry script without headers keeps working for a run with one
       form, but its `answer` must key its values when that form has more than
       one question. A script that relied on an `answer` filling omitted
       questions must now name every question it answers. A script that used
       a bare `answer` to accept the first option must now name that option
       as its `value`.
    3. An OpenAI-compatible API or ACP client that assumed at most four
       decisions in a clarification payload accepts any number. It resumes
       them through `decision_answers`, keyed by `decision_ref`, and may
       resume them in parts.
    4. The release notes (with change 1), `docs/cli.md` and
       `docs/questions.md` state these steps.
  - **Coverage** (deterministic, with scripted model responses,
    mutation-checked where a guard exists):
    - a reply whose calls raise more than four questions: one form, one
      request event, one submission, every header bound;
    - pages on the TUI and on the Web, including page navigation that keeps
      entries;
    - partial answers across pages;
    - cancellation, expiry and absence on any page;
    - reconnect with more than four questions;
    - each atomic-refusal reason, with its sibling mutation withheld and a
      valid retry;
    - a header collision;
    - scripted interactions:
      - a matching single entry, and matching multi-entry scripts;
      - an unmatched entry, and a leftover entry;
      - an `answer` without headers for a form of several questions;
      - a bare `answer`, on a one-question and on a multi-question form:
        rejected before the run, exit `1`, no decision resolved;
      - an explicit `answer` whose `value` names the first option: accepted,
        and it selects exactly that option;
      - a keyed partial `answer` that leaves omitted questions open;
      - no application to a later form;
    - the same decision under two headers: one question shown, each call
      answered under its own header;
    - the OpenAI-compatible API and ACP: a payload listing six decisions, a
      partial `decision_answers` resumption, and the rest still open;
    - channel payloads.

  *Binds*: FR-014, FR-018, FR-020, FR-023, FR-082, SC-007, SC-008, SC-009,
  SC-023; D18 (supersedes its **Limit** item); the surface classification rows
  for TUI, Web UI, CLI / Headless, API / Protocols, Channels / Integrations and
  Tests / Documentation.

### Session 2026-09-28 (acceptance scope)

The owner set the final acceptance scope of the feature.

- Q: What does acceptance require, and what does it retire? → A: **D14.**
  Acceptance requires no model call other than scripted responses, no paid
  tokens and no provider credential. Retired:
  FR-076, FR-077, SC-001, SC-011, SC-012, SC-021, SC-026, SC-036 and User
  Story 6; FR-064 keeps only its first clause. Kept: the product's
  capabilities, its production token-usage accounting, its deterministic
  behavioural and security tests, and its deterministic performance ceilings
  that call no model. Nothing retired is marked as passed, completed task
  history is not rewritten, and Git history is the record. The final tracked
  tree carries nothing this decision removes, in any file, dated text
  included.
  It supersedes the 2026-09-27 acceptance-scope decision and the acceptance
  effect of Q1, D5 and D10 to D13. *Binds*: FR-064, FR-076, FR-077; SC-001,
  SC-011, SC-012, SC-021, SC-026, SC-036; User Stories 3 and 6.
- Q: How does constitution Principle XXI change? → A: **D15.** The unmerged
  amendment in this pull request is revised, and its final version stays
  2.0.0: `main` is still at 1.1.0, so one unmerged pull request does not take
  two MAJOR increments. The former requirement for model-dependent evidence
  is removed from Principle XXI and from the context-change gate. The
  context-change gate remains: a change to what is sent to a model is accepted
  on deterministic tests that exercise the changed mechanism with scripted
  model responses, and on truthful, supportable claims about tokens and
  quality. The Development Workflow rule is aligned, so every acceptance gate
  is deterministic and requires no provider calls or paid tokens. Kept: the
  rule against unsupported token-efficiency or quality-improvement claims,
  production token-usage accounting, and the deterministic correctness,
  security and performance gates. The Sync Impact Report records the motivation and the migration plan,
  and Git history is not rewritten. Until the amendment is implemented, the
  requirements checklist's Principle XVI / XXI item stays pending. *Binds*:
  Constitution Principle XXI and "Compatibility Surfaces and Quality Gates";
  the *Acceptance* statement under Measurable Outcomes.
- Q: How is each affected success criterion decided? → A: **D16.** Per
  criterion:
  - kept only where existing deterministic tests cover its complete, precisely
    worded invariant, with its measurement stated as those tests;
  - where coverage is partial, narrowed to what the tests establish, or kept
    with a deterministic product regression test to be added;
  - an outcome or improvement criterion that only a model-dependent
    measurement could show is retired and never relabelled as a test;
  - a criterion that no deterministic test measures is retired;
  - no universal behaviour is claimed from a finite fixture set.

  The audit below records each decision. *Binds*: every criterion in the
  audit.
- Q: Are the two runtime-only context-assembly settings removed?
  → A: **D17.** Yes, from configuration and the runtime; neither was ever
  offered to a person. The deterministic safety and neutrality invariants that
  switched optimizations off stay covered by switching them off inside the
  tests only. *Binds*: SC-013, SC-027, SC-028; User Story 3 acceptance
  scenario 5.

**D16 audit** (evidence at the PR #61 head `7361c50`; counts are test
functions in each file):

| Criterion | Decision | Deterministic evidence |
| --- | --- | --- |
| SC-001 | Retire | — |
| SC-002 | Rewrite (narrow) | `tests/test_clarification_pause.py` (19, including the withheld-check mutation check and the three D7 cases) and `tests/test_clarification_required.py` (6). The clause that the agent asks in 100% of attempts is model behaviour and is not claimed. |
| SC-003 | Rewrite (narrow) | `tests/test_claims.py` (11) and `tests/test_baseline_loop.py::test_an_unverified_pass_claim_is_noticed_but_not_blocked`. The notice covers the claim forms it recognises, not every phrasing. |
| SC-007 | Keep (measurement) | `tests/test_clarification_one_form.py`, to be added with the product fix; the batch case fails at `7361c50` (D18). Added by T216 and fixed by T218; it passes. |
| SC-006 | Rewrite (narrow) | `tests/test_clarification_restraint.py` (10, including two mutation checks). Whether the model treats a question as settled is not claimed. |
| SC-011, SC-012, SC-036 | Retire | — |
| SC-013 | Rewrite (narrow) | `tests/test_context_no_superseded.py` (3, including the sweep mutation check) and `tests/test_baseline_staleness.py`. Holds once the sweep has run. |
| SC-015 | Rewrite (narrow) | `tests/test_context_stable_prefix.py`: the three head tests, including the read-once mutation check. Covers the head within one turn. |
| SC-018 | Rewrite (narrow) | `tests/test_learning_admission.py` (31) and `tests/test_learning_untrusted.py` (9), both with mutation checks. Covers new items through the admission gate. |
| SC-021 | Retire | — |
| SC-026 | Retire | — |
| SC-028 | Rewrite (narrow) | `tests/test_context_dedup.py` (14). Covers tool-result material admitted to the context. |
| SC-029 | Rewrite (narrow) | `tests/test_context_invalidation.py`: its three ledger tests. Covers the evidence ledger, not whether the model calls a tool again. |
| SC-031 | Rewrite (measurement) | `tests/test_learning_recurring.py` (7, including the recurrence-guard mutation check). |
| SC-033 | Rewrite (narrow) | `tests/test_evidence_decisions.py`: its four confidence tests; `tests/test_failure_states.py`: its two low-confidence tests. |
| SC-034 | Rewrite (narrow) | `tests/test_capability_honesty.py` (3). Covers attempts and advertisement; a claim made in prose is not measured. |
| SC-037 to SC-040 | Keep (measurement) | `tests/test_clarification_no_fabrication.py`, parametrised over the four non-answer outcomes, with a guard mutation check per outcome. |
| SC-041 | Keep (measurement) | `tests/test_clarification_pause.py` (its dismissed-batch and turn-ends tests) and `tests/test_clarification_lifecycle.py` cases 3 to 6. |
| SC-042 | Keep (measurement) | `tests/test_decision_resumption.py` and `tests/test_clarification_required.py::test_a_later_answer_in_the_next_turn_resumes_the_work`. |
| SC-043 | Keep (measurement) | `tests/test_clarification_pause.py`: its independent-work and D7 tests. |
| SC-044 | Keep; test required | No existing deterministic test shows that a **cancelled** mandatory question is not re-raised within the same decision attempt before an explicit user resumption. A deterministic, mutation-sensitive test of exactly that is required: it fails when the re-raise suppression is removed. A test of a declined question alone does not satisfy SC-044. Added by T219 in `tests/test_clarification_lifecycle.py`, mutation-checked; it passes. |

### Session 2026-09-26

- **D13** — superseded by D14 (2026-09-28).

### Session 2026-09-25

- **D10** — superseded by D14 (2026-09-28).
- **D11** — superseded by D14 (2026-09-28).
- **D12** — superseded by D14 (2026-09-28).

### Session 2026-09-24 (post-gate amendment)

After the specification quality gate reached 131/131, a constitutional
consistency audit found three specification-level gaps. The owner decided them
as follows.

- Q: Does SC-002 forbid every file write before the clarification, even
  demonstrably independent work and changes made before a late-discovered
  decision became known? → A: **D7.** No. SC-002 measures the clarification
  safety invariant, not a ban on legitimate work:
  - the decision is asked or reported in 100% of attempts;
  - from the moment the dependency is known, zero dependent mutations run
    before a valid answer, and uncertain dependency counts as dependent;
  - where the decision was identifiable before dependent mutation began, zero
    dependent mutations precede the clarification;
  - demonstrably independent work is not a failure;
  - in a legitimate late-discovery case, earlier mutations are not a failure,
    no potentially dependent mutation runs after discovery, and the earlier
    changes are disclosed.

  The no-fabrication and no-dependent-mutation invariant is unchanged.
  *Binds*: SC-002, FR-013, FR-018, FR-123 (and the User Story 1 Independent
  Test, aligned to SC-002). *SC-002's measure is narrowed by D16
  (2026-09-28).*
- Q: May the specification delegate its ten-surface classification to
  plan.md? → A: **D8.** No. Constitution XI requires the specification itself
  to classify every canonical surface and to give concrete evidence for every
  surface claimed unchanged. The normative ten-row table now sits in
  §Requirements. plan.md may keep an implementation-level version, but it must
  agree with the spec and cannot override it. *Binds*: Constitution XI; the
  §Requirements surface classification; FR-078 to FR-082.
- Q: What happens to a resumption answer whose `decision_ref` is unknown,
  malformed, stale, unresolvable, or missing where one is required? → A:
  **D9.** It is an invalid resumption answer. It is rejected, applied to no
  decision, and never matched to another decision by recency, position,
  textual similarity, first-unresolved order or any other heuristic. It
  authorises no dependent work, every unresolved decision stays unresolved, and
  the caller is told the reference could not be resolved. An answer given
  through an interactive pending form is unaffected, because its transport
  already carries the decision association. The wire representation is left to
  planning; no new error enum is specified. *Binds*: FR-024, FR-026, FR-129;
  Edge Cases (clarification lifecycle).

### Session 2026-09-24 (specification review)

The reviewer-owned specification quality gate (`checklists/spec-gate.md`)
first passed 108 of 131 criteria. Six of the remaining 23 needed a product
decision; the owner decided them as follows.

- Q: When is a decision material — what does "can materially change" mean?
  (CHK013; contributes to CHK015, CHK124) → A: **D1.** A decision is material
  only when at least two plausible, grounded resolutions exist and choosing one
  instead of another can change the delivered behaviour or one of the FR-007
  effects. It is non-material when every grounded alternative satisfies the same
  explicit intent, compatibility contract and acceptance criteria and differs
  only in internal implementation detail. "The requested behaviour" applies only
  when the user-visible or requested result differs. If equivalence cannot be
  determined, FR-130 applies and the decision is material.
  *Binds*: FR-007, FR-122, FR-130; Operational definitions (Material).
- Q: How is implementation freedom told apart from missing product intent?
  (CHK015) → A: **D2.** Implementation discretion exists when all grounded
  alternatives satisfy the request and the repository and specification
  constraints, preserve compatibility, security and persistence semantics, meet
  the same acceptance criteria and stay below the materiality threshold; the
  agent may choose. Missing product intent exists when two or more grounded
  interpretations remain unsettled by repository, configuration and trustworthy
  knowledge, and the choice changes a material outcome; it is a mandatory
  clarification. Where the classification is ambiguous, material and
  clarification win. *Binds*: FR-003, FR-011, FR-012, FR-130; Operational
  definitions (Implementation discretion, Missing product intent).
- Q: May independent work continue while a clarification is outstanding?
  (CHK025) → A: **D3.** It is permitted, not mandatory. An outstanding
  clarification does not by itself prohibit demonstrably independent work.
  Dependent work pauses, and uncertain dependency counts as dependent. No
  unrelated work is started just to stay active, and a clarification is never
  bypassed because independent work happened. A non-interactive run may finish
  already identified, bounded independent work before returning
  `clarification_required`, but must not begin speculative work to delay the
  stop. *Binds*: FR-018, FR-123, SC-043.
- Q: How does a later answer resume a decision that was cancelled, expired or
  unattended? (CHK043; also CHK040) → A: **D4.** Every material unresolved
  decision has a stable `decision_ref` that identifies the decision across
  lifecycle instances; a form's own lifecycle identifier is not a substitute.
  The clarification-required outcome carries at least `decision_ref`, the
  decision, the candidates, the evidence consulted, the reason and the lifecycle
  outcome. A later answer resumes a decision only when it is explicitly
  associated with its `decision_ref`, never by position, recency, textual
  similarity, first-unresolved order or heuristic inference. Headless, API and
  subsequent-invocation inputs carry the `decision_ref` explicitly. No second
  clarification mechanism is introduced. *Binds*: FR-020, FR-034, FR-129,
  SC-042; Operational definitions (Decision reference).
  *Implementation gap, recorded for the plan/tasks convergence step (not fixed
  here)*: at candidate `21af97f`, the question shape carries `decision_ref`
  (`questions.py`, set by `tools/ask.py`), but the structured
  clarification-required payload (`tools/ask.py::payload_for`) has no top-level
  `decision_ref` — only a per-decision `id` inside `decisions[]`. No headless or
  API resumption input carries a `decision_ref`. Whether the decision id stays
  stable across lifecycle instances and turns has not been verified.
- **D5** — superseded by D14 (2026-09-28).
- Q: What do "material", "relevant", "proportionate validation" and
  "trustworthy stored knowledge" mean? (CHK124; supports CHK005) → A: **D6.**
  They are defined operationally in §Requirements, Operational definitions:
  material per D1; relevant = able to change, support, refute or validate an
  active requirement, decision, completion claim or affected-surface judgement;
  proportionate validation = the smallest set of checks that exercises the
  changed behaviour, the affected contracts and surfaces, and the applicable
  repository-mandated gates, where a policy-required repository-wide gate stays
  in scope and an optional suite with no coverage is unrelated; trustworthy
  stored knowledge = FR-056-admitted, active, correctly scoped, neither stale
  nor superseded, uncontradicted by current evidence, and attributable.
  *Binds*: FR-008, FR-038, FR-042, FR-051, FR-087, FR-097, FR-110.

**Corrections without a new decision.** The other 17 gate findings were closed
from intent the Feature 002 artifacts already record: CHK001 (definition of
high-quality output); CHK005 (FR-038/FR-042 reconciled); CHK009 and CHK131
(information origin separated from lifecycle state; VERIFIED and VALIDATED
defined; Key Entities); CHK012 (FR-002's mechanical rule); CHK040 (FR-020
question metadata); CHK051 and CHK123 (FR-099); CHK053 (FR-100, FR-101);
CHK054 (FR-105 invalidation); CHK086 (FR-031; Appendix A); CHK107 (a criterion D14 later retired); CHK117 (FR-082); CHK119 (this section);
CHK121 (User Story 1, scenario 1); CHK122 (FR-125, FR-127); CHK127
(Edge Cases; FR-013). Earlier statements calling FR-082 "the one" intended
user-visible behaviour change — the Q2 decision below included — are
superseded by FR-082's current text, which names four (D18).

### Session 2026-09-14 (remediation)

- Q: When a user explicitly cancels or declines a **mandatory** clarification,
  may the agent proceed on a stated assumption? → A: **No.** Cancellation,
  decline, expiry and absence are lifecycle outcomes, not information outcomes.
  None of them supplies the missing answer, and none authorises the agent to
  invent one. Only a real answer resolves a mandatory clarification and resumes
  dependent work. An agent-chosen assumption remains available **only** for
  decisions that do not pass the materiality test of FR-007.
  *Binds*: FR-003, FR-018, FR-019, FR-022, FR-130; SC-037 to SC-041.
- Q: Does the user-cancelled case need a new protocol state? → A: **No.**
  *(Refined by the encoding session below. "No new state" still holds; what that
  session settles is **where** the distinction is carried — the clarification
  payload, not the turn outcome.)*
  *Binds*: FR-022, FR-035, FR-080.
- Q: May a cancelled mandatory question be re-raised? → A: **Not within the same
  decision attempt.** The agent reports the unresolved decision; a later explicit
  user request may resume or answer it.
  *Binds*: FR-129; SC-044.

### Session 2026-09-14 (outcome encoding)

- Q: How should a dismissed or expired **question** be reported, given that the
  turn-level cancelled outcome already means the whole turn was cancelled or
  interrupted? → A: **One top-level stop category for every mandatory
  clarification that ends without the required answer** —
  `stopped = "clarification_required"` — with the precise clarification lifecycle
  carried in an additive, optional field inside the structured clarification
  payload: `clarification.outcome ∈ {cancelled, expired, unattended}`.
  *Binds*: FR-035, FR-123.
- Q: Should `stopped` gain `clarification_cancelled` / `clarification_expired`?
  → A: **No.** No clarification-specific value is added to the turn outcome.
  `stopped = "cancelled"` is preserved **exclusively** for cancellation or
  interruption of the entire agent turn, exactly as the repository uses it today,
  and is never reused for question dismissal.
  *Binds*: FR-022, FR-035, FR-071.
- Q: What protects old clients? → A: `clarification.outcome` is additive and
  optional under the already-planned negotiated clarification capability
  (FR-080). A client that does not negotiate the capability never receives it and
  keeps its existing semantics unchanged.
  *Binds*: FR-079, FR-080; SC-023.

**Why this encoding.** The turn lifecycle and the clarification lifecycle are
different things. Collapsing them would have made a dismissed question
indistinguishable from the person pressing stop — a fresh ambiguity introduced in
the middle of a feature whose whole purpose is removing ambiguity. The payload
already carries clarification detail, so the discriminator belongs there.

**Supersession**: this session narrows the declined path that Q2 below left in
place. Q2's decision — that all non-interactive surfaces block — stands
unchanged. What changed is that an *attended* form which the user cancels no
longer proceeds on assumptions either. Options B and C in the Q2 table remain
recorded as what was rejected; the "proceed with stated assumptions" behaviour
they describe is now forbidden for mandatory clarifications on every surface.

### Q1: What token reduction counts as success?

**Superseded by D14 (2026-09-28).**

### Q2: Which surfaces block on a mandatory clarification?

**Context**: FR-033–FR-035, FR-082. Today, a form that nobody answers — whether
dismissed by a person or raised where no client was listening — returns the same
outcome, and the agent is told to choose sensible defaults and say which it took.
Separating those cases is the central behaviour change of this initiative, and it
changes what a scheduled run, a channel message or a piped command does when the
agent needs a decision.

**What we need to know**: Which surfaces stop with a clarification-required
outcome, and which keep today's proceed-with-stated-assumptions behaviour.

> **Historical record.** The options below are reproduced as they were put to the
> user on 2026-09-14. **Options B and C were rejected, and the behaviour they
> describe is now forbidden outright** by the remediation session recorded above
> (FR-019, FR-130). Nothing in this table is a live rule.

| Option | Answer | Implications |
| ------ | ------ | ------------ |
| A ✅ chosen | All non-interactive surfaces block | Strongest guarantee against invented values. Scheduled jobs and channel requests that hit an ambiguity stop and report instead of producing something; some currently-completing automated runs will begin returning "needs a decision". |
| B ❌ rejected, now forbidden | Block only where the decision is destructive, security-relevant, or changes persisted state; proceed with stated assumptions otherwise | Preserves most automation while closing the cases that cause real damage. Requires a defensible line between the two classes and will occasionally place a decision on the wrong side. |
| C ❌ rejected, now forbidden | Never block; always proceed with stated assumptions, but report the open decision in a structured field the caller can read | No existing automation changes behaviour. Weakest option — an invented value still reaches the output, only now it is labelled. |
| Custom | Provide your own answer | Name the surfaces (scheduled runs, channels, piped command line, API, agent-to-agent) and the behaviour each should have. |

**Decision (2026-09-14)**: **Option A — all non-interactive surfaces block.**
See FR-035, FR-121 to FR-123. This is the reading Constitution XV already
mandates. Blocking is confined to decisions that pass the FR-007 materiality
test, and a run ending in the clarification-required outcome reports it as a
distinct machine-readable outcome so callers can route it for an answer rather
than retry it as an error. This is the initiative's one intended user-visible
behaviour change (FR-082).

### Q3: May the completion gate block a completion claim, or only annotate it?

**Context**: FR-036, FR-043. The existing mechanism annotates: where an answer
claims a passing check that nothing ran, a notice is attached beside it, and the
answer still reaches the user. Extending the gate to cover unresolved requested
work raises the question of whether it may also *withhold* a completion claim.

**What we need to know**: The gate's authority when it finds unresolved work.

| Option | Answer | Implications |
| ------ | ------ | ------------ |
| A | Annotate only — the answer is delivered with the unresolved work named beside it | Consistent with existing behaviour and never wrong in a way that costs the user their result. A user skimming the answer may still read it as complete. |
| B | Block the completion claim — the agent must rewrite its answer to state the work is incomplete before it is delivered | Strongest guarantee that "done" is truthful. Costs an extra model turn, and a gate that misjudges completeness turns a finished task into a confusing one. |
| C | Annotate by default; block only where the agent explicitly claimed completion and evidence contradicts it | Targets the precise failure — a false claim of completion — while leaving honest partial answers untouched. More conditions to get right. |
| Custom | Provide your own answer | State when the gate may block, and what the agent does when it does. |

**Decision (2026-09-14)**: **Option C — annotate by default, block only a
contradicted completion claim.** See FR-124 to FR-127. An honest partial answer
is never withheld; an explicit claim of completion that the evidence contradicts
is corrected before delivery, at a cost of at most one additional turn.

---

## Assumptions

- **Existing architecture is extended, not replaced.** Every behaviour in this
  specification maps onto an existing subsystem (Appendix A). No new parallel
  memory, question, context, prompt or orchestration subsystem is introduced.
- **The clarification transport already exists and is sufficient.** Questions are
  already a negotiated protocol capability carried in session snapshots and
  rendered by both interfaces; this initiative changes when questions are raised
  and what happens when they are not answered, not how they travel.
- **The mandatory custom-answer row already exists** and is appended by the core
  rather than the model. This specification preserves that guarantee rather than
  creating it.
- **Acceptance calls no provider** (D14).
  Behaviour is established by deterministic tests with scripted model
  responses, and learning stays switchable off (FR-064).
- **Token counting is estimated and calibrated against reported provider usage**;
  figures are treated as calibrated estimates, and no success criterion depends
  on exact tokenizer parity with any single provider.
- **No new outbound network transmission is introduced.** Observability is
  aggregation over records the product already writes locally.
- **Security and permission invariants are unchanged.** Mode capabilities, the
  fail-closed rule for unknown modes, and the rule that a frontend never grants
  authorization on its own are preserved exactly; clarification never becomes a
  route to an action the mode forbids.
- **Scope is the core agent.** Trading is excluded. Desktop is unaffected because
  the surface does not exist yet.

---

## Dependencies and Integration Notes

### PR #39 — "Establish the trading core domain" (branch `feat/trading-core-foundation`)

**Status**: Open, based on `main`, reported mergeable, last updated 2026-09-07.

**Overlap assessment**: Inspected for overlap only, as instructed. The pull
request touches thirteen paths: `src/comodor/trading/` (nine files),
`tests/test_trading_domain.py`, `tests/test_trading_market.py`,
`tests/test_trading_orders.py`, `docs/trading.md` and `docs/README.md`.

**Finding — no material conflict.** None of the subsystems this initiative
extends is touched by PR #39. The single shared path is `docs/README.md`, a
documentation index, where both changes would add an entry. That is an ordinary
textual merge, not an architectural conflict, and it is **not** recorded as a
blocking integration decision.

**Note on local state**: a `src/comodor/trading/` directory exists in the working
tree containing only a `__pycache__` folder. It is untracked build residue from a
previous checkout of that branch, not source, and it carries no code this
initiative could depend on.

**Constraints honoured**: PR #39 is not merged, closed, rebased, modified or
depended upon, and no trading functionality enters this specification.

### Release constraints

No tag, release workflow, publication, release, deployment or production change
forms any part of this initiative (FR-084).

---

## Appendix A: Existing Capability Inventory

Taken from the repository before this specification was written. It is the
evidence for "extend, do not duplicate", and the basis of the gap statements
above. Requirements reference behaviour; this table names the owner so a reviewer
can check that no parallel subsystem was introduced.

| Area | Existing owner | What already holds | The gap this initiative closes |
| --- | --- | --- | --- |
| Question form primitive | `src/comodor/questions.py` | Shapes shared by tool, terminal and browser; mandatory custom-answer row appended by the core; nothing answered on the user's behalf | Nothing structural — preserve and test the guarantees |
| Terminal question overlay | `apps/tui/src/App.tsx`, `packages/questions` | The terminal renders a question form as an overlay; the shared `packages/questions` package holds form position and selection as a pure reducer with no rendering and no timers, so keyboard behaviour is deterministic by construction | Render the added reason and evidence fields; keep keyboard behaviour deterministic (FR-031) |
| Asking tool | `src/comodor/tools/ask.py` | One call for the whole set; SAFE, so available in plan mode; guidance not to ask what it can find out | Distinguish "declined" from "nobody present"; strengthen when asking is mandatory |
| Clarification transport | `schemas/protocol/v2.json` | `question.requested`, `question.answer`, `question.resolved`; `QuestionField`/`QuestionOption`/`QuestionAnswer`; answers matched by stable header; pending interaction in session snapshot; `questions` is a negotiated capability | Additive representation of a clarification-required outcome for non-interactive callers |
| Blocking-request lifecycle | `src/comodor/events.py` | `resolve()` waits, claims, and publishes expiry so no client shows a settled decision; `listening` reports whether anyone is there | Use presence to separate declined from unattended |
| Mode capability | `src/comodor/safety/modes.py` | Frozen policy table; every real mode permits questions; conversation-only modes permit no inspection tools; unknown mode denies everything | Make the evidence-before-asking duty mode-aware |
| Unverified-claim notice | `src/comodor/agent/claims.py` | Four-condition notice when an answer claims a passing check and nothing ran | Extend to unresolved requested work (subject to Q3) |
| Completion verification | `src/comodor/agent/verify.py` | Project check runs once after a file-changing turn; bounded; one correction turn; never becomes the error | Add request-versus-delivery comparison |
| Constraint recall | `src/comodor/agent/constraints.py` | User prohibitions restated on write results without touching the cached system prompt | Reuse for decision constraints |
| Context and compaction | `src/comodor/agent/context.py` | Compaction past a configured fraction, only at boundaries with no outstanding tool call; original request always preserved | Relevance-based selection against an explicit budget |
| Stale-read removal | `src/comodor/agent/staleness.py` | Superseded reads replaced by a note; never the newest read; never an unedited file | Measurement and coverage |
| Token accounting | `src/comodor/agent/tokens.py` | Estimation calibrated against reported provider usage | — |
| Prefix caching | `src/comodor/providers/caching.py` | Cache marks and byte-identical prefix discipline | Preserve under every new behaviour |
| Oversized results | `src/comodor/tools/overflow.py` | Spill to file with head, tail and an exact pointer; originals pointed at in place, never copied | Measurement |
| Delegated work | `src/comodor/tools/delegate.py`, `src/comodor/agent/background.py` | Sub-agent reading stays in the sub-conversation; completions land at turn boundaries; origin-tagged events | Clarifications raised by delegates |
| User-supplied context | `src/comodor/context_refs.py` | `@` expansion with credential, binary and budget refusals | Unchanged |
| Learning engine | `src/comodor/learning/memory.py` | Recall, credit, reflect, consolidate; recalled items shown to the user | Provenance and staleness discipline |
| Knowledge store | `src/comodor/learning/store.py`, `facts.py` | Single store, project versus user scope, hard caps, refusal rather than silent eviction | Invalidation on repository change |
| Behavioural signals | `src/comodor/learning/signals.py`, `rules.py` | Deterministic correction and convention detection, counted with evidence, no model call | Conflict resolution between contradictory corrections |
| Curation | `src/comodor/learning/curator.py` | Deterministic staleness marking, duplicate merging, nothing hard-deleted | Repository-fact-driven invalidation |
| Learning visibility | `src/comodor/learning/journey.py`, `progress.py`, `tools/memory.py` | Timeline, improvement measures with honesty rules, user curation | Hit-rate and stale-rate reporting |
| Session persistence | `src/comodor/session/store.py` | Append-only records surviving a crash; redacted exports | Outstanding forms across reconnect |
| Local metrics | `src/comodor/insights.py` | Aggregation over records already written; no new collection; no guessed figures | Token and clarification metrics |
| Capability discovery | `src/comodor/tools/registry.py` | Tools filtered by mode at advertisement as well as at enforcement, both reading one rule, so a forbidden capability is never offered to the model | Extend to any capability this initiative adds |
| Capability inventory | `tools/capability-map.py`, `CAPABILITIES.md` | Inventory generated from the code, with a check form for CI, rather than hand-maintained | Register new capabilities; keep the check green |
| Project instructions | `src/comodor/agent/prompts.py` | System prompt assembled in a fixed order chosen so stable parts come first and provider prefix caching keeps hitting; learned material injected as a separate, visibly distinct block | Keep instructions stable per task; keep recalled knowledge budgeted and traceable |
