# Implementation Plan: Desktop Foundation (D1)

**Branch**: `003-desktop-foundation` | **Date**: 2026-09-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-desktop-foundation/spec.md`

## Summary

D1 adds a second client of the Comodor Core: a Tauri 2 desktop application
in `apps/desktop/`. Its native side starts one `comodor core --stdio` per
window in the chosen workspace, performs the protocol v2 handshake, supervises
the process (classified failures, bounded automatic restart, orderly and
forced stop, no orphans on any platform), and relays protocol lines to the
window over in-process IPC. No network listener is involved.

The window runs the **unchanged** `@comodor/client` `CoreClient` over a bridge
`Transport`, and renders one session with the unchanged `@comodor/session`,
`@comodor/questions`, `@comodor/modes`, `@comodor/commands` and
`@comodor/design-tokens`. The Core, the protocol schema and the Python package
are not changed.

The two owner decisions stand:
- one usable session: prompt, stream, tool activity, cancel, mode, questions
  and permissions;
- `comodor setup` in a terminal when no provider is configured, with "Check
  again" restarting the Core.

Three further owner decisions (2026-09-30) replace the spec's earlier model
defaults:
- **OD-1**: automatic restart stops after the third consecutive crash of a
  ready Core without a completed turn; only a completed turn resets the count.
- **OD-2**: a 10-second shutdown grace with "Closing…" and "Quit now", and an
  honest report after a forced stop.
- **OD-3**: an explicit workspace choice on every fresh launch, with an
  explicit command-line path taking precedence and the workspace kept for the
  whole launch.

## Technical Context

**Language/Version**: Rust (stable, pinned by `rust-toolchain.toml`) for the
native side; TypeScript 5.9 and React for the window. Python ≥ 3.11 (existing
Core, unchanged).

**Primary Dependencies**:
- Tauri 2, with the single-instance and dialog plugins used from Rust only;
- serde and serde_json;
- platform crates for Windows job objects and the Linux parent-death signal;
- React and React DOM, the Tauri JS API, a bundler (Vite) and its React
  plugin, and the Tauri CLI;
- a DOM test environment, for development only.

All are confined to `apps/desktop/` and pinned exactly
([research.md](./research.md) R15).

**Storage**: one JSON preferences file per user in the application's
configuration directory ([data-model.md](./data-model.md) §5). Session
storage stays the Core's.

**Testing**:
- `cargo test`: native unit and integration tests, including a real Core
  process and a scripted Core fixture;
- the desktop workspace's DOM tests of the window over an in-memory
  `Transport`;
- in-application scenarios in a test build;
- process-lifetime tests driven from outside.

All offline ([research.md](./research.md) R14).

**Target Platform**: Windows 10/11 (WebView2), Linux (WebKitGTK 4.1), macOS
(WKWebView), each built and tested in CI.

**Project Type**: desktop application (native shell and web frontend) as a
client of an existing local server process.

**Performance Goals**: ready window within 10 s of launch (SC-001); recovery
from a Core crash within 10 s (SC-003). Both are measured in the scenario
runs; neither is achieved with sleeps.

**Constraints**:
- no network listener (FR-010);
- no credential reachable by the window (FR-028);
- no change to the Core, protocol or shared-package behaviour (FR-025,
  FR-026);
- deterministic tests (FR-035);
- no provider calls (FR-034).

**Scale/Scope**: one window, one Core, one session per window.

## Constitution Check (before research)

*Against constitution 2.0.0.*

| Principle | Assessment |
| --- | --- |
| I Backward compatibility | **PASS** — no existing surface changes; D1 is additive (a new `apps/desktop`). |
| II Three platforms | **PASS, with conditions** — every desktop gate runs on Windows, Linux and macOS; each platform difference (job object, parent-death signal, process group) sits behind an explicit platform check (FR-033). |
| III Fix the invariant | **PASS** — the design uses observable states. The only time bound is the 10-second shutdown grace (OD-2), a product bound tested with an injected clock, not a synchronisation; the restart policy counts events (OD-1). |
| IV Deterministic tests | **PASS** — layers of R14; every guard gets a mutation-sensitive test (relay generation drop, method allowlist, command list, restart limit, forced stop, canary). |
| V Narrow scope | **PASS** — D2–D6, bundling, remote Core, terminal attach, credential entry and history browsing are excluded; one observed defect in `spawnCore` is recorded, not fixed (R6). |
| VI Boundaries | **PASS** — policy stays in the Core; the relay owns lifecycle only; no schema or generated-file change. |
| VII Reproducible artifacts | **PASS** — D1 commits no build output; the TUI bundle check stays in the gates. |
| VIII Security | **PASS, central** — see R9, R10 and the native-bridge contract. |
| IX Release infrastructure | **PASS** — no release, bundling or publishing. The CI workflow gains a desktop job: an audited change with deterministic steps. |
| X Quality gates | **PASS** — existing gates unchanged; desktop gates added; results recorded against the exact commit. |
| XI Surfaces named | **PASS** — the spec's table, refined below. |
| XII Everything agrees | **PASS** — `docs/desktop-architecture.md` and `docs/surface-parity.md` are updated in D1's docs task. |
| XIII–XIX Agent behaviour | **NOT AFFECTED** — no change to what the agent does or what is sent to a model. The context-change gate does not apply. |
| XX User control | **PASS** — nothing consequential is triggered by the desktop without the person's action; no merge, release or deploy. |
| XXI Acceptance | **PASS** — acceptance is deterministic and offline. |

No violation to justify. **Gate: PASS** — proceed to research.

## Design Overview

```text
┌──────────── Desktop application (apps/desktop) ────────────┐
│ Window content (React/TS)             Native side (Rust)   │
│  CoreClient  ◀─ bridge Transport ─▶  Relay ◀─▶ Supervisor ─┼─ stdin/stdout ─▶ comodor core --stdio
│  @comodor/session reducer            (ids, generations,    │   (the unchanged Core)
│  @comodor/questions, modes,           method allowlist,    │  stderr ─▶ DiagnosticTail
│  commands, design-tokens              cached handshake)    │
│                                      Preferences file      │
└────────────────────────────────────────────────────────────┘
```

- **Supervisor** ([core-supervision.md](./contracts/core-supervision.md),
  [data-model.md](./data-model.md) §1): locate, start, handshake, classify,
  restart, stop, and prevent orphans.
- **Relay** ([native-bridge.md](./contracts/native-bridge.md)): per-page
  generations, id rewriting, a local hello, and a refusal list.
- **Window**: one screen with
  - a status strip (Core state, workspace, provider, model, configured);
  - the conversation (messages, tool activity lines, an interrupted-turn
    notice, a delegate summary line);
  - the pending form or permission card;
  - the composer with send, cancel and the mode control;
  - a failure view with diagnostics, "Try again" and "Check again".

## Reuse Boundaries

| Shared piece | Used for | Changed? |
| --- | --- | --- |
| `@comodor/protocol` | envelopes, method and event lists, `PROTOCOL_VERSION`, types | No |
| `@comodor/client` (`CoreClient`, `Transport`) | the page's connection, over the bridge `Transport` | No — `spawn.ts` is not used; the native side starts the Core |
| `@comodor/session` | the session projection, snapshot reconciliation, the interaction queue, streaming, follow policy, mode intent | No |
| `@comodor/questions` | form selection state | No |
| `@comodor/modes` | the mode cycle, labels and summaries | No |
| `@comodor/commands` | send, cancel, mode next and retry as commands reachable from button and keyboard | No |
| `@comodor/design-tokens` | `cssVariables()` for every colour; the lint rule forbids colour literals in `apps/` | No |
| `comodor core --stdio` | the Core | No |
| TUI discovery variables `COMODOR_BIN` and `COMODOR_ARGS` | Core discovery | No — the same meaning |

If implementation finds a shared package unusable as is (for example, an
unexpected runtime import), the change must be additive and pass the TUI
renderer suite (FR-025). An unavoidable Core or schema change stops D1 and is
specified separately (FR-026).

**Not reused, deliberately**: the browser interface (`src/comodor/web/`),
which has its own server and agent assembly; the computer-control backend
(`src/comodor/desktop/`), which the application never imports (FR-027); and
the TUI's in-file `FakeCore` test double. The desktop tests keep their own
double, and extracting a shared test helper is a later, separate change.

## Requirement-to-Evidence Map

Test layers: **U** native unit, **I** native integration with a real or
scripted Core, **W** window logic (DOM), **S** in-application scenario (test
build), **L** process lifetime, **G** existing repository gates, **D**
documentation and code review. All run on Windows, Linux and macOS unless
noted.

| Requirement | Design | Evidence |
| --- | --- | --- |
| FR-001 own and supervise one Core | Supervisor | I: start, stop, one Core per window; L |
| FR-002 discovery order, report tried | core-supervision §1 | U: order and message; I: `not_found` |
| FR-003 no credential in args or env | core-supervision §2 | U: the constructed command; S: canary absent from the Core's arguments (the test build records them) |
| FR-004 detect exit | Supervisor | I: kill between and during turns |
| FR-005 bounded restart (OD-1) | RestartPolicy and TurnObservation (data-model §3) | U: crashes 1 and 2 restart, 3 does not; the conservative completion rule — only a completed turn resets; cancel and failure between and within messages, a clarification stop, warning or error notices, Core-started turns, and "Try again" do not; I: the sequenced double — crash, completed turn, crash — across real restarts, and the scripted Core's uncertain outcomes |
| FR-006 diagnostic tail | DiagnosticTail | U: the bounds; I: a Core writing past them never blocks |
| FR-007 bad stdout line is a fault | Relay and Supervisor | I: a `protocol_fault` double |
| FR-008 protocol only | Relay forwards envelopes only | U: a non-request line refused; D: no import of Core internals |
| FR-009 handshake, version refusal | core-supervision §3 | I: a mismatch double names both versions |
| FR-010 no listener | R2, R14 | S: the test build reports the application process's TCP listening and bound UDP sockets per platform (R14); the set is empty; D |
| FR-011 reload reconnect | Generations and R13 | U: a stale-generation answer dropped; S: reload during streaming (SC-005) |
| FR-012 gap repair, duplicates | the `@comodor/session` reducer | W: a gap triggers a snapshot; a duplicate is ignored |
| FR-013 one session | the Window | W and S: prompt, stream, tools, cancel, mode, form, permission |
| FR-014 derived from the Core | reducer only; no optimistic state | W: the mode label unchanged until `mode.changed`; a refusal keeps the old mode |
| FR-015 answer only the person's choice | the form and permission card | W: every option shown; nothing sent without a click; I: the scripted Core receives exactly that answer |
| FR-016 reopen after crash, interrupted turn | R12 | I and S: the transcript restored; the interrupted notice; nothing re-sent; the nothing-stored case |
| FR-017 orderly stop, 10 s, honest (OD-2) | core-supervision §5 | U: the sequence with a fake clock — forced stop at exactly 10 s and on "Quit now"; no "saved" claim on any forced path; I: an orderly exit without termination; a non-cooperating double terminated with its children; W: "Closing…", "Quit now", the stopped-before-finishing notice; S: the close flow |
| FR-018 no orphans | R8 | L: close, quit during a turn, abrupt kill — zero Core processes |
| FR-019 single instance, confirmation | core-supervision §6 | U: the switch decision (same path, different path confirmed, declined, unanswered); L: a second launch leaves one window and one Core; a different path switches only after confirmation |
| FR-020 workspace shown | `workspace.get` | W and S |
| FR-021 workspace at launch and change (OD-3) | core-supervision §2a, `choose_workspace` | U: launch resolution — a valid explicit path, an invalid one, no path; a dismissed chooser starts nothing; the chooser opens at the last selected folder; W and S: a reload and a restart keep the workspace with no chooser; a change stops the old Core and starts a new one |
| FR-022 workspace checked | core-supervision §2 | U and I: missing and unreadable workspace |
| FR-023 reuse packages | Reuse table | D: the dependency graph; G: typecheck |
| FR-024 no policy in the window | the relay and the window rules | W: the view sends `session.set_mode` and `permission.reply` and never branches on allow or deny; D |
| FR-025 shared packages unchanged | — | G: the TUI renderer suite and `npm test` unchanged |
| FR-026 no Core or schema change | — | G: `protocol-codegen --check`; the diff has no `src/`, `schemas/` or `packages/` change |
| FR-027 no computer-control backend, no web UI | Reuse table | D: no import; G: `tests/test_desktop.py`, `tests/test_web.py` unchanged |
| FR-028 no credential reachable | R10 | S: the canary (SC-009) |
| FR-029 inert display | R9 | W: the SC-010 cases; S: the same strings from the scripted Core |
| FR-030 minimal native operations | native-bridge contract, one command constant | U: no command outside the contract (early), then equality (final); CI: the release configuration's generated manifest grants exactly the contract commands; the `e2e` build adds only `e2e_report`; S: a plugin command is refused |
| FR-031 unconfigured provider | R11 | W: send unavailable, direction shown; S: "Check again" after the config is restored |
| FR-032 logs and preferences clean | data-model §5 | U: the exact preferences schema; S: canary in the log and preferences |
| FR-033 three platforms | CI desktop job | every layer on all three, with recorded evidence for the exact final SHA in the PR description; any missing platform leaves D1 incomplete |
| FR-034 offline acceptance | `fake` provider, scripted Core | the CI desktop job has no provider secret |
| FR-035 no timing sync | observers, process-exit waits, injected clocks | D; a lint check rejects fixed delays in desktop test files |
| SC-001 ready ≤ 10 s | — | S: time to ready recorded on each platform |
| SC-002 named startup failures | failure classes | I: each double; W: each message |
| SC-003 crash recovery ≤ 10 s | R12 | I and S: all platforms |
| SC-004 interrupted, nothing re-sent | R12 | I and S |
| SC-005 reload exact | R13 | S: rebuilt state equals the Core's snapshot |
| SC-006 restart limit | RestartPolicy | U and I |
| SC-007 zero orphans | R8 | L: all platforms |
| SC-008 single instance | core-supervision §6 | L, including the confirmation |
| SC-009 canary zero | R10 | S |
| SC-010 adversarial strings inert | R9 | W and S |
| SC-011 other native ops refused | the contract | U (early and final), the release-manifest check, S |
| SC-012 existing gates unchanged | — | G |
| SC-013 offline | — | the CI desktop job has no secrets; the fixtures are offline |
| SC-014 scripted prompt, question, permission | the scripted Core | I and S |
| SC-015 unconfigured path | R11 | W and S |
| SC-016 10 s shutdown, honest | R6 | U, I, W and S; L on all platforms |
| SC-017 workspace at launch | R7, R14 | U: the exact start directory handed to the chooser adapter; W and S; recorded real-dialog evidence on all three platforms |

## Project Structure

### Documentation (this feature)

```text
specs/003-desktop-foundation/
├── plan.md              # this file
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   ├── native-bridge.md
│   ├── core-supervision.md
│   └── protocol-usage.md
├── checklists/requirements.md
└── tasks.md             # /speckit.tasks — not created here
```

### Source Code (repository root)

```text
apps/desktop/                   # the desktop application (new)
├── package.json                # workspace package; test, e2e, lifetime scripts
├── tsconfig.json               # referenced from the root tsconfig
├── index.html
├── src/                        # window content (React/TS)
│   ├── bridge.ts               # the bridge Transport (native-bridge contract)
│   ├── app.tsx                 # one screen, driven by the @comodor/session reducer
│   ├── view/                   # status strip, conversation, form, permission, composer, failure
│   └── text.ts                 # inert display: control characters to visible symbols
├── test/                       # window logic tests (in-memory Transport)
├── e2e/                        # scenario runner (test build only)
└── src-tauri/                  # native side (Rust)
    ├── Cargo.toml
    ├── tauri.conf.json         # CSP, no plugin permissions, single window
    ├── capabilities/           # the app's own commands only
    ├── src/
    │   ├── main.rs
    │   ├── supervisor.rs       # CoreProcess state machine, restart, stop
    │   ├── platform/           # job object | parent-death signal | process group
    │   ├── relay.rs            # generations, id mapping, allowlist, cached hello
    │   ├── commands.rs         # exactly the contract's commands
    │   └── prefs.rs
    └── tests/                  # integration: real Core, scripted Core, doubles
        └── fixtures/scripted_core.py   # test-only scripted Core (CoreService + assemble_with)

