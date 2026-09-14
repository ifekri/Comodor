<!--
Sync Impact Report
- Version change: 1.0.0 → 1.1.0 — nine new principles added, none removed or
  redefined
- Modified principles: none. Principles I–XII are preserved verbatim in
  wording and intent
- Added sections: Core Principles XIII–XXI (Quality-First Agent Behaviour;
  Evidence Before Assumption; Interactive Clarification Is a Product
  Invariant; Token Efficiency Is a Product Requirement; Progressive Learning
  With Continued Use; Extend Existing Capabilities, Never Duplicate Them;
  Grounded Tool Use; User Control Over Consequential Actions; Quality and
  Token Efficiency Are Measured Together); one paragraph added to
  "Compatibility Surfaces and Quality Gates" naming the benchmark evidence
  required of context- and token-affecting changes
- Removed sections: none
- Other edits: one clarifying sentence added to the preamble distinguishing
  the build-time principles (I–XII) from the agent-behaviour principles
  (XIII–XXI); no existing rule changed
- Templates: dependent templates and commands read this file at runtime and
  were not modified
- Application source: not modified by this amendment
- Follow-up TODOs: none — no placeholder tokens deferred
-->

# Comodor Constitution

Comodor is a mature, production-oriented, cross-platform coding agent: a
Python core that owns truth, a versioned protocol that transports it, shared
client semantics that reconstruct it, and frontends — a terminal interface,
a browser interface, a headless command line, channel integrations and a
packaged container — that present it. This constitution states the rules
every change to Comodor MUST satisfy. Principles I–XII govern how Comodor is
built; Principles XIII–XXI govern how the agent Comodor ships MUST behave,
and a change that degrades that behaviour is a defect in the product, not a
matter of taste. Where a repository guide (`AGENTS.md`, `CLAUDE.md`) gives
more specific direction, that direction applies within these rules; where the
two conflict, this constitution wins.

## Core Principles

### I. Backward Compatibility by Default

Every user-facing surface is a compatibility contract: the command line,
the terminal interface, the headless and API entry points, the protocol,
configuration files, persisted state (sessions, the brain store, journals),
channel integrations, and the packaged runtimes (wheel, sdist, container
image). A change MUST preserve the observable behaviour of each of these
unless a breaking change is explicitly specified, named as breaking, and
accompanied by the migration or deprecation path the specification calls
for. Silent removals, renames and format changes are violations even when
the new behaviour is better.

Rationale: people run Comodor from installed releases, scripts, containers
and integrations they did not write; a surprise on upgrade costs more trust
than any feature earns.

### II. Three First-Class Platforms

Windows, Linux and macOS are equally supported. A change MUST work on all
three, and a fix MUST NOT depend on the timing, scheduling, path handling,
line endings, file modes or terminal behaviour of one platform unless that
dependency is explicitly isolated behind a platform check and stated in the
change. A failure that reproduces on one platform is a defect on all of
them until proven otherwise.

Rationale: the same source ships as one wheel and one image to every
platform; "works on my machine" is not a passing result.

### III. Fix the Invariant, Not the Symptom

A defect involving concurrency, rendering, asynchronous work, event loops,
inter-process communication, networking or state transitions MUST be fixed
by correcting the product invariant that was violated. The following are
NOT fixes and MUST NOT be committed as such: arbitrary sleeps, timeouts
raised to make a race rarer, blind retries, weakened or removed assertions,
skipped or expected-failure tests, or serializing a whole suite to hide a
race. Where a synchronization point is needed, it MUST be a deterministic
one — an event, a barrier, a settled state, a frame that proves the update
landed — and it MUST correspond to the state the code then relies on.

Rationale: a race made rarer is a race shipped to users; a timing fix in a
test hides a product bug and returns on the next loaded machine.

### IV. Deterministic Regression Tests

