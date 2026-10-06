# Tasks: Desktop Foundation (D1)

**Input**: Design documents from `/specs/003-desktop-foundation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)

**Tests**: Required. The spec makes every acceptance test deterministic and
offline (FR-034, FR-035), and the constitution requires a mutation-sensitive
test for every guard (IV). In every phase the listed tests are written first
and must fail before the implementation that satisfies them is written.

**Organization**: Tasks are grouped by user story, in priority order:
- P1: US1, US2, US5;
- P2: US3, US4;
- P3: US6.

Workspace selection (OD-3, FR-020–FR-022, SC-017) belongs to US1. Single
instance and the second-launch confirmation (FR-019, SC-008) belong to US4.
Assertions that need every command or every flow — the final command list,
the release manifest and the full canary — run in Phase 9, after US6.

**Offline and determinism rules (every task)**:
- The Core runs with the offline `fake` provider, the scripted Core fixture,
  or a Core double. No task calls a model provider, needs a credential, or
  spends paid tokens.
- No test waits a fixed time. Waits are on process exit, a line read, a DOM
  change, an injected clock, or an explicit hold released by the harness. A
  wait may carry a failure deadline, never a delay.
- Every "during a turn" case uses the `hold-mid-turn` scenario. The volume
  scenario `stream-long` is never used for timing.

**Evidence rules**:
- Development runs use `workflow_dispatch` on the pushed branch. Their
  results are kept for the PR description and never committed.
- Evidence for the exact final SHA lives in the PR description and the owner
  report, never in a repository commit after the final validation round.
- A requirement without recorded evidence on Windows, Linux **and** macOS
  leaves D1 incomplete. NOT VERIFIED is never a pass (FR-033).

**Out of scope (do not start)**:
- D2–D6;
- bundling, installers, signing, auto-update;
- a remote Core, or a terminal attaching to the desktop's Core;
- credential entry, and history browsing;
- PR #39;
- the TUI `spawnCore` shutdown observation (plan K10).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US6, from spec.md
- Test layers:
  - **U**: native unit;
  - **I**: native integration against a real or scripted Core or a double;
  - **W**: window logic (Bun and happy-dom);
  - **S**: in-application scenario (`e2e` build, real WebView);
  - **L**: process lifetime (external harness);
  - **G**: existing repository gates.

## Path Conventions

- Window content: `apps/desktop/src/`; its tests: `apps/desktop/test/`
- Native side: `apps/desktop/src-tauri/src/`; its tests: `apps/desktop/src-tauri/tests/`
- Test fixtures (Python, test-only, not packaged): `apps/desktop/src-tauri/tests/fixtures/`
- Scenarios, harnesses and CI scripts: `apps/desktop/e2e/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The new workspace exists, builds and lints. Outside
`apps/desktop/`, only the root `tsconfig.json`, the root `package-lock.json`,
`tools/lint-frontend.mjs` and `.github/workflows/ci.yml` change in this
feature.

- [X] T001 Create the window workspace in `apps/desktop/package.json`, `apps/desktop/tsconfig.json`, `apps/desktop/index.html` and `apps/desktop/vite.config.ts`:
  - package name `comodor-desktop`;
  - dependencies on `@comodor/protocol`, `@comodor/client`, `@comodor/session`, `@comodor/questions`, `@comodor/modes`, `@comodor/commands`, `@comodor/design-tokens`, `react`, `react-dom` and `@tauri-apps/api`;
  - dev dependencies on `vite`, `@vitejs/plugin-react`, `@tauri-apps/cli` and `@happy-dom/global-registrator`;
  - all at exact versions;
  - scripts `test` (`bun test apps/desktop/test`), `build`, `e2e`, `lifetime`, `release-manifest`.
- [X] T002 Add `{ "path": "apps/desktop" }` to the references in the root `tsconfig.json`, and update the root `package-lock.json` with `npm install` so `npm ci` reproduces it; verify `npm run typecheck` and `npm run lint` still pass at the root.
- [X] T003 [P] Create the native crate in `apps/desktop/src-tauri/Cargo.toml`, `apps/desktop/src-tauri/Cargo.lock`, `apps/desktop/src-tauri/rust-toolchain.toml`, `apps/desktop/src-tauri/build.rs`, `apps/desktop/src-tauri/src/command_names.rs`, `apps/desktop/src-tauri/src/main.rs` and `apps/desktop/src-tauri/.gitignore`.
  - **Dependencies**: `tauri` 2, `tauri-build` 2, `tauri-plugin-single-instance`, `tauri-plugin-dialog`, `serde`, `serde_json`, `windows-sys` (Windows) and `libc` (Unix), all pinned exactly. Add a cargo feature `e2e`, off by default.
  - **One command list**: `src/command_names.rs` holds `pub const COMMANDS: [&str; 9] = ["connect", "send_line", "status", "diagnostics", "choose_workspace", "retry", "check_again", "quit_now", "open_external"];` with no `e2e_report`. It is used by both `build.rs` (via `include!`) and `main.rs` (as a module).
  - **`build.rs`**: calls `tauri_build::try_build(tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&names)))`. `names` is `COMMANDS`, plus `"e2e_report"` only when the `CARGO_FEATURE_E2E` environment variable is set. This registers the app's commands in the app manifest, so the build generates an allow/deny permission pair per command instead of allowing every command to every window. The handler registration in `main.rs` registers only names from `COMMANDS` — each command is added by the task that implements it, and all nine are registered by T084 — plus `e2e_report` under `#[cfg(feature = "e2e")]` only. A permission generated for a command not yet registered grants nothing callable.
  - **Generated files**: `apps/desktop/src-tauri/.gitignore` ignores `gen/`, so release and `e2e` builds never leave generated permission files in the tree.
  - **Verify against the pinned version**, recording each point in `apps/desktop/README.md`:
    - (a) without the app manifest, every registered command is allowed to every window;
    - (b) with it, a command whose permission no enabled capability grants is refused;
    - (c) the exact generated permission identifiers for the nine commands (format `allow-<command>`/`deny-<command>`);
    - (d) the generated files `gen/schemas/acl-manifests.json` (app permissions under `__app-acl__`) and `gen/schemas/capabilities.json`;
    - (e) any `core:` permission the IPC channel used by `connect` requires;
    - (f) the single-instance plugin's mechanism per platform (plan K11).

    If any point differs from this task, stop and correct [native-bridge.md](./contracts/native-bridge.md) and T004/T085 before continuing.
- [X] T004 [P] Create `apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/src-tauri/capabilities/main.json` and `apps/desktop/src-tauri/tauri.e2e.conf.json` per [native-bridge.md](./contracts/native-bridge.md) §Capability configuration:
  - **`tauri.conf.json`** — release: one window labelled `main`; `app.security.capabilities` set explicitly to `["main"]`, so only that capability is used; a CSP with scripts and styles from the bundle only, no inline script, no `eval`, no remote origin, and IPC as the only connection; devtools off in release.
  - **`capabilities/main.json`** — identifier `main`, windows `["main"]`. Its permissions are exactly the nine generated `allow-<command>` identifiers recorded in T003(c), plus only the `core:` permissions recorded in T003(e) as required by the IPC channel. No plugin permission, and never `e2e_report`.
  - **`tauri.e2e.conf.json`** — used only by the `e2e` build through `--config`: replaces `app.security.capabilities` with `["main", {inline capability "e2e-test", windows ["main"], permissions [the generated allow identifier for e2e_report]}]`. No capability file for `e2e_report` exists under `capabilities/`, so a release build cannot load one.
