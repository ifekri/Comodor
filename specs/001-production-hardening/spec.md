# Feature Specification: Production Hardening and Quality Improvement

**Feature Branch**: `001-production-hardening`

**Created**: 2026-09-14

**Status**: Draft

**Input**: User description: "Create a production-hardening and quality-improvement specification for the existing Comodor codebase. This is an existing mature project. Do not redesign or rewrite the application and do not introduce a new architecture unless a concrete defect proves that it is necessary. [Context: cross-platform coding agent on Windows, Linux and macOS; core/runtime, CLI/headless surfaces, a terminal interface, protocols and code generation, integrations, persistence and session handling, release infrastructure, container support, committed generated interface artifacts, a large automated test suite; the recent macOS renderer failure was a stale render-time overlay ref, fixed by eager overlay state synchronization and a closing ownership latch; timing-sensitive tests must not be fixed with sleeps, retries, widened timeouts or weakened assertions; generated artifacts must remain reproducible; release infrastructure and protocol contracts are production surfaces; existing behaviour and public interfaces stay backward compatible unless a breaking change is explicitly approved; no release workflow run, tag, publication or deployment is part of this work.] Primary objective: systematically raise the engineering quality, reliability, determinism, maintainability, release safety and cross-platform correctness of the existing repository without unnecessary refactoring, covering at minimum eighteen named areas, separating confirmed defects from suspected risks, with repository evidence for every defect, an explicit acceptance criterion for every behaviour change, minimal targeted corrections, no stylistic-only changes, no speculative abstractions, no weakened tests, explicit affected and unchanged surfaces, and measurable completion criteria."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A person's keystrokes always mean what they meant (Priority: P1)

Someone using the terminal interface types, pastes, holds a key, opens and
closes overlays (the command palette, the model chooser, the earlier-
conversations picker, the work panel, permission and question cards), and
resizes the window — sometimes faster than the screen can redraw. Every key
is handled against the state the person is acting on, not the state that
happened to be drawn last, and no key ever reaches a part of the interface
the person cannot see.

**Why this priority**: The most recent production defect was exactly this —
a pasted command and its Enter ran a different command and flipped the
working mode. Input ownership is the interface's core promise, and a
failure here silently does something the person did not ask for.

**Independent Test**: Deliver the interface to a tester with a scripted set
of fast inputs (pasted text with Enter, repeated Enter while an overlay
closes, arrow keys during a redraw, a resize mid-interaction) and confirm
every outcome matches the intended action; all of these are also encoded as
deterministic automated scenarios that pass on all three platforms.

**Acceptance Scenarios**:

1. **Given** any overlay is open, **When** a query and its confirming key
   arrive in one chunk, **Then** the confirmed item is the one the query
   selected, never the item drawn before the query.
2. **Given** an overlay has just been dismissed but is still on screen,
   **When** further keys arrive before the redraw, **Then** they are
   consumed by the dismissed overlay and none reach the composer or any
   surface beneath it.
3. **Given** a blocking prompt (permission or question) is showing,
   **When** keys arrive, **Then** they are handled by that prompt only, and
   a duplicate reply is refused rather than sent twice.
4. **Given** the terminal is resized during any interaction, **When** the
   redraw completes, **Then** the interaction's state is intact and the
   layout fits the new size with no content silently clipped.

---

### User Story 2 - A release can be trusted before it is cut (Priority: P1)

A maintainer preparing a release rehearses it without publishing anything,
sees exactly what each destination holds and what the release would do,
builds the distributions and the packaged interface artifact reproducibly,
installs the result on a clean machine, and only then decides to tag. If a
publication is interrupted, running it again finishes the release without
duplicating or overwriting anything.

**Why this priority**: Publication is the one action that cannot be undone;
the project has already lost one version number to a release-time failure.

**Independent Test**: Run the non-mutating rehearsal for a version that
does not exist yet and confirm its plan names every destination as absent;
build the artifacts twice and confirm they are identical; install the wheel
into a clean environment and confirm the reported version, the interface
launch and the diagnostics all agree.