Every confirmed regression MUST be accompanied by a deterministic regression
test whenever it is technically possible to write one, and the test MUST
fail on the defective code and pass on the fix (a mutation check). Tests
MUST assert externally observable behaviour — what a person, a client, a
registry or an API would see — rather than implementation timing or
internal ordering. A change that cannot be given such a test MUST say so
and say why.

Rationale: a test that asserts behaviour survives refactors and catches the
regression; a test that asserts timing is the flake of next month.

### V. Narrow Scope

A change does one thing. A feature or a bug fix MUST NOT be combined with
unrelated refactors, cleanup, formatting churn, dependency bumps or
architectural changes. Incidental problems discovered on the way are
recorded and addressed separately unless the change is impossible without
them, in which case the coupling is stated explicitly. A pull request whose
diff cannot be reviewed as one decision is too large.

Rationale: a reviewer must be able to hold the whole change in mind and
say what it does; a revert must be able to undo exactly one thing.

### VI. Architectural Boundaries and Protocol Contracts

The layering — core, application services, protocol, shared client
semantics, presentation — MUST be respected: business policy stays in the
core, and frontends present rather than decide. The protocol is versioned
and its schema is the single source of truth; a protocol or other
generated-surface change MUST change the source definition and regenerate
every derived artifact through the repository's established tooling.
Generated files MUST NOT be hand-edited, and a change that makes the
current protocol version incompatible without declaring it is a breaking
change under Principle I.

Rationale: the boundaries are what let several frontends and a future
desktop shell share one truth; a shortcut through them is a fork in waiting.

### VII. Reproducible Committed Artifacts

Committed generated artifacts — the packaged terminal-interface
distribution above all — MUST be reproducible from their source with the
repository's build tooling, byte for byte where the tooling promises it,
and MUST be rebuilt and committed whenever their source changes. A build
that alters anything outside the artifact's own path, or an artifact that
no longer matches its source, is a failed build.

Rationale: what an installed Comodor runs is the committed artifact, not
the source; the two drifting apart ships a fix that nobody receives.

### VIII. Security Is Not Negotiable

Permission, approval, safety, mode and trust-boundary behaviour are
compatibility surfaces and MUST NOT be weakened to make an implementation
easier, faster or greener. The standing invariants hold: the ask mode grants
no general tools, the plan mode is read-only, the act mode is
permission-controlled, an unknown explicit mode fails closed, direct tool
invocation cannot bypass policy, and a frontend never grants authorization
on its own. Secrets MUST NOT enter ordinary state, snapshots, journals,
checkpoints, logs, URLs, process arguments or fixtures.

Rationale: a coding agent runs commands and edits files on someone's
machine; the boundaries are the product's promise, and every relaxation is
a permanent one.

### IX. Release Infrastructure Is Production Code

Workflows, packaging, version derivation, tagging, artifact building,
container images and publication to any registry are production code and
MUST be changed with the same care: audited before editing, tested with
deterministic tests of their decision logic, rehearsed without mutation
where the tooling allows, and validated on the platforms the release runs
on. Publication MUST be anchored to a real release tag, MUST be idempotent
and recoverable — a rerun verifies what exists, publishes only what is
missing, and fails closed on a conflict — and MUST never overwrite a
published file, asset or semantic-version image.

Rationale: a release is the one change that cannot be reverted; PyPI
files and published releases are immutable, and a mistake there costs a
version number forever.

### X. Quality Gates Are Mandatory

The repository's established checks are gates, not suggestions: lint,
type-checking, code-generation freshness, unit and integration tests,
renderer tests on the real renderer, release-infrastructure tests, and the
cross-platform continuous-integration matrix. A change is not done while
any applicable gate is red, and a check MUST NOT be reported as passed
unless it was actually executed on the change as submitted. Evidence is
taken from the exact commit under review, never from an earlier one.

Rationale: a gate that can be skipped is a gate that will be; the matrix
exists because the defects it catches are the ones a single machine hides.

### XI. Specifications Name Their Surfaces