- [X] T005 [P] Add a rule to `tools/lint-frontend.mjs`, applying only under `apps/desktop/test` and `apps/desktop/e2e`, that rejects fixed delays: `setTimeout` or `sleep` with a literal delay, outside an injected-clock helper (FR-035). Include a failing and a passing sample if the file has a self-check.
- [X] T006 [P] Create the window test setup in `apps/desktop/test/setup.ts`: happy-dom registered globally, so React renders into a DOM under `bun test`, and no network access.

**Checkpoint**:
- `npm ci`, `npm run lint`, `npm run typecheck` and `npm run build` pass at the root;
- `cargo build` succeeds in `apps/desktop/src-tauri`;
- `bun test apps/tui/test/bun/renderer.test.tsx` is unchanged.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Fixtures, the spawn primitive, the bridge `Transport`, the
scenario and lifetime tooling, and the CI job every story's tests run on.

**⚠️ CRITICAL**: No user-story work begins until this phase is complete.

- [X] T007 [P] Write the offline Core home helper in `apps/desktop/src-tauri/tests/support/mod.rs`:
  - it creates a temporary `COMODOR_HOME` whose `config.json` has the single `fake` provider (`base_url: "offline"`, model `fake-1`), `learning`, `mcp`, `cron` and `skills` disabled, and `agent.loop: false`, as `apps/tui/test/bun/orphan.test.ts` does;
  - options: a given `api_key` (the canary), and "unconfigured" (no provider);
  - it resolves the interpreter from `COMODOR_PYTHON` (default `python`) and sets `PYTHONPATH` to the repository's `src`.
- [X] T008 [P] Write the scripted Core fixture in `apps/desktop/src-tauri/tests/fixtures/scripted_core.py`. It builds `CoreService(config, assemble_with=…)` with scripted `Gateway(config, scripts=…)` responses, as `tests/test_protocol_permissions.py` does, and serves it on real stdin/stdout with `own_stdout`, `Channel` and `Server`, as `serve_stdio` does. There is no network and nothing outside the temporary home. One scenario per argument:
  - `echo`;
  - `stream-long` (volume only, never timing);
  - `hold-mid-turn` — opens a message, emits at least one delta, then blocks until the harness releases a hold over a dedicated control channel (a blocking read the harness completes, such as a named pipe on Windows or a FIFO on Unix), never by elapsed time or polling; it then completes or stays held;
  - `question` (an `ask` form with two options and the write-your-own row);
  - `permission` (a `write_file` call with writes not auto-approved);
  - `adversarial` (the strings of [quickstart.md](./quickstart.md) §6 in text, tool output, file names and an error);
  - `complete-turn`;
  - `cancel-between-messages` — the scripted model calls `hold_step`, a test-only blocking tool registered in the fixture's own `ToolRegistry` (never in the product). The tool waits on the control channel, so the test's `session.cancel` arrives while no message is open;
  - `cancel-mid-message` (`hold-mid-turn`, then cancel);
  - `fail-between-messages` — the second model call raises a provider error before any output;
  - `fail-mid-message` — an error after one chunk;
  - `clarification-stop` — an `ask` form the test dismisses, so the turn stops for the decision.
- [X] T009 [P] Write the Core doubles in `apps/desktop/src-tauri/tests/fixtures/doubles.py`. Each is selected by argument:
  - `exit-immediately` exits with a message on stderr;
  - `bad-line` writes one non-protocol line on stdout after the handshake;
  - `version-mismatch` answers `client.hello` with protocol version 3, with a variant that answers `unsupported_version` carrying `supported`;
  - `ignore-stop` handshakes, ignores `shutdown` and stdin EOF, and starts one child process;
  - `crash-on-send` handshakes, then exits abruptly on the first `session.send`;
  - `stderr-flood` writes past 200 lines and 64 KiB on stderr while handshaking;
  - `sequenced` reads `COMODOR_TEST_SEQUENCE`, a JSON list of per-launch behaviours (`crash-on-send`, `complete-turn`, or `scripted:<scenario>`, which delegates to `scripted_core.py`), and advances an atomic counter file, so each launch takes the next entry deterministically.

  Also add a non-executable target file `apps/desktop/src-tauri/tests/fixtures/not-executable`, with no execute permission, for `spawn_failed`.
- [X] T010 Write spawn tests in `apps/desktop/src-tauri/tests/spawn.rs` (**I**, all platforms). With `COMODOR_BIN` and `COMODOR_ARGS` pointing at the interpreter and the `echo` fixture, the spawned process:
  - has exactly the arguments `[<COMODOR_ARGS…>, core, --stdio]`;
  - has the workspace as its working directory;
  - inherits the environment unchanged;
  - runs with no shell and no console window on Windows;
  - has all three streams piped.
- [X] T011 Implement spawning in `apps/desktop/src-tauri/src/platform/mod.rs`, `apps/desktop/src-tauri/src/platform/windows.rs` and `apps/desktop/src-tauri/src/platform/unix.rs`, always from the supervisor's single long-lived thread, which T076's parent-death signal relies on. Orphan guarantees are added in US4. T010 must pass.
- [X] T012 [P] Write bridge `Transport` tests in `apps/desktop/test/bridge.test.ts` (**W**), with an injected fake of `invoke` and the IPC channel:
  - `lines()` yields `line` messages in order;
  - `write()` calls `send_line` with the page's generation;
  - a `closed` message ends `lines()`;
  - `close()` detaches without calling any stop command.
- [X] T013 Implement the bridge `Transport` in `apps/desktop/src/bridge.ts` per [native-bridge.md](./contracts/native-bridge.md) §The page's `Transport`, so `CoreClient` runs over it unchanged. T012 must pass.
- [X] T014 [P] Write the in-memory Core double for window tests in `apps/desktop/test/fake-core.ts`. It implements `Transport` and scripts protocol lines. It does not import from `apps/tui`.
- [X] T015 Create the `e2e`-only test support in `apps/desktop/src-tauri/src/e2e.rs` and the scenario runner in `apps/desktop/e2e/runner.ts`. The runner drives the real UI with DOM events and waits on `MutationObserver` or status messages. The test support provides:
  - the `e2e_report` command;
  - a recorder of every inbound IPC message (`line`, `status`, `closed`) and every bridge command's arguments and return value;
  - a report of the Core's pid and of the application process's network listeners (TCP listening and bound UDP sockets), read per platform as [research.md](./research.md) R14 says;
  - a chooser double that records the start directory it is given and returns a scripted choice;
  - a second-launch confirmation double.
- [X] T016 Create the scenario harness in `apps/desktop/e2e/harness.mjs`:
  - it builds the `e2e` test build once;
  - per scenario, it launches the application with `COMODOR_HOME`, `COMODOR_BIN`, `COMODOR_ARGS`, `COMODOR_TEST_SEQUENCE` where used, an explicit workspace argument where used, and the scenario name;
  - it releases fixture holds through their control channel;
  - it collects the JSON result, the recorder output, the application log and the preferences file;
  - it fails on a missing result by a failure deadline, not a delay;
  - on Linux it runs under `xvfb-run` inside `dbus-run-session`.
