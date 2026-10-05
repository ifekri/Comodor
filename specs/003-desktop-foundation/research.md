# Research: Desktop Foundation (D1)

Phase 0 of [plan.md](./plan.md). Every finding below was read from the
repository at `190763b` or follows from the agreed architecture
(`docs/desktop-architecture.md`, `docs/app-architecture.md`,
`docs/protocol.md`). Where a finding is a property of an external tool
(Tauri 2, a WebView, an operating system), it is marked **external** and is
verified by the implementation's tests rather than assumed.

---

## R1. Starting the Core

**Decision**: The native side starts the Core itself as a child process:
`<core executable> [<leading args>] core --stdio`, working directory = the
workspace, standard streams all piped, no shell, no console window on
Windows. The executable is found in this order, and every location tried is
reported when none works (FR-002):

1. `COMODOR_BIN`, with `COMODOR_ARGS` as whitespace-separated leading
   arguments — the variables the terminal interface already honours for the
   same purpose (`apps/tui/src/main.tsx`, set by
   `src/comodor/transport/commands.py::run_tui`);
2. `comodor` on `PATH`.

The environment is inherited unchanged (FR-003); the arguments are exactly
the list above and never carry a credential.

**Rationale**: `comodor core --stdio` is the one supported way to run a Core
for a client (`serve_stdio`). Reusing the terminal interface's discovery
variables means one convention for "which Comodor runs my Core", and lets
tests point the application at a scripted Core without a product setting.

**Alternatives considered**:
- *The shell plugin's sidecar/`Command` API*: rejected — it is designed to be
  callable from the window's content with scoped permissions, which is exactly
  the capability the window must not have (FR-030).
- *Bundling Python and the Core*: D6 (spec §Assumptions).
- *A settings screen to pick the executable*: not needed for D1; the two
  variables cover development and tests, and the failure message names them.

---

## R2. The private connection

**Decision**: Two links, neither of them a network listener (FR-010):

- **Native side ↔ Core**: the Core's own anonymous stdin/stdout pipes. Only
  the parent holds them.
- **Window content ↔ native side**: the WebView's in-process IPC (an app
  command for outbound lines, one IPC channel for inbound lines and status).

**Rationale**: `docs/desktop-architecture.md` rules out loopback TCP for local
connections because every local process and any web page can reach a port.
Anonymous pipes carry the operating system's own isolation, and the WebView
IPC never leaves the process. No secret is needed because nothing is
listening.

**Alternatives considered**:
- *Named pipe / Unix socket*: reserved for letting a terminal attach to the
  desktop's Core, which is out of D1's scope. D1 has one client per Core, so a
  rendezvous point would only add something to secure.
- *A loopback WebSocket from the window to the Core*: rejected by the
  architecture, and it would put the Core's full protocol one fetch away from
  any page.

**Note (external)**: in development mode the frontend's assets are served by
a local development server. That serves static assets only, never the Core's
protocol; test and release builds embed the assets and start no server. The
CI desktop job uses the embedded-asset build.

---

## R3. The native bridge: a relay that owns the handshake

Three facts from the code fix the design:

- The Core refuses a second `client.hello` on a connection
  (`already_initialized`, `src/comodor/transport/server.py`).
- `CoreClient` numbers its requests from `"1"` again in every new instance
  (`packages/client/src/index.ts`), so after a page reload the new page's `"7"`
  can meet the old page's late answer to `"7"`.
- A `shutdown` answer makes the Core close its channel and exit.

**Decision**: The native side performs the handshake itself when the Core
starts, and caches the answer. The window's content runs the unchanged
`CoreClient` over a bridge `Transport`; the relay then:

1. answers the page's `client.hello` locally from the cached handshake,
   with the page's own request id;
2. forwards every other request in the method allowlist (every protocol v2
   method except `client.hello` and `shutdown`) after prefixing its `id` with
   the page's **generation** — a counter the native side increments on every
   page load (`"g3:7"`);