**Acceptance Scenarios**:

1. **Given** no release exists for the rehearsed version, **When** the
   rehearsal runs, **Then** it reports every destination as absent, plans
   the full publication, and changes nothing anywhere.
2. **Given** the generated interface artifact is rebuilt from unchanged
   source, **When** the outputs are compared, **Then** they are
   byte-identical and the working tree shows no change outside the
   artifact's own path.
3. **Given** a release stopped after some destinations were published,
   **When** it is run again, **Then** the published destinations are
   verified and skipped and only the missing ones are completed.
4. **Given** the built distribution is installed into a clean environment,
   **When** the version, the diagnostics and the interface launch are
   checked, **Then** all three agree with the built version and the
   packaged interface is the one used.

---

### User Story 3 - The test suite says the same thing every time (Priority: P2)

A contributor runs the full automated suite — core, interface renderer,
frontend, release infrastructure — on any of the three platforms and under
load, and gets the same result every run. A failure is a defect, never
"try again".

**Why this priority**: A suite that sometimes fails trains people to ignore
failures, which is how real defects ship; the last three renderer failures
in continuous integration were each a real synchronization defect that a
rerun would have hidden.

**Independent Test**: Run the complete suite repeatedly on each platform
and under artificial load; every run passes, and the set of tests that
depend on wall-clock timing, single scheduler yields or transient text is
known and either converted to deterministic synchronization or justified.

**Acceptance Scenarios**:

1. **Given** the full suite, **When** it is run twenty consecutive times on
   each platform, **Then** every run passes with the same counts.
2. **Given** a test synchronizes on an intermediate frame, a single yield
   or unrelated text, **When** the audit is complete, **Then** that test
   waits on the semantic state it then asserts, with no sleep, retry or
   widened timeout introduced.
3. **Given** a confirmed defect, **When** its fix is delivered, **Then** a
   deterministic regression test exists that fails on the defect and
   passes on the fix.

---

### User Story 4 - A conversation survives interruption (Priority: P2)

A person's session — its transcript, plan, background work and settings —
survives a disconnect, a reconnect, a reopen from history and a restart of
the core. Events from a conversation left behind never appear in the one
now on screen; a gap in the event stream is repaired from the source of
truth, not guessed at.

**Why this priority**: Persistence is how the agent keeps what it learned
and what it was doing; losing or mixing conversations destroys trust in the
product's memory.

**Independent Test**: Start work, disconnect, reconnect, open an earlier
conversation, restart the core, and confirm the transcript, plan, delegate
states and mode are exactly as they were, with no events from the previous
conversation showing.

**Acceptance Scenarios**:

1. **Given** a live session with running background work, **When** the
   connection drops and returns, **Then** the screen is rebuilt from the
   core's snapshot and continues from it without duplicate or lost events.
2. **Given** an earlier conversation is reopened, **When** the previous
   session's events arrive afterwards, **Then** none of them land on the
   reopened conversation.
3. **Given** the event stream skips a number, **When** the gap is
   detected, **Then** the state is refreshed from the source of truth and
   the stale event is discarded.
4. **Given** the core restarts, **When** the person returns, **Then**
   settings, learned rules and history are intact and readable.

---

### User Story 5 - Background work ends the way it says (Priority: P3)

A person delegates work to a background agent, watches it, stops it, or
loses it to a crash, and the interface always shows the true state as the
core reports it — running, stopping, stopped, done, lost — with a stop
control that is offered only where a stop is possible and acts only on the
row the person chose.

**Why this priority**: Background work runs commands on the person's
machine; a stop that does not stop, or a stop aimed at the wrong work, is a
safety problem.

**Independent Test**: Delegate several tasks, stop one by keyboard and one
by mouse, crash one, and confirm each row's state and the stop control's
availability match the core's events, with exactly one stop request per
stop action.

**Acceptance Scenarios**:

