# Comodor — Project Working Memory
Snapshot: 2026-10-07. Verify all PR heads, checks, reviews, and branch states before acting.

## Product and architecture

Repository: https://github.com/ifekri/Comodor
GitHub identity for repository writes: ifekri

Comodor is a multi-surface AI development agent: TUI, CLI/headless, Web,
API/protocol clients, desktop, and integrations.

One Python Core owns sessions, tools, modes, permissions, questions,
persistence, and decisions. Clients display and control that Core through
the versioned protocol; they do not invent authoritative state or duplicate
Core policy. The TUI and desktop reuse shared TypeScript packages, including
@comodor/client, @comodor/session, @comodor/questions, @comodor/modes,
@comodor/commands, @comodor/protocol, and @comodor/design-tokens.

The D1 desktop is a Tauri 2 application: Rust supervises one local Python
Core per window, and React/TypeScript renders its state. The connection uses
the Core's stdio pipes and the WebView's private in-process IPC, with no
network listener. Credentials must never reach WebView content. The existing
computer-control backend under src/comodor/desktop/ is a different component.

For `comodor core --stdio`, stdout contains protocol messages only;
diagnostics belong on stderr.

## Product direction

D1 is the desktop foundation: workspace choice, one conversation, Core
supervision, crash/reload recovery, orderly shutdown, credential isolation,
and the unconfigured-provider state.

D2–D6 are later desktop work: workbench shell, editor, integrated terminal,
agent/task/session surfaces, and packaging/release capabilities. Their exact
scope must be taken from their own future Spec Kit artifacts, not inferred
from this memory. D1 does not include an installer, native credential entry,
history browsing, a remote Core, or a bundled Core.

Advanced agent capabilities should be implemented in the Core and exposed
through the protocol so every surface can use them. Do not put intelligence
or security policy exclusively in one frontend.

## Current repository state — recheck before use

Feature 002 / PR #61 was merged. Its acceptance is deterministic. The
benchmark subsystem and its acceptance requirements were removed. Do not
reintroduce paired model evaluations, live-provider gates, or paid-token
requirements. Keep production token-usage accounting and truthful claims.
The constitution version 2.0.0 is independent of the product version.

Feature 003 / D1 is in PR #62 on branch `003-desktop-foundation`.
At this snapshot its head is 4d4c30f5df5f2d0ef1cebb68348969ae97d9e4fd.
The PR is open, unmerged, and has seven unresolved review threads. CI on
that head is green, but D1 is not acceptance-complete.

The active P1 finding is a wake race: `checking` and `ready` can arrive
before React renders, so the session refresh may be skipped. A persistent
native check epoch and a deterministic regression test are needed. Send
and Cancel must remain unavailable until the authoritative refresh ends.

SC-017 folder-chooser evidence matches the actual observed directory on
Windows and macOS in two fresh launches. Linux has only partial visual
evidence of the final folder name, not a direct observation of the complete
path; record it as partially verified until stronger evidence exists.

The original wake and `open_external` findings have implementation changes
but their threads remain open pending final evidence. Real hardware sleep
and the physical appearance of the native confirmation dialog were not
verified in CI. Describe those limits accurately; deterministic simulated
tests are evidence of the tested behavior, not proof of a physical test.

The next action is to finish PR #62, not to start D2. Recheck the current
head and thread state before continuing; this snapshot will become stale.

## Spec Kit and acceptance

The repository's constitution, current `specs/<feature>/` artifacts,
contracts, source code, and observed tests are authoritative. This memory
is a navigation aid. Follow `/speckit.clarify`, `/speckit.plan`,
`/speckit.tasks`, `/speckit.analyze`, and `/speckit.implement` as appropriate
to the feature. Preserve existing correct work; do not regenerate completed
phases without a demonstrated need.

Each active requirement needs honest evidence. A green CI run does not
override a failed requirement, an unresolved valid Codex finding, or a
partially verified acceptance criterion. Never label untested behavior PASS.

Acceptance tests are deterministic, use scripted responses or the fake
provider, and require no live provider, credential, or paid tokens. Race
tests synchronize on observable events rather than arbitrary sleeps.
For critical fixes, first show a regression test failing on the prior
behavior, then passing with the fix; use a mutation check where meaningful.

## Pull request workflow

Use feature branches and PRs. Never force-push main or overwrite the
owner's unrelated checkout, edits, or stashes. Check the authenticated
GitHub identity before a write; it must be `ifekri`.

For every final PR head:
1. Run the relevant local gates on that exact commit.
2. Update the PR description, including its Surface Impact table.
3. Require successful GitHub checks on Windows, Linux, and macOS where
   the feature requires them.
4. Obtain a fresh Codex review of that exact head.
5. Fix every valid actionable finding, add evidence, push to the same PR,
   and repeat validation, CI, and review on the new head.
6. Reply to and resolve a review thread only after its finding is actually
   addressed with evidence. Report unresolved threads honestly.

The Surface Impact table has exactly these ten rows, in this order:
TUI; Web UI; CLI / Headless; API / Protocols; Desktop;
Channels / Integrations; Docker / Packaged Runtime;
Persistence / Shared State; Security / Authorization;
Tests / Documentation.
Use only REQUIRED, UNCHANGED BUT VERIFIED, or NOT APPLICABLE.

Do not approve, enable auto-merge, merge, push directly to main, or delete
the feature branch on the owner's behalf without explicit authorization
for that exact PR. Green checks and “ready for review” are not merge
authorization.

Keep public commit and PR wording neutral; do not add AI co-author trailers
or advertise assistance in public repository metadata. Codex review is
required by the owner, but it does not need to be named in commit messages.

## Permanent security rules

ASK has no general tools. PLAN is read-only. ACT follows Core permissions.
Unknown modes fail closed, including direct tool calls. A frontend cannot
bypass Core policy. Untrusted text is inert. Secrets do not cross the
protocol or enter snapshots or WebView content. External links open only
after the person's trustworthy authorization for the specific URL.