3. maps each response or error back to the page's own id, and drops it if its
   generation is not the current one;
4. forwards every event to the current page only;
5. refuses `shutdown` from the page (Core lifetime is the native side's,
   FR-001), refuses a line that is not a JSON request envelope, and never
   changes anything but the `id`. It reads, without changing them, only the
   fields the restart counter needs (R5).

**Rationale**: It keeps the protocol, the Core and `@comodor/client`
unchanged (FR-008, FR-025, FR-026). It makes reload safe by construction —
a stale answer cannot reach a new page — rather than by timing. It makes
"ready" a native fact, so startup failure and restart are supervised without
any page. The method allowlist is lifecycle ownership, not policy: whether a
method is *allowed* for a session remains the Core's decision.

**Alternatives considered**:
- *Let the page do the handshake and restart the Core on reload*: violates
  FR-011 (reconnect to the same Core).
- *Add a "pre-initialized" mode to `CoreClient`*: a shared-package change
  that the relay makes unnecessary.
- *Parse and validate full envelopes natively*: the relay needs only `type`,
  `id` and `method`; full validation belongs to the protocol packages on both
  ends.

---

## R4. Core lifecycle states and supervision

**Decision**: One state machine per Core, owned by the native side:
`absent → starting → handshaking → ready → (stopping → stopped) | failed`,
with `restarting` between a crash and the next `starting`. Detail in
[data-model.md](./data-model.md) §1. Failures are classified at the moment
they happen: `not_found`, `spawn_failed`, `workspace_unavailable`,
`exited_before_ready`, `protocol_mismatch`, `protocol_fault`, `crashed`.

**Rationale**: Each class has its own message (SC-002) and its own next step:
only a Core that had reached `ready` is restarted automatically (a startup
failure repeats identically and is shown with "Try again"; US1 scenario 4).
All transitions are driven by observable events — process exit, a line read,
the handshake answer — never by elapsed time, except the one explicit bound,
the 10-second shutdown grace, which takes an injected clock in tests (FR-035,
Constitution III). The restart policy counts events and has no clock.

---

## R5. Restart policy — owner decision OD-1 (2026-09-30)

**Decision**: Restart automatically only after a crash of a Core that had
reached `ready`. After the **third consecutive** such crash without a
completed turn in between, do not restart; wait for the person's explicit
"Try again". There is no time window, and interrupted work is never replayed
(spec FR-005, FR-016).

**Completed turn — conservative, from existing events** (verified in
`src/comodor/application/__init__.py`):

- The `session.send` response, with its `turn_id`, is written before any of
  that turn's events (`Server._handle` defers the events, and the worker
  waits on `release`).
- Each `message.*` event carries the turn's `turn_id`.
- The worker's `finally` persists the turn and only then emits
  `session.updated` with `busy: false`, so that event is the turn's last.
- Cancellation (`Kind.CANCELLED`) closes an open message as `cancelled`, if
  one is open, and **always** emits `notification.created` at `warning` — the
  only signal when cancellation lands between messages.
- A failure (`Kind.ERROR`) closes an open message as `failed` and emits an
  `error` notification. A worker exception emits an `error` notification.
- A turn that stops for a decision emits `clarification.required` only to a
  client that negotiated it. The desktop does not, so its last
  `message.completed` stands as `completed`. The `warning` notification
  ("Stopped: a decision is needed…") is still sent.

So the turn is completed only when all of these hold:
- the relay saw its `session.send` result;
- `busy: false` follows;
- at least one `message.completed` for that `turn_id` arrived, all of them
  `completed`;
- no `warning` or `error` notification arrived;
- no `session.cancel` was relayed.

Everything else is uncertain and leaves the count unchanged. The rule can
miss a reset, which only makes the policy stricter; it can never reset on a
turn that did not complete. No protocol or Core change is needed.