1. **Given** several background agents, **When** one is stopped by
   keyboard or mouse, **Then** exactly one stop request is sent for exactly
   that agent, and its row moves only when the core confirms.
2. **Given** a background agent is lost, **When** its final event arrives,
   **Then** the row shows the loss and its reason and no stop is offered.
3. **Given** a cancellation or a cleanup path, **When** it runs, **Then**
   every resource it owned (processes, watchers, temporary files, raw
   terminal mode) is released, and this is verified rather than assumed.

---

### User Story 6 - The same behaviour on every platform and every surface (Priority: P3)

Whether someone uses the command line, the headless mode, the browser
interface, a chat integration or the container, on Windows, Linux or macOS,
documented commands and options work as documented, the protocol and its
generated definitions agree, and any difference between platforms is
deliberate, isolated and stated.

**Why this priority**: The product ships as one package to three platforms
and several surfaces; drift between them is discovered by users, one
platform at a time.

**Independent Test**: Run the documented command-line, headless and
integration entry points on each platform against the documented
behaviour; regenerate the protocol definitions and confirm no difference;
compare documentation with actual behaviour and list every disagreement.

**Acceptance Scenarios**:

1. **Given** the protocol schema, **When** the generated definitions are
   regenerated, **Then** the tree does not change.
2. **Given** a documented command, option or integration behaviour,
   **When** it is exercised, **Then** it behaves as documented, or the
   disagreement is recorded as a confirmed defect with a decided
   resolution.
3. **Given** a platform-specific code path, **When** it is audited,
   **Then** it is explicitly isolated, its reason is stated, and the other
   platforms are unaffected.

---

### Edge Cases

- Two returns arrive in one chunk while an overlay's close is queued: the
  second must be consumed, not delivered to the composer with a draft.
- A key arrives while a blocking prompt exists in the projection but no
  draft has been built for it yet: keys are ignored until the draft exists.
- The event stream skips a number during a redraw: repair must not wipe
  work the person is doing in the composer.
- An overlay is closed and reopened within the same batch of keys.
- A background agent's final event arrives after the person opened another
  conversation.
- The interface is resized to the narrowest supported width while a card
  with buttons is showing: buttons wrap, remain reachable and remain
  actionable.
- A generated artifact is rebuilt on a platform other than the one it was
  committed from: the reproducible part must still match; the
  platform-specific part is excluded by design and stated.
- A release rerun finds a destination holding a file with the expected name
  but different contents: the run fails closed and names both digests.
- A dry run is dispatched from a branch with publication switched off: it
  must be refused, not published.
- A tool call, cancellation or shutdown races with a pending permission
  reply: the reply is refused or applied exactly once, never twice.
- Untrusted text (from providers, models, integrations or errors) contains
  terminal control sequences or forged status words: the interface is not
  rewritten and the words are not shown as the product's own status.
- A test is run under heavy load: it must synchronize on the state it
  asserts, and a slow machine must only make it slower, never wrong.

## Requirements *(mandatory)*

### Functional Requirements

**Method and evidence**

- **FR-001**: The hardening effort MUST begin with an audit of each of the
  eighteen areas named in the input, and MUST record for each area a list
  of findings, each classified as exactly one of *confirmed defect*
  (reproduced, with the reproducing command, test or log cited) or
  *suspected risk* (reasoned, not reproduced, with what would confirm it).
- **FR-002**: No behaviour change MAY be made on the basis of a suspected
  risk alone; a suspected risk is either promoted to a confirmed defect by
  a reproduction or recorded as accepted with its rationale.
- **FR-003**: Every confirmed defect MUST be fixed by correcting the
  product or test invariant that was violated, with the smallest change
  that does so, and MUST NOT be addressed by sleeps, retries, raised
  timeouts, skipped or expected-failure tests, weakened assertions, suite
  serialization, or widened terminals.
- **FR-004**: Every fix MUST carry a deterministic regression test that
  asserts externally observable behaviour and that fails on the defective
  code and passes on the fix; where such a test is technically impossible,
  the delivery MUST say so and why.
