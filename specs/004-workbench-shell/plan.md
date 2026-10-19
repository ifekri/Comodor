# Implementation Plan: Workbench Shell (D2)

**Branch**: `004-workbench-shell` | **Date**: 2026-10-07 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/004-workbench-shell/spec.md`
(clarified 2026-10-07: Q1 A, Q2 A, Q3 A; requirements checklist 16/16)

## Summary

D2 turns D1's single-screen desktop window into a workbench shell: a
navigation rail, a main area holding D1's conversation and views unchanged, a
side panel for three supporting surfaces (Core, diagnostics, keyboard
shortcuts), and a status bar. A command palette, buttons and shortcuts are all
commands of the one shared registry (`@comodor/commands`), and every command
that reaches the Core keeps D1's gates. The shell holds no Core truth: it
shows what the native side and the Core report for the current Core and
clears it on restart, workspace change or a new client. One versioned,
non-secret layout (panel open, surface, width) is kept for the whole
application in D1's native preferences file, read and written through exactly
two new native operations, `read_layout` and `write_layout`, validated
strictly on the native side; a refused write performs no file operation, so
the file stays byte-identical. The release operation set grows from nine to
eleven and nothing else; D1's nine-operation record stays as history.
Acceptance is deterministic and offline on Windows, Linux and macOS: native
unit tests, happy-dom window tests, real-WebView scenarios (including window
resizing and an automated WCAG 2.1 A/AA check), process-lifetime relaunch
tests, the credential canary and the release command-manifest check.

## Technical Context

**Language/Version**: Rust 2021, `rust-version = "1.85"` (native side);
TypeScript with React 19.2.8 (window content); Node ≥ 22.6 for scripts; Bun
for the window test runner. Python is not changed.

**Primary Dependencies**: Tauri 2.12.1 (`tauri`, `tauri-build` 2.7.1),
`serde`/`serde_json` (already pinned); `@comodor/commands`, `@comodor/client`,
`@comodor/session`, `@comodor/modes`, `@comodor/questions`,
`@comodor/protocol`, `@comodor/design-tokens` (workspace packages). New: one
development dependency of `apps/desktop`, `axe-core` at an exact version, used
only by the test build's scenario runner (research R12); and, for the owner's
reference look (spec Clarifications, 2026-10-15), three pinned font packages
whose files are bundled into the page — `@fontsource/ibm-plex-sans` 5.3.0,
`@fontsource/jetbrains-mono` 5.3.0 and `material-symbols` 0.47.5 — served
from the application bundle under the unchanged `font-src 'self'`. The
colours are an additive `desktop` mapping in `@comodor/design-tokens`. No new
Tauri plugin, no new crate.

**Storage**: D1's `preferences.json` in the per-user application
configuration directory, gaining one optional `layout` object (data-model §1–§2).
The window's session storage keeps only D1's per-launch recovery facts.

**Testing**: `cargo test` (native unit and integration) in
`apps/desktop/src-tauri`; `bun test ./test` with happy-dom (window logic);
`node e2e/harness.mjs` (test build, real WebView scenarios with checkpoints
and acts; the scenario list is `SETUPS` in `e2e/setups.mjs`), `e2e/lifetime.mjs`
(the `SETUPS` marked `lifetime`), `e2e/canary-full.mjs`,
`e2e/release-manifest.mjs`; the repository's unchanged gates (quickstart §2).

**Target Platform**: Windows (WebView2), Linux (WebKitGTK 4.1 under `xvfb`,
whose screen the harness sets explicitly to 1920 × 1080 × 24), macOS
(WKWebView), all three in the CI `desktop` job matrix. No runner resolution is
assumed: scenarios read the monitor's work area through the test-build
`window` query, choose the wide size from it (at most 1280, at least 1000),
and wait until the query reports the size applied; a display too small is
reported as capability-unavailable, an acceptance blocker. Operating-system-
level evidence (key injection, the reduced-motion preference) runs only with
`COMODOR_E2E_OS_LEVEL=1`, set only in the CI `desktop` job.

**Project Type**: desktop application (Tauri) in a monorepo with shared
TypeScript packages and a Python Core.

**Performance Goals**: palette results update within one rendered frame for
the registry's size (≈25 commands; no measurement-driven optimisation is
planned, CLAUDE.md §22's rule applies only to large model lists); one
`write_layout` per completed change, never per pointer move (research R14).

**Constraints**: offline and deterministic, no provider call, no credential,
no paid tokens (FR-033, SC-013, Principle XXI); exactly eleven native
operations (FR-030, FR-031); window minimum 520 × 400 unchanged; every D1
behaviour and regression test kept passing with all its assertions, except the
two command-set assertions SC-001 names, which move from nine to eleven, and
D1's test files and infrastructure gaining additions only; the page details D1's tests read kept (quickstart §2,
contracts/workbench-shell.md); D1's NOT VERIFIED items carried forward.

**Scale/Scope**: 4 regions, 4 surfaces, 25 commands, 1 stored object of 4
fields, 2 native operations; 37 FRs, 17 SCs.

No item above was left as NEEDS CLARIFICATION; research R1–R14 records each
choice.

## Constitution Check

The constitution used is **version 2.0.0**, read from the immutable commit
`427ecca` (D1's merge) and restored byte for byte into this worktree's
`.specify/` as **local, untracked tooling**. **Current `main` (`180c3f6`) has
no tracked constitution and no tracked Spec Kit scripts or templates**; the
restored files are ignored, are not committed, are not part of the pull
request, and their permanent restoration would be a separate governance
change. The checks below are judged against that 2.0.0 text.

*GATE: before Phase 0 research, and again after Phase 1 design.*

| # | Principle | Before design | After design |
| --- | --- | --- | --- |
| I | Backward compatibility | PASS — the spec keeps D1 behaviour (FR-002) and adds an optional preferences field | PASS — `layout` is optional, the file version stays 1, a D1 build ignores it and a D2 build reads a D1 file as "no layout" (R1); a bad layout never costs D1's values (R2); D1's page details its tests read are kept (contracts/workbench-shell.md). SC-001 (corrected 2026-10-08 by the owner's direction, Q2 unchanged; reworded after analysis) keeps every D1 behaviour and regression test passing, lets exactly two existing D1 assertions change — the command-set assertions in `commands.rs` and `release-manifest.mjs`, from nine to eleven — and lets D1's test files and infrastructure gain additions that change no existing assertion (tests, scenarios, registrations, setups, harness acts and checkpoints, canary flows, native-double answers) (R6, quickstart §2); D1's nine-operation record stays as history |
| II | Three platforms | PASS — FR-033/FR-034 require all three | PASS — every gate in quickstart §3 runs in the `desktop` matrix on all three; geometry is checked in each platform's real WebView (R10, R11); atomic rename holds on all three (layout-persistence.md) |
| III | Invariant, not symptom | PASS | PASS — scenarios wait on checkpoints and settled states (D1's harness), never on sleeps; acts are asynchronous and return nothing, so the window's size and focus are read through the test-build `window` query until they show the requested state; the stale-Core rule is a clearing invariant on status and client identity (R13) |
| IV | Deterministic regression tests | PASS | PASS — every guard has a mutation check (quickstart §4), including the byte-identical refusal and the eleven-operation set |
| V | Narrow scope | PASS — D3–D6, the TUI and the Core are out of scope | PASS — no TUI migration (R8), no Core or protocol change, no theme work; the one new dev dependency (`axe-core`) serves SC-006 directly. Recorded in Complexity Tracking |
| VI | Architectural boundaries | PASS — Python authoritative, shell presents | PASS — no Core value is computed or kept across Cores (R13, data-model §5); commands reach the Core only through D1's session functions and native operations; layout is presentation only and never sent to the Core; no schema or generated file changes |
| VII | Reproducible artifacts | PASS | PASS — D2 does not touch the TUI distribution; its unchanged rebuild is a gate (quickstart §2) |
| VIII | Security | PASS — FR-029, FR-032, FR-036 | PASS — the page cannot grant itself anything: two operations, strictly validated natively, no file path or other value exposed (layout-persistence.md); Core-bound commands keep D1's gates in every path; inert text everywhere; canary extended over both operations and the file (R7); no secret enters the layout |
| IX | Release infrastructure | PASS | PASS — the release command-manifest check is updated deliberately with a mutation check; the CI `desktop` job changes only by installing `xdotool` in its existing Linux setup step, setting `COMODOR_E2E_OS_LEVEL=1` in its `env` for the operating-system-level evidence, and giving the steps after `e2e` `if: ${{ !cancelled() }}` so every layer's evidence is produced while a failed `e2e` still fails the job; no packaging or publication change; test-only acts and the `window` query stay behind the `e2e` feature (T085) |
| X | Quality gates | PASS | PASS — the full gate list (quickstart §2–§3) on the exact final commit, all three platforms; NOT VERIFIED is never a pass |
| XI | Surfaces named | PASS — the spec's ten-row table | PASS — unchanged by design; evidence commands named in quickstart §2 |
| XII | Done means everything agrees | PASS | PASS — `docs/desktop-architecture.md` is updated with the shell and the eleven operations; D1's documents stay as history; D1's two NOT VERIFIED items carried forward (quickstart §6) |
| XIV / XIX | Evidence before assumption; grounded tool use | PASS | PASS — every design fact was read from the repository at `180c3f6` (research preamble); one wrong assumption found while writing (that `release-manifest.mjs` takes its count only from `COMMANDS`) was checked against the file and corrected in R6 |
| XV | Clarification | PASS — three owner questions answered | PASS — no new owner decision arose; SC-001 was corrected by the owner's direction of 2026-10-08 (spec Clarifications), which leaves Q2 unchanged |
| XVIII | Extend, never duplicate | PASS | PASS with one recorded item — one registry, one search, one preferences file, one lock and one save path; the palette selection rule is added to `@comodor/commands` and the TUI's own copy is left for its own change (Complexity Tracking) |
| XX | User control | PASS | PASS — this step writes no code, commits nothing, pushes nothing, opens no pull request |
| XXI / XVI | Deterministic acceptance; tokens | PASS | PASS — no model is involved in any D2 behaviour; every acceptance test uses the scripted Core and spends no tokens; no token or quality claim is made |
| XIII, XVII | Agent quality; learning | NOT APPLICABLE — D2 changes no agent behaviour, context, memory or learning | NOT APPLICABLE |

**Result**: no violation; recorded complexity items only (Complexity
Tracking). No ERROR.

## Project Structure

### Documentation (this feature)

```text
specs/004-workbench-shell/
├── spec.md                       # clarified specification
├── checklists/requirements.md    # 16/16
├── plan.md                       # this file
├── research.md                   # R1–R14
├── data-model.md                 # stored layout, regions, Core reports, commands
├── quickstart.md                 # gates, mutation checks, evidence
├── contracts/
│   ├── native-operations.md      # the eleven operations
│   ├── layout-persistence.md     # read_layout / write_layout
│   └── workbench-shell.md        # regions, commands, keys, focus, sizes
└── tasks.md                      # next step (/speckit.tasks), not created here
```

### Source code (planned changes, real paths)

```text
apps/desktop/
├── package.json                  # + axe-core (dev, exact version)
├── src/
│   ├── app.tsx                   # mounts the shell around D1's views
│   ├── commands.ts               # registers the D2 catalogue in the one registry
│   ├── native.ts / bridge.ts     # unchanged connection path; typed layout calls added
│   ├── styles.css                # shell layout, focus ring from border.focused, reduced motion
│   ├── shell/                    # new: the frame
│   │   ├── Shell.tsx             # regions, landmarks, F6 cycle, focus return
│   │   ├── Rail.tsx
│   │   ├── SidePanel.tsx         # beside / covering, drag and keyboard resize
│   │   ├── StatusBar.tsx         # replaces StatusStrip, keeps its test hooks
│   │   ├── Palette.tsx           # dialog + combobox + listbox over registry.search/run
│   │   ├── CorePanel.tsx
│   │   ├── DiagnosticsPanel.tsx
│   │   ├── ShortcutsPanel.tsx    # generated from the registry's bindings
│   │   ├── layout.ts             # pure layout function (data-model §4)
│   │   ├── preference.ts         # read once, write after each change
│   │   └── reports.ts            # Core values for the current Core only (data-model §5)
│   └── view/                     # D1's views, unchanged in behaviour
├── src-tauri/
│   ├── src/command_names.rs      # COMMANDS: [&str; 11]
│   ├── src/commands.rs           # read_layout, write_layout; CONTRACT test → eleven
│   ├── src/prefs.rs              # optional, leniently loaded `layout`; validation
│   ├── src/e2e.rs                # test build only: `resize` and `focus-window` acts; `window` query (size, work area, focus)
│   ├── capabilities/main.json    # + allow-read-layout, allow-write-layout
│   └── tests/                    # integration: file bytes after write_layout
├── test/                         # new *.test.tsx for the shell; fake-native.ts additive
└── e2e/
    ├── scenarios/                # new: shell, palette, keyboard, layout, narrow, a11y
    ├── harness.mjs               # read-preferences checkpoint; relaunch with the same data folder;
    │                             # press-keys (OS-level injection); explicit Linux xvfb screen
    ├── runner.ts                 # axe-core run in the page
    ├── setups.mjs                # SETUPS entries for every D2 scenario (the run list)
    ├── canary-full.mjs           # FLOWS + D2 flows; layout ops in the recorded commands
    └── release-manifest.mjs      # count and comments → eleven