**Rationale**: It is the owner's decision. Analysis supports it: the
time-window form ("3 per 60 s") never stops a Core that crashes every 25 s,
while a count of consecutive failures does, and needs no clock. A Core that
cannot reach `ready` is never restarted automatically; its failure repeats
identically and is shown with "Try again".

**Alternatives considered**: a time window (3 within 60 s) — rejected by the
owner and by the slow-loop analysis; no automatic restart — contradicts
FR-005.

**Verification**: counted from events, so the tests need no clock:
- crashes 1 and 2 restart; crash 3 does not;
- a completed turn between crashes resets the count;
- none of these reset it:
  - cancel between messages and cancel mid-message;
  - failure between messages and mid-message;
  - a clarification stop;
  - a warning or error notification;
  - a turn the Core started itself;
- "Try again" after the limit does not reset it;
- a crash before `ready` is never restarted automatically.

A **sequenced Core double** (one behaviour per launch, from a state file)
produces crash → completed turn → crash sequences across restarts.

---

## R6. Shutdown bound — owner decision OD-2 (2026-09-30)

What the Core does on shutdown (`src/comodor/application/__init__.py`,
`CoreService.close`): it marks sessions closing, stops background delegates,
interrupts a running turn, refuses pending prompts, **joins each busy
session's worker for up to 5.0 s**, then closes the assembly — which flushes
the learning store and releases MCP and provider resources. The server
answers `shutdown` *before* running `close()`.

**Decision**: After the stop request, wait up to **10 seconds** for the Core
**process to exit**, not merely for the `shutdown` answer. While waiting, the
window shows "Closing…" and offers "Quit now". At the deadline, or on "Quit
now", terminate the owned Core and the processes it started, record that it
was stopped before it finished, and present anything the Core had not
persisted as interrupted, never as saved. The same bound applies when a
workspace change or "Check again" stops a Core.

**Rationale**: It is the owner's decision. The code supports it: a grace of
5 s, the earlier model default, equals the Core's own worker join and leaves
nothing for the assembly close, so a quit during a turn could lose what the
turn learned. Ten seconds covers the join and the close in ordinary cases,
and "Quit now" keeps the person in control.

**Honesty rule**: the application cannot know what a terminated Core did not
persist. What it does know is that the Core did not finish its own shutdown.
So it reports exactly that — "Comodor was stopped before it finished; work it
had not saved may be lost" — in the window when the window is still open
(workspace change, "Check again") and always in its own log. It never
displays a "saved" message after a forced stop.

**Verification**:
- an injected clock;
- a Core double that ignores the stop request, proving the forced stop at
  exactly the deadline and the report;
- "Quit now" before the deadline, proving an immediate forced stop;
- the real scripted Core, proving an orderly exit within the bound with no
  termination;
- a string check that no forced-stop path produces a "saved" claim.

**Recorded for later triage, outside D1**: the terminal interface's
`spawnCore` kills the Core 2 s after closing its input
(`packages/client/src/spawn.ts`), inside the Core's own 5 s join, which can
cut the same flush short. D1 does not change it (Constitution V); it needs its
own change and review.

---

## R7. Workspace at launch — owner decision OD-3 (2026-09-30)

**Decision**:
- **Fresh launch**: the person explicitly chooses the workspace, in the
  operating system's folder chooser, opened at the **last selected folder**.
  If that folder no longer exists, the chooser opens at the system's default.
- **Explicit path**: a valid workspace path given on the command line takes
  precedence and is used without the chooser. An invalid one is reported, and
  the chooser opens.
- **Same launch**: a reload of the window's content or a Core restart —
  automatic, "Try again" or "Check again" — keeps the chosen workspace and
  never asks again.
- **Dismissed chooser**: no Core starts; the window offers "Choose
  workspace…".
- **Single instance**: a second launch with an explicit path different from
  the current workspace asks the person before switching; it never switches
  silently.

**Rationale**: It is the owner's decision. It matches the repository guide's
rule that the person must know which workspace Comodor operates on and that
it is never changed silently: an Act-mode agent can only work in a folder the
person chose, or named, in this launch.