A specification for any non-trivial change MUST explicitly identify which
product surfaces it affects and which it leaves unchanged, using the
repository's canonical surface list — terminal interface, browser
interface, command line and headless, API and protocols, desktop, channels
and integrations, container and packaged runtime, persistence and shared
state, security and authorization, tests and documentation — and MUST give
concrete evidence for every surface claimed unchanged. "Not touched" is a
claim to be verified, not an answer.

Rationale: most regressions arrive through a surface nobody thought the
change reached; naming every surface makes that thought mandatory.

### XII. Done Means Everything Agrees

A change is complete only when the implementation, its tests, its
regenerated artifacts, its documentation where applicable, and the recorded
validation evidence all agree with the specification. Partial delivery MUST
be reported as partial, with what was left out and why; work that is
blocked on a decision is finished around the block and the block is named.
Confidence is stated only where evidence exists; "not verified" is an
acceptable and expected statement where it does not.

Rationale: a report that overstates completion is worse than an honest gap,
because the gap will be discovered by the next person instead of this one.

### XIII. Quality-First Agent Behaviour

Consistently high-quality output is Comodor's primary product
characteristic. Correctness, completeness, relevance, evidence,
architectural consistency and fidelity to the user's intent MUST take
priority over speed, superficial completion and reducing the number of
model calls. The system MUST prefer a small number of well-grounded actions
over a larger number of speculative ones. A result MUST NOT be treated as
high quality merely because it compiles, because tests pass, or because the
model stated it confidently; quality is judged against the user's actual
request, repository evidence, project conventions, the applicable
specification, observable runtime behaviour, tests, and recorded validation
evidence.

Rationale: an agent is trusted for what it gets right unattended; a fast,
confident, wrong answer costs more of the user's time than the agent saved.

### XIV. Evidence Before Assumption

Comodor MUST NOT silently invent facts. This covers files, APIs, repository
state, user preferences, architecture, requirements, values, identifiers,
commands, configuration, expected behaviour and implementation details.
Information MUST be held internally as exactly one of: explicitly provided
by the user; verified from the repository or an available tool; established
project knowledge; deterministically derived from verified information; or
unknown. Unknown information MUST remain unknown until it is resolved, and a
gap MUST NOT be filled with a plausible assumption merely to keep execution
moving. Where information required for a correct decision is missing or
materially ambiguous, execution MUST stop at that decision boundary and ask
(Principle XV).

Rationale: a single invented fact propagates into every later step, and the
user discovers it after the work is built on top of it.

### XV. Interactive Clarification Is a Product Invariant

Where unresolved uncertainty can materially change implementation,
behaviour, architecture, output, security, compatibility, a destructive
action or the interpretation of user intent, Comodor MUST ask the user
rather than guess, using the project's interactive question mechanism rather
than free-form speculative continuation. Each question MUST be concise; MUST
state exactly what decision is required; MUST offer grounded multiple-choice
answers wherever meaningful choices can be identified; MUST NOT offer
invented or misleading options; MUST let the user select exactly the
intended choice; MUST always end with a final option meaning "Other / Enter
a custom answer" when the listed choices may not match the user's intent;
and MUST wait for the answer before continuing any work that depends on it.

A required clarification MUST NOT be bypassed by selecting the first option,
auto-selecting a recommended option, applying a default the project or the
user has not established, inferring intent from incomplete text, or
proceeding and documenting the assumption afterwards. On non-interactive
surfaces the system MUST return an explicit, structured "clarification
required" state instead of guessing.

Rationale: the user is the only authority on their own intent; a question
costs seconds, and a wrong guess costs the whole task and the trust with it.

### XVI. Token Efficiency Is a Product Requirement

Comodor MUST be designed to consume substantially fewer of the user's model
tokens than a naive coding-agent workflow while preserving or improving
quality. Token reduction MUST NOT be obtained by omitting information
required for correctness, weakening validation, skipping relevant repository
inspection, suppressing a useful clarification, truncating critical
evidence, or replacing verified context with unsupported summaries.