.github/workflows/ci.yml          # desktop job: `xdotool`; env COMODOR_E2E_OS_LEVEL=1; `!cancelled()` on steps after e2e
packages/commands/src/index.ts    # additive: pure palette selection rule
docs/desktop-architecture.md      # the shell and the eleven operations
```

Not changed: `src/comodor/**`, `schemas/**`, generated protocol files,
`apps/tui/**`, `specs/003-desktop-foundation/**`, `e2e/lifetime.mjs` (it runs
every `SETUPS` entry marked `lifetime`), and `.github/workflows/ci.yml` beyond
adding `xdotool` to the desktop job's Linux setup step,
`COMODOR_E2E_OS_LEVEL=1` to that job's `env`, and `if: ${{ !cancelled() }}` to its
steps after `e2e` (the existing `e2e`,
`lifetime`, `canary` and `release-manifest` steps already run per platform).

**Structure Decision**: the shell lives in a new `apps/desktop/src/shell/`
beside D1's `src/view/`, so D1's views stay where they are and are composed
into the main area; native changes stay in D1's existing modules, with no
new module for preferences.

## Requirement coverage (deterministic, offline, all three platforms)

Layers: **NU** native unit · **NI** native integration · **W** window logic
(happy-dom) · **E** real-WebView scenarios (test build) · **A** `axe-core` in
E · **L** process lifetime · **C** credential canary · **RM** release
command-manifest · **G** unchanged gates (quickstart §2). Every layer runs on
Windows, Linux and macOS in the `desktop` job; none calls a provider.

| Req | Evidence |
| --- | --- |
| FR-001 | W four landmarks in every state and D1 views in `main`; E same in the real WebView |
| FR-002 | G every D1 window test, scenario, lifetime and canary flow passing with all its assertions; E D1 flows inside the shell |
| FR-003 | W status bar values from D1's reports, palette control present; E boundary scenario still sees one `status-strip` |
| FR-004 | W rail lists exactly four entries with names and icons, active marked |
| FR-005 | W/E scan of rail, palette (every state) and bindings for D3–D6 terms; mutation: adding one fails |
| FR-006 | W surface set equals contract; `panel_surface` set in NU |
| FR-007 | W choose by rail, key, palette; choosing the shown surface closes |
| FR-008 | W Core panel shows reported values and "not reported yet"; E against the scripted Core |
| FR-009 | W inert tail, refresh, auto-refresh on failure, available in every state; E adversarial tail |
| FR-010 | W Core-panel buttons are registry commands, same `enabled` as palette and failure view |
| FR-011 | W palette opens by mod+K and by control; button/key/entry run the same command id; **E** `key-delivery`: mod+K delivered by the operating system opens it on each platform |
| FR-012 | W eight-state palette lists (SC-004); mutation: ignoring `enabled` fails |
| FR-013 | W ranking via `registry.search`, highlight resets on query change (shared rule unit test) |
| FR-014 | W/E Enter, click, Escape, click outside; effect equals the button's |
| FR-015 | W catalogue equals contracts/workbench-shell.md |
| FR-016 | W every command has a key or palette path and a mouse path (SC-002) |
| FR-017 | W reserved-key test, `mod` per platform, punctuation named by `event.key`, text-field rule, Escape precedence; registry binding validation; E dispatched keys in the real WebView; **E** `key-delivery` for platform delivery |
| FR-018 | E focus ring visible (computed style from `border.focused`), Tab order, F6 cycle, no trap, at each of the four sizes; **E** `key-delivery`: F6 and Shift+F6 delivered by the operating system; A |
| FR-019 | W/E focus into overlay and back, composer fallback, Escape on topmost |
| FR-020 | A names and roles; W live-region announcements once and the reduced-motion marking; **E** `reduced-motion`: the stylesheet rule on each platform, and with `COMODOR_E2E_OS_LEVEL=1` in CI the operating system's preference set, read back, observed through `matchMedia` and restored; and **E** `reduced-motion-transition` on macOS: switched off then on, each in a fresh launch confirmed by `NSWorkspace` and `matchMedia`, zero-duration shell motion only when on, the exact original (type and value, or absence) restored and read back; outcome `verified`, `product-failure` or `capability-unavailable` (NOT VERIFIED, an acceptance blocker) |
| FR-021 | NU round-trip; E reload, restart, workspace change; L relaunch |
| FR-022 | NU stored object has four fields; C no conversation text or canary in the file |
| FR-023 | NU lenient load; W reset writes defaults once; E pre-seeded invalid layout |
| FR-024 | E workspace change keeps layout; L relaunch in another workspace |
| FR-025 | W layout function bounds over a fractional width (899.2, 899.99, 900.0) and splitter keys (arrows, Home, End); E drag and keyboard resize within bounds |
| FR-026 | W covering mode, Escape, click outside; E across 899/900 |
| FR-027 | E `resize` act (a Tauri `PhysicalSize` computed from the scale factor `s`) at the minimum `ceil(520·s)` × `ceil(400·s)`, the widths `ceil(900·s) − 1` and `ceil(900·s)` either side of the threshold, and a wide size fitted to the queried work area (≤ 1280, ≥ 1000 logical), each confirmed through the `window` query's physical size; the page's size and the shell's measured width (`ResizeObserver`) within 1 px of physical ÷ `s`, on macOS less the measured title-bar offset (constant, ≤ 40 px; zero on Windows and Linux; spec Clarifications 2026-10-16); compact judged by the measured width: no horizontal scroll, the essentials in view, reachable by the pointer and usable (a draft enables Send, the palette opens inside the window and closes with Escape); only no monitor or a display too small is capability-unavailable |
| FR-028 | W clearing on restart, workspace change, new client; mutation: keeping values fails |
| FR-029 | W each Core-bound command disabled under `gated` from button, key and palette; E wake `checking` scenario; mutation |
| FR-030 | NU `COMMANDS` equals eleven; RM; G TUI renderer, codegen check, `npm test` |
| FR-031 | NU/RM no other operation; W no quit/reload/log command |
| FR-032 | W/E inert text in every surface; C extended flows |
| FR-033 | the whole table, offline, all three platforms; SC-013 below |
| FR-034 | E geometry and focus at the four sizes per platform, work area and applied sizes recorded; dispatched keys and keys delivered by the operating system (`key-delivery`, after a delivery probe; Linux through `xdotool windowfocus` and `getwindowfocus` on the window-manager-less `xvfb`) recorded separately with their outcome; every other layer's evidence still produced on that platform (`!cancelled()` steps); missing platform evidence or `capability-unavailable` = NOT VERIFIED = a failed job = incomplete |
| FR-035 | docs and PR evidence list D1's two NOT VERIFIED items (quickstart §6) |
| **FR-036** | **NU** each rule 1–7 refused with its reason and every boundary accepted; refusal performs no file operation — file bytes equal before and after, no temp file left, for every SC-017 case; mutation: saving before validating fails; lenient read with defaults; **NI** file on disk after an accepted write keeps D1's values; **E** a refused write through the real bridge with `preferences.json` byte-identical between in-run checkpoints immediately before and after it; pre-seeded invalid layout → defaults |
| **FR-037** | **RM** exactly eleven allow/deny pairs, only `main`, eleven allow identifiers plus the `core:` minimum, no plugin permission, `e2e` differs only by `e2e_report`; mutation: removing `write_layout` from the capability or adding a twelfth name fails; **NU** `CONTRACT` written out as eleven; **C** both operations present in the recorded commands of the canary run, zero canary occurrences in their arguments, results and the preferences file, across every D1 and D2 flow |

| SC | Evidence |
| --- | --- |
| SC-001 | G + every D1 desktop layer on the exact commit, three platforms: all D1 assertions kept except the two command-set assertions (`CONTRACT` in `commands.rs`; the count and its comments in `release-manifest.mjs`), which move from nine to eleven (R6); only additions in `canary-full.mjs`'s flow list and `fake-native.ts`; a file-by-file review of the diff of D1's test files shows no other changed, removed or skipped assertion |
| SC-002 | W full-coverage keyboard/mouse mapping test over the catalogue; E keyboard-only run |
| SC-003 | W for every command, first three letters of each title word → top three; Enter runs |
| SC-004 | W eight states × expected lists from the contract; E ready, failed, unconfigured, closing |
| SC-005 | W/E focus return and Tab cycle in every state |
| SC-006 | A WCAG 2.1 A/AA, zero violations, every state, three platforms |
| SC-007 | E the four sizes computed in physical pixels from `s` (so fractional scaling is always representable), each confirmed as applied, the threshold judged by the shell's measured fractional width, three platforms; physical size, `s`, measured width, page size and mode recorded per size and platform |
| SC-008 | E reload, restart, workspace change; L relaunch with the same data folder (same and other workspace); three platforms |
| SC-009 | NU lenient load cases; E pre-seeded unreadable, other-version, out-of-range layouts |
| SC-010 | W clearing tests; E crash-restart and workspace change with the Core panel open |
| SC-011 | C every D1 and D2 flow; layout ops in the record; four-field layout, no conversation text |
| SC-012 | W/E D3–D6 term scan of rail, palette and bindings |
| SC-013 | all layers use the scripted Core and the `fake` provider; no network to a provider |
| SC-014 | G TUI renderer, frontend tests, Python suite, codegen check unchanged |
| SC-015 | docs + PR evidence list both items NOT VERIFIED |
| **SC-016** | **RM** eleven exactly, every run, three platforms, with its mutation check; **NU** `CONTRACT` |
| **SC-017** | **NU** for each case — unknown field, wrong type, out-of-range width, unknown surface, another version, over 1 KiB, not an object, missing field — refused, and the whole preferences file (with `version`, `window`, `last_selected_folder`) byte-for-byte unchanged, no temp file; mutation check; **NI** same against a file on disk; **E** one refusal through the real bridge with the file compared between in-run checkpoints immediately before and after it (D1's geometry save on close legitimately changes the file afterwards) |

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| Palette selection rule added to `@comodor/commands` while `apps/tui/src/palette.ts` keeps its own copy (Principle XVIII) | The desktop palette must not grow a second rule; a shared, pure export is the one place for it | Migrating the TUI now would change the TUI surface the spec classifies UNCHANGED BUT VERIFIED and mix a TUI refactor into D2 (Principle V). The duplication is recorded for a separate change that moves the TUI onto the shared export |
| New dev dependency `axe-core` (exact pin, test build only) | SC-006 requires an automated WCAG 2.1 A/AA check in the real WebView on three platforms | A hand-written rule set would be less complete and unproven; checking in happy-dom cannot see contrast or focus visibility |
| Test-build-only `resize` act | Geometry (FR-027, SC-007) exists only in the real WebView, and the page has no permission to resize its window | Granting a window-resize permission to the release page adds a release permission for a test need (FR-031) |

## Correction 2026-10-17: the reference window

The owner's `_ide_ui` reference binds the whole window (spec Clarifications
2026-10-17 and its conflict table). It is read from the owner's checkout and
never copied, committed or bundled.

**Structure** (`apps/desktop/src/shell/`, presentation only; no Core, native
or protocol change):

- `Shell.tsx` lays out the reference's grid — a 64 px top bar, a body of
  sidebar and canvas, a 31 px status bar — and owns the open menu, the
  sidebar's beside/covering state at 760 px (the reference's minimum width;
  corrected 2026-10-18 from 900), the modal panel,
  the palette and a notice ("toast") for unavailable items.
- `TopBar.tsx`: wordmark, `Menus.tsx` (the eight reference menus; items are
  real commands or unavailable), the search that opens the palette in its
  place, and the four actions (Cancel the turn is real; the others are
  unavailable).
- `Sidebar.tsx`: toolbar (Change workspace is real), WORKSPACE/EXPLORER tabs,
  SESSION (the session the Core opened), AGENTS (the snapshot's delegates),
  TASKS (the snapshot's task list), each read-only or a truthful empty state.
- The canvas keeps D1's `<main data-testid="window">` and D1's views; on an
  empty conversation it shows the reference's tile card (Workspace = Change
  workspace; Loop, Skill, Memory unavailable).
- The prompt area is D1's composer over the reference's footer: the model the
  Core reports, unavailable attachments and Agentic, D1's mode control,
  Send/Cancel, "Command [Ctrl+K]", "Shortcuts [Ctrl+/]".
- `StatusBar.tsx` renders D1's strip once, in the reference's cells, plus
  Diagnostics (real) and the unavailable Terminal and power cells.
- `ModalPanel.tsx` replaces `SidePanel.tsx`: the reference's modal for the
  Core panel, diagnostics and keyboard shortcuts; the stored layout's
  `panel_open`/`panel_surface` reopen it; `panel_width` is not drawn.

**Evidence** (SC-018): a test-build-only `screenshot` checkpoint in
`e2e/harness.mjs` captures the application's own window — Windows
`PrintWindow` of the client area, macOS `screencapture -l`, Linux `import
-window` under the harness's Xvfb — and a `visual` scenario drives each size
(1440 × 900, the minimum, 899 and 900 wide, 759 and 760 wide) through the normal, menu,
question, palette and panel states; CI keeps the images. The reference is
rendered locally, at the same sizes and states, in a headless browser driven
over the DevTools protocol from the owner's checkout, and compared section by
section; the comparison table and both sets of images go into the pull
request.

| Item | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| Test-build-only `screenshot` checkpoint (harness side only) | SC-018 needs the real WebView's pixels on three platforms; the page cannot read its own pixels | DOM or happy-dom checks cannot show composition, typography or rendering (the owner ruled them insufficient) |

## Remaining before `/speckit.tasks`

No blocker. The earlier SC-001 wording note is resolved by the owner's
direction of 2026-10-08 (spec Clarifications).