- **FR-005**: Every fix and every audit finding MUST be delivered in a
  narrowly scoped change that does one thing, with no unrelated refactor,
  cleanup, formatting or dependency change attached.
- **FR-006**: The effort MUST NOT redesign, rewrite or re-architect any
  part of the product unless a confirmed defect cannot be fixed within the
  existing structure, in which case the change MUST be proposed and
  approved separately before it is made.

**Runtime, state and concurrency**

- **FR-007**: Every state a handler acts on (keyboard, mouse, events,
  timers, replies) MUST be the latest committed state, and the audit MUST
  enumerate every place where a handler reads a snapshot taken at draw time
  and confirm or correct each.
- **FR-008**: Every asynchronous operation whose result can arrive after
  the person has moved on (provider probes, model discovery, snapshot
  repair, reopen, background work) MUST carry an identity so that a stale
  result is discarded, and the audit MUST verify this for each such
  operation.
- **FR-009**: Every state transition that can be triggered from more than
  one source (a stop from keyboard and mouse, a close from a key and a
  command, a reply from a card and a shortcut) MUST be applied exactly
  once, and duplicate triggers MUST be refused observably.
- **FR-010**: The core MUST remain the authority for mode, permissions,
  session state and delegate state; the interface MUST move a row, a label
  or a mode only on the core's confirming event, never on the request
  alone.

**Terminal interface determinism and input ownership**

- **FR-011**: Exactly one owner of the keyboard MUST exist at any moment —
  a blocking prompt, an overlay (including one dismissed but not yet
  redrawn), the work panel, or the composer — and the ordering of ownership
  MUST be stated and tested.
- **FR-012**: The renderer's supported widths (160, 120, 100, 80, 60
  columns) MUST each draw every card, overlay and panel within bounds with
  interactive controls reachable, verified on the real renderer.
- **FR-013**: Untrusted display text MUST NOT be able to rewrite the
  interface or forge its status.

**Detection of unsafe timing assumptions**

- **FR-014**: The audit MUST identify every test that reads a frame after
  a single scheduler yield, waits on transient or unrelated text, or
  depends on wall-clock timing for correctness, and every such test MUST
  be converted to wait on the semantic state it then asserts or be
  justified in writing.
- **FR-015**: The audit MUST identify every product path where a
  render-time snapshot, a one-yield assumption or an unguarded transition
  exists, and each MUST be classified under FR-001.

**Session lifecycle and persistence**

- **FR-016**: Reconnect, reopen, gap repair and core restart MUST restore
  the session exactly — transcript, plan, delegates, mode, settings,
  learned rules — with no duplicated, lost or cross-session events, and
  these MUST be covered by deterministic tests.
- **FR-017**: Persisted formats (configuration, session store, brain
  store, journals, checkpoints) MUST remain readable by the current
  version from every previous format still in use, and any format change
  MUST be a declared breaking change with a migration.

**Background work**

- **FR-018**: Every delegate state the core can report MUST be presented,
  a stop MUST be offered only where the core allows one, and a stop action
  MUST produce exactly one stop request for exactly the chosen delegate.

**Compatibility surfaces**

- **FR-019**: Command-line commands, options, exit codes and output
  formats, headless and API entry points, integration behaviours and the
  container's entry behaviour MUST remain backward compatible; any
  intentional change MUST be declared as breaking and approved before it
  is made.
- **FR-020**: The protocol schema MUST remain the single source of the
  generated definitions; regenerating them MUST produce no change, and any
  schema change MUST be compatible with the current protocol version or be
  declared breaking.

**Generated artifacts and packaging**

- **FR-021**: The committed interface artifact MUST be rebuilt whenever
  its source changes and MUST be byte-identical on a second build; the
  only tree change a build may cause is within the artifact's own path.
- **FR-022**: The distribution build MUST be reproducible, MUST name
  exactly the release version, MUST pass the wheel-contents and metadata
  guards, and MUST install and run from a clean environment reporting that
  version.