Where appropriate the architecture SHOULD prefer relevance-based context
selection, incremental context, deduplication, content-addressed reuse,
cached stable context, delta-based updates, structured compact state,
bounded conversation context, selective retrieval, durable project
knowledge, concise tool results, canonical summaries that carry their
provenance, avoiding retransmission of unchanged files and history, avoiding
re-explanation of facts the system already holds, and using a smaller
context window where it is sufficient. Token consumption MUST be measurable,
and an optimization that reduces tokens while measurably reducing
correctness or quality is a regression, not an improvement.

Rationale: the user pays for every token the agent spends, and an agent that
is cheap by being careless is not cheap — it is paid for twice.

### XVII. Progressive Learning With Continued Use

Comodor MUST become more useful to a user and a project the longer it is
used. Learning MUST be grounded in trustworthy signals: explicit user
corrections, explicit user preferences, accepted implementation decisions,
verified repository conventions, successfully validated outcomes, project
specifications, and durable facts confirmed by a tool or by source. The
system MUST NOT learn permanent behaviour from unsupported model guesses,
failed implementations, rejected suggestions, transient errors, speculative
conclusions or unverified generated content.

Learned knowledge MUST carry its provenance and scope, MUST carry a
confidence where confidence is meaningful, MUST distinguish user-level from
project-level knowledge, MUST NOT leak between unrelated projects, MUST
provide a way to supersede stale knowledge, and MUST resolve conflicts
deterministically. Learning MUST reduce repeated clarification and repeated
token spend without introducing stale assumptions.

Rationale: the value of a long-lived agent is that it stops asking what it
already learned; the risk is that it keeps applying what has since changed.

### XVIII. Extend Existing Capabilities, Never Duplicate Them

Before introducing any new memory, learning, clarification,
context-management, prompt-management, question, state or agent-control
subsystem, the existing Comodor implementation MUST be inspected. Where
equivalent or related machinery already exists, it MUST be extended or
consolidated rather than paralleled by a second architecture. This applies
with particular force to learning, memory, session state, ask and question
flows, permission prompts, prompt construction, context construction,
history, model orchestration, tools, capability discovery, protocol messages
and persistence.

Rationale: two systems that do the same thing diverge, and the product then
behaves differently depending on which one a code path happened to reach.

### XIX. Grounded Tool Use

Where a repository or runtime fact can be verified with an available tool,
Comodor MUST verify it before making a consequential claim or modification.
The agent MUST NOT claim that a file exists without evidence, that a test
passed without running it or receiving its result, that an API exists
without verification, that the repository is in a given state without
inspecting it, or that a bug is fixed without reproducing or otherwise
validating the relevant behaviour.

Rationale: the tools are what separate an agent from a guess; declining to
use them converts verifiable work into an assertion the user has to check.

### XX. User Control Over Consequential Actions

Comodor MUST NOT merge a pull request, enable auto-merge, dispatch a release
workflow, create or move a release tag, publish a package, deploy, modify
production infrastructure, or take an equivalent consequential external
action without the user's explicit authorization for that specific action.
General approval of a task, a green check, a review approval or words such
as "done" or "continue" are never such authorization. Pending pull requests
MUST NOT be silently incorporated, rebased, closed, merged, or used as the
foundation for unrelated work.

Rationale: these are the actions that reach beyond the working tree and
cannot be undone by the next commit; the decision belongs to the person who
owns the consequences.

### XXI. Quality and Token Efficiency Are Measured Together

Quality optimization and token optimization MUST be treated as one
multi-objective engineering problem, never as independent goals. The project
MUST maintain evidence that a token reduction does not introduce lower task
success, more retries, more user corrections, more hallucinated assumptions,
more failed tool calls, more regressions, weaker tests, or the loss of
necessary context. Where practical, representative benchmark scenarios MUST
compare input tokens, output tokens, number of model turns, number of tool
calls, clarification count, task success, correction count and validation
success, before and after the change.