.github/workflows/ci.yml        # + one "Desktop" job on three platforms
docs/desktop-architecture.md    # "planned" → what D1 delivers
docs/surface-parity.md          # the Desktop row names both the app and the computer-control backend
tsconfig.json                   # + reference to apps/desktop
```

**Structure Decision**: one new workspace, `apps/desktop`, beside
`apps/tui`. `src/`, `schemas/`, `packages/` and `tests/` are not edited
(FR-025, FR-026). The scripted Core fixture is Python test code under the
desktop's own tests and is not part of the Python package (the sdist includes
`src/comodor` and `tests` only).

## Surface Impact

| Surface | Status | Evidence / Notes |
| --- | --- | --- |
| TUI | UNCHANGED BUT VERIFIED | `apps/tui/` untouched; `packages/` untouched; verified by `bun test apps/tui/test/bun/renderer.test.tsx`, `bun test apps/tui/test/bun/orphan.test.ts` and `npm test`. The root `package-lock.json` gains the desktop's dependencies, so `npm ci` for the TUI is re-verified. |
| Web UI | UNCHANGED BUT VERIFIED | `src/comodor/web/` untouched and not embedded (FR-027); `tests/test_web.py` and `tests/test_real_web_ui.py` pass unchanged. |
| CLI / Headless | UNCHANGED BUT VERIFIED | `comodor core --stdio` is used as is; `tests/test_core_stdio.py` and `tests/test_transport_commands.py` pass unchanged. |
| API / Protocols | UNCHANGED BUT VERIFIED | `schemas/protocol/v2.json` unchanged; `python tools/protocol-codegen.py --check`; the desktop uses the methods in [protocol-usage.md](./contracts/protocol-usage.md) only. |
| Desktop | REQUIRED | The new `apps/desktop`. The computer-control backend in `src/comodor/desktop/` is unchanged; `tests/test_desktop.py` passes unchanged. |
| Channels / Integrations | NOT APPLICABLE | `src/comodor/channels/` has no path to a desktop window, and the desktop adds no integration. |
| Docker / Packaged Runtime | UNCHANGED BUT VERIFIED | The wheel packages `src/comodor`; the sdist includes `src/comodor`, `tests`, `pyproject.toml`, `README.md` and `LICENSE`; the image installs from PyPI. None includes `apps/desktop`. Verified by `python tools/check-wheel-contents.py` in the CI build job. No desktop bundle or installer (D6). |
| Persistence / Shared State | REQUIRED | The desktop preferences file (data-model §5). The Core's session store is used through `session.open` only. |
| Security / Authorization | REQUIRED | The window/native trust boundary: native-bridge contract, CSP, no listener, the canary. Modes and permissions stay in the Core. |
| Tests / Documentation | REQUIRED | Desktop test layers and the CI job; `docs/desktop-architecture.md`, `docs/surface-parity.md`, and a README section on running the desktop from source. |

## Risks

| # | Risk | Mitigation or status |
| --- | --- | --- |
| K1 | On macOS, and for grandchildren on Linux, processes the Core started (a tool's shell command) depend on the Core's own cleanup when the application is killed abruptly | The Core leads a process group and a forced stop signals the group; abrupt-kill cleanup of grandchildren is **not guaranteed** on macOS. Recorded; SC-007 counts Core processes, as the spec defines. |
| K2 | The Linux parent-death signal follows the spawning *thread* | The Core is spawned only from the supervisor's long-lived thread; a test kills the application and checks the Core exits. |
| K3 | WebKitGTK and a virtual display on Linux CI; the macOS runner's window server | The in-application runner needs no WebDriver; the CI job installs the Linux packages; a platform where a layer cannot run is recorded **NOT VERIFIED**, never passed, and D1 is then incomplete; the Linux leg also runs in a D-Bus session (K11). |
| K4 | The development server listens on loopback in dev mode | It serves static assets only; tests and releases use embedded assets (R2). |
| K5 | New dependencies (Rust and npm) and lockfile churn | Pinned exact versions; confined to `apps/desktop`; `npm ci` and the TUI suites re-verified. |
| K6 | The diagnostic tail relies on the Core never logging secrets | It is the Core's invariant (Constitution VIII); the canary covers D1's flows (R10). |
| K7 | A relay bug could misroute an answer | The generation prefix and unknown-id drop are unit- and mutation-tested; the relay changes nothing but `id`, and reads only the fields listed in native-bridge guarantee 2. |
| K11 | The single-instance plugin's per-platform mechanism, and its D-Bus dependency on Linux CI | Checked against the pinned plugin version; the Linux CI job runs in a D-Bus session; the FR-010 check is scoped to network (TCP/UDP) listeners. |
| K8 | `COMODOR_ARGS` is split on whitespace (existing convention) | Kept for consistency; a path with spaces goes in `COMODOR_BIN`, not `COMODOR_ARGS`; documented. |
| K9 | CI time grows by a three-platform desktop job | A separate job, so it runs in parallel with the Python matrix. |
| K10 | `spawnCore` in the TUI kills 2 s after closing stdin, inside the Core's own 5 s join (R6) | **Recorded for later triage, outside D1.** Not changed by D1 (Constitution V); it needs its own change and review. |

## Recorded Decisions (owner, 2026-09-30)

The spec's earlier model defaults are replaced by these owner decisions (spec
§Clarifications). They are D1 decisions, not defaults.

| # | Decision | Where it lands |
| --- | --- | --- |
| OD-1 | Automatic restarts stop after the **third consecutive** crash of a Core that had reached ready, without a completed turn in between; the person must choose "Try again". Only a completed turn (`message.completed` at `status: completed`, then idle) resets the count. No time window; interrupted work is never replayed. | FR-005, SC-006; data-model §3; core-supervision §4; research R5 |
| OD-2 | **10 seconds** for graceful shutdown, with "Closing…" shown and "Quit now" offered. At the deadline or on "Quit now", terminate the owned Core and its processes, report that it was stopped before it finished, and never claim unsaved work was saved. | FR-017, SC-016; data-model §6; core-supervision §5; native-bridge `quit_now` and status; research R6 |
| OD-3 | On **every fresh launch** the person explicitly chooses the workspace, in a chooser opened at the last selected folder. A valid explicit command-line path takes precedence. A reload or Core restart within the launch keeps the workspace without asking. | FR-021, SC-017; data-model §5 and §8; core-supervision §2a and §6; research R7 |

## Constitution Check (after design)

| Principle | Assessment after Phase 1 |
| --- | --- |
| I | **PASS** — additive; the contracts use existing protocol only. |
| II | **PASS** — each platform mechanism is isolated (`platform/`); every layer runs on three platforms, and the macOS WebView gap is closed by the in-application runner (R14). |
| III | **PASS** — no handshake timeout; waits are on process exit, lines and DOM changes; the two product bounds use injected clocks. |
| IV | **PASS** — mutation-sensitive guards listed in the evidence map. |
| V | **PASS** — K10 is recorded, not fixed; no shared-package or Core edit. |
| VI | **PASS** — the relay changes only envelope ids and reads, without changing, the few fields the restart counter needs; the method allowlist is lifecycle ownership; authorization stays in the Core. |
| VII | **PASS** — no committed build output. |
| VIII | **PASS** — no listener, no plugin permission, strict CSP, inert text, canary. The window cannot stop the Core or read configuration. |
| IX | **PASS** — CI only; no bundling or publishing. |
| X | **PASS** — existing gates plus desktop gates, on the exact final SHA. A layer or platform without recorded evidence leaves D1 incomplete; NOT VERIFIED is never a pass (FR-033). |
| XI | **PASS** — the table above, with evidence per row. |
| XII | **PASS** — docs updates are part of D1; OD-1 to OD-3 are recorded owner decisions, and the spec, the plan, the data model, the contracts and the quickstart state them identically. |
| XIII–XXI | **PASS / not affected** — no change to agent behaviour or model input; acceptance offline. |

**Gate: PASS.** No open decision remains.

## Complexity Tracking

No constitution violation requires justification. The one structural
addition beyond "spawn and pipe" is the relay's generation-scoped id rewriting
with a cached handshake. It is needed because the Core refuses a second
handshake and `CoreClient` restarts its ids on every page load (R3). The
simpler alternatives — restarting the Core on reload, or changing
`CoreClient` — violate FR-011 or FR-025.