- [X] T017 Add a `desktop` job to `.github/workflows/ci.yml` on `ubuntu-latest`, `windows-latest` and `macos-latest`. It reads no repository secret and is runnable by `workflow_dispatch` on the branch. It:
  - installs Python with `pip install -e ".[dev]"`, Node with `npm ci`, the pinned Rust toolchain, and, on Linux only, WebKitGTK 4.1, `xvfb` and `dbus`;
  - runs `cargo test` in `apps/desktop/src-tauri`, `npm run -w apps/desktop test` and `npm run -w apps/desktop e2e`;
  - is the three-platform evidence for FR-033.

  `lifetime` is added in T074 and `release-manifest` in T085.

**Checkpoint**:
- each fixture answers `client.hello` when piped by hand;
- a `hold-mid-turn` run stays held until released;
- the `sequenced` double takes its entries in order across relaunches;
- T010 and T012 pass on all three platforms through `workflow_dispatch`;
- an empty scenario reports pass on all three platforms.

---

## Phase 3: User Story 1 — Open Comodor as a desktop window, ready to work (Priority: P1) 🎯 MVP

**Goal**: On a fresh launch the person chooses a workspace, or names one on
the command line. A Core starts there and completes the handshake; the window
shows the workspace, provider, model, configured state and "ready". Every
startup failure has its own named view.

**Independent Test**: The ready view against the offline Core. Each named
failure against its double (SC-002). The launch-workspace rules, including the
exact chooser start directory (SC-017).

**Covers**: FR-001–FR-004 (detection), FR-006–FR-010, FR-020–FR-022, FR-032
(preferences); SC-001, SC-002, SC-017.

### Tests for User Story 1 ⚠️ (write first; they must fail)

- [X] T018 [P] [US1] Write Core discovery tests (**U**) in `apps/desktop/src-tauri/src/locate.rs`:
  - with `COMODOR_BIN` set, it is used with `COMODOR_ARGS` split on whitespace;
  - otherwise `comodor` on `PATH`;
  - when neither exists, the `not_found` message lists every location tried and names `COMODOR_BIN` and how to install Comodor (FR-002).
- [X] T019 [P] [US1] Write command-construction tests (**U**) in `apps/desktop/src-tauri/src/supervisor.rs` (test module): the arguments are exactly `[<COMODOR_ARGS…>, "core", "--stdio"]` with no value from the Core home's configuration, and the environment passed equals the parent's (FR-003).
- [X] T020 [P] [US1] Write state-machine tests (**U**) in `apps/desktop/src-tauri/src/supervisor.rs` (test module), covering every transition of [data-model.md](./data-model.md) §1:
  - `absent → starting → handshaking → ready`;
  - each failure class — `not_found`, `spawn_failed`, `workspace_unavailable`, `exited_before_ready`, `protocol_mismatch` and `protocol_fault` — lands in `failed` with its own message;
  - `ready` only when `protocol_version` is 2;
  - "Try again" moves `failed` to `starting`;
  - there is no handshake timeout, and no stop action while handshaking — only a window close (stop sequence) or a workspace change.
- [X] T021 [P] [US1] Write diagnostic-tail tests (**U**) in `apps/desktop/src-tauri/src/diag.rs`: "at most 200 lines and at most 64 KiB, dropping the oldest first"; plain text; never parsed as protocol (FR-006, FR-007).
- [X] T022 [P] [US1] Write preferences tests (**U**) in `apps/desktop/src-tauri/src/prefs.rs`:
  - the serialised type has exactly `version` (integer, starting at 1), `window` (`{width, height, x, y, maximized}`) and `last_selected_folder` (string or absent);
  - an unknown field is ignored;
  - a malformed file is treated as absent and replaced through a temporary file and rename;
  - a round trip writes no other field (FR-032).
- [X] T023 [P] [US1] Write launch-workspace tests (**U**) in `apps/desktop/src-tauri/src/workspace.rs` per [data-model.md](./data-model.md) §8, with a fake chooser adapter that records the start directory:
  - a valid command-line path is used with no chooser;
  - an invalid one is reported and the chooser opens;
  - no path makes the chooser adapter receive **exactly** `last_selected_folder`, or the system default when that folder is gone;
  - a choice stores `last_selected_folder`;
  - a dismissal starts no Core and reports "no workspace chosen";
  - a missing or unreadable directory is `workspace_unavailable` (FR-021, FR-022, SC-017).
- [X] T024 [P] [US1] Write handshake tests (**U**) in `apps/desktop/src-tauri/src/relay.rs` (test module): the native `client.hello` declares exactly `["questions", "permissions"]` with protocol version 2, and the answer is cached.
- [X] T025 [US1] Write startup integration tests (**I**, all platforms) in `apps/desktop/src-tauri/tests/startup.rs`:
  - the offline Core reaches `ready`; `model.get` reports `fake`, `fake-1` and configured, and `workspace.get` the workspace;
  - `not_found`;
  - `spawn_failed`, with `COMODOR_BIN` pointing at `tests/fixtures/not-executable`;
  - `exited_before_ready`, with the tail;
  - `protocol_mismatch`, naming 2 and 3, and the error variant naming `supported`;
  - `protocol_fault`;
  - `workspace_unavailable` before any spawn;
  - `stderr-flood` never blocks the handshake (FR-006, FR-009).
- [X] T026 [P] [US1] Write status and failure view tests (**W**) in `apps/desktop/test/status.test.tsx`:
  - the ready strip shows workspace, provider, model and configured state as reported;
  - each failure class has its own message, with the tail as inert text, and "Try again" calls `retry`;
  - "no workspace chosen" offers "Choose workspace…", which calls `choose_workspace`.
- [X] T027 [US1] Write the scenario `ready` (**S**, all platforms) in `apps/desktop/e2e/scenarios/ready.ts`:
  - elapsed time from launch to the ready strip is recorded and fails above 10 s (SC-001);
  - the test build's network-listener report for the application process is empty (FR-010).
- [X] T028 [US1] Write the scenario `workspace-launch` (**S**, all platforms) in `apps/desktop/e2e/scenarios/workspace-launch.ts`, with the chooser double:
  - a fresh launch without a path gives the chooser exactly the stored folder, and no Core starts before a choice;
  - a valid path starts the Core there with no chooser;
  - a dismissal leaves "no workspace chosen" (SC-017, automated part).

### Implementation for User Story 1

- [X] T029 [P] [US1] Implement Core discovery in `apps/desktop/src-tauri/src/locate.rs` to pass T018.
- [X] T030 [P] [US1] Implement the diagnostic tail in `apps/desktop/src-tauri/src/diag.rs`, read on its own thread, to pass T021.
- [X] T031 [P] [US1] Implement preferences in `apps/desktop/src-tauri/src/prefs.rs`, in the application's per-user configuration directory, to pass T022.
- [X] T032 [US1] Implement launch-workspace resolution in `apps/desktop/src-tauri/src/workspace.rs`, held in memory for the whole launch. The chooser adapter is a thin wrapper that passes the start directory to the dialog plugin, used from Rust only; the `e2e` feature swaps in the double. T023 must pass.
- [X] T033 [US1] Implement the supervisor state machine, command construction and failure classification in `apps/desktop/src-tauri/src/supervisor.rs`, to pass T019 and T020.
- [X] T034 [US1] Implement the native handshake, its cache, and the stdout bad-line check that raises `protocol_fault` in `apps/desktop/src-tauri/src/relay.rs`, to pass T024 and T025.
- [X] T035 [US1] Implement `connect`, `status`, `diagnostics`, `choose_workspace` and `retry` in `apps/desktop/src-tauri/src/commands.rs`, per [native-bridge.md](./contracts/native-bridge.md). Every name comes from the single command constant.
- [X] T036 [US1] Implement the window shell in `apps/desktop/src/main.tsx`, `apps/desktop/src/app.tsx`, `apps/desktop/src/view/StatusStrip.tsx`, `apps/desktop/src/view/FailureView.tsx` and `apps/desktop/src/view/WorkspaceGate.tsx`, with colours only from `cssVariables()`. T026 must pass.
- [X] T037 [US1] Push the branch normally (no force) and run the `desktop` job of `.github/workflows/ci.yml` with `workflow_dispatch`. T025, T027 and T028 must pass on all three platforms. Keep the run link, per-platform results and the SC-001 time for the PR description.