Rationale: without a paired measurement, every token saved looks like a win
and every quality loss it caused is invisible until a user reports it.

## Compatibility Surfaces and Quality Gates

The canonical surface list for specifications, plans and pull requests is
exactly, in this order: TUI; Web UI; CLI / Headless; API / Protocols;
Desktop; Channels / Integrations; Docker / Packaged Runtime; Persistence /
Shared State; Security / Authorization; Tests / Documentation. Each surface
is classified as exactly one of REQUIRED, UNCHANGED BUT VERIFIED or NOT
APPLICABLE, and an UNCHANGED BUT VERIFIED classification carries concrete,
checkable evidence (a path, a command, a test, an implementation
identifier).

The baseline gates every change MUST pass on the exact commit under review
are the repository's lint, type-check and code-generation checks, the full
Python test suite and its performance ceilings, the frontend lint,
type-check, tests and build, the renderer suite on the real renderer, the
release-infrastructure tests, and the cross-platform continuous-integration
matrix on the supported Python versions and all three platforms. Release
changes additionally MUST pass the release-build sequence (dependency
install leaving the tree clean, the all-platform artifact build, the
integrity guard, distribution build, wheel-contents guard, metadata check
and a clean installed-wheel smoke test) and a non-mutating rehearsal where
one exists.

A change that alters context construction, prompt construction, retrieval,
summarization, memory, learning, model orchestration or any other mechanism
that determines what is sent to a model carries one additional gate: the
paired quality-and-token evidence required by Principle XXI, measured on
representative scenarios and reported with both halves. Token figures
presented without the accompanying quality figures do not satisfy this gate.

## Development Workflow

Audit before edit: inspect the current source, tests, git state and recent
history; treat handoff notes and prior reports as hypotheses until the
repository confirms them; reproduce a defect before changing code; design
the smallest coherent change; implement; test; mutation-check where the
change guards an invariant; review the diff; commit. Existing local work is
preserved and classified, never reset or cleaned blindly.

Changes are made on a dedicated branch from the current main branch and
delivered through a pull request against main. The permanent branches are
never rewritten, force-pushed or deleted. Release tags are never moved,
deleted or recreated. Merging, enabling auto-merge and creating a release
tag are decisions reserved to the repository owner and are never inferred
from green checks, review approval or the words "done" or "continue".

Public commit and pull-request metadata uses neutral engineering language
and carries no tool or model attribution. Review findings are classified,
fixed where valid, answered with evidence, and resolved only after the fix
is pushed and the checks on the new commit support it. A live model is
invoked by tests only where a deterministic fake cannot exercise the
behaviour, and then only the model the repository designates for that
purpose; credentials are never exposed.

## Governance

This constitution supersedes all other practices in the repository. Every
specification, plan, task list, implementation and review MUST be checked
against it, and a pull request MUST state how any complexity it introduces
is justified under these principles.

Amendments are made by a pull request that changes this file, states the
motivation, and classifies the change under the versioning policy below;
an amendment that removes or redefines a principle MUST include a migration
plan for work in flight. The version line at the end of this file is
updated in the same change.

Versioning follows semantic versioning: a MAJOR increment for a backward-
incompatible removal or redefinition of a principle or governance rule; a
MINOR increment for a new principle or section or materially expanded
guidance; a PATCH increment for clarifications, wording and non-semantic
refinements.

Compliance is reviewed on every pull request by its author and its
reviewers against the surfaces and gates named above. Day-to-day execution
guidance for agents and contributors lives in `AGENTS.md` and `CLAUDE.md`,
which MUST remain consistent with this constitution; where they diverge,
this constitution governs and the guide is corrected.

**Version**: 1.1.0 | **Ratified**: 2026-09-14 | **Last Amended**: 2026-09-14