**Persistence**: the last selected folder is a non-secret preference
(FR-032). It only decides where the chooser opens; it never starts a Core by
itself.

**Verification**:
- a fresh launch opens the chooser at the stored folder and starts no Core
  until one is chosen;
- a valid explicit path skips the chooser; an invalid one reports and opens
  the chooser;
- a dismissed chooser starts nothing;
- reload and every kind of restart keep the workspace with no chooser.

---

## R8. Leaving nothing behind

**Decision (per platform; external facts verified by SC-007's tests)**:

| Platform | Normal stop | Application killed abruptly |
| --- | --- | --- |
| Windows | stop request, then end the job | the Core runs in a **job object** set to kill on close; the job dies with the application's handle, taking the Core and its descendants. The Core starts suspended and runs only once it is in the job, so nothing it starts escapes it (review finding on PR #62) |
| Linux | stop request, then signal the Core's process group | the Core is started with a **parent-death signal**, from a dedicated long-lived supervisor thread (the signal follows the spawning thread); a **watchdog** (below) ends the Core's whole process group; stdin also reaches EOF and the Core exits (`serve_stdio`) |
| macOS | stop request, then signal the Core's process group | a **watchdog** (below) ends the Core's whole process group; stdin reaches EOF and the Core exits through its own `close()` |

The watchdog (added for a review finding on PR #62) is the application's own
executable, started with each Core in a process group of its own. It waits for
the application or the Core to exit (`pidfd` on Linux, `kqueue` on macOS),
then signals the Core's group. It reports once it is watching (one byte on
its stdout), and a watchdog that exits before that counts as not started. A
Core whose watchdog cannot start is ended at once and reported as a failed
start, on both platforms: on macOS nothing else ends a Core that ignores EOF,
and on Linux the parent-death signal reaches the Core alone, not what it
started. (`pidfd_open` is in every kernel Tauri's WebKitGTK runs on, so this
fails only when resources are exhausted.)

**Rationale**: The Core already exits on EOF. The OS mechanisms and the
watchdog add a guarantee that does not depend on the Core noticing. **Risk**:
on Linux and macOS, a process the Core started that leaves the Core's process
group (its own session or group) is outside what the group signal reaches;
see plan §Risks.

---

## R9. The window's content: security

**Decision**:

- **Commands**: the application defines its own commands (contract:
  [native-bridge.md](./contracts/native-bridge.md)) and grants the window no
  plugin permission at all. The folder chooser, single-instance handling and
  external-link opening run on the native side.
- **Content Security Policy**: scripts and styles from the application
  bundle only, no remote origin, no inline script, no `eval`, and IPC as the
  only connection. Navigation away from the application's own origin and new
  windows are refused. Developer tools are off in release builds.
- **Inert display**: all text from outside the application is rendered as
  text nodes. No raw-HTML rendering exists in D1. Control characters,
  including the escape character, are shown as visible symbols. The
  connection and status indicators are driven only by native status and Core
  events, never by content.
- **External links**: opened only by the native side, only `http`/`https`,
  only after the person activates them.

**Rationale**: FR-028–FR-030. The window renders untrusted model output. A
compromised page could otherwise approve a permission (a `permission.reply`
it forges); keeping script execution impossible is what makes the person's
click the only source of an answer.

---

## R10. Credential isolation

**Decision**: No path carries a credential to the window. The protocol never
sends one (`docs/protocol.md` §What never crosses). The native side never
reads Comodor's configuration and passes the environment through unchanged.
The Core's diagnostic output is shown only as a bounded tail. The
preferences file holds only the fields in [data-model.md](./data-model.md) §5.

**Verification**: a canary credential configured for the offline provider;
every channel the window can reach is searched for it (SC-009); see
[quickstart.md](./quickstart.md) §5.

**Risk**: the diagnostic tail is the Core's own log output. The Core's
invariant is that secrets never enter logs (Constitution VIII). D1 relies on
it and the canary test checks it for D1's flows; D1 does not add redaction
the native side cannot do correctly without knowing the secrets.

---

## R11. No configured provider

**Decision**: When `model.get` reports `configured: false`, the window shows
the state and the direction to run `comodor setup` in a terminal, and the
send action is unavailable. **"Check again" restarts the Core** (orderly stop,
start, handshake, `model.get`).

**Rationale**: The owner decision (spec §Clarifications). Code finding: a
running Core holds the configuration it loaded at start, and each session
deep-copies it (`CoreService.__init__`, `docs/app-architecture.md`), so a
`model.get` on the old Core cannot see what `comodor setup` wrote. A restart
does, with no Core change. The application itself is not restarted (FR-031).

---

## R12. Recovery after a Core crash

**Decision**: The page remembers the conversation's **stored id**. For a
session it created, that is the session id: `CoreService.create_session`
sets `store_id = session_id`. For a session it opened, it is the id it opened.
After a restart the page calls `session.open(stored_id)`. If the Core refuses
because nothing was persisted yet (the crash came before the first turn
boundary), the page creates a new session and says the earlier one had nothing
saved. A turn the page had sent and not seen complete is shown as interrupted
and not saved; nothing is re-sent (FR-016). Background delegates are reported
in the states the restarted Core's snapshot gives (`lost`), as one summary
line; D1 has no delegate panel (D5). The stored id belongs to the workspace it
was made in: after a change of workspace nothing is reopened, and a new
conversation starts (review finding on PR #62).

**Rationale**: Sessions persist at turn boundaries and `session.open`
restores transcript, plan and title (`docs/app-architecture.md`). The
interrupted turn is a fact the page itself observed (it holds the `turn_id`
the Core accepted and no completion), not an invented state.

---

## R13. Reload recovery

**Decision**: On a new page load: ask the native side for status; start the
unchanged `CoreClient` over the bridge (local hello); subscribe to events; call
`session.list` (D1 holds one session per Core) and `session.snapshot`; feed
both into the `@comodor/session` reducer, which already drops a stale snapshot
and applies only events above its revision (FR-011, FR-012).

What the page keeps for recovery (R12: the stored id, the live session it
last held, the interrupted turn, and their workspace) is mirrored into the
window's session storage, which a reload keeps and a new launch does not. A
reload therefore finds its live session in `session.list` and still knows
the stored id a later restart must open; a reopened session's live id is
never mistaken for it (review finding on PR #62).

**Rationale**: Exactly the protocol's documented rejoin path
(`docs/protocol.md` §Sequence numbers). The relay's generations make stale
answers harmless.

---

## R14. Verification strategy

**Decision**: Four layers, all offline and deterministic (FR-034, FR-035):

1. **Native unit tests** — state machine, restart policy, shutdown sequence
   with an injected clock, relay id mapping, method allowlist, discovery order,
   preferences schema. Pure, on all three platforms.
2. **Native integration tests** — the real supervisor and relay against a
   **real Core process**:
   - the offline `fake` provider in an isolated `COMODOR_HOME`, the way
     `apps/tui/test/bun/orphan.test.ts` does it;
   - a **scripted Core fixture**: a test-only Python entry that builds
     `CoreService(config, assemble_with=...)` with scripted provider responses,
     as `tests/test_protocol_permissions.py` does, and serves it on real stdio.
     This produces question forms and permission requests from a separate
     process with no product change.

   Crash, protocol-fault, version-mismatch and non-cooperating Cores are small
   doubles. All three platforms.
3. **Window logic tests** — the React view against `CoreClient` over an
   in-memory `Transport`, the pattern of `apps/tui/test/bun/renderer.test.tsx`,
   in a DOM test environment. Includes the adversarial display cases
   (SC-010). Platform-independent; run on all three.
4. **In-application scenarios** — a **test build** (a compile-time feature,
   never in a release build) loads a scenario runner inside the real WebView.
   It drives the real UI through DOM events against the real bridge and the
   scripted Core, waits on DOM and status changes (observers, not sleeps),
   reads the WebView's own storage for the canary, reports through one
   test-only command and exits. It works where WebDriver does not: macOS has
   no WebView driver (**external**). Run on all three platforms, with a
   virtual display on Linux.

**Abrupt-kill tests** (SC-007) are driven from outside: the harness starts the
application, learns the Core's pid from the test build, kills the
application, and waits for the Core's exit. The wait has a failure deadline
but no fixed delay.

**Mid-turn races** use a **hold-mid-turn** fixture scenario. It opens a
message, emits at least one delta, then blocks until the harness releases an
explicit hold over a dedicated control channel. Every kill, reload, cancel or
quit "during a turn" happens while the hold is in place, so the turn cannot
finish first. The volume scenario (`stream-long`) is never used for timing.

**Startup failures** include `spawn_failed`: `COMODOR_BIN` pointing at an
existing file that cannot be executed.

**Network listeners** (FR-010): the test build reports the TCP listening
sockets and bound UDP sockets owned by the application's own process:
- Windows: the IP helper tables filtered by pid;
- Linux: `/proc/net/{tcp,tcp6,udp,udp6}` matched to the socket inodes in
  `/proc/self/fd`;
- macOS: the system `lsof` for the process's own internet sockets
  (`lsof -nP -a -p <pid> -i`), keeping `LISTEN` and UDP entries. (Chosen in
  T015 over hand-written `proc_pidinfo` bindings, which this repository could
  not build and check without a macOS machine.)

The expected set is empty. The single-instance plugin's own channel is not a
network listener: a named mutex and window message on Windows, D-Bus on
Linux, a local mechanism on macOS. This is **external**: the per-platform
mechanism is checked against the plugin version pinned in T003. The Linux CI
job runs inside a D-Bus session.

**Release command proof** (FR-030, SC-011): one command-name constant feeds the
handler registration and the build manifest. CI builds the release
configuration and inspects its generated permission and ACL manifest. The
`e2e` build is asserted to differ only by `e2e_report`.

**The folder chooser** (SC-017): the automated tests assert the exact start
directory the application hands to its chooser adapter, a thin wrapper over
the dialog plugin. Whether the operating system's real dialog honours it is
**external**. It is recorded per platform (screenshot or screen recording,
with the folder shown) in the PR description. Missing evidence on any
platform leaves D1 incomplete (FR-033).

**Where evidence lives**: CI runs during development use `workflow_dispatch`
on the pushed branch. All evidence for the exact final SHA — per-platform
results, timings, the canary, the real-chooser recordings — goes in the PR
description and the owner report, never in a repository commit after the
final validation round.

**Alternatives considered**: WebDriver-based end-to-end testing — no macOS
support, so it cannot give three-platform evidence.

---

## R15. Where the code lives, and what it depends on

**Decision**: `apps/desktop/` — the React/TypeScript window content, and
`apps/desktop/src-tauri/` — the native side. Its package name makes clear it
is the desktop *application*, never the computer-control backend in
`src/comodor/desktop/`, which it does not import (FR-027).

New dependencies, all confined to `apps/desktop`:

- **Frontend**: React, React DOM, the Tauri JS API, a bundler and its React
  plugin, the Tauri CLI, and a DOM test environment (development only).
- **Native**: Tauri 2, the single-instance and dialog plugins used from Rust
  only, JSON serialisation, and platform crates for job objects and the
  parent-death signal.

**Pinned exact versions** with a committed lockfile. The Python package and
its single runtime dependency are untouched.

**Rationale**: `apps/*` is already an npm workspace root, and
`tools/lint-frontend.mjs` already lints `apps/` — including the rule that
forbids colour literals outside `@comodor/design-tokens`. The new app is added
to the root TypeScript project references like `apps/tui`.