**Checkpoint**: US1 works alone on Windows, Linux and macOS.

---

## Phase 4: User Story 2 — Hold one conversation with the agent (Priority: P1)

**Goal**: One session: send a prompt, see the reply and tool activity stream
in, cancel, change mode, and answer forms and permissions — all derived from
what the Core sent.

**Independent Test**: With the scripted Core — prompt, streaming, a form and
a permission answered exactly, cancel, and a mode change shown only after
`mode.changed` (SC-014).

**Covers**: FR-008, FR-012–FR-015, FR-023, FR-024; SC-014.

### Tests for User Story 2 ⚠️

- [X] T038 [P] [US2] Write relay tests (**U**) in `apps/desktop/src-tauri/src/relay.rs` (test module):
  - `7` from generation 3 becomes `g3:7`, and its answer maps back;
  - stale-generation and unknown-id answers are dropped;
  - the page's `client.hello` is answered from the cache with the page's id;
  - `shutdown`, a non-v2 method and a non-request line are refused;
  - events reach the current generation only, and order is preserved;
  - every envelope is byte-identical after relaying except its `id`.

  Mutation check: removing the generation drop fails a test.
- [X] T039 [US2] Write relay integration tests (**I**, all platforms) in `apps/desktop/src-tauri/tests/conversation.rs`, against the scripted Core:
  - `echo` streams in the Core's order;
  - `question` delivers every option, including the `free` row, and the chosen answer reaches the Core exactly;
  - `permission` delivers `options`, `tool` and `risk`, and the reply reaches the Core exactly;
  - an unanswered request is resolved by the Core, never by the relay;
  - `session.cancel` sent during `hold-mid-turn` returns `cancelled: true` (the schema's `CancelResult`) and the turn ends cancelled;
  - `session.cancel` sent while idle returns `cancelled: false` (SC-014).
- [X] T040 [P] [US2] Write conversation tests (**W**) in `apps/desktop/test/conversation.test.tsx`:
  - deltas render in `seq` order, and tool activity lines by `call_id`;
  - a gap triggers `session.snapshot`, and a duplicate is ignored (FR-012);
  - send and cancel are single `@comodor/commands` commands, reached by button and keyboard.
- [X] T041 [P] [US2] Write form and permission tests (**W**) in `apps/desktop/test/interactions.test.tsx`:
  - every option is shown, with the write-your-own row as a text field;
  - nothing is sent without the person's action, and the answer equals the selection;
  - an unanswered form stays until `question.resolved`;
  - a permission shows `allow`, `allow_always` and `deny` (FR-015).
- [X] T042 [P] [US2] Write mode tests (**W**) in `apps/desktop/test/mode.test.tsx`:
  - the control sends `session.set_mode` and keeps the old label until `mode.changed`;
  - a refusal keeps the Core's mode;
  - no view branches on whether an action is allowed (FR-014, FR-024).
- [X] T043 [US2] Write the scenario `conversation` (**S**, all platforms) in `apps/desktop/e2e/scenarios/conversation.ts`: prompt, stream, a form answered, a permission answered, a mode change, and cancel during `hold-mid-turn` (FR-013, SC-014).

### Implementation for User Story 2

- [X] T044 [US2] Implement the relay in `apps/desktop/src-tauri/src/relay.rs`: generations, id mapping, drops, the method allowlist, refusals and order. T038 must pass.
- [X] T045 [US2] Implement `send_line` in `apps/desktop/src-tauri/src/commands.rs`, wiring the relay to the supervisor's stdin and stdout. T039 must pass.
- [X] T046 [US2] Implement session bootstrap and state in `apps/desktop/src/state.ts`:
  - `connect`, then `CoreClient.start()`, then subscribe, then `session.create`, then `session.snapshot`;
  - fed into the unchanged `@comodor/session` reducer;
  - holding `stored_id` and `unsent_turn`.
- [X] T047 [P] [US2] Implement `apps/desktop/src/view/Conversation.tsx` and `apps/desktop/src/view/Composer.tsx`, with commands in `apps/desktop/src/commands.ts`. T040 must pass.
- [X] T048 [P] [US2] Implement `apps/desktop/src/view/FormCard.tsx`, with `@comodor/questions`, and `apps/desktop/src/view/PermissionCard.tsx`. T041 must pass.
- [X] T049 [P] [US2] Implement `apps/desktop/src/view/ModeControl.tsx` from `@comodor/modes`. T042 must pass.
- [X] T050 [US2] Run the `desktop` job of `.github/workflows/ci.yml` by `workflow_dispatch`. T039 and T043 must pass on all three platforms. Keep the results for the PR description.

**Checkpoint**: US1 and US2 work — a usable single-session window.

---

## Phase 5: User Story 5 — Credentials never reach the window's content (Priority: P1)

**Goal**: No credential reaches anything the window can touch; outside text
is inert; the window can call nothing outside the contract.

**Independent Test**: The early canary, the adversarial display cases, and a
refused plugin command and navigation. The full canary and the final command
list come later, in T084–T086.

**Covers**: FR-003 (the canary check), FR-028–FR-030, FR-032 (logs); SC-009,
SC-010, SC-011 (early).

### Tests for User Story 5 ⚠️

- [X] T051 [P] [US5] Write the early command-list test (**U**) in `apps/desktop/src-tauri/src/commands.rs` (test module), run without the `e2e` feature:
  - the command constant contains no name outside the nine of [native-bridge.md](./contracts/native-bridge.md);
  - every registered handler comes from the constant;
  - `e2e_report` exists only with `e2e`;
  - `capabilities/main.json` grants no plugin permission, never names `e2e_report`, and holds no `core:` permission beyond the minimum recorded in T003(e);
  - `tauri.conf.json` has the CSP of T004, and devtools off in release.

  Mutation check: adding a name outside the contract fails the test (SC-011).
- [X] T052 [P] [US5] Write `open_external` tests (**U**) in `apps/desktop/src-tauri/src/commands.rs` (test module): `http` and `https` links the current generation displayed are opened; any other scheme, or a URL not displayed, is refused.
- [X] T053 [P] [US5] Write inert-display tests (**W**) in `apps/desktop/test/inert.test.tsx`. With `<script>`, `<img onerror>`, `javascript:` links, `\x1b[2J`, `\x1b[H`, an OSC title sequence, `[Connected]` and `[Ready]` in messages, tool output, file names, model names and errors:
  - all render as text;
  - control characters appear as visible symbols;
  - no script runs, no navigation happens, and the status strip is unchanged (FR-029, SC-010).
- [X] T054 [US5] Write the scenario `canary-early` (**S**, all platforms) in `apps/desktop/e2e/scenarios/canary-early.ts`. The Core home has a unique `api_key`; the ready, conversation and adversarial flows run; then each of these has zero occurrences of the canary (SC-009, early part):
  - every recorded inbound IPC message of every kind;
  - every bridge command's arguments and return value;
  - local storage, session storage, IndexedDB and the document text;
  - the Core's recorded arguments;
  - the application log, the preferences file, and the diagnostic tail.
- [X] T055 [US5] Write the scenario `boundary` (**S**, all platforms) in `apps/desktop/e2e/scenarios/boundary.ts`:
  - a plugin command from the page is refused;
  - `window.location` navigation and `window.open` are refused;
  - the `adversarial` scenario renders inertly in the real WebView (SC-010, SC-011).

### Implementation for User Story 5

- [X] T056 [P] [US5] Implement inert rendering in `apps/desktop/src/text.ts`, used by every view that shows outside text. T053 must pass.
- [X] T057 [P] [US5] Implement `open_external` in `apps/desktop/src-tauri/src/commands.rs`. T052 must pass.
- [X] T058 [US5] Implement the navigation and new-window refusals in `apps/desktop/src-tauri/src/main.rs`, and the log writer in `apps/desktop/src-tauri/src/logfile.rs` (no credential, environment or session content). T051, T054 and T055 must pass.

**Checkpoint**: all P1 stories pass on three platforms. T084–T086 later
extend the boundary checks to every command and flow.

---

## Phase 6: User Story 3 — Survive a Core failure or a window reload (Priority: P2)

**Goal**: A crash restarts the Core under OD-1, counting only conservatively
completed turns as resets, and reopens the conversation. An interrupted turn
is shown as interrupted and never re-sent. A reload rebuilds exactly. The
workspace is kept.

**Independent Test**: A kill between turns and during a held turn; a reload
during a held stream; the sequenced crash and reset sequences; uncertain
turns that do not reset (SC-003–SC-006).

**Covers**: FR-004, FR-005, FR-011, FR-016, FR-021 (workspace kept);
SC-003–SC-006, SC-017 (within a launch).

### Tests for User Story 3 ⚠️

- [X] T059 [P] [US3] Write restart-policy and completion tests (**U**) in `apps/desktop/src-tauri/src/restart.rs`, per [data-model.md](./data-model.md) §3, with synthetic relayed events.
  - **Crash count**: crashes 1 and 2 restart; crash 3 does not and waits for "Try again".
  - **Completed**: a `session.send` result with `turn_id`, then `message.completed` all `completed`, then `busy: false`, with no `warning` or `error` notification and no `session.cancel` — resets to 0.
  - **Uncertain — no reset**: each of these leaves the count unchanged:
    - a `cancelled` or `failed` message;
    - a `warning` notification with no message change, which is cancel between messages and the clarification stop;
    - an `error` notification, which is a failure between messages;
    - a relayed `session.cancel`;
    - zero `message.completed`;
    - a turn whose `session.send` the relay did not see;
    - a crash before `busy: false`.
  - "Try again" and time do not reset.
  - A failure before `ready` is never restarted.

  Mutation checks: treating the clarification stop as completed fails a test, and so does resetting on "Try again" (FR-005, SC-006).
- [X] T060 [P] [US3] Write reconnect tests (**U**) in `apps/desktop/src-tauri/src/relay.rs` (test module): a Core restart sends `closed` and empties `in_flight`; the next `connect` gets a new generation; the cached handshake is the new Core's.
- [X] T061 [US3] Write recovery integration tests (**I**, all platforms) in `apps/desktop/src-tauri/tests/recovery.rs`:
  - kill a ready Core between turns: it restarts in the same workspace, and `session.open(<stored id>)` returns the persisted transcript within 10 s (SC-003, time recorded);
  - kill during `hold-mid-turn`: the turn is not persisted, and nothing is re-sent (SC-004);
  - with the `sequenced` double, each launch is ended by its own crash (`crash-on-send`, when the test sends) or, for `complete-turn` and `scripted:<scenario>` launches, by the test killing the Core after that launch's turn has ended. Expected counts per launch:
    - `[crash-on-send, crash-on-send, crash-on-send]`: counts 1, 2, 3; no automatic restart after launch 3, and "Try again" is required;
    - `[crash-on-send, complete-turn, crash-on-send, crash-on-send]`: launch 1 → 1; launch 2's turn completes → 0, then the kill → 1; launch 3 → 2; launch 4 → 3, and it stops;
    - `[crash-on-send, scripted:<s>, crash-on-send]` for each `<s>` in `cancel-between-messages`, `cancel-mid-message`, `fail-between-messages`, `fail-mid-message` and `clarification-stop`: launch 1 → 1; launch 2's uncertain turn does not reset, and the kill → 2; launch 3 → 3, and it stops (SC-006);
  - the relay log shows no `session.send` the test did not issue.
- [X] T062 [P] [US3] Write recovery tests (**W**) in `apps/desktop/test/recovery.test.tsx`:
  - after `closed` and `ready`, the page reconnects with a new `CoreClient` and calls `session.open(stored_id)`;
  - a refusal (nothing stored) leads to `session.create` and a notice;
  - `unsent_turn` is shown as interrupted and not saved, and nothing is re-sent;
  - delegates are summarised in one line, including `lost`;
  - the stop at the limit shows the count and "Try again".
- [X] T063 [US3] Write the scenario `reload` (**S**, all platforms) in `apps/desktop/e2e/scenarios/reload.ts`:
  - during `hold-mid-turn`, reload the page, then release the hold;
  - the rebuilt conversation equals a bridge `session.snapshot`, with no duplicate and no missing message (SC-005);
  - no chooser appears and the workspace is unchanged (SC-017).
- [X] T064 [US3] Write the scenario `crash` (**S**, all platforms) in `apps/desktop/e2e/scenarios/crash.ts`, with the `sequenced` double and the harness's pid kill:
  - a kill between turns: the transcript is back within 10 s;
  - a kill during `hold-mid-turn`: the interrupted notice appears and nothing is re-sent;
  - three consecutive crashes require "Try again";
  - the workspace is kept and no chooser appears (SC-003, SC-004, SC-006, SC-017).

### Implementation for User Story 3

- [X] T065 [US3] Implement `RestartPolicy` and `TurnObservation` in `apps/desktop/src-tauri/src/restart.rs`. Add the read-only observation of the fields listed in native-bridge guarantee 2 in `apps/desktop/src-tauri/src/relay.rs`, changing nothing. Integrate in `apps/desktop/src-tauri/src/supervisor.rs`. T059 must pass.
- [X] T066 [US3] Implement restart and reconnect in `apps/desktop/src-tauri/src/supervisor.rs` and `apps/desktop/src-tauri/src/relay.rs`: `closed` to the page, a new handshake, the same workspace, a new generation, and `restart_count` in `status`. T060 and T061 must pass.
- [X] T067 [US3] Implement page recovery and reload rejoin in `apps/desktop/src/state.ts` and `apps/desktop/src/view/Conversation.tsx`. T062 must pass.
- [X] T068 [US3] Run the `desktop` job of `.github/workflows/ci.yml` by `workflow_dispatch`. T061, T063 and T064 must pass on all three platforms. Keep the results and the SC-003 times for the PR description.

**Checkpoint**: recovery is correct and honest, and US1, US2 and US5 still pass.

---

## Phase 7: User Story 4 — Close cleanly, leave nothing behind (Priority: P2)

**Goal**: Closing or quitting gives the Core 10 seconds, with "Closing…" and
"Quit now" (OD-2). A forced stop terminates the owned Core and its children,
and is reported honestly. No Core outlives the application. A second launch
focuses the window, and switches workspace only after confirmation.

**Independent Test**: A normal close, a quit during a held turn, a
non-cooperating Core, "Quit now", an abrupt kill, and second launches with
the same and a different path — on each platform (SC-007, SC-008, SC-016).

**Covers**: FR-017, FR-018, FR-019; SC-007, SC-008, SC-016.

### Tests for User Story 4 ⚠️

- [X] T069 [P] [US4] Write shutdown-sequence tests (**U**) in `apps/desktop/src-tauri/src/shutdown.rs`, with an injected clock:
  - the order is `shutdown`, then stdin closed, then wait for exit;
  - the forced stop happens at exactly 10 s and not before, or immediately on `quit_now`;
  - `outcome` is `orderly` or `forced`;
  - a forced outcome logs "stopped before it finished", and also reports it in the window for `workspace_change` and `check_again`;
  - no forced path produces text containing "saved".

  Mutation checks: a 5 s deadline fails a test, and so does a "saved" string on a forced path (FR-017, SC-016).
- [X] T070 [P] [US4] Write platform orphan tests (**I**) in `apps/desktop/src-tauri/tests/orphans.rs`, each behind its platform check:
  - **Windows**: dropping the job handle ends the Core and the `ignore-stop` child.
  - **Linux**: the parent-death signal ends the Core when the supervisor's process ends.
  - **Linux and macOS**: a forced stop signals the process group, ending the double and its child.
  - **macOS**: closing stdin ends the real Core by EOF.
- [X] T071 [US4] Write shutdown integration tests (**I**, all platforms) in `apps/desktop/src-tauri/tests/shutdown.rs`:
  - the scripted Core stopped during `hold-mid-turn` exits within the bound, `orderly`, with no termination;
  - `ignore-stop` is terminated at the deadline with its child, and `forced` is logged;
  - `quit_now` terminates immediately.
- [X] T072 [P] [US4] Write closing tests (**W**) in `apps/desktop/test/closing.test.tsx`:
  - `stopping` shows "Closing…" with the seconds remaining, and "Quit now" calls `quit_now`;
  - `stop_outcome: forced` shows "Comodor was stopped before it finished; work it had not saved may be lost", with no "saved" text.
- [X] T073 [P] [US4] Write second-launch decision tests (**U**) in `apps/desktop/src-tauri/src/instance.rs`:
  - no path, or the current path: focus only;
  - a different valid path: ask through the confirmation adapter;
  - confirmed: the stop sequence with reason `workspace_change`, then a Core in the new path;
  - declined or unanswered: keep the current workspace and Core;
  - never a second Core (FR-019, SC-008).
- [X] T074 [US4] Write the lifetime harness and cases (**L**, all platforms) in `apps/desktop/e2e/lifetime.mjs`. It learns the Core's pid from the test build and waits for process exit with a failure deadline, not a delay. Cases:
  - a normal close, a quit during `hold-mid-turn`, "Quit now", and an abrupt kill of the application — after each, zero Core processes remain (SC-007, SC-016);
  - a second launch: one window and one Core;
  - a second launch with a different path, declined through the confirmation double: workspace kept;
  - the same, confirmed: switched after an orderly stop (SC-008).

  Add `npm run -w apps/desktop lifetime` to the `desktop` job in `.github/workflows/ci.yml`.

### Implementation for User Story 4

- [X] T075 [US4] Implement the stop sequence in `apps/desktop/src-tauri/src/shutdown.rs`, integrated in `apps/desktop/src-tauri/src/supervisor.rs`:
  - reasons `window_closed`, `quit`, `workspace_change`, `check_again` and `os_session_end`;
  - a grace of 10 s from the injected clock;
  - `outcome` recorded, the log line written, and `closing` and `stop_outcome` in `status`.

  T069 and T071 must pass.
- [X] T076 [US4] Implement the orphan guarantees in `apps/desktop/src-tauri/src/platform/windows.rs` (a job object that kills on close), `apps/desktop/src-tauri/src/platform/linux.rs` (a parent-death signal in `pre_exec`) and `apps/desktop/src-tauri/src/platform/unix.rs` (a process-group leader, and a group signal on forced stop). T070 must pass.
- [X] T077 [US4] Hold the close request until the stop sequence ends, show "Closing…", and implement `quit_now` in `apps/desktop/src-tauri/src/main.rs` and `apps/desktop/src-tauri/src/commands.rs`. Implement `apps/desktop/src/view/ClosingView.tsx`. T072 must pass.
- [X] T078 [US4] Implement single-instance handling and the second-launch confirmation in `apps/desktop/src-tauri/src/instance.rs` and `apps/desktop/src-tauri/src/main.rs`:
  - `tauri-plugin-single-instance` and a native confirmation dialog through `tauri-plugin-dialog`, both used from Rust only;
  - the `e2e` double replaces the dialog.

  T073 must pass.
- [X] T079 [US4] Run the `desktop` job of `.github/workflows/ci.yml` by `workflow_dispatch`. T070, T071 and T074 must pass on all three platforms. Keep the results for the PR description.

**Checkpoint**: nothing is left behind, no forced stop is reported as saved,
and second launches behave as specified, on every platform.

---

## Phase 8: User Story 6 — Start with a provider that is not configured (Priority: P3)

**Goal**: The window shows the unconfigured state and the `comodor setup`
direction, and cannot send. "Check again" restarts the Core and shows the
configured state with no application restart.

**Independent Test**: Launch with an unconfigured home, fix the config, use
"Check again" (SC-015).

**Covers**: FR-031; SC-015.

### Tests for User Story 6 ⚠️

- [X] T080 [P] [US6] Write `check_again` tests (**U**) in `apps/desktop/src-tauri/src/commands.rs` (test module):
  - refused in `starting`, `handshaking` and `stopping`;
  - otherwise the stop sequence with reason `check_again` (10 s grace), then a Core in the same workspace.
- [X] T081 [P] [US6] Write unconfigured tests (**W**) in `apps/desktop/test/unconfigured.test.tsx`:
  - `configured: false` shows the direction to run `comodor setup` in a terminal;
  - send is unavailable;
  - "Check again" calls `check_again`;
  - after a configured `model.get`, send is available.
- [X] T082 [US6] Write the scenario `unconfigured` (**S**, all platforms) in `apps/desktop/e2e/scenarios/unconfigured.ts`: the unconfigured state is shown and send is refused; the harness writes the offline provider into the home; "Check again" then shows it configured, with no application restart (SC-015).

### Implementation for User Story 6

- [X] T083 [US6] Implement `check_again` in `apps/desktop/src-tauri/src/commands.rs`, using T075's stop sequence, and `apps/desktop/src/view/SetupNotice.tsx`, with the composer gated on the reported `configured`. T080, T081 and T082 must pass.

**Checkpoint**: all six stories pass on three platforms, and every command exists.

---

## Phase 9: Final Boundary Assertions, Documentation and Delivery

**Purpose**: Assertions that need every command and every flow, then docs,
then delivery on one exact SHA.
- T084–T089 are committed work.
- T090 is the last repository commit before the final validation round.
  After it, a new commit is made only to fix a valid Codex finding, a failing
  local gate, or a failing CI check. Every such commit reruns T092–T098 —
  final validation, three-platform CI and a fresh Codex review — on the new
  exact head SHA.
- T091–T099 are recorded in the PR description and the owner report, and
  stay unchecked in the tree by design.

- [X] T084 Write the final command-list test (**U**) in `apps/desktop/src-tauri/src/commands.rs` (test module), run without the `e2e` feature:
  - the constant equals exactly `connect`, `send_line`, `status`, `diagnostics`, `choose_workspace`, `retry`, `check_again`, `quit_now` and `open_external`;
  - every name has a registered handler.

  Mutation check: removing or adding a command fails the test (FR-030, SC-011).
- [X] T085 Write the release-manifest check in `apps/desktop/e2e/release-manifest.mjs`, and add it as a step of the `desktop` job in `.github/workflows/ci.yml`.
  1. Build the **release configuration** (`tauri build --no-bundle`, no features, no `--config` override) and copy `apps/desktop/src-tauri/gen/schemas/acl-manifests.json` and `apps/desktop/src-tauri/gen/schemas/capabilities.json` aside.
  2. Assert from those copies:
     - the `__app-acl__` manifest holds exactly one allow/deny pair for each of the nine commands of `COMMANDS`, and nothing for `e2e_report`;
     - the resolved capabilities are exactly `main`, for window `main`;
     - `main`'s permissions are exactly the nine allow identifiers plus the `core:` minimum recorded in T003(e);
     - no plugin permission appears.

     Identifiers are read from the generated files and matched by command name, never hard-coded.
  3. Build the `e2e` configuration (`--features e2e --config src-tauri/tauri.e2e.conf.json`) into a separate target directory, and assert its app manifest and capabilities differ from the release copies only by `e2e_report`'s pair and the `e2e-test` capability that grants its allow identifier.
  4. A mutation check: adding `"e2e_report"` to `capabilities/main.json` in a scratch copy makes step 2 fail (FR-030, SC-011).
- [X] T086 Write the scenario `canary-full` (**S**, all platforms) in `apps/desktop/e2e/scenarios/canary-full.ts`. Run every flow with a unique `api_key`:
  - ready, conversation, adversarial;
  - reload during `hold-mid-turn`;
  - a crash and restart through `sequenced`;
  - "Check again" from an unconfigured home;
  - "Closing…" with a forced stop;
  - a second launch.

  Then assert zero canary occurrences in every channel listed in T054 (FR-028, FR-032, SC-009).
- [X] T087 [P] Update `docs/desktop-architecture.md` from "planned, not built" to what D1 delivers: supervision, the relay and its read-only observation, the bridge commands, OD-1–OD-3, the test layers, and what remains for D2–D6.
- [X] T088 [P] Update the Desktop row meaning in `docs/surface-parity.md` to name both the desktop application (`apps/desktop`) and the computer-control backend (`src/comodor/desktop/`). Run `pytest tests/test_surface_impact_contract.py`; it pins row names only, so no test change is expected.
- [X] T089 [P] Add a "Desktop from source" section to `README.md` and `apps/desktop/README.md`. Cover:
  - prerequisites per platform;
  - `COMODOR_BIN` and `COMODOR_ARGS` (a path with spaces goes in `COMODOR_BIN`, plan K8);
  - that D1 is not packaged.
- [X] T090 Mark `[X]` in `specs/003-desktop-foundation/tasks.md` each of T001–T089 whose evidence exists from the development runs, leaving any without evidence open. Commit with a neutral message and no attribution. From here, a commit is made only to fix a valid Codex finding (T098), a failing local gate (T092–T096) or a failing CI check (T097). Each fix commit changes code, tests or docs only — never evidence — and sends the work back to T092 on the new exact head SHA.
- [X] T100 [US3] After the machine sleeps (spec: Machine sleep and wake; review thread on `d996b86`):
  - `apps/desktop/src-tauri/src/wake.rs` reads sleep from two platform clocks (one runs while the machine sleeps, one does not) and reports each sleep of 1 s or more once; looked for every second and before every line the page sends (`Desktop::send_line`);
  - `apps/desktop/src-tauri/src/supervisor.rs` moves a `ready` Core to `checking` on a wake, sends it a native `session.list`, refuses the page's lines until any answer, and treats an exit, a bad line, or no answer within `CHECK_GRACE` (10 s) as from `ready` (crash, OD-1);
  - the window keeps the conversation during `checking`, offers no Send, and reads the session again once `ready` (`apps/desktop/src/state.ts`, `app.tsx`, `view/SessionView.tsx`, `view/StatusStrip.tsx`).

  Tests written first, each failing on the previous behaviour: the machine tests in `supervisor.rs`, `wake.rs`'s own tests (including this platform's clocks, run on all three), `apps/desktop/src-tauri/tests/wake.rs` (the real Core answers; a Core that never answers is restarted; a line sent before the wake was noticed is held back), `apps/desktop/test/wake.test.tsx`, and the scenario `wake` (S, all platforms; the harness checks `checking`, then `ready`, then a fresh `session.snapshot`, in the run's record). Mutation-checked.
- [X] T101 [US5] `open_external` opens a link only after the person says yes to exactly that URL in a native dialog (review thread on `d996b86`): `ConfirmLink` and `open_link` in `apps/desktop/src-tauri/src/commands.rs`; one confirmation at a time; the test build records instead of opening a browser. Tests written first in `commands.rs`: refusal, confirmation, every call asked again, a URL only in a field never shown as a link, an older generation's link refused without asking. Mutation-checked.
- [ ] T091 Push `003-desktop-foundation` normally (never forced) and open one PR against `main`, as the owner's stated D1 workflow authorizes. First confirm the identity: `gh auth status` and `gh api user --jq .login` must show `ifekri`. The PR body, from `.github/PULL_REQUEST_TEMPLATE.md`, has:
  - a neutral description with no tool or model attribution;
  - the Surface Impact table with the ten canonical rows and statuses from [plan.md](./plan.md) §Surface Impact, each with evidence;
  - OD-1–OD-3;
  - the out-of-scope list, including the TUI shutdown observation.
- [ ] T092 On the PR's exact head SHA, run the boundary audit, with `BASE=$(git merge-base origin/main HEAD)`, and record the outputs in the PR description:
  - `git diff "$BASE" HEAD -- src schemas packages tests apps/tui` prints nothing (FR-025, FR-026);
  - no import of `comodor.desktop`, `src/comodor/desktop` or `src/comodor/web` from `apps/desktop` (FR-027);
  - `apps/desktop/package.json` depends on the seven shared packages (FR-023).
- [ ] T093 On the same SHA, in a clean detached worktree with a fresh virtual environment, run the existing gates of [quickstart.md](./quickstart.md) §2 and record the counts against the merge base in the PR description (SC-012, FR-025):
  - `python -m ruff check src tests tools`;
  - `python -m pytest -q` and `python -m pytest -m performance -n 0 -q`;
  - `python tools/protocol-codegen.py --check` and `python tools/capability-map.py --check`;
  - `npm ci`, then `npm run lint`, `npm run typecheck`, `npm test` and `npm run build`;
  - `bun test apps/tui/test/bun/renderer.test.tsx` and `bun test apps/tui/test/bun/orphan.test.ts`;
  - `bun tools/build-tui-distribution.ts` with an empty `git status --porcelain`;
  - `python tools/check-wheel-contents.py` on a built wheel;
  - `git diff --check`.
- [ ] T094 On the same SHA, the `desktop` job in `.github/workflows/ci.yml` runs every layer (U, I, W, S, L and the release manifest) on Windows, Linux and macOS. Record per platform in the PR description:
  - every scenario's result;
  - the SC-001 and SC-003 times;
  - the canary results.

  A layer or platform without a passing result is NOT VERIFIED, and D1 is then incomplete (FR-033).
- [ ] T095 Record real-folder-chooser evidence on Windows, Linux and macOS for the same build ([quickstart.md](./quickstart.md) §7): on two consecutive fresh launches, the folder the OS dialog opened at, read from the dialog itself, equals the folder the application passed; the screenshots are kept as supporting evidence. A platform where it could not be read is reported as such, not as observed. Attach it to the PR description. Missing evidence on any platform leaves SC-017, and D1, incomplete.
- [ ] T096 Record the offline evidence in the PR description (FR-034, SC-013):
  - the `desktop` job reads no secret;
  - every fixture config under `apps/desktop/src-tauri/tests/` uses `base_url: "offline"`;
  - no test configures a real provider;
  - the `grep` output.
- [ ] T097 On the exact head SHA, require every check of `.github/workflows/ci.yml` and `.github/workflows/surface-contract.yml` to pass, including the three-platform `desktop` job. Re-run a flaky job once and report it in the PR description; never hide it. A check that still fails is fixed by a new commit (see T090), and T092–T098 then repeat on the new head.
- [ ] T098 Request a fresh Codex review of that exact SHA. Classify every finding with evidence. Fix each valid one in its owning file under `apps/desktop/`, or the doc it names, with a test where it guards behaviour. Reply with evidence and resolve only addressed threads. After any fix commit, whether for a review finding, a local gate or a CI check:
  - repeat T092–T097 on the new SHA, updating the PR description, never the tree, for evidence;
  - request a fresh review.

  Repeat until a review of the exact final SHA has no unaddressed finding and CI is green on it.
- [ ] T099 Report to the owner, from the PR description built from `.github/PULL_REQUEST_TEMPLATE.md`: the final SHA, every gate, per-platform evidence, the Codex review history, remaining risks (plan K1–K11) and the PR state. Call D1 **ready for owner review** only if every FR and SC has passing evidence on all three platforms, including T095. Otherwise call D1 **incomplete** and list each gap. Leave the PR open: no merge, no auto-merge, no approval, and no branch deletion.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup**: none.
- **Foundational**: needs Setup; blocks every story.
- **US1**: needs Foundational. It is the MVP.
- **US2**: needs US1.
- **US5**: needs US2.
- **US3**: needs US2.
- **US4**: needs US2 — its mid-turn shutdown tests (T071, T074) need the relay and `send_line`. It can follow US3, or interleave, but T065–T066 and T075 both edit `supervisor.rs`, so sequence them.
- **US6**: needs US4 (T075's stop sequence).
- **Phase 9**:
  - T084–T086 need US6 (every command and flow);
  - T087–T089 can run any time after US6;
  - T090 needs T084–T089;
  - T091–T099 run strictly in order after T090.
  - any fix commit after T090 — for a Codex finding, a local gate or a CI check — loops back to T092 on the new exact head.

### Within Each Story

Tests first, failing; then native modules; then window views; then the
story's three-platform `workflow_dispatch` run.

### Parallel Opportunities

- Setup: T003–T006 after T001.
- Foundational: T007–T009 together; T012 and T014 alongside T010 and T011.
- US1: T018–T024 and T026 together; T029–T031 together.
- US2: T040–T042 together; T047–T049 after T046.
- US5: T051–T053 together; T056 and T057 together.
- US3 and US4 test writing together: T059, T060 and T062 alongside T069, T070, T072 and T073.
- Phase 9: T087–T089 together.

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
T018 locate.rs   T020 supervisor.rs states   T021 diag.rs
T022 prefs.rs    T023 workspace.rs           T026 status.test.tsx
# Then implementations in parallel:
T029 locate.rs   T030 diag.rs   T031 prefs.rs
```

## Implementation Strategy

1. **MVP**: Setup, Foundational, US1 — a window that owns a Core and shows
   ready, or a named failure, on three platforms.
2. US2, then US5 (early boundary): P1 complete — the first point the
   application is usable by a person.
3. US3 and US4 (P2), then US6 (P3).
4. Phase 9: final boundary assertions, docs, one commit (T090), then delivery
   and review on one exact SHA, with all evidence in the PR.

## Requirement Coverage

| Requirement | Tasks |
| --- | --- |
| FR-001 | T010, T011, T025, T033, T074 |
| FR-002 | T018, T029, T025 |
| FR-003 | T010, T019, T033, T054, T086 |
| FR-004 | T020, T061, T066 |
| FR-005 (OD-1) | T008, T009, T059, T061, T064, T065 |
| FR-006 | T021, T025, T030 |
| FR-007 | T020, T025, T034 |
| FR-008 | T013, T038, T044 |
| FR-009 | T024, T025, T034 |
| FR-010 | T015, T027 |
| FR-011 | T060, T063, T067 |
| FR-012 | T040, T067 |
| FR-013 | T039–T043, T046–T049 |
| FR-014 | T042, T046 |
| FR-015 | T039, T041, T048 |
| FR-016 | T061, T062, T064, T067 |
| FR-017 (OD-2) | T069, T071, T072, T075, T077 |
| FR-018 | T070, T074, T076 |
| FR-019 | T073, T074, T078 |
| FR-020 | T026, T036 |
| FR-021 (OD-3) | T023, T028, T032, T063, T064, T073, T095 |
| FR-022 | T023, T025, T032 |
| FR-023 | T001, T092 |
| FR-024 | T042, T092 |
| FR-025 | T092, T093 |
| FR-026 | T092, T093 |
| FR-027 | T092, T093 |
| FR-028 | T054, T058, T086 |
| FR-029 | T053, T055, T056 |
| FR-030 | T051, T052, T055, T057, T084, T085 |
| FR-031 | T080–T083 |
| FR-032 | T022, T054, T058, T086 |
| FR-033 | T017, T037, T050, T068, T079, T094, T095, T099 |
| FR-034 | T007–T009, T096 |
| FR-035 | T005, T008, T015, T016, T074 |
| SC-001 | T027, T037, T094 |
| SC-002 | T020, T025, T026 |
| SC-003 | T061, T064, T068 |
| SC-004 | T061, T062, T064 |
| SC-005 | T063 |
| SC-006 (OD-1) | T059, T061, T064 |
| SC-007 | T070, T074, T079 |
| SC-008 | T073, T074, T078 |
| SC-009 | T054, T086 |
| SC-010 | T053, T055 |
| SC-011 | T051, T055, T084, T085 |
| SC-012 | T093 |
| SC-013 | T096 |
| SC-014 | T039, T043 |
| SC-015 | T081, T082 |
| SC-016 (OD-2) | T069, T071, T072, T074 |
| SC-017 (OD-3) | T023, T028, T063, T064, T095 |
