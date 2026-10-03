# Feature Specification: Desktop Foundation (D1)

**Feature Branch**: `003-desktop-foundation`

**Created**: 2026-09-30

**Status**: Draft

**Input**: User description: "Define the next Comodor product milestone: D1, the
cross-platform Tauri 2 desktop foundation. Specify a minimal usable desktop
foundation that starts and supervises the existing authoritative Python Core,
connects through the versioned protocol using secure local transport, reuses
shared frontend semantics, handles startup, shutdown, failure and reconnection,
works on Windows, Linux and macOS, and never exposes credentials to the
WebView. Distinguish this new desktop application from the existing
computer-control code in src/comodor/desktop. Define independently testable
requirements and success criteria, compatibility and security boundaries, and
deterministic acceptance without provider calls or paid tokens. Keep the full
workbench, Monaco, integrated terminal, agent/task panels, release and
deployment in their later D2–D6 phases. Do not rewrite the Python Core or
duplicate its policies in the frontend."

## Context

This specification was written against `origin/main` at `190763b` (Feature 002
merged as PR #61), constitution 2.0.0. The facts below were read from the
repository, not assumed.

- **The agreed shape.** `docs/desktop-architecture.md` and
  `docs/app-architecture.md` fix the architecture this milestone builds: one
  authoritative Python Core, a versioned protocol (`schemas/protocol/v2.json`),
  shared client packages, and frontends that present rather than decide. The
  desktop application is the second client of that protocol after the terminal
  interface. The agreed stack is Tauri 2 with React and TypeScript; the
  milestone sequence is D1 (this foundation), D2 workbench shell, D3 editor and
  workspace, D4 integrated terminal, D5 agent, task and session panels, D6
  production hardening.
- **The Core already serves a client.** `comodor core --stdio` speaks protocol
  v2 as newline-delimited JSON on its standard streams, keeps stdout for
  protocol only, and exits when its input closes
  (`src/comodor/transport/__init__.py::serve_stdio`). The handshake
  (`client.hello`) refuses a version it does not speak and names the versions it
  does. `session.snapshot` with per-event sequence numbers lets a client rebuild
  a session exactly after a gap. A request nobody answers is resolved by the
  Core with its safe fallback.
- **The shared client semantics already exist.** Seven packages under
  `packages/` hold what every client shares: the protocol types and envelopes,
  the connection client (handshake, correlation, events, closing), the session
  projection and snapshot reconciliation, commands, modes, question-form
  selection and design tokens. The connection client accepts any transport with
  a line stream; only its optional process-spawning helper is specific to a
  runtime that can start processes.
- **"Desktop" already names something else.** `src/comodor/desktop/` is the
  computer-control backend: screen capture, pointer and keyboard input and a
  safety overlay that the agent's computer-use tool drives. It is part of the
  Core, governed by modes and permissions, and it is unrelated to this
  milestone. In this document **desktop application** means the new windowed
  client; **computer-control backend** means `src/comodor/desktop/`. The
  canonical Desktop surface row covers both, and this milestone changes only
  the first.
- **Transport security is already decided.** The architecture rules out an
  unauthenticated TCP port on loopback for local connections, because any local
  process and any web page can reach one. The protocol never carries a provider
  key, a GitHub installation token, an OAuth secret, signing material or the
  environment; `model.get` answers only whether a provider is configured.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Open Comodor as a desktop window, ready to work (Priority: P1)

A developer who already has Comodor installed launches the desktop application.
It starts a Comodor Core of its own for the chosen workspace, confirms the Core
speaks the protocol version it expects, and shows a window that says which
workspace, which provider and which model the Core is using, and that it is
ready. If the Core cannot be found, will not start, or speaks a different
protocol version, the window says exactly that and what to do, instead of
showing an empty or broken screen.

**Why this priority**: Nothing else in D1–D6 is possible without a desktop
client that can own a Core's lifecycle and complete the handshake. It is the
smallest slice that proves the architecture: a second client, on the unchanged
protocol and shared packages, with the Core still the only authority.

**Independent Test**: Launch the application against an installed Core
configured with the offline scripted provider and verify the ready state shows
the workspace, provider, model and configured status the Core reports. Repeat
with the Core missing, with a Core that exits immediately, and with a Core
answering a different protocol version, and verify each shows its own named
failure and never the ready state.

**Acceptance Scenarios**:

1. **Given** Comodor is installed and a workspace is chosen, **When** the
   person launches the desktop application, **Then** a Core is started for that
   workspace, the handshake succeeds, and the window shows the workspace,
   provider, model and whether the provider is configured, as the Core reports
   them.
2. **Given** no Comodor installation can be found, **When** the application
   starts, **Then** it shows that the Core was not found, where it looked, and
   how to install or point to one; it does not show a ready state.
3. **Given** the Core answers the handshake with a protocol version the
   application does not speak, **When** the handshake completes, **Then** the
   application refuses to continue, names both versions, and opens no session.
4. **Given** the Core process exits before the handshake completes, **When**
   startup fails, **Then** the application shows a startup failure with the
   Core's own diagnostic summary, and offers to try again.

---

### User Story 2 — Hold one conversation with the agent (Priority: P1)

From the ready window, the person works with the agent in one session: they
send a prompt, watch the reply and the agent's tool activity stream in, cancel
a turn, change mode, and answer the question forms and permission requests the
agent raises. Browsing and reopening earlier conversations is not part of D1
(D5).

**Why this priority**: A foundation that cannot run a turn is not "minimal
usable", and the failure and recovery behaviour of Story 3 is only observable
while a session holds real state.

**Independent Test**: With the offline scripted provider, send a prompt and
verify the reply streams into the window in order, that a scripted question
form and a scripted permission request can be answered from the window and the
Core receives exactly the answer given, and that the mode shown changes only
after the Core confirms it.

**Acceptance Scenarios**:

1. **Given** a ready window, **When** the person sends a prompt, **Then** the
   reply appears as it streams, in the order the Core sent it, and the turn's
   end is shown when the Core reports it.
2. **Given** a turn in progress, **When** the Core asks a question form or a
   permission, **Then** the window presents it with every option the Core
   supplied, including the write-your-own row, and sends the person's answer
   only when they give one; an unanswered request is resolved by the Core, not
   by the window.
3. **Given** a turn in progress, **When** the person cancels, **Then** the
   application asks the Core to cancel and shows the outcome the Core reports.
4. **Given** the person chooses another mode, **When** the Core confirms the
   change, **Then** the window shows the new mode; if the Core refuses, the
   window keeps showing the mode the Core holds.

---

### User Story 3 — Survive a Core failure or a window reload (Priority: P2)

While the person works, the Core may crash or be killed, and the window's own
content may be reloaded. The application notices, says so, restarts the Core
or reconnects, and brings the person back to the same conversation as the Core
last recorded it — without inventing progress, repeating a turn, or losing
what the Core had persisted.

**Why this priority**: Supervision is the reason the desktop application owns
the Core's process at all. Without honest recovery, every Core fault becomes a
lost session and a restart by hand.

**Independent Test**: With the offline scripted provider, kill the Core
between turns and during a turn, and reload the window's content during a
turn; verify each case against the expected recovered state and against the
bounded restart policy.

**Acceptance Scenarios**:

1. **Given** a session with completed turns, **When** the Core process
   terminates unexpectedly, **Then** the window shows that the Core stopped,
   starts a new Core for the same workspace, and reopens the stored
   conversation with the transcript the Core had persisted.
2. **Given** a turn in progress, **When** the Core terminates unexpectedly,
   **Then** the interrupted turn is shown as interrupted, background work that
   was running is shown in the state the restarted Core reports (for example
   `lost`), and nothing is re-sent automatically.
3. **Given** a running Core, **When** the window's content reloads, **Then**
   the application reconnects to the same Core without restarting it, rebuilds
   the session from a snapshot, and continues with the live events after that
   snapshot, with no duplicated and no missing messages.
4. **Given** a Core that reached ready has crashed twice since the last
   completed turn and been restarted each time, **When** it crashes a third
   time without a completed turn in between, **Then** the application does
   not restart it, shows the failure and its diagnostics, and waits for the
   person to choose "Try again"; no interrupted work is replayed.
5. **Given** a restarted Core, **When** a turn completes on it, **Then** the
   crash count starts again from zero.

---

### User Story 4 — Close cleanly, leave nothing behind (Priority: P2)

When the person closes the window or quits the application, the Core is asked
to shut down and given ten seconds to finish, while the window shows
"Closing…" and offers "Quit now". If the Core has not exited by then, or the
person chooses "Quit now", the application terminates the Core it owns and
says honestly what was interrupted — it never claims that unsaved work was
saved. No
Core process outlives the application on any platform, including when the
application itself is killed. Launching the application a second time brings
the running window to the front rather than starting a second Core for it.

**Why this priority**: An orphaned Core keeps a session store, a workspace and
possibly a running tool alive with nobody watching — a resource leak on a good
day and an unsupervised agent on a bad one.

**Independent Test**: On each platform, close the window normally, quit during
a turn, and kill the application process; after each, verify no Core process
started by the application remains. Launch twice and verify one window and one
Core.

**Acceptance Scenarios**:

1. **Given** an idle session, **When** the person closes the window, **Then**
   the Core receives an orderly shutdown request and exits, and the application
   exits after it.
2. **Given** a turn in progress, **When** the person quits, **Then** the turn
   is cancelled through the Core, the window shows "Closing…" with "Quit now",
   and the stored conversation is left as the Core last persisted it.
3. **Given** the window shows "Closing…", **When** the Core exits within ten
   seconds, **Then** the application exits without terminating it.
4. **Given** the window shows "Closing…", **When** ten seconds pass without the
   Core exiting, or the person chooses "Quit now", **Then** the application
   terminates the Core it started and the processes that Core started, records
   that the Core was stopped before it finished, and presents any work the Core
   had not persisted as interrupted, never as saved.
5. **Given** the application process is killed abruptly, **When** it is gone,
   **Then** its Core notices its client has gone and exits; no Core process
   started by the application remains.
6. **Given** the application is running, **When** it is launched again,
   **Then** the existing window is brought to the front and no second Core is
   started.

---

### User Story 5 — Credentials never reach the window's content (Priority: P1)

Provider keys, GitHub installation tokens, OAuth secrets and signing material
stay with the Core and the operating system. The window's content — the part
that renders model output and could be compromised by it — never receives,
stores or logs any of them, and cannot ask the native side for them.

**Why this priority**: The window renders untrusted text from models, tools
and repositories. A credential that reaches that context can leave the machine.
This is the security rule the desktop architecture was written around, and it
must hold from the first release of the client.

**Independent Test**: Configure a recognisable canary credential for the
offline scripted provider, run the ready, conversation, failure and recovery
flows, then search everything the window's content can reach — its storage, the
messages it received, the native operations it may call, its logs and the
application's logs — and verify the canary appears nowhere.

**Acceptance Scenarios**:

1. **Given** a configured provider credential, **When** the window shows the
   provider state, **Then** it shows only whether the provider is configured.
2. **Given** a model reply containing markup, scripts, terminal control
   sequences or text that imitates the interface, **When** it is shown, **Then**
   it is displayed as inert text and cannot run code, navigate the window or
   forge interface state.
3. **Given** the window's content, **When** it requests any native operation
   outside the small set this application declares, **Then** the request is
   refused.

---

### User Story 6 — Start with a provider that is not configured (Priority: P3)

A person launches the desktop application on a machine where Comodor has no
configured provider. The window says so, as the Core reports it, and tells the
person how to become ready: run `comodor setup` in a terminal, then ask the
window to check again. D1 has no credential entry of its own.

**Why this priority**: First-run matters, but D1's scope is the client
foundation; the setup experience already exists in the terminal, and the
credential boundary of Story 5 limits what the window may do here.

**Independent Test**: Launch against a Core with no configured provider and
verify the window shows the unconfigured state and the defined path to
readiness, and that no credential passes through the window's content at any
point.

**Acceptance Scenarios**:

1. **Given** the Core reports the provider as not configured, **When** the
   window becomes ready, **Then** it shows that state and the defined path to
   readiness, and a prompt cannot be sent until the Core reports the provider
   as configured.
2. **Given** the person completes provider setup by the defined path, **When**
   the application checks again, **Then** the window shows the configured state
   without the application being reinstalled.

---

### Edge Cases

- **Workspace unavailable.** The chosen workspace was deleted, is on an
  unmounted drive, or is not readable: startup reports that before starting a
  Core, and offers to choose another.
- **Core writes to stdout outside the protocol.** A line that is not a protocol
  message is a protocol fault: the application reports it, keeps the Core's
  diagnostics, and restarts under the restart policy; it never shows the line
  as content.
- **Core diagnostics are large or continuous.** The application keeps a
  bounded tail of the Core's diagnostic output for display and support, and
  never blocks the Core by not reading it.
- **Event gap after reload or sleep.** A sequence gap is repaired from a
  snapshot, never by continuing with a hole; a duplicate event is ignored.
- **Machine sleep and wake.** On wake the application confirms the Core is
  alive and the session is current before accepting input.
- **Workspace or path with non-ASCII characters.** Persian, mixed right-to-left
  and left-to-right text, emoji, combining characters and long paths are shown
  as the Core reports them and passed through unchanged.
- **Untrusted display text.** Provider, model, tool and repository strings
  containing screen-clearing sequences, cursor moves, window-title sequences or
  imitation status such as "[Connected]" or "[Ready]" cannot change the
  interface's own state indicators.
- **A permission request arrives while the window is hidden or minimised.** It
  is not answered by the application; it waits for the person or for the Core's
  own safe fallback.
- **The computer-use tool.** When the agent drives the machine through the
  computer-control backend, it does so under the Core's mode and permission
  rules exactly as it does for any other client; the desktop application grants
  nothing on its own and does not change that backend.
- **Two workspaces.** Switching workspace ends the current Core cleanly and
  starts one for the new workspace; there is never more than one Core per
  window.
- **Workspace chooser dismissed at launch.** No Core is started; the window
  shows that no workspace is chosen and offers to choose one. It never falls
  back to a folder the person did not choose.
- **Explicit path invalid.** A command-line path that does not exist or is not
  a readable directory is reported as such, and the chooser opens as on any
  fresh launch.
- **Last selected folder gone.** The chooser opens at the operating system's
  default location instead.
- **An uncertain turn between crashes.** A turn that was cancelled, failed,
  stopped for a decision, raised a warning or error notice, or was not started
  by the application is not a completed turn, and does not reset the crash
  count (FR-005).

## Requirements *(mandatory)*

### Functional Requirements

**Core lifecycle and supervision**

- **FR-001**: The desktop application MUST start its own Core for the chosen
  workspace, using an existing Comodor installation, and MUST own that Core's
  lifetime: one Core per window, started by the application and ended by it.
- **FR-002**: The application MUST locate the Core in a defined, documented
  order, and MUST report which locations it tried when none is found.
- **FR-003**: The application MUST start the Core without placing any
  credential in the Core's command-line arguments, and MUST NOT add credentials
  to the Core's environment beyond what the person's own environment already
  provides.
- **FR-004**: The application MUST detect that its Core has exited, whether by
  crash, by being killed, or by a protocol fault, and MUST show the person that
  it happened.
- **FR-005**: After an unexpected exit of a Core that had reached ready, the
  application MUST start a new Core for the same workspace automatically,
  unless this is the **third consecutive** such crash without a completed turn
  in between. In that case it MUST NOT restart the Core, and MUST wait for the
  person's explicit "Try again".

  A **completed turn** is decided conservatively, from what the Core sends. A
  turn counts as completed only if all of the following hold:
  - the application relayed the `session.send` that started it and saw its
    `turn_id`;
  - the Core then reported the session idle (`session.updated` with
    `busy: false`);
  - between the two, at least one `message.completed` for that `turn_id`
    arrived, and every one of them had `status: completed`;
  - no `notification.created` at level `warning` or `error` arrived for that
    session;
  - no `session.cancel` for that session was relayed.

  Any other outcome is uncertain, and an uncertain outcome never resets the
  count. Uncertain outcomes include a cancellation or a failure between
  messages, a turn that stopped for a decision (`clarification_required`, which
  this client sees as a warning notification), a Core crash, and a turn the
  application did not start. Only a completed turn resets the count: the
  person's "Try again" and the passage of time do not. There is no time window.
  A Core that fails before reaching ready is never restarted automatically. No
  restart replays interrupted work (FR-016).
- **FR-006**: The application MUST keep a bounded tail of the Core's diagnostic
  output, MUST keep reading it so the Core never blocks on it, and MUST make it
  available to the person when a failure is shown.
- **FR-007**: The application MUST NOT treat the Core's diagnostic output as
  protocol content, and MUST treat any non-protocol line on the protocol
  channel as a protocol fault.

**Connection and protocol**

- **FR-008**: The application MUST connect to the Core only through the
  versioned protocol as defined by `schemas/protocol/v2.json`, and MUST NOT
  call into Core internals by any other route.
- **FR-009**: The application MUST complete the protocol handshake before any
  other request, MUST refuse to continue when the protocol versions differ, and
  MUST name both versions when it refuses.
- **FR-010**: The connection between the application and its Core MUST be
  reachable only by the application and its Core: it MUST NOT be a network
  listener, on loopback or elsewhere, that another local process or a web page
  could reach, and it MUST NOT depend on a secret passed where other processes
  can read it.
- **FR-011**: After the window's content reloads while the Core is running,
  the application MUST reconnect to the same Core, rebuild the session from a
  snapshot and apply only the events after it, so that no message is shown
  twice and none is missing.
- **FR-012**: The application MUST repair a detected sequence gap by requesting
  a snapshot and MUST ignore a duplicate event.

**Conversation**

- **FR-013**: From the ready state the person MUST be able to work in one
  session: send a prompt, see the reply and the agent's tool activity as they
  stream, cancel a turn in progress, change mode, and answer question forms and
  permission requests. Listing and reopening stored conversations is not part
  of D1 (D5); the only reopening D1 does is the automatic one after a Core
  restart (FR-016).
- **FR-014**: Everything the window shows about a session — messages, tool
  activity, pending questions and permissions, mode, model and usage — MUST be
  derived from what the Core sent, through the shared session semantics, and
  MUST NOT be advanced by the window ahead of the Core's confirmation.
- **FR-015**: The application MUST answer a question form or a permission
  request only with an answer the person gave, MUST offer every option the Core
  supplied, and MUST leave an unanswered request to the Core's own resolution.
- **FR-016**: After a Core restart the application MUST reopen the conversation
  the person was in from what the Core persisted, MUST show a turn that was
  interrupted as interrupted, and MUST NOT re-send any prompt or answer
  automatically.

**Shutdown and instances**

- **FR-017**: On window close or application quit, the application MUST cancel
  a turn in progress through the Core, request an orderly Core shutdown, show
  "Closing…" and offer "Quit now", and wait up to **10 seconds** for the Core
  to exit. If the Core has not exited when the 10 seconds end, or the person
  chooses "Quit now", the application MUST terminate the Core it owns and the
  processes that Core started. It MUST then report that the Core was stopped
  before it finished, in the window while the window is still open and always
  in its own log, and MUST NOT state or imply that work the Core had not
  persisted was saved. The same bound and honesty apply when a workspace
  change or "Check again" stops a Core.
- **FR-018**: No Core process started by the application may outlive it on any
  supported platform, including when the application is terminated abruptly.
- **FR-019**: A second launch of the application while it is running MUST bring
  the existing window to the front and MUST NOT start a second Core for it. If
  the second launch names a workspace different from the current one, the
  application MUST ask the person before switching, and MUST NOT switch when
  the person declines or does not answer.

**Workspace**

- **FR-020**: The window MUST always show which workspace the Core is operating
  on, as the Core reports it.
- **FR-021**: On every fresh launch of the application, the person MUST
  explicitly choose the workspace, in a chooser that opens at the last folder
  they selected. A valid workspace path given on the command line takes
  precedence and is used without the chooser. Within one launch, a reload of
  the window's content or a restart of the Core MUST keep the chosen workspace
  without asking again. The person MUST be able to change the workspace later;
  changing it MUST end the current Core cleanly and start one for the new
  workspace. The application MUST NOT start a Core in a workspace the person
  did not choose, or name on the command line, in the current launch.
- **FR-022**: The application MUST check that the chosen workspace exists and is
  readable before starting a Core for it, and MUST report a missing or
  unreadable workspace as such.

**Reuse and boundaries**

- **FR-023**: The application MUST reuse the shared client packages for the
  protocol, the connection, session state, commands, modes, question forms and
  design tokens, rather than reimplementing any of them.
- **FR-024**: The application MUST NOT decide what a mode permits, whether a
  tool may run, whether a request is allowed, or any other rule the Core owns;
  it presents what the Core reports and sends what the person chooses.
- **FR-025**: Any change D1 needs in a shared client package MUST be additive,
  MUST NOT change that package's behaviour for the terminal interface, and MUST
  pass the terminal interface's renderer suite unchanged.
- **FR-026**: D1 MUST NOT require any change to the protocol schema, the Core's
  application services or the Core's policies. If implementation finds one
  unavoidable, it MUST be specified and reviewed as its own change first.
- **FR-027**: The desktop application MUST NOT import, wrap, modify or depend on
  the computer-control backend in `src/comodor/desktop/`, and MUST NOT embed or
  serve the existing browser interface.

**Security**

- **FR-028**: The window's content MUST NOT receive, store, cache, log or be
  able to request a provider key, a GitHub installation token, an OAuth secret,
  signing material or the Core's environment.
- **FR-029**: The window's content MUST display every string that originates
  outside the application — model output, tool output, file names, provider
  and model names, error messages — as inert text: it MUST NOT execute scripts,
  load remote resources, navigate the window or change the interface's own
  status indicators.
- **FR-030**: The native side MUST expose to the window's content only the
  operations this specification requires — relaying protocol messages to and
  from its own Core, choosing a workspace, reporting Core status and
  diagnostics, and opening an external link in the system browser after the
  person asks — and MUST refuse everything else.
- **FR-031**: When the Core reports the provider as not configured, the
  application MUST show that state, MUST direct the person to run
  `comodor setup` in a terminal, MUST NOT accept a prompt until the Core reports
  the provider as configured, and MUST re-check the Core's provider state when
  the person asks, without a restart of the application. D1 MUST NOT offer
  credential entry of its own, in the window's content or elsewhere; trusted
  native credential entry is a later change and needs its own specification.
- **FR-032**: The application's own logs and persisted preferences MUST contain
  no credential, and MUST contain only non-secret presentation state (window
  geometry, the last selected folder, and similar).

**Platforms and acceptance**

- **FR-033**: The desktop application MUST build, start, supervise a Core, shut
  down and pass its tests on Windows, Linux and macOS, with any
  platform-specific behaviour isolated behind a stated platform check. Each
  requirement's evidence MUST be recorded for every one of the three
  platforms. A platform without recorded evidence leaves D1 incomplete:
  NOT VERIFIED is never a pass.
- **FR-034**: Every acceptance test of this milestone MUST be deterministic, MUST
  run the Core with the offline scripted provider or scripted responses, and
  MUST NOT call a model provider, spend paid tokens, or need a credential.
- **FR-035**: Tests of races — Core exit during a turn, reload during
  streaming, shutdown during a turn — MUST synchronise on observable states
  (a process exit, an event, a snapshot revision), never on elapsed time.

### Key Entities

- **Desktop application**: the new windowed client. It has a native side that
  owns processes, the operating system and the window, and window content that
  renders. It is a client of the Core, never an authority.
- **Core process**: one Comodor Core started by the application for one
  workspace. It has a lifecycle state (starting, handshaking, ready, failed,
  restarting, stopping, stopped) owned by the native side, a protocol version
  and identity learned at the handshake, and a bounded diagnostic tail.
- **Connection**: the private channel between the application and its Core,
  carrying protocol v2 messages only.
- **Restart policy**: the count of consecutive crashes of a ready Core since the
  last completed turn; at three, automatic restarts stop until the person
  retries (FR-005).
- **Workspace**: the directory the Core operates on, chosen by the person at
  each fresh launch or given on the command line, kept for the rest of that
  launch, and reported by the Core.
- **Desktop preferences**: non-secret presentation state the application
  persists for itself, including the last selected folder, which only decides
  where the chooser opens.
- **Computer-control backend**: the existing Core capability in
  `src/comodor/desktop/`; named here only to be kept apart from the desktop
  application.

### Surface classification (Constitution XI)

| Surface | Status | Evidence / Notes |
| --- | --- | --- |
| TUI | UNCHANGED BUT VERIFIED | The terminal interface in `apps/tui/` is not changed. It shares the packages under `packages/` with the desktop application; FR-025 allows only additive package changes, verified by the TUI renderer suite (`bun test apps/tui/test/bun/renderer.test.tsx`) and `npm test` passing unchanged. |
| Web UI | UNCHANGED BUT VERIFIED | `src/comodor/web/` is not changed, embedded or served by the desktop application (FR-027); verified by `tests/test_web.py` and `tests/test_real_web_ui.py` passing unchanged. |
| CLI / Headless | UNCHANGED BUT VERIFIED | The desktop application starts the existing `comodor core --stdio` (`src/comodor/transport/__init__.py::serve_stdio`) without changing it; verified by `tests/test_core_stdio.py` and `tests/test_transport_commands.py`. |
| API / Protocols | UNCHANGED BUT VERIFIED | Protocol v2 (`schemas/protocol/v2.json`) is used unchanged (FR-008, FR-026); verified by `python tools/protocol-codegen.py --check` and the protocol test suites. D1 has no credential entry (FR-031), so no setup method is added. |
| Desktop | REQUIRED | The new desktop application: Core lifecycle and supervision, connection, conversation per FR-013, shutdown, instances, workspace, security (FR-001–FR-035). The computer-control backend in `src/comodor/desktop/` is unchanged (FR-027), verified by `tests/test_desktop.py` passing unchanged. |
| Channels / Integrations | NOT APPLICABLE | Channel integrations (`src/comodor/channels/`) run their own sessions and never talk to a desktop window; the desktop application adds no channel, and the GitHub connection flow stays in the Core and the terminal. |
| Docker / Packaged Runtime | UNCHANGED BUT VERIFIED | The container image and the Python wheel and sdist do not include the desktop application: the wheel packages `src/comodor` and the sdist includes `src/comodor`, `tests`, `pyproject.toml`, `README.md` and `LICENSE` (`pyproject.toml` `[tool.hatch.build]`); verified by the wheel-contents guard in CI. Desktop installers, signing and auto-update belong to D6. |
| Persistence / Shared State | REQUIRED | The application persists its own non-secret preferences (FR-032). Session persistence is unchanged and owned by the Core; recovery reopens what the Core persisted (FR-016). |
| Security / Authorization | REQUIRED | A new trust boundary between the native side and the window's content: credential exclusion, inert display of untrusted text, a minimal native operation set, a private connection (FR-010, FR-028–FR-032). Mode and permission policy stay in the Core (FR-024). |
| Tests / Documentation | REQUIRED | Deterministic cross-platform tests for lifecycle, recovery, shutdown, orphan prevention and the credential canary (FR-033–FR-035); `docs/desktop-architecture.md` updated from "planned, not built" to what D1 delivers, and the Desktop row meaning in `docs/surface-parity.md` updated to name both the desktop application and the computer-control backend. |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On each of Windows, Linux and macOS, a person with Comodor
  installed reaches the ready window — workspace, provider, model and configured
  status shown — within 10 seconds of launch on a typical developer machine, in
  every run of the startup test.
- **SC-002**: Each startup failure — Core not found, Core exits before the
  handshake, protocol version mismatch, workspace unavailable — produces its own
  named message and never the ready state, in 100% of the injected-failure
  tests.
- **SC-003**: After the Core is killed between turns, the person is back in the
  same conversation, with every turn the Core had persisted, within 10 seconds,
  in 100% of the injected-crash tests on all three platforms.
- **SC-004**: After a Core crash during a turn, the interrupted turn is shown as
  interrupted and no prompt or answer is re-sent, in 100% of the tests.
- **SC-005**: After the window's content reloads during a streamed reply, the
  rebuilt conversation matches the Core's own snapshot exactly — no duplicated
  and no missing message — in 100% of the tests.
- **SC-006**: Two consecutive crashes of a ready Core without a completed turn
  are each followed by an automatic restart; the third is not, and the
  application waits for "Try again". A completed turn between crashes starts
  the count again. Both hold in 100% of the tests.
- **SC-007**: After a normal close, a quit during a turn and an abrupt kill of
  the application, zero Core processes started by it remain, on all three
  platforms, in 100% of the runs.
- **SC-008**: A second launch leaves exactly one window and one Core, and one
  that names a different workspace switches only after the person confirms,
  in 100% of the runs.
- **SC-009**: A canary credential configured for the Core appears zero times in
  everything the window's content can reach — its storage, the messages it
  received, the native operations it may call, its logs — and in the
  application's own logs and preferences, across the startup, conversation,
  failure, recovery and shutdown tests.
- **SC-010**: Untrusted strings containing markup, scripts, terminal control
  sequences and imitation status indicators are shown as inert text and change
  no interface state, in 100% of the adversarial display tests.
- **SC-011**: Every native operation outside the declared set is refused, in
  100% of the tests that attempt one.
- **SC-012**: The terminal interface's renderer suite, the frontend tests, the
  Python test suite and the protocol code-generation check pass unchanged on
  the exact commit under review.
- **SC-013**: Every acceptance test runs without network access to a model
  provider, without a credential, and without paid tokens.
- **SC-014**: With the offline scripted provider, a prompt
  sent from the window produces the scripted reply, and a scripted question and
  permission are each answered from the window with exactly the answer the
  person gave, in 100% of the tests.
- **SC-015**: Launched against a Core with no configured provider, the window
  shows the unconfigured state and the `comodor setup` direction, refuses to
  send a prompt, and shows the configured state after setup and a re-check
  without an application restart, in 100% of the tests.
- **SC-016**: A Core that exits within ten seconds of a close or quit is never
  terminated. One that does not, or one ended by "Quit now", is terminated
  together with the processes it started; the application reports it as
  stopped before finishing and never as saved. All of this holds in 100% of
  the tests, on all three platforms.
- **SC-017**: Every fresh launch without a command-line path opens the chooser
  at the last selected folder and starts no Core until a folder is chosen. A
  valid command-line path starts the Core there with no chooser. A reload of
  the window's content or a Core restart within the launch never asks again.
  All of this holds in 100% of the tests. In addition, recorded evidence from
  Windows, Linux and macOS shows the operating system's real folder chooser
  opening at the folder the application passed to it.

## Clarifications

### Session 2026-09-30

- Q: How much conversation does the D1 window include? → A: One session: send
  a prompt, streamed reply and tool activity, cancel, change mode, answer
  question forms and permission requests. No history browsing (D5). *Binds*:
  FR-013, FR-016, SC-014; User Story 2.
- Q: What is D1's path to readiness when the Core reports no configured
  provider? → A: Show the state, direct the person to run `comodor setup` in a
  terminal, and re-check on request. No credential entry in D1; trusted native
  credential entry needs its own specification later. *Binds*: FR-031, SC-015;
  User Story 6; the API / Protocols surface row.
- Q: When does automatic restarting of a crashing Core stop? → A: After the
  third consecutive crash of a Core that had reached ready, without a
  completed turn in between. The application then waits for the person's
  explicit retry. The count resets only after a completed turn; there is no
  time window, and interrupted work is never replayed. *Binds*: FR-005,
  FR-016, SC-006; User Story 3.
- Q: How long does a close or quit wait for the Core, and what happens then?
  → A: Ten seconds, with "Closing…" shown and "Quit now" offered. At the
  deadline, or on "Quit now", the application terminates the Core it owns,
  reports the interrupted state honestly, and never claims that unsaved work
  was saved. *Binds*: FR-017, FR-018, SC-016; User Story 4.
- Q: Which workspace does a fresh launch use? → A: The person explicitly
  chooses one on every fresh launch, in a chooser opened at the last selected
  folder. A valid explicit command-line path takes precedence. A page reload
  or Core restart within the same launch keeps the chosen workspace without
  asking again. *Binds*: FR-021, FR-022, FR-032, SC-017.

### Session 2026-10-01

- Q: Which Core events prove that a turn completed, for the crash count? → A:
  Only the conservative rule in FR-005. A relayed `session.send` with its
  `turn_id`, then `busy: false`, with at least one `message.completed` for that
  turn and all of them `completed`, no warning or error notification, and no
  relayed `session.cancel`. Every uncertain outcome — including a turn that
  stopped for a decision — leaves the count unchanged. This makes OD-1
  precise; it is not a new decision. The event order was verified in
  `src/comodor/application/__init__.py`: `send`'s worker `finally` persists
  before `busy: false`; `_relay` handles `CANCELLED` and `ERROR`;
  `_relay_clarification` emits its notification even when the event itself is
  withheld. *Binds*: FR-005, SC-006; data-model §3; native-bridge relay
  guarantee 2.
- Q: When is D1 accepted across platforms? → A: Only with recorded evidence for
  every requirement on Windows, Linux and macOS, including the real folder
  chooser for SC-017. A platform without evidence leaves D1 incomplete;
  NOT VERIFIED is never a pass and is never waived silently. *Binds*: FR-033,
  SC-017.
- Q: What happens when a second launch names a different workspace? → A: The
  running instance asks before switching, and keeps the current workspace if
  the person declines or does not answer. *Binds*: FR-019, SC-008.

## Scope Boundaries

**In D1**: the desktop application's native side and window, Core lifecycle and
supervision, the private connection, protocol handshake and reconnection,
shutdown and single-instance behaviour, workspace selection, the conversation
defined by FR-013 (one session), the provider-state path defined by FR-031
(direct to `comodor setup`), the credential
boundary, and deterministic cross-platform tests.

**Not in D1**, each kept for its phase:

- the full workbench layout, panels and command palette (D2);
- a code editor and workspace browsing (D3);
- an integrated terminal (D4);
- agent, task, delegate and session panels (D5);
- installers, code signing, auto-update, release and deployment (D6);
- credential entry of any kind in the desktop application, including a trusted
  native dialog, and browsing or reopening stored conversations;
- attaching the terminal interface to the desktop application's Core over local
  IPC, and remote Cores;
- any change to the trading work in PR #39.

## Assumptions

- The person has a working Comodor installation whose Core speaks protocol v2;
  D1 does not bundle a Python runtime or the Core. Bundling is part of D6
  packaging.
- D1 is run from a local build on each platform; it is built and tested in CI
  but not published.
- The offline scripted provider that the terminal interface's tests already
  use is sufficient for every D1 acceptance test.
- The Core exits when its client's connection closes, as it does today
  (`serve_stdio`); FR-018 relies on that, plus the application stopping the
  Core it started.
- The restart limit, the shutdown bound and the workspace choice at launch are
  owner decisions recorded under Clarifications (2026-09-30), not defaults.
- The workspace chooser is the operating system's own folder chooser.
- The window renders right-to-left and mixed-direction text through the
  platform's own text rendering; D1 does not reorder text itself.
- The agreed stack (Tauri 2, React, TypeScript) comes from
  `docs/desktop-architecture.md`; this specification states behaviour and
  boundaries, and the plan chooses the mechanisms.