- **FR-023**: The release workflow MUST remain non-mutating in every dry
  run and rehearsal, MUST be anchored to a real tag for publication, MUST
  be idempotent and recoverable across all four destinations, and MUST
  fail closed on any conflict; the container image MUST carry its version
  and revision and report the version it installs. This effort MUST NOT
  run a production release, create or move a tag, publish, or deploy.

**Cross-platform**

- **FR-024**: Every confirmed platform-specific difference in behaviour
  MUST be either eliminated or explicitly isolated with its reason stated,
  and the automated suite MUST pass on all three platforms.

**Security and trust boundaries**

- **FR-025**: No permission, approval, mode, safety or trust-boundary
  behaviour MAY be weakened; the standing invariants (ask mode grants no
  general tools, plan mode is read-only, act mode is permission-controlled,
  unknown mode fails closed, direct tool invocation cannot bypass policy,
  the interface never grants authorization) MUST be re-verified by tests
  after the effort, and secrets MUST NOT appear in state, snapshots,
  journals, checkpoints, logs, arguments or fixtures.

**Errors, cancellation and resources**

- **FR-026**: Every cancellation and cleanup path MUST release everything
  it owns — child processes, watchers, background threads, temporary files,
  raw terminal mode — and the audit MUST verify each with a test or a
  documented reason none is possible; user-facing errors MUST be
  actionable and MUST NOT show raw stack traces in the normal interface.

**Static analysis and types**

- **FR-027**: The existing lint and type-check gates MUST remain green,
  and any newly typed or newly checked area MUST be added without
  suppressions that hide real findings.

**Performance**

- **FR-028**: A performance change MAY be made only where a measurement
  against the repository's existing ceilings shows a regression or a
  defect, and the measurement MUST be recorded with the change.

**Dead code, duplication and drift**

- **FR-029**: Dead code, duplicate logic or an obsolete compatibility path
  MAY be removed only with repository evidence that nothing reaches it
  (no caller, no documented entry point, no test, no protocol reference),
  in its own change, and never as part of a fix.
- **FR-030**: Every disagreement between documented behaviour and actual
  behaviour MUST be recorded as a confirmed defect and resolved by
  correcting whichever side is wrong, with the decision stated.

**Reporting**

- **FR-031**: Every change MUST state, using the canonical surface list
  below, which surfaces are affected and which are unchanged, with
  concrete evidence for each unchanged claim.
- **FR-032**: The effort MUST end with a report listing every confirmed
  defect and its fix, every suspected risk and its disposition, every
  change made, and the validation evidence for each, on the exact final
  revision.

### Affected Surfaces

The canonical surface list and the effort's expected classification. The
audit may move a surface from unchanged to affected when a confirmed defect
requires it; it may never claim a surface unchanged without evidence.

| Surface | Expected | Rationale |
|---|---|---|
| TUI | Affected | input ownership, renderer determinism, width behaviour, artifact rebuild |
| Web UI | Unchanged unless a confirmed defect | shares the core; verified by its own tests |
| CLI / Headless | Unchanged in behaviour; verified | compatibility is a requirement (FR-019) |
| API / Protocols | Unchanged in schema; generated definitions verified fresh | FR-020 |
| Desktop | Not applicable | no desktop client exists in the repository |
| Channels / Integrations | Unchanged unless a confirmed defect | verified by their tests and documented commands |
| Docker / Packaged Runtime | Affected only through verification and any confirmed defect | FR-021 to FR-023; no publication |
| Persistence / Shared State | Unchanged in format; behaviour verified | FR-016, FR-017 |
| Security / Authorization | Unchanged; re-verified | FR-025 |
| Tests / Documentation | Affected | regression tests, deterministic waits, corrected documentation |

### Key Entities

- **Finding**: one observation from the audit — its area, evidence,
  classification (confirmed defect or suspected risk), disposition, and
  the change that resolved it, if any.
- **Confirmed Defect**: a finding with a reproduction — command, test or
  log — that the fix's regression test encodes.
- **Suspected Risk**: a finding without a reproduction, carrying what
  would confirm it and whether it was accepted or promoted.
- **Surface**: one of the ten canonical product surfaces, with its
  classification and evidence per change.
- **Hardening Change**: one narrowly scoped delivery — its findings, its
  regression tests, its surface table and its validation evidence.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every one of the eighteen audit areas has a recorded set of
  findings, and 100% of findings are classified as confirmed defect or
  suspected risk with the evidence FR-001 requires.
- **SC-002**: 100% of confirmed defects are fixed with a regression test
  that was shown to fail before the fix and pass after it, or carry a
  written reason none is possible.
- **SC-003**: The complete automated suite (core, renderer, frontend,
  release infrastructure) passes twenty consecutive runs on each of
  Windows, Linux and macOS with identical pass counts, and ten consecutive
  runs on one platform under artificial load, with zero failures.
- **SC-004**: The renderer suite contains zero tests that read a frame
  after a single yield, wait on transient or unrelated text, or depend on
  wall-clock timing for correctness, other than those individually
  justified in writing.
- **SC-005**: The generated interface artifact and the distributions are
  byte-identical across two consecutive builds, and a build changes
  nothing in the tree outside the artifact's own path.
- **SC-006**: Regenerating the protocol definitions produces no change,
  and the protocol version is unchanged.
- **SC-007**: A clean-environment install of the built distribution
  reports the built version, launches the packaged interface, and passes
  the diagnostics check on all three platforms.
- **SC-008**: The non-mutating release rehearsal for an unreleased version
  reports every destination as absent and makes zero changes to the
  package index, the release page, either registry or any tag; a rerun of
  a complete release makes zero changes.
- **SC-009**: The input-ownership scenarios in User Story 1 — pasted
  query and confirm, repeated confirm during close, keys during a blocking
  prompt, resize mid-interaction — each have a deterministic automated
  scenario passing on all three platforms.
- **SC-010**: Every documented command, option and integration behaviour
  exercised in the audit matches its documentation, or the disagreement is
  recorded and resolved; zero unresolved documentation disagreements
  remain.
- **SC-011**: Every change delivered by the effort carries the ten-row
  surface table with evidence, and the effort's final report accounts for
  every finding on the exact final revision.
- **SC-012**: The security invariants in FR-025 are each covered by a
  passing test after the effort, and zero tests that existed before the
  effort were removed, skipped or weakened.
- **SC-013**: No production release was run, no tag created or moved, and
  nothing was published or deployed during the effort.

## Assumptions

- The effort is delivered as a sequence of small, independently reviewable
  changes — one per confirmed defect or tightly related cluster — rather
  than one large change, in keeping with the project's narrow-scope rule.
- "Twenty consecutive runs" is the completion bar for suite determinism on
  each platform; where a platform is only available through continuous
  integration, the twenty runs are continuous-integration runs of the
  final revision.
- The audit's eighteen areas are examined in the order of user impact
  given by the user stories (input ownership and release safety first,
  then test determinism, session lifecycle, background work, then the
  remaining areas), and areas with no confirmed defect are closed with
  their suspected-risk list.
- The repository's existing quality gates (lint, type-check, generation
  freshness, full test suite, performance ceilings, renderer suite,
  release-infrastructure tests, cross-platform continuous integration) are
  the definition of "green"; no new gate is introduced unless a confirmed
  defect shows a gap.
- Windows, Linux and macOS are exercised through the existing
  continuous-integration matrix plus local runs on the platforms
  available to contributors; a defect reproducible only on a platform not
  locally available is diagnosed from its logs and fixed with a
  deterministic test that would fail on that platform.
- Performance work is limited to the repository's existing measured
  ceilings; no new performance targets are set by this effort.
- Documentation corrections are limited to disagreements with actual
  behaviour; documentation is not rewritten for style.
- The next intended release remains outside this effort's scope; the
  effort neither prepares nor blocks it beyond leaving the release
  infrastructure verified.
