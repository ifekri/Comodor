---

description: "Task list for D2 — Workbench Shell"
---

# Tasks: Workbench Shell (D2)

**Input**: Design documents from `specs/004-workbench-shell/` — spec.md
(clarified; SC-001 corrected 2026-10-08), plan.md, research.md (R1–R14),
data-model.md, contracts/ (native-operations.md, layout-persistence.md,
workbench-shell.md), quickstart.md.

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/,
quickstart.md — all present.

**Tests**: Required. The spec requires deterministic tests for every D2
behaviour (FR-033, FR-034) and the plan names ten mutation checks
(quickstart §4). Every test task precedes the implementation it verifies and
must fail before that implementation exists.

**Organization**: by user story (US1–US6, spec priority order), after a
foundational phase that changes the native operation set and adds the shared
pieces every story uses.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel — different files, no dependency on an open task
- **[Story]**: US1–US6 for user-story phases only
- Paths are repository-relative; `desktop/` below means `apps/desktop/`

## Rules every task follows

- **Offline and deterministic.** No provider call, no credential, no paid
  tokens; the scripted Core and the offline `fake` provider home only
  (FR-033, SC-013, Constitution XXI). No sleeps as synchronisation
  (Constitution III).
- **SC-001 boundary.** All D1 behaviour and regression tests keep passing with
  every existing assertion. Exactly two existing D1 assertions change, from
  nine to eleven: `CONTRACT` in `desktop/src-tauri/src/commands.rs` (T008) and
  the count with its comments in `desktop/e2e/release-manifest.mjs` (T009).
  Otherwise D1 test files and test infrastructure receive **additions only**,
  changing no existing assertion, and only these: `desktop/test/fake-native.ts`
  (T021), `desktop/e2e/canary-full.mjs` (T075), `desktop/e2e/harness.mjs`
  (T093, T094, T057, T070, T075 — checkpoints, acts, the relaunch, the explicit
  Linux `xvfb-run -s "-screen 0 1920x1080x24"` arguments), `desktop/e2e/runner.ts`
  (T049), `desktop/e2e/setups.mjs` (`SETUPS` entries and setup options),
  `desktop/e2e/scenarios/index.ts`, `desktop/e2e/scenarios/lifetime.ts`,
  appended `#[cfg(test)]` tests in `desktop/src-tauri/src/prefs.rs`,
  `commands.rs` and `e2e.rs` (T093, T070). `desktop/e2e/lifetime.mjs` is not changed. No D1
  test is deleted, skipped, loosened or rewritten; D1's
  `desktop/test/*.test.ts(x)` files and D1's scenario functions are not edited
  (T080 inspects this).
- **Operating-system-level steps** (T093 key injection, T094 the reduced-motion
  preference) run only when `COMODOR_E2E_OS_LEVEL=1`, set only in the CI
  `desktop` job; otherwise those scenarios report `not-run` — like D1's
  `notApplicable`, it does not fail the run, and it is never evidence (T089
  requires `verified` from CI on every platform). Acts are asynchronous (`e2e.rs:113-134`: they run on their own
  thread after the checkpoint reply) and return nothing; a scenario observes
  their effect through the test-build `window` query and the page, waiting
  for the observed state, never sleeping.
- **Scenario registration.** The harness runs `Object.keys(SETUPS)` from
  `desktop/e2e/setups.mjs` (`harness.mjs:444-445`), and `lifetime.mjs` runs the
  entries marked `lifetime`. Every new scenario therefore needs an export in
  its scenario file, an entry in `desktop/e2e/scenarios/index.ts`, and a
  `SETUPS` entry in `desktop/e2e/setups.mjs`.
- **D1 page details kept** (contracts/workbench-shell.md): exactly one
  `data-testid="status-strip"` with D1's `data-state`, `.status-state`,
  `.status-workspace`, the "Change workspace…" text, every D1 `data-testid`;
  `COMMAND_IDS` in `desktop/src/commands.ts` stays exactly
  `{ send: "conversation.send", cancel: "conversation.cancel" }` (asserted by
  `desktop/test/conversation.test.tsx`).
- **D1 preferences type kept** (data-model §1, research R2): `prefs::Preferences`
  keeps exactly its three fields; `prefs::load` and `prefs::save` keep their
  signatures and behaviour; the layout travels in `prefs::Stored`;
  `Desktop::new` keeps its signature (`desktop/src-tauri/tests/wake.rs:39`).
- **No placeholder** for D3–D6, no editor, terminal, history browsing,
  credential entry, quit/reload/open-log operation, or live-provider
  acceptance (FR-005, FR-031).
- **Specs of D1** (`specs/003-desktop-foundation/**`) are never edited.
- **`.specify/`** stays local, ignored and untracked (T084).

---

## Phase 1: Setup

- [X] T001 Verify the worktree `E:\AiTools\Comodor-D2` is on branch `004-workbench-shell` created from the latest `origin/main` (`git fetch --prune origin`, compare `git merge-base HEAD origin/main` with `git rev-parse origin/main`), that `git status --short --ignored` shows only `?? specs/004-workbench-shell/` and `!! .specify/`, and that the owner's checkout `E:\AiTools\Comodo-Agent` is untouched (its modified files and its three stashes; never run `git stash` there); record the base SHA outside the repository
- [X] T002 Record the SC-001 baseline inventory outside the repository: the path and blob id at the base SHA of every D1 test file — `desktop/test/**`, `desktop/e2e/**`, `desktop/src-tauri/tests/**`, and the `#[cfg(test)]` modules of `desktop/src-tauri/src/*.rs` (with their test function names) — plus `packages/commands/test/**`, for the final diff inspection (T080)
- [X] T003 Run the unchanged gates of quickstart §2 and the desktop layers of quickstart §3 (`cargo test`, `cargo test --features e2e --lib e2e::tests`, `npm run -w apps/desktop test`, `e2e`, `lifetime -- --skip-build`, `canary -- --skip-build`, `release-manifest`) on the unmodified base on Windows, and record the results outside the repository as the SC-001 reference (Linux and macOS references come from CI on the base)
- [X] T004 [P] Add `axe-core` at an exact version as a development dependency of `desktop/package.json` only (`npm install -w apps/desktop --save-dev --save-exact axe-core`), update `package-lock.json`, and confirm with `npm run -w apps/desktop build` that the release page bundle does not contain it (research R12)

**Checkpoint**: base recorded; nothing in the product changed except one dev dependency.

---

## Phase 2: Foundational (blocks every story)

**Purpose**: the eleven-operation native set with strict validation and atomic
persistence (FR-030, FR-031, FR-036, FR-037), and the shared pure pieces every
story uses.

### Native tests first

- [X] T005 [P] Add a new `#[cfg(test)] mod layout_tests` at the end of `desktop/src-tauri/src/prefs.rs` (additive) testing layout validation, each refusal returning a reason that names the first problem, in this order: (1) "the `layout` argument, serialised as compact JSON (`serde_json::to_vec`), is at most 1024 bytes"; (2) "`layout` is a JSON object"; (3) "exactly the fields `version`, `panel_open`, `panel_surface`, `panel_width` — an unknown field or a missing one is refused"; (4) "`version` is the integer `1`"; (5) "`panel_open` is a boolean"; (6) "`panel_surface` is one of `core`, `diagnostics`, `shortcuts`"; (7) "`panel_width` is an integer from 240 to 960 inclusive"; and accepting every boundary — width 240 and 960, each surface, both booleans, a layout of exactly 1024 serialised bytes; also `1.0`, `"1"`, `239`, `961`, `320.5`, `null`, `"conversation"` and 1025 serialised bytes refused (contracts/layout-persistence.md; FR-036)
- [X] T006 In the same `layout_tests` module of `desktop/src-tauri/src/prefs.rs` (after T005), test `prefs::Stored`, `prefs::load_stored` and `prefs::save_stored`: a D1 file without `layout` loads with `layout: None` and D1's values; a `layout` that is malformed, of another version, has an unknown or missing field, a wrong type or an out-of-range width loads as `None` while `window` and `last_selected_folder` load exactly as D1's `load` loads them; a malformed whole file is the default (D1 rule); an unknown top-level field is ignored and never written back; `save_stored` round-trips the layout, writes no other field, and leaves no `preferences.json.tmp`; `prefs::Preferences` still serialises exactly three fields (FR-021, FR-023, SC-009; research R2)
- [X] T007 [P] Add a new `#[cfg(test)] mod layout_command_tests` at the end of `desktop/src-tauri/src/commands.rs` (additive) testing `Desktop::read_layout` and `Desktop::write_layout` against a preferences file in a temporary directory, built with `Desktop::new` as `desktop/src-tauri/tests/wake.rs:39` does. The file is seeded with bytes any save would change — compact (not pretty) JSON, an unknown top-level field, and a trailing newline — so that any write is visible. For each SC-017 case — unknown field, wrong type, out-of-range width, unknown surface, another version, over 1024 serialised bytes, not an object, missing field — the write is refused with its reason, the file's bytes before and after are identical (including `version`, `window`, `last_selected_folder`), no temporary file exists, and the in-memory preferences are unchanged; an accepted write is stored and returned exactly; a save that fails (the preferences path made a directory) reports the failure and leaves the in-memory layout unchanged; a D1 save (geometry through `save_preferences`, the chosen folder, launch resolution) after an accepted write keeps the stored layout; `read_layout` returns exactly `{layout, stored}` with `layout` exactly its four fields, the defaults `{"version":1,"panel_open":false,"panel_surface":"core","panel_width":320}` with `stored: false` when none is stored, and performs no file write (an absent file stays absent) (FR-021, FR-022, FR-036, SC-017)
- [X] T008 **Allowed D1 assertion change 1 of 2.** In `desktop/src-tauri/src/commands.rs` (after T007, same file), change only `const CONTRACT: [&str; 9]` to `[&str; 11]` by adding `"read_layout"` and `"write_layout"`, and its doc comment to cite `specs/004-workbench-shell/contracts/native-operations.md`; no other line of the D1 tests changes (SC-001, SC-016, FR-037)
- [X] T009 [P] **Allowed D1 assertion change 2 of 2.** In `desktop/e2e/release-manifest.mjs`, change only `commands.length !== 9` to `!== 11` and the comments that say "nine" to "eleven", citing `specs/004-workbench-shell/contracts/native-operations.md`; every other check (one allow/deny pair per command, only the `main` capability, the recorded `core:` minimum, no plugin permission, the `e2e` build differing only by `e2e_report`, its self-check) stays as it is (SC-001, SC-016, FR-037)
- [X] T010 [P] Add the integration test `desktop/src-tauri/tests/layout.rs`: through the library's public API, an accepted `write_layout` leaves on disk a file whose `version`, `window` and `last_selected_folder` equal what was there before and whose `layout` is the value written; a refused write leaves the file on disk byte-identical (FR-036, SC-017)

### Native implementation

- [X] T011 In `desktop/src-tauri/src/prefs.rs` (after T005, T006), add `LayoutPreference` (`version: u32`, `panel_open: bool`, `panel_surface` enum `core|diagnostics|shortcuts`, `panel_width: u32`), `validate_layout` implementing rules 1–7 in order before anything else (rule 1: the `layout` argument, serialised as compact JSON (`serde_json::to_vec`), is at most 1024 bytes), `Stored { preferences: Preferences, layout: Option<LayoutPreference> }`, `load_stored` (D1's `load` rules for the three fields, the layout read leniently and on its own from the same text) and `save_stored`. D1's `save` and `save_stored` share one private writer (temporary file, then rename), so there is one atomic write path and `save` stays in use; keep `Preferences`, `load` and `save` unchanged in fields, signatures and behaviour; add no compiler warning
- [X] T012 In `desktop/src-tauri/src/commands.rs` (after T008, T011), hold `Mutex<Stored>` in `Desktop` with `Desktop::new`'s signature unchanged; keep `preferences()` and `save_preferences()` signatures and route them, the launch resolution (`commands.rs:76-82`) and `choose_workspace` (`commands.rs:207-210`) through `save_stored` so every D1 save — including the geometry save on close (`lib.rs:250-251`, `:282`) — keeps the layout; add `Desktop::read_layout` (reads memory only, never writes) and `Desktop::write_layout` (applies rule 1 — the `layout` argument, serialised as compact JSON (`serde_json::to_vec`), is at most 1024 bytes — then validates completely, then under the same lock builds the new `Stored`, saves through `save_stored`, and commits to memory only if the save succeeded) and the two `#[tauri::command]` handlers `read_layout` and `write_layout`, each returning through the test build's `recorded(name, args, result)` (`commands.rs:106-117`) for every result, refusals and failures included
- [X] T013 In `desktop/src-tauri/src/command_names.rs` set `COMMANDS: [&str; 11]` adding `read_layout` and `write_layout`; register both in the release and the `e2e` handler lists of `desktop/src-tauri/src/lib.rs`; grant exactly `allow-read-layout` and `allow-write-layout` in addition to D1's nine in `desktop/src-tauri/capabilities/main.json`, and change its `description` from "the nine app commands of contracts/native-bridge.md" to the eleven of `specs/004-workbench-shell/contracts/native-operations.md` (after T012; FR-030, FR-037)
- [X] T014 Run `cargo test`, `cargo test --features e2e --lib e2e::tests` in `desktop/src-tauri` and `npm run -w apps/desktop release-manifest`: T005–T010 and every D1 native test pass; the release manifest shows exactly eleven allow/deny pairs (SC-016)

### Native mutation checks (each must fail its test, then be restored exactly)

- [X] T015 Mutation 1: in `Desktop::write_layout` (`desktop/src-tauri/src/commands.rs`) save before validating; confirm T007's byte-identical refusal test fails; restore and re-run green (SC-017)
- [X] T016 Mutation 2: in `validate_layout` (`desktop/src-tauri/src/prefs.rs`) remove, one at a time, the size limit, the unknown-field rule, the width range and the surface set; confirm each makes the matching T005 test fail; restore and re-run green (FR-036)
- [X] T017 Mutation 3: make the `layout` read in `load_stored` strict (a bad layout fails the whole file); confirm T006's lenient-load test fails; restore and re-run green (FR-023, SC-009)
- [X] T018 Mutation 4: (a) add a twelfth name to `COMMANDS` in `desktop/src-tauri/src/command_names.rs` and confirm that the `CONTRACT` tests (`the_command_constant_names_nothing_outside_the_contract`, `the_command_constant_is_exactly_the_contract`) and `release-manifest` fail; (b) separately remove `allow-write-layout` from `desktop/src-tauri/capabilities/main.json` and confirm that D1's `the_main_capability_grants_only_the_commands` (`commands.rs:452`) and `release-manifest` fail; restore each and re-run green (SC-016)

### Shared and window foundations

- [X] T019 [P] Add `packages/commands/test/palette-selection.test.ts` (new file) for a pure palette selection rule: the highlight is `0` after every query change, `-1` when there are no results, and moves within the results on next/previous (data-model §7; FR-013)
- [X] T020 Add the pure palette selection export to `packages/commands/src/index.ts` (after T019), additive only: no existing export, signature or behaviour changes; `apps/tui/**` is not touched (FR-030; research R8)
- [X] T021 [P] Extend `desktop/test/fake-native.ts` additively with `read_layout` (returns a seeded value, by default `{}` exactly as its current default branch does) and `write_layout` (stores the value, can be told to refuse the next write with a reason, records calls); every existing case and the default branch stay as they are
- [X] T022 [P] Add `desktop/test/layout.test.ts` for the pure layout function of data-model §4, which takes the shell's measured width `w` as a fractional number of logical pixels, unrounded: `compact` is `w < 900`, so 899.2 and 899.99 are compact and 900.0 is not; `room` and the shown width at 520, 899.2, 899.99, 900.0 and 1600 with a stored width of 240, 320 and 960; beside versus covering; a stored width wider than the room is shown limited and never rewritten; the transitions of data-model §4 (FR-025, FR-026)
- [X] T023 Implement `desktop/src/shell/layout.ts` (after T022): the pure function of data-model §4 over a fractional width, with no rounding before the comparison with 900
- [X] T024 [P] Add `desktop/test/keys.test.ts`: `mod` is Command on macOS and Control on Windows and Linux (platform injected); key naming for `mod+k`, `mod+1`…`mod+3`, `mod+/`, `mod+shift+m`, `f6`, `shift+f6`, `escape`, `enter`; punctuation named by `event.key` whether or not the layout needed Shift (`/` produced as Shift+7 still names `mod+/`), letters and digits keeping their Shift state; the reserved-key test — no registry binding is Tab, Shift+Tab, an unmodified printable key, a text-editing movement or selection key, mod+A/C/X/V/Z/Y, mod+Shift+Z, mod+W, mod+Q, mod+M, mod+H, Cmd+., Alt+F4, Ctrl+Alt+arrows, mod+R, F5, mod+plus, mod+minus or mod+0; inside a text field only modified keys and F6 reach the shell, except Enter and Escape in the composer (FR-017; contracts/workbench-shell.md)
- [X] T025 Implement `desktop/src/shell/keys.ts` (after T024)

**Checkpoint**: eleven operations, validated and atomic, proven by native tests and four mutation checks; shared pieces ready.

---

## Phase 3: User Story 1 — Work in a coherent workbench around the conversation (P1) 🎯 MVP

**Goal**: four regions around D1's unchanged conversation and views; the rail offers exactly the four D2 surfaces.

**Independent test**: launch against the scripted Core; the rail, main area, side panel and status bar are present and every D1 flow passes inside the shell.

### Tests

- [X] T026 [P] [US1] Add `desktop/test/shell.test.tsx`: in every state (ready, starting, handshaking, checking, restarting, failed, unconfigured, stopping, no workspace) the four landmarks — `navigation` named "Workbench", `main`, `complementary` named after its surface when open, `contentinfo` with a `status` live region — and D1's failure, "Closing…", no-workspace and unconfigured views inside `main`; exactly one `[data-testid="status-strip"]` with D1's `data-state`, `.status-state` and `.status-workspace` text, provider, model, configured and the palette control (FR-001, FR-003); the rail lists exactly Conversation, Core, Diagnostics, Keyboard shortcuts and the palette control, each with a name and an icon, the active one marked with `aria-current` (FR-004, FR-006); choosing a surface by the rail shows it — the conversation in `main`, the others in the side panel — and choosing the shown side-panel surface closes the panel (FR-007)
- [X] T027 [P] [US1] Add `desktop/test/boundaries.test.tsx`: the rail, the palette's results in every state, and every registry command id, title, keyword and binding contain no entry for an editor, file tree, workspace browsing, terminal, agent, task, delegate, session panel, history, installer, update, credential or API key entry, and no quit, reload-window or open-log-folder command (FR-005, FR-031, SC-012)
- [X] T028 [US1] Add the real-WebView scenario `desktop/e2e/scenarios/shell.ts` (new file), registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry `shell` in `desktop/e2e/setups.mjs` (additive): landmarks present (the shell's `main` is D1's `main[data-testid="window"]`, and there is only one `main`); a prompt sent from the composer streams in `main`; the failure view appears inside the shell after the third crash and the rail and status bar stay usable; one status strip, still "Ready" with D1's labels (FR-001, FR-002, FR-003)

### Implementation

- [X] T029 [US1] Implement `desktop/src/shell/Shell.tsx` and `desktop/src/shell/Rail.tsx`: the four regions and landmarks, the main area being D1's existing `<main data-testid="window">` (no second `main`); the rail's four surface buttons and the palette control; no other entry
- [X] T030 [P] [US1] Implement `desktop/src/shell/StatusBar.tsx`: the `contentinfo` region rendering D1's `desktop/src/view/StatusStrip.tsx` unchanged and exactly once, with the props D1 passes today (model and workspace from the session projection in the ready and checking states, status only otherwise), the palette control, and the polite live status for the Core state
- [X] T031 [P] [US1] Implement the base of `desktop/src/shell/SidePanel.tsx`: open and closed, the surface host, the `complementary` landmark named after its surface (sizing in T072)
- [X] T032 [US1] Mount the shell in `desktop/src/app.tsx` (after T029–T031): D1's views in D1's `main`; `desktop/src/view/SessionView.tsx` and the non-ready branch of `App` stop rendering their own `StatusStrip` so the status bar's is the only one; D1's connection, kept recovery facts and diagnostics fetching unchanged
- [X] T033 [US1] Add the shell layout to `desktop/src/styles.css`: regions as a grid, colours only from the design tokens (`desktop/src/theme.ts`), a visible focus ring from `border.focused`, no animation under `prefers-reduced-motion: reduce`
- [X] T034 [US1] Run `npm run -w apps/desktop test` (every D1 window test unedited and green, T026–T027 green), `npm run -w apps/desktop typecheck`/`lint` via the root scripts, and the `shell` scenario plus every D1 scenario with `npm run -w apps/desktop e2e`

**Checkpoint**: the MVP shell works and D1 is intact.

---

## Phase 4: User Story 2 — Find and run any action from a command palette (P1)

**Goal**: a palette over the one registry, listing exactly the commands that apply.

**Independent test**: open the palette in the ready, failed and unconfigured states; it lists exactly what applies; Enter runs with the button's effect; Escape returns focus.

### Tests

- [X] T035 [P] [US2] Add `desktop/test/palette.test.tsx`: mod+K and the palette control open it with the input focused; results are `registry.search(query, context)` with group and shortcut; typing narrows and ranks; the highlight returns to the first result after every query change; Enter and a click close it and run the command through `registry.run` with exactly the effect of its button or key (same session function or native call recorded); Escape and a click outside close it without running anything and return focus to the opener; a Core restart while it is open updates the list and runs nothing (FR-011, FR-013, FR-014)
- [X] T036 [P] [US2] Add `desktop/test/palette-states.test.tsx`: for each of the eight states of SC-004 (ready, starting, checking, restarting, failed, unconfigured, closing, no workspace) the palette lists exactly the commands whose "Enabled when" rule in contracts/workbench-shell.md holds — zero that do nothing, zero missing; "Closing…" lists only `app.quit_now` and layout and view commands (FR-012, FR-015, SC-004)
- [X] T037 [P] [US2] Add `desktop/test/palette-ranking.test.ts`: for every command of the catalogue and every word of its title, typing its first one, two and three letters places it among the first three results, and Enter runs the highlighted result (SC-003)
- [X] T038 [P] [US2] Add `desktop/test/gates.test.tsx`: every command that reaches the Core (`conversation.send`, `conversation.cancel`, `mode.*`, `workspace.change`, `core.check_again`, `core.retry`, `app.quit_now`) is not enabled and sends nothing to the Core or the native side while `session.gated` holds (not ready, wake check pending, session being read, connection not ready) or its D1 precondition fails — from its button, its shortcut and the palette alike; the Core panel's, the status bar's and the failure view's forms of change workspace, check again and try again are the same command ids (FR-010, FR-029)

### Implementation

- [X] T039 [US2] Register the 25-command catalogue of contracts/workbench-shell.md — ids, titles, groups, keywords, bindings and "Enabled when" rules — in the window's one registry: extend `desktop/src/commands.ts` so `commands` holds them with a context that extends `ConversationContext` additively (the composer's calls keep working; `COMMAND_IDS` stays exactly `{send, cancel}`; D1's `enter` and `escape` bindings stay first, so the composer's `forKey("escape")` still resolves to Cancel), with the D2 ids in `WORKBENCH_COMMAND_IDS` in the new `desktop/src/shell/commands.ts`
- [X] T040 [US2] Route D1's buttons for change workspace, check again, try again, Quit now and the mode choices (`desktop/src/view/StatusStrip.tsx`, `FailureView.tsx`, `SetupNotice.tsx`, `ClosingView.tsx`, `ModeControl.tsx`) through `registry.run` with the same command ids, keeping their text, `data-testid` values and behaviour, and every Core-bound run going through D1's existing session functions and native operations (after T039)
- [X] T041 [US2] Implement `desktop/src/shell/Palette.tsx`: a modal dialog with a combobox and a listbox over `registry.search`, the shared selection rule (T020), the result count announced once, running through `registry.run`, focus returned on close
- [X] T042 [US2] Add the real-WebView scenario `desktop/e2e/scenarios/palette.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs` (after T028): mod+K, type "dia", Enter opens diagnostics; a click runs a result; after a crash the palette lists "Try again" and not "Send"; from the unconfigured home it lists "Check again"; while closing it lists "Quit now"
- [X] T043 [US2] Mutation 5: make the palette list `registry.all()` instead of honouring `enabled`; confirm T036 fails; restore and re-run green
- [X] T044 [US2] Mutation 6: let one Core-bound command (`conversation.send`) run while `session.gated` holds; confirm T038 fails; restore and re-run green

**Checkpoint**: every action is reachable from the palette, and only when it works.

---

## Phase 5: User Story 3 — Operate everything with the keyboard, accessibly (P1)

**Goal**: full keyboard operation, visible focus, no trap, focus return, announcements.

**Independent test**: keyboard only through every region and overlay; focus visible and returned; automated accessibility check with no violation.

### Tests

- [X] T045 [P] [US3] Add `desktop/test/focus.test.tsx`: Tab and Shift+Tab move through every interactive element of every visible region in a stable order (rail, main, side panel, status bar) with no trap; F6 and Shift+F6 cycle rail → main → side panel (when open) → status bar → rail; opening the palette or a panel moves focus into it; closing returns focus to the opener, or to the composer if the opener is gone, or to `main`; Escape precedence — with the palette open over a covering panel and a busy turn, one Escape closes only the palette; the next closes only the covering panel; the next, in the composer, cancels exactly once (one `session.cancel`); with the panel beside, Escape in the composer cancels and leaves the panel open; no Escape or Enter in the composer is handled twice (FR-018, FR-019, SC-005)
- [X] T046 [P] [US3] Add `desktop/test/coverage.test.tsx`: for every command of the catalogue there is a mouse path (a rail, panel, composer or status-bar control, or a palette entry) and a keyboard path (a binding or the palette), and every binding resolves to a command (FR-016, SC-002)
- [X] T047 [P] [US3] Add `desktop/test/announce.test.tsx`: the Core state change, a panel opening (its name) and the palette's result count are each announced once in a live region; every region and control has an accessible name; under a `prefers-reduced-motion: reduce` media match the shell marks itself to disable animation (FR-020; the real-WebView and operating-system evidence is T094)
- [X] T048 [P] [US3] Add `desktop/test/shortcuts-panel.test.tsx`: the keyboard shortcuts reference lists every binding of the registry, read from the registry, with its command title and the platform's modifier name (Cmd on macOS, Ctrl elsewhere), and every listed shortcut runs its command (US3 scenario 4)
- [X] T049 [US3] Add an accessibility helper to the test build's scenario runner `desktop/e2e/runner.ts` (additive): bundle `axe-core` (T004), run it on the document restricted to the WCAG 2.1 A and AA rule tags, and fail the scenario on any violation with its rule ids and targets
- [X] T050 [US3] Add the real-WebView scenario `desktop/e2e/scenarios/keyboard.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs` (after T042): keyboard events dispatched in the page traverse every region; each focused element's computed outline uses the `border.focused` colour; F6 cycles; the palette and each panel open and close by keys with focus returned; Escape follows the precedence of contracts/workbench-shell.md. Its evidence is recorded as "real WebView, dispatched key events" — not as delivery by the operating system, which is T093 (FR-018, FR-034)

### Implementation

- [X] T051 [US3] Implement `desktop/src/shell/focus.ts`: the focus-return stack (data-model §8) and the region cycle, used by `Shell.tsx`, `Palette.tsx` and `SidePanel.tsx`
- [X] T052 [US3] Add the keyboard dispatcher to `desktop/src/shell/Shell.tsx` (after T029): window key events named by `shell/keys.ts`, resolved with `registry.forKey`, run only when enabled, the text-field rule applied, reserved keys never intercepted; Escape resolved in the order palette → covering panel → composer, at most one action per press; events the composer handled (`defaultPrevented`) and Enter or Escape targeted at the composer are ignored
- [X] T053 [US3] Implement `desktop/src/shell/ShortcutsPanel.tsx` from the registry's bindings, and the announcements and accessible names of T047 in `Shell.tsx`, `StatusBar.tsx` and `SidePanel.tsx`
- [X] T054 [US3] Mutation 8: skip focus return when an overlay closes (`desktop/src/shell/focus.ts`); confirm T045 fails; restore and re-run green
- [X] T055 [US3] Mutation 9: bind an unmodified printable key (for example `k` to `palette.open`); confirm T024's reserved-key test fails; restore and re-run green
- [X] T093 [US3] Platform key-delivery evidence (after T050, T052, T055). It runs its operating-system-level steps only when `COMODOR_E2E_OS_LEVEL=1`, which only the CI `desktop` job sets; without it the scenario reports `outcome: "not-run"` ("operating-system-level evidence disabled"), which is never evidence. Add to `desktop/src-tauri/src/e2e.rs` (test build only, with unit tests in its `#[cfg(test)]` module, additive) a `focus-window` act that brings the main window to the foreground, and the test-build query `window` (a new arm of the `query` match in `e2e_report`, `desktop/src-tauri/src/e2e.rs:156-170`, additive) that returns, for the main window, its `inner` and `outer` size in physical pixels, its `scale_factor`, and the same two sizes in logical pixels rounded to whole numbers; for its current monitor, the work area in physical pixels, the monitor's own `scale_factor`, and the work area in logical pixels rounded to whole numbers (from the pinned Tauri's monitor API; if that version exposes no work area, the monitor's size, reported as `work_area_source: "monitor"`; if `current_monitor()` returns none, `monitor: null`); and whether the window is `focused`. Add the scenario `desktop/e2e/scenarios/key-delivery.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs`, and a `press-keys` checkpoint in `desktop/e2e/harness.mjs` (additive) that injects keys into the application, whose pid the harness holds: Windows `SendInput` through PowerShell, checking immediately before every `SendInput` that `GetForegroundWindow`'s process is the application's pid and stopping otherwise; macOS `CGEventPostToPid` to the application's pid through a Swift helper; Linux, on the harness's own `xvfb` display only — it has no window manager, so `windowactivate` is not used: `xdotool search --sync --pid <pid>` finds the window, `xdotool windowfocus --sync <id>` gives it the input focus, before every key `xdotool getwindowfocus` must return that window (otherwise the injection stops), and the key is sent with `xdotool key` without `--window` (events sent to a window with `--window` are synthetic and GTK may ignore them). Sequence: (1) preflight — the injection tool is present (PowerShell with `user32`; the Swift helper builds; `xdotool` on `PATH` with the harness's `DISPLAY`), on macOS both `AXIsProcessTrusted()` and `CGPreflightPostEventAccess()` are true; send `focus-window` (on Linux followed by `windowfocus --sync` above) and wait until the `window` query reports `focused` (waiting with the runner's `waitFor` under the scenario's failure deadline until the query reports it — never a fixed sleep); on Windows the foreground pid matches; any failure here is `capability-unavailable` with its reason; (2) delivery probe — the scenario adds a test-only text field (never product markup), focuses it, the harness injects the plain letter `q`, and the page waits for the field's value to become `q`; if it does not, `capability-unavailable` ("injected keys do not reach the WebView"); (3) only then, with the probe removed and focus in the rail, inject F6, Shift+F6, mod+K and Escape one at a time, each judged by the state the page observes afterwards (the region focused, the palette open, the palette closed with focus returned), waiting for that state under the deadline; a missing result is `product-failure` (a WebView that swallows the key counts as product failure, since the shortcut then does not work). The scenario's result carries `outcome`: `verified`, `product-failure`, or `capability-unavailable` with a `reason`; only `verified` passes, and `capability-unavailable` is NOT VERIFIED and an acceptance blocker, reported apart from a product failure. In `.github/workflows/ci.yml`, in the `desktop` job only: add `xdotool` to the existing Linux setup step; set `COMODOR_E2E_OS_LEVEL: "1"` in the job's `env`; and give every step after "In-application scenarios" that does not already run regardless — "Lifetime", "Credential canary, every flow", "Release command list", "Folder chooser tools (Linux)" (keeping its `runner.os` condition, combined as `${{ !cancelled() && runner.os == 'Linux' }}`), "Real folder chooser evidence" and any evidence upload without an `if:` — `if: ${{ !cancelled() }}`, so their evidence is still produced when `e2e` fails, including on `capability-unavailable`; the job's result stays failed, because the failed `e2e` step still fails the job (FR-011, FR-017, FR-018, FR-034)
- [X] T094 [US3] Reduced-motion evidence (after T053, T093). It runs its operating-system-level steps only when `COMODOR_E2E_OS_LEVEL=1`, which only the CI `desktop` job sets; without it the scenario reports `outcome: "not-run"` ("operating-system-level evidence disabled"), which is never evidence; the stylesheet check below runs in every case. Add the scenario `desktop/e2e/scenarios/reduced-motion.ts`, registered in `desktop/e2e/scenarios/index.ts` and with `SETUPS` entries in `desktop/e2e/setups.mjs`, plus a setup option in `desktop/e2e/setups.mjs` and `desktop/e2e/harness.mjs` (additive) that, before the launch: (1) records the original setting — Windows `SystemParametersInfo(SPI_GETCLIENTAREAANIMATION)`, macOS `defaults read com.apple.universalaccess reduceMotion` (noting whether the key was absent) and the effective value from the `NSWorkspace` helper of step (3), Linux nothing global; (2) sets it — Windows `SPI_SETCLIENTAREAANIMATION` off with `fWinIni = SPIF_SENDCHANGE` only, never `SPIF_UPDATEINIFILE`, so it is never saved to the profile; macOS `defaults write com.apple.universalaccess reduceMotion -bool true`; Linux `gtk-enable-animations=false` in `gtk-3.0/settings.ini` under a per-run `XDG_CONFIG_HOME` passed to the application's environment only (the test build's data folder comes from `COMODOR_DESKTOP_DATA_DIR`, `lib.rs:195-199`, so it does not move); (3) reads back the effective value — Windows with `SystemParametersInfo(SPI_GETCLIENTAREAANIMATION)`; macOS with a Swift test helper under `desktop/e2e/` that prints `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion` (the value WebKit uses; a successful `defaults` write alone is not enough); Linux the per-run settings file — and a refused write or an effective value that differs is `capability-unavailable` ("the operating system did not apply the preference"); and (4) in a `finally` that runs after a pass, a failure or the scenario's deadline, restores the original — Windows the recorded value with `SPIF_SENDCHANGE` only; macOS the recorded value, or `defaults delete com.apple.universalaccess reduceMotion` if the key was absent; Linux removes the per-run settings folder — and confirms the restoration with the same effective read-back (on macOS the `NSWorkspace` helper must report the original effective value); a restoration that cannot be confirmed fails the run loudly. In the page, on each platform: the stylesheet's `prefers-reduced-motion: reduce` rule removes the shell's transitions (CSSOM check); with the preference set, if `matchMedia("(prefers-reduced-motion: reduce)").matches` is false the outcome is `capability-unavailable` ("the WebView does not expose the preference"); if it is true but the panel or the palette has a computed transition duration other than `0s`, `product-failure`; otherwise `verified`. The scenario's result carries `outcome`: `verified`, `product-failure`, or `capability-unavailable` with a `reason`; only `verified` passes, and `capability-unavailable` is NOT VERIFIED and an acceptance blocker, reported apart from a product failure (FR-020)
  - *Recorded (CI, e087ec5):* `verified` on all three platforms. On the macOS runner the preference was already on before the run (original `reduceMotion` = 1), so there the evidence shows the window honouring the preference while it is on, not a change from off to on; Windows (client-area animation off from on) and Linux (a per-run settings file) show the change itself.

**Checkpoint**: keyboard-only operation works, verified with dispatched events in the real WebView and with keys delivered by each operating system (T093); reduced motion verified (T094).

---

## Phase 6: User Story 4 — Arrange panels, and find them as left (P2)

**Goal**: one layout restored after reload, Core restart, workspace change and relaunch; reset to defaults.

**Independent test**: arrange; reload, restart, change workspace, relaunch — restored each time; corrupt the stored layout — defaults; an invalid write is refused and the file is unchanged.

### Tests

- [X] T056 [P] [US4] Add `desktop/test/preference.test.tsx`: `read_layout` is called once per page load and never delays or reorders `connect`; an answer that is not exactly `{layout, stored}` with a valid layout (`{}`, an error, a refusal, a wrong shape) means the defaults without an error; `write_layout` is called after each completed change — open, close, surface choice, drag end, each keyboard resize step, Reset layout — and never per pointer move; a refused write keeps the window's layout, shows one quiet notice, and the next change writes again; Reset layout writes the defaults once; the layout survives a Core restart, a new `workspace_id` and a new client; no Core request contains a layout value (FR-021, FR-022, FR-023, FR-024)
- [X] T057 [US4] Extend `desktop/e2e/setups.mjs` and `desktop/e2e/harness.mjs` additively (after T094): (a) a setup may seed `preferences.json` with exact text; (b) a `read-preferences` checkpoint returns the current bytes of `preferences.json` (base64) and whether `preferences.json.tmp` exists, while the application runs; (c) a setup option `relaunch: { workspace: "same" | "other", scenario: "<name>" }` makes the harness, after the first launch has ended itself, launch the application again with the same `COMODOR_DESKTOP_DATA_DIR` folder (`harness.mjs:249`, `:286`) and the same or a new workspace, running the named scenario, the run passing only if both launches pass; (d) the Linux wrapper (`harness.mjs:43-46`) gains the arguments `-s "-screen 0 1920x1080x24"` for `xvfb-run`
- [X] T058 [US4] Add the real-WebView scenario `desktop/e2e/scenarios/layout.ts`, registered in `desktop/e2e/scenarios/index.ts` and with `SETUPS` entries in `desktop/e2e/setups.mjs` (after T057): open the Core panel and resize it; reload — restored; crash and restart — kept; change workspace — kept; take a `read-preferences` checkpoint, invoke an invalid `write_layout` from the page (refused with its reason), take a second `read-preferences` checkpoint immediately, and assert the two byte strings are identical and no temporary file exists — all before the application closes, because D1 saves the window geometry on close (`lib.rs:250-251`); seeded unreadable, other-version and out-of-range layouts each yield the defaults with D1's `window` and `last_selected_folder` intact (FR-021, FR-023, FR-036, SC-008, SC-009, SC-017)
- [X] T059 [US4] Add the relaunch cases as new exported scenarios in `desktop/e2e/scenarios/lifetime.ts`, registered in `desktop/e2e/scenarios/index.ts`, with exactly two `SETUPS` entries in `desktop/e2e/setups.mjs`, named `layout-relaunch-same` and `layout-relaunch-other`, marked `lifetime` and using T057's `relaunch` option (`workspace: "same"` and `"other"` respectively; additive; after T058; `desktop/e2e/lifetime.mjs` unchanged): arrange a layout, quit, launch again with the same data folder in the same workspace and in another one, and find it restored; the file after exit holds the layout and D1's values (FR-021, FR-024, SC-008)

### Implementation

- [X] T060 [US4] Implement `desktop/src/shell/preference.ts`: one `read_layout` per page load through the window's `NativeApi`, independent of the connection; validation of the answer's shape; `write_layout` after each completed change; the quiet notice on refusal or failure
- [X] T061 [US4] Wire the stored layout and `layout.reset` into `desktop/src/shell/Shell.tsx` and `desktop/src/shell/SidePanel.tsx` (after T052, T060): the panel closed until the read answers, then restored

**Checkpoint**: layout persistence works across every boundary of SC-008.

---

## Phase 7: User Story 5 — See the Core and its diagnostics as reported (P2)

**Goal**: a Core panel and a diagnostics panel that show only what was reported for the current Core.

**Independent test**: compare every value with the reports; restart and change workspace with the panel open — values cleared, never kept; adversarial diagnostics inert.

### Tests

- [X] T062 [P] [US5] Add `desktop/test/core-panel.test.tsx`: state, workspace (Core-reported, native until it answers), Core name and version, protocol version, provider, model, configured state and restart count of the limit are shown exactly as the native status, the handshake and the Core's `workspace.get`/`model.get` report them, the failure only when failed; each unreported value reads "not reported yet"; a new client, a status naming another Core, or a new `workspace_id` clears every Core value at once and none comes back until reported again; actions shown only when they apply; a long path, model name or Core identity is truncated visually with the whole value on focus and hover (FR-008, FR-010, FR-028, SC-010)
- [X] T063 [P] [US5] Add `desktop/test/diagnostics-panel.test.tsx`: the native diagnostic tail is shown as inert text — `\x1b[2J`, `\x1b[H` and an OSC title sequence as visible symbols, `<script>` and `<img onerror>` as text, `javascript:` not a link, `[Connected]` and `[Ready]` changing no indicator; fetched on open, on refresh and whenever the Core fails; available in every state (FR-009, FR-032)
- [X] T064 [US5] Add the real-WebView scenario `desktop/e2e/scenarios/core-panel.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs` (after T059): with the Core panel open, a crash and restart clears the values and shows the new Core's; a workspace change does the same; the diagnostics panel shows the scripted Core's adversarial output inert (FR-008, FR-009, FR-028, SC-010)

### Implementation

- [X] T065 [US5] Implement `desktop/src/shell/reports.ts`: the Core values of data-model §5 keyed to the current native status and client, cleared on a new client, another Core or a new `workspace_id`
- [X] T066 [P] [US5] Implement `desktop/src/shell/CorePanel.tsx` over `reports.ts`, with its actions as registry commands
- [X] T067 [P] [US5] Implement `desktop/src/shell/DiagnosticsPanel.tsx` with D1's inert text rendering (`desktop/src/view/InertText.tsx`) and `diagnostics.refresh`
- [X] T068 [US5] Mutation 7: keep the previous Core's values across a restart in `desktop/src/shell/reports.ts`; confirm T062 fails; restore and re-run green

**Checkpoint**: Core facts are shown only as reported.

---

## Phase 8: User Story 6 — Use the workbench in a narrow window (P3)

**Goal**: covering panel below 900; everything essential visible at 520 × 400; no horizontal scroll.

**Independent test**: resize to the minimum, 899, 900 and a wide size; composer, Send, Core state and palette control visible, no horizontal scroll, every command reachable.

### Tests

- [X] T069 [P] [US6] Add `desktop/test/side-panel.test.tsx`: beside mode above 900 and covering mode below; covering closes on Escape and a click outside; widening past 900 returns it beside at its remembered width; the edge is a focusable `separator` with its current, minimum and maximum width; with it focused, Left widens and Right narrows in 32 px steps within the range, Home and End go to the minimum and maximum; arrow keys act nowhere else; a drag writes once when it ends (FR-025, FR-026)
- [X] T070 [US6] Add to `desktop/src-tauri/src/e2e.rs` (`act_for_harness`, test build only) a `resize` act that sets the main window's inner size in physical pixels — `set_size(tauri::PhysicalSize::new(width, height))` — from the harness's `{ act: "resize", width, height }` reply (the scenario computes physical sizes from the scale factor, so every requested size is representable), with a unit test in its `#[cfg(test)]` module (additive), and the harness side of the act in `desktop/e2e/harness.mjs` (after T057, T093). The act returns nothing (acts run on their own thread after the reply); its effect is observed through T093's `window` query (its physical `inner` size), waiting with the runner's `waitFor` under the scenario's failure deadline until the query reports it — never a fixed sleep; no release operation or permission is added (research R11)
- [X] T071 [US6] Add the real-WebView scenario `desktop/e2e/scenarios/narrow.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs` (after T064, T070). First read the `window` query and take the window's scale factor `s`. If it reports `monitor: null`, the outcome is `capability-unavailable` ("no monitor reported"). All four sizes are computed in physical pixels from `s` and applied with `PhysicalSize`, so fractional scaling never makes a size unrepresentable: the minimum `ceil(520·s)` × `ceil(400·s)`; just below the threshold, width `ceil(900·s) − 1` (a logical width in [900 − 1/s, 900)); at or above it, width `ceil(900·s)` (in [900, 900 + 1/s)) — at an integer scale exactly 899 and 900 — both with height `ceil(600·s)`; and a wide size whose width is the smaller of `floor(1280·s)` and the physical work-area width minus the physical frame width (`outer` − `inner`), required to be at least `ceil(1000·s)`, and whose height is the smaller of `floor(720·s)` and the physical work-area height minus the frame height, required to be at least `ceil(600·s)`. Each size plus the frame must fit the physical work area. If one does not, the outcome is `capability-unavailable` with the work area and `s` it read ("the runner's display is too small") — NOT VERIFIED, an acceptance blocker, kept apart from a product failure, never fixed by going below these bounds; fractional scaling is never `capability-unavailable`. For each size: send the `resize` act; wait until the query's physical `inner` equals the request (waiting with the runner's `waitFor` under the scenario's failure deadline until the query reports it — never a fixed sleep); then assert that the page's `innerWidth` and `innerHeight` are each within 1 px of the physical size divided by `s`, and that the shell's measured width (`data-width`, T072) is within 1 px of the physical width divided by `s`; judge the threshold by that measured width alone: below the threshold `data-width` < 900 and the panel covers (`data-mode="covering"`), at or above it `data-width` ≥ 900 and the panel sits beside (`data-mode="beside"`); a size that does not settle, a page size or measured width outside the 1 px bound, or a mode that contradicts the measured width is `product-failure` with the values observed; `document.documentElement.scrollWidth` does not exceed its `clientWidth` and no region scrolls horizontally; the composer, Send, the Core state and the palette control lie inside the viewport; focus — F6 cycles the regions, opening the covering or beside panel moves focus into it, Escape on a covering panel returns focus to its opener; keyboard resize on the focused edge stays in range. For each size the result records the physical size requested and applied, `s`, the measured shell width, the page's `innerWidth`/`innerHeight`, and the mode, together with the work area and the frame (after T072 for the measured width; FR-025, FR-026, FR-027, FR-034, SC-007)
  - *Found during implementation (CI, macOS):* Tauri reports the title bar inside the window's inner size on macOS (inner = outer = 520 × 400 with a 520 × 368 page). The scenario measures that offset once at the default size and requires it to be zero on Windows and Linux (so their check is unchanged), between 0 and 40 px on macOS, and the same at every size; each page is judged against the requested size less it, and the result records it as `titleBarInInner`. At the minimum window the page on macOS is therefore 368 px tall, and every essential must still be in view there. *Accepted by the owner (spec Clarifications, 2026-10-16); usability at every size added in T096.*

### Implementation

- [X] T072 [US6] Complete `desktop/src/shell/SidePanel.tsx` and the measurement in `desktop/src/shell/Shell.tsx` (after T061): the shell root (`[data-testid="shell"]`, spanning the window, no padding or border) is observed with a `ResizeObserver`, and its `contentRect.width` — a fractional number of logical pixels, never rounded — is the `w` passed to `shell/layout.ts`; the root exposes that value as `data-width` and the resulting mode as `data-mode` (`beside` or `covering`) for the scenarios, beside D1's own `data-` attributes; the splitter, drag, covering mode with Escape and click outside, and the narrow-window rules in `desktop/src/styles.css`

**Checkpoint**: every story is complete.

---

## Phase 9: Polish, cross-cutting checks and SC-001 evidence

- [X] T073 [P] Add `desktop/test/shell-inert.test.tsx`: the adversarial strings of D1's SC-010 in the status bar, the Core panel and the diagnostics panel are inert; Persian and mixed-direction text shows in its own direction (`dir="auto"`) and the layout does not mirror (FR-032; edge cases)
- [X] T074 Add the real-WebView scenario `desktop/e2e/scenarios/accessibility.ts`, registered in `desktop/e2e/scenarios/index.ts` and with a `SETUPS` entry in `desktop/e2e/setups.mjs` (after T071, T094): the T049 checker reports zero WCAG 2.1 A and AA violations in the ready, starting, checking (through the `wake` act), restarting, failed, unconfigured, closing and no-workspace states, with the palette open, with each side-panel surface open, and in covering mode (SC-006, FR-020)
- [X] T075 Extend the credential canary (after T074): add the D2 flows (`shell`, `palette`, `keyboard`, `layout`, `layout-relaunch-same`, `layout-relaunch-other`, `core-panel`, `narrow`, `accessibility`, `key-delivery`, `reduced-motion`) to `FLOWS` in `desktop/e2e/canary-full.mjs` (additive), and add to the harness's canary check in `desktop/e2e/harness.mjs` (additive) assertions that `read_layout` and `write_layout` — including a refused `write_layout` — appear in the recorded bridge commands of the run (T012's `recorded(...)`), that the stored `layout` has exactly its four fields, and that no conversation text of the run appears in `preferences.json` — beside D1's existing zero-occurrence search over every IPC message, every bridge command's arguments and results, WebView storage, the document text, the log and the preferences file (FR-032, FR-037, SC-011)
- [X] T076 Mutation 10: remove the layout operations from the canary run's flows (or skip recording them); confirm T075's coverage assertion fails; restore and re-run green (SC-011)
- [X] T077 [P] Update `docs/desktop-architecture.md`: the workbench shell, the four surfaces, the command palette over the shared registry, the keyboard model, the layout preference in `preferences.json` through `read_layout`/`write_layout`, the eleven native operations (D1's nine kept as history in `specs/003-desktop-foundation/`), and D1's two NOT VERIFIED items carried forward unchanged (FR-035, SC-015)
- [X] T078 Prove offline execution: every D2 setup in `desktop/e2e/setups.mjs` uses the scripted Core or the offline `fake` home; no test reads a provider credential or `.env`; the CI `desktop` job defines no provider secret; record the result (FR-033, SC-013)
- [ ] T079 Run every gate of quickstart §2 and every desktop layer of quickstart §3 locally on Windows on the final tree, without `COMODOR_E2E_OS_LEVEL`, and record the results; compare with T003. `key-delivery` and `reduced-motion` report `not-run` locally and are recorded as "not run locally (operating-system-level evidence disabled)", never as passing evidence; their evidence comes only from the exact-SHA CI run (T089) (SC-001, SC-014)
- [X] T080 **SC-001 test-diff inspection.** Diff every file of the T002 inventory against the base: the only changed existing lines are T008's `CONTRACT` (nine → eleven and its doc comment) and T009's count and comments in `release-manifest.mjs`; every other change is an addition, in a file listed under "Rules every task follows", that changes no existing assertion — the one insertion into an existing expression being T057(d)'s `xvfb-run` screen arguments; no D1 test function or scenario is removed, renamed, skipped (`#[ignore]`, `.skip`, `.todo`) or has an assertion changed; D1's `desktop/test/*.test.ts(x)` files, `desktop/e2e/lifetime.mjs` and `specs/003-desktop-foundation/**` show no diff. Record the file-by-file result
- [X] T081 Verify the exact eleven-operation release set: `npm run -w apps/desktop release-manifest` passes with exactly eleven allow/deny pairs, only the `main` capability, the eleven allow identifiers plus the recorded `core:` minimum, no plugin permission, and the `e2e` build differing only by `e2e_report`; record the output (SC-016, FR-030, FR-031, FR-037)
- [X] T082 Run `npm run -w apps/desktop canary -- --skip-build` over every D1 and D2 flow: zero canary occurrences anywhere searched, both layout operations recorded, the layout four fields and free of conversation text; record the output (SC-011, FR-037)
- [X] T083 Confirm the boundaries of FR-030: `git diff --stat` of the base against HEAD shows no change under `src/comodor/`, `schemas/`, `apps/tui/`, `specs/003-desktop-foundation/`, `src/comodor/protocol/_generated.py` or `packages/protocol/src/generated.ts`; `packages/` changes are additive (T020, and T095's `desktop` mapping and window-only roles in `packages/design-tokens/`, with the `terminal` mapping unchanged); `python tools/protocol-codegen.py --check` and `bun test apps/tui/test/bun/renderer.test.tsx` pass (SC-014)
- [X] T084 Keep the local tooling out of the tracked tree: `git ls-files .specify` prints nothing, `git check-ignore -q .specify/memory/constitution.md` succeeds, `git status --short` shows no `.specify/` path, and no staged or committed path begins with `.specify/` (the constitution 2.0.0 and scripts restored from `427ecca` stay local; current `main` has none tracked)
- [X] T085 Run `git diff --check` and review the whole diff as one decision (Constitution V): no unrelated change, no formatting churn, no new runtime dependency beyond T095's three pinned font packages (owner decision, spec Clarifications 2026-10-15), no generated file edited by hand. Also verify that test-only code cannot reach the release build: the `resize` and `focus-window` acts and the `window` query exist only in `desktop/src-tauri/src/e2e.rs`, which compiles only with `--features e2e` (`lib.rs:12-13`), and nothing else references them outside `#[cfg(feature = "e2e")]`; the scenario runner, `axe-core` and the scenarios load only in `MODE === "e2e"` (`desktop/src/main.tsx:13-15`) and are absent from the release page bundle (search the `npm run -w apps/desktop build` output for `axe-core`, `runScenario` and the scenario names); the key-injection helpers and the reduced-motion setup live only in `desktop/e2e/` and the CI job; `desktop/src-tauri/tauri.conf.json`, the release capability (beyond T013's two permissions), and any macOS entitlements or `Info.plist` settings are unchanged from the base

---

- [X] T095 The owner's reference look (spec Clarifications, 2026-10-15), look only and within D2's surfaces: add the window's finer roles to `packages/design-tokens/src/index.ts` as a window-only list (`WINDOW`, with a `STAND_IN` for themes without them) and an additive `desktop` mapping beside `terminal`, leaving the `terminal` mapping and therefore the committed TUI bundle (`src/comodor/tui/dist`) unchanged, with tests in `packages/design-tokens/test/tokens.test.ts` that every role has a colour and that every text colour reaches WCAG 2.1 AA (4.5:1) on each ground it is drawn on (mutation: the reference's `#8a8a8a` for `text.muted` fails it); switch `desktop/src/theme.ts` to `cssVariables(desktop)`; bundle the pinned fonts through `desktop/src/fonts.ts` (CSP unchanged); restyle `desktop/src/styles.css` (tokens only) and draw icons from `data-icon` in `desktop/src/shell/Rail.tsx`, `StatusBar.tsx` and `SidePanel.tsx`, and tag the mode buttons with `data-mode` in `desktop/src/view/ModeControl.tsx` (additive attribute). No region beyond D2's is added; the reference stays unpublished

## Phase 10: Delivery (exact final commit; PR left open)

- [X] T086 Verify the GitHub identity before any remote action: `gh auth status` and `gh api user --jq .login` print `ifekri`; otherwise stop
- [X] T087 Commit on `004-workbench-shell` with neutral engineering messages and no tool or model attribution or co-author line for any tool (repository rule; CLAUDE.md §57 and the constitution's workflow section); confirm no `.specify/` path is committed (T084); push the branch
- [X] T088 Open the pull request against `main` with a neutral title (for example "Add the desktop workbench shell") and a body containing: the summary; the Surface Impact table with exactly the ten rows TUI, Web UI, CLI / Headless, API / Protocols, Desktop, Channels / Integrations, Docker / Packaged Runtime, Persistence / Shared State, Security / Authorization, Tests / Documentation and only the statuses REQUIRED, UNCHANGED BUT VERIFIED, NOT APPLICABLE, as in the spec; the SC-001 boundary and T080's result; the eleven-operation set; the evidence per layer and per platform, with dispatched key events, platform key delivery (T093) and the reduced-motion preference (T094) reported as separate rows with their `outcome`; any `capability-unavailable` or missing platform named as NOT VERIFIED and an acceptance blocker, never as a pass; the local `not-run` of T079 stated as such; D1's two NOT VERIFIED items; no tool or model attribution
- [ ] T089 Record the exact HEAD SHA; wait for every required CI check on that SHA — lint, the Python matrix, frontend, the renderer on three platforms, `Desktop on ubuntu-latest`, `Desktop on windows-latest`, `Desktop on macos-latest`, packaged — to be green; record per platform the native, window, scenario, lifetime, canary, release-manifest and chooser results — produced even when `e2e` fails, through T093's `if: ${{ !cancelled() }}` steps — the work area, frame, scale factors and sizes `narrow` reports as applied, and the `outcome` of `key-delivery` and `reduced-motion` (each must be `verified`) in the PR body; a `capability-unavailable` outcome leaves that platform's `desktop` job failed and is NOT VERIFIED, as is a platform without recorded evidence; D2 is then incomplete, and the gap is reported as an acceptance blocker, never as green (FR-020, FR-034, SC-001, SC-007, SC-008)
- [ ] T090 Request a fresh Codex review of that exact SHA on the pull request, naming the SHA
- [ ] T091 Classify every review finding (valid and actionable, valid but out of scope, not valid) with evidence; fix every valid actionable finding with a test that fails before the fix; push; reply with the evidence; resolve a thread only after its fix is pushed and CI on the new SHA supports it; then repeat T089–T091 — exact-SHA CI green on all three platforms and a fresh Codex review of the new SHA — after every fix, until a review of the final SHA has no valid actionable finding
- [ ] T092 Report to the owner: final SHA, CI per platform, review state and open-thread count, T080's SC-001 result, the NOT VERIFIED items. Leave the pull request open: do not approve it, do not enable auto-merge, do not merge, do not delete the branch
  - *Recorded gap (PR #64):* the fresh Codex review requested for PR #64's final head `eb5cab449c7588e001c91db618aefc426565dc67` (and for `0d9a438`) failed on the account's Codex usage limit. PR #64 was merged by the owner without it. That head has no Codex review; a review of a later pull request does not cover it.

---

## Dependencies and execution order

### Phases

- **Phase 1** → **Phase 2** → **Phase 3 (US1)** → US2–US6 → **Phase 9** → **Phase 10**.
- US2 (Phase 4), US3 (Phase 5), US4 (Phase 6), US5 (Phase 7) and US6 (Phase 8)
  each need US1's shell; they are ordered by priority, and their shared files
  force the sequence below.
- T093 and T094 keep new IDs (the 92 original IDs are preserved) but run
  inside Phase 5, after T055 and before Phase 6; the shared-file table gives
  their order against T057, T058 and T070.
- Phase 9 needs every story; Phase 10 needs T079–T085 green.

### Shared files (tasks touching one file run in this order)

| File | Tasks, in order |
| --- | --- |
| `desktop/src-tauri/src/prefs.rs` | T005 → T006 → T011 → T016 → T017 |
| `desktop/src-tauri/src/commands.rs` | T007 → T008 → T012 → T015 |
| `desktop/src-tauri/src/command_names.rs`, `lib.rs`, `capabilities/main.json` | T013 → T018 |
| `desktop/src-tauri/src/e2e.rs` | T093 (`focus-window`, `window` query) → T070 (`resize`) |
| `desktop/e2e/release-manifest.mjs` | T009 → T018 |
| `packages/commands/src/index.ts` | T019 → T020 |
| `desktop/src/shell/Shell.tsx` | T029 → T051 → T052 → T053 → T061 → T072 (T071's scenario reads T072's `data-width`; T071 runs green only after T072) |
| `desktop/src/shell/SidePanel.tsx` | T031 → T051 → T053 → T061 → T072 |
| `desktop/src/shell/StatusBar.tsx` | T030 → T053 |
| `desktop/src/shell/Palette.tsx` | T041 → T051 |
| `desktop/src/app.tsx`, `desktop/src/view/SessionView.tsx` | T032 → T040 |
| `desktop/src/commands.ts` | T039 |
| `desktop/src/styles.css` | T033 → T072 |
| `desktop/e2e/scenarios/index.ts` | T028 → T042 → T050 → T093 → T094 → T058 → T059 → T064 → T071 → T074 |
| `desktop/e2e/setups.mjs` | T028 → T042 → T050 → T093 → T094 → T057 → T058 → T059 → T064 → T071 → T074 |
| `desktop/e2e/harness.mjs` | T093 → T094 → T057 → T070 → T075 |
| `desktop/e2e/runner.ts` | T049 |
| `desktop/e2e/canary-full.mjs` | T075 → T076 |
| `.github/workflows/ci.yml` | T093 (`xdotool`; `COMODOR_E2E_OS_LEVEL` in the `desktop` job's `env`) |

### Test-before-implementation pairs

T005/T006 → T011 · T007/T008 → T012 · T009/T010 → T013 · T019 → T020 · T022 → T023 ·
T024 → T025 · T026–T028 → T029–T033 · T035–T038 → T039–T041 · T045–T050 → T051–T053 → T093 → T094 ·
T056–T059 → T060–T061 · T062–T064 → T065–T067 · T069–T071 → T072 · T073–T075 before T079.

### Parallel opportunities

- Phase 2: T005, T007, T009, T010 together; then T019, T021, T022, T024 together.
- US1: T026, T027 together; T030, T031 together.
- US2: T035–T038 together.
- US3: T045–T048 together.
- US5: T062, T063 together; T066, T067 together.
- Phase 9: T073 and T077 alongside other work.

## Implementation strategy

1. **MVP**: Phases 1–3 — the shell around D1 with the eleven-operation native
   set in place and proven. Stop and validate: D1 intact, shell scenario green.
2. **P1 complete**: add US2 (palette) and US3 (keyboard, accessibility).
3. **P2/P3**: US4 (persistence), US5 (Core and diagnostics panels), US6
   (narrow windows).
4. **Evidence**: Phase 9 on the final tree, then Phase 10 on the exact final
   SHA, repeated after every fix.

## Mutation checks (quickstart §4)

| # | Mutation | Task | Test that must fail |
| --- | --- | --- | --- |
| 1 | save before validating | T015 | T007 byte-identical refusal |
| 2 | drop size limit, unknown-field rule, width range or surface set | T016 | T005 validation |
| 3 | strict `layout` load | T017 | T006 lenient load |
| 4 | twelfth name; `allow-write-layout` removed from the capability | T018 | (a) the `CONTRACT` tests and `release-manifest`; (b) D1's `the_main_capability_grants_only_the_commands` and `release-manifest` |
| 5 | palette ignores `enabled` | T043 | T036 eight states |
| 6 | Core-bound command without D1's gate | T044 | T038 gates |
| 7 | Core values kept across a restart | T068 | T062 clearing |
| 8 | no focus return | T054 | T045 focus return |
| 9 | unmodified printable key bound | T055 | T024 reserved keys |
| 10 | layout operations left out of the canary | T076 | T075 coverage assertion |

## Requirement traceability

| Req | Tasks |
| --- | --- |
| FR-001 | T026, T028, T029, T032 |
| FR-002 | T003, T028, T032, T034, T040, T079, T080 |
| FR-003 | T026, T028, T030 |
| FR-004 | T026, T029 |
| FR-005 | T027, T029 |
| FR-006 | T005, T026, T029 |
| FR-007 | T026, T029, T031 |
| FR-008 | T062, T064, T065, T066 |
| FR-009 | T063, T064, T067 |
| FR-010 | T038, T040, T062, T066 |
| FR-011 | T035, T039, T041, T093 |
| FR-012 | T036, T039, T043 |
| FR-013 | T019, T020, T035, T041 |
| FR-014 | T035, T041, T042 |
| FR-015 | T036, T039 |
| FR-016 | T046 |
| FR-017 | T024, T025, T045, T052, T055, T093 |
| FR-018 | T033, T045, T050, T051, T071, T093 |
| FR-019 | T045, T051, T052, T054, T071 |
| FR-020 | T047, T053, T074, T094 |
| FR-021 | T006, T007, T056, T057, T058, T059, T060 |
| FR-022 | T007, T056, T075 |
| FR-023 | T006, T017, T056, T058, T061 |
| FR-024 | T056, T059 |
| FR-025 | T022, T023, T069, T071, T072 |
| FR-026 | T022, T069, T071, T072 |
| FR-027 | T071, T072 |
| FR-028 | T062, T064, T065, T068 |
| FR-029 | T038, T040, T044 |
| FR-030 | T013, T020, T081, T083 |
| FR-031 | T013, T027, T081 |
| FR-032 | T063, T073, T075 |
| FR-033 | T078, T079, T089 |
| FR-034 | T050, T070, T071, T074, T089, T093, T094 |
| FR-035 | T077, T088 |
| FR-036 | T005, T007, T010, T011, T012, T015, T016, T057, T058 |
| FR-037 | T008, T009, T012, T013, T018, T075, T076, T081, T082 |
| SC-001 | T002, T003, T008, T009, T034, T079, T080, T089 |
| SC-002 | T046 |
| SC-003 | T037 |
| SC-004 | T036, T043 |
| SC-005 | T045, T054 |
| SC-006 | T049, T074 |
| SC-007 | T022, T057, T070, T071, T072, T089 |
| SC-008 | T057, T058, T059, T089 |
| SC-009 | T006, T017, T058 |
| SC-010 | T062, T064, T068 |
| SC-011 | T075, T076, T082 |
| SC-012 | T027, T106, T107 |
| SC-013 | T078 |
| SC-014 | T079, T083 |
| SC-015 | T077, T088 |
| SC-016 | T008, T009, T014, T018, T081 |
| SC-017 | T007, T010, T015, T057, T058 |
| SC-018 | T109, T110, T111 |

---

## Phase 11: Follow-up — owner decisions of 2026-10-16 (new pull request; left open)

**Goal**: the macOS title-bar interpretation of the minimum window made explicit, with the essentials proven usable at every size; and macOS evidence of reduced motion changing from off to on.

- [X] T096 [US6] Align `spec.md` (Clarifications 2026-10-16, FR-027, SC-007, edge cases), `plan.md`, `quickstart.md` and `contracts/workbench-shell.md` with the owner's reading of the minimum: 520 × 400 is the native window; on macOS the page is shorter by the measured, constant title-bar offset (≤ 40 px, 32 px on the CI runner), on Windows and Linux the offset stays zero. Extend `desktop/e2e/scenarios/narrow.ts` (additive) so that at every size the composer, Send, the Core state, the palette control, every rail button, the mode buttons and "Change workspace…" are in view and reachable by the pointer at their centres (`elementFromPoint`), a draft makes Send available (and is cleared, never sent), the palette opens inside the window, its field is reachable, and Escape closes it with focus back on the control, with no horizontal scroll after use; "Change workspace…" is required, its absence failing the scenario. Mutations: `pointer-events: none` on the palette control fails it ("covered at its centre"), and removing "Change workspace…" from the status strip fails it ("Change workspace… is there"); restored
- [X] T097 [US3] Add `desktop/test/os-preferences.test.ts` for the exact restoration of the macOS setting — `macTypeFlag` (the `defaults read-type` type to its write flag; unknown types refused), `macRestoreArguments` (delete an absent key; write the original type and value back), `macRestoredExactly` (presence, type, value and effective value must all match) — written before the helpers in `desktop/e2e/os-preferences.mjs` (additive; the T094 code is unchanged). Mutations: ignoring the type in `macRestoredExactly`, and writing instead of deleting an absent key, each fail it; restored. After the Codex review of `e66c651`: `macReadOutcome` counts the key as absent only when `defaults` says the pair does not exist (any other failed read is an error, never an absence to be restored by deleting), and keeps a value exactly, removing only the newline `defaults` appends; mutations (any failure taken as absent; trimming the value) each fail the test
- [X] T098 [US3] Add the macOS off-to-on check (FR-020): the setup `reduced-motion-transition` in `desktop/e2e/setups.mjs` (`platforms: ["darwin"]`, `motionTransition`), the page phase `reducedMotionTransition` in `desktop/e2e/scenarios/reduced-motion.ts` registered in `index.ts`, and in `desktop/e2e/harness.mjs` the `motion-phase` checkpoint and `runMotionTransition`: record the original (`macReadMotion`; an unrestorable type is `capability-unavailable` before anything changes); switch off and confirm the effective value off, then a launch whose page requires `matchMedia` off, the shell unmarked and the panel easing in; switch on and confirm it on, then a fresh launch whose page requires `matchMedia` on, the shell marked, and zero-duration panel and palette motion; in a `finally`, restore exactly (`macRestoreMotion`) and fail the case unless the read-back matches. A WebView not following the operating system is `capability-unavailable`; a shell not following the WebView is `product-failure`; elsewhere the case is N/A
- [ ] T099 Exact-head CI on the new pull request: every required check green on all three platforms; `reduced-motion-transition` `verified` on macOS with the original, both phases and the exact restoration recorded (or, if the runner cannot perform or expose a transition, NOT VERIFIED with its reason — never a pass), N/A on Windows and Linux; `narrow` `verified` on all three with the usability checks; record the evidence in the pull request
- [ ] T100 Request a fresh Codex review of the new pull request's exact final head when the account limit permits; fix every valid actionable finding with a failing-first test, push, repeat T099 and T100; it does not cover PR #64's unreviewed head (T090's recorded gap)
- [ ] T101 Report to the owner: branch, pull request, final SHA, changed files, the macOS off-to-on and restoration evidence, CI per platform, the review state, every NOT VERIFIED item. Leave the pull request open: no approval, no auto-merge, no merge

---

## Phase 12: Correction — the reference window (owner decision of 2026-10-17; new pull request, left open)

**Goal**: the whole visible window composed as the `_ide_ui` reference is — top bar with menus and search, left sidebar, canvas with the home card, prompt area with its footer, modal panel, status bar, question cards — with every value the Core's, every working action real, and every later-phase element unavailable and saying so. `_ide_ui` is read, never committed or bundled.

- [X] T102 Record the conflicts with the earlier D2 scope before implementing: `spec.md` (Clarifications 2026-10-17, the conflicts table, FR-001/003/004/005/007/011/015/019/026/027, FR-025 withdrawn, SC-012, SC-018), `plan.md` (Correction 2026-10-17), `contracts/workbench-shell.md` (Regions, Sizes, focus rules: the panel is drawn over the canvas but not modal; nothing traps focus)
- [X] T103 [P] Add the window-only roles the reference needs to `packages/design-tokens/src/index.ts` (`surface.active`, `surface.foot`, `surface.backdrop`, `border.tile`, each with its terminal stand-in) and their contrast pairs to `packages/design-tokens/test/tokens.test.ts`; the TUI bundle in `src/comodor/tui/dist` is unchanged
- [X] T104 Compose the window in `apps/desktop/src/shell/`: `TopBar.tsx` (the reference's eight menus item for item, folded into "Menu" below 760 px; the search in the palette's place; Cancel real, the other actions later), `Sidebar.tsx` (toolbar, WORKSPACE/EXPLORER, the session, the Core's delegates and tasks, read-only), `HomeCard.tsx`, `PromptFooter.tsx`, `ModalPanel.tsx` (replaces `SidePanel.tsx`), `StatusBar.tsx`, `Later.tsx`; `Shell.tsx` (sidebar beside from 900 px, covering below; Escape order palette → panel → covering sidebar); `Rail.tsx` and `SidePanel.tsx` removed; `commands.ts` (`sidebar.toggle`, `mod+o`, `mod+b`; panel width commands withdrawn); D1's `Composer.tsx` and `SessionView.tsx` gain only optional presentation slots (Send and Cancel keep their text)
- [X] T105 Style the window in `apps/desktop/src/styles.css` from the reference's measurements (top bar 64 px, sidebar `clamp(236px, 20vw, 250px)`, status bar 31 px, modal 600 px, prompt footer 33 px, question cards with numbered answers), reduced motion respected; later controls dimmed and `cursor: not-allowed`
- [X] T106 Update the D2 window tests for the new regions without changing a D1 test: `shell`, `focus` (regions top bar → sidebar → main → panel → status; the panel not modal; the covering sidebar; Escape order), `sidebar` (replaces `side-panel`: 900/899, toggle, `mod+b`, the panel unresized at every width), `preference` (the stored width carried, not drawn), `shortcuts-panel`, `boundaries` (a control naming a later phase is unavailable and says so, unless it only shows the Core's report), `shell-inert` (the layout does not mirror), `announce`, `palette*`, `core-panel`, `coverage`, `diagnostics-panel`. Fix found by the new sidebar test: the palette's opener is taken off the focus stack when the palette closes, so a command run from the palette records the right opener and keeps the focus it placed
- [X] T107 Mutation checks of the truthfulness guards (each fails `shell.test`/`boundaries.test`; restored): a later control without `aria-disabled`; a later menu item that runs a real command; the sidebar inventing an agent when the Core reported none
- [X] T108 Update the real-WebView scenarios in `apps/desktop/e2e/scenarios/` that used the rail, the side panel or its edge (shell, palette, keyboard, layout, core-panel, narrow, accessibility, reduced-motion, key-delivery, the lifetime relaunch) to the menus, the search, the modal panel and the sidebar; the narrow essentials become the menus or "Menu", the sidebar toggle, the palette control, the mode control, Send, the Core state and "Change workspace…"
- [X] T109 Add a `screenshot` checkpoint to `apps/desktop/e2e/harness.mjs` that captures the real WebView window on each platform (Windows: the window's client area; macOS: `screencapture -l` of the window; Linux: the X window under Xvfb), and a `visual` scenario that sets 1440 × 900, the minimum, 899 and 900 and shows the normal, menu, question, palette and panel states; CI uploads the images per platform
- [ ] T110 Compare the real screenshots with the reference rendered at the same sizes and states, section by section (top bar, sidebar, canvas, conversation and question, prompt area, menus, modal panel, status bar); correct every material difference; record the comparison table and the remaining deliberate, truthful differences (SC-018)
- [ ] T111 Offline gates (ruff, pytest, frontend lint/typecheck/tests, window tests, capability map, protocol codegen check, `git diff --check`), then exact-head CI on all three platforms with the screenshots attached
- [ ] T112 Request a Codex review of the new pull request's exact final head; fix every valid actionable finding with a failing-first test; repeat T111 and T112 after each new commit
- [ ] T113 Report to the owner: final SHA, the screenshots, the comparison table, the remaining visual differences, CI, the review, every NOT VERIFIED item. Leave the pull request open: no approval, no auto-merge, no merge. PR #64's missing final-head review stays a separate recorded gap; T099–T101 are not ticked by this work
- [X] T114 Make the harness read the bridge record as a log still being written (`apps/desktop/e2e/record.mjs`, test `apps/desktop/test/record.test.ts`): an unfinished last line (a second launch still writing) is not an entry; every finished line must parse. Found as a macOS canary failure on main at `9f7aa37` (`lifetime-second-confirmed`: "Unterminated string in JSON"); mutation (keeping the unfinished line) fails the test; restored
- [X] T115 Fix what the first exact-head CI (`871f321`) found, each with a check that fails without it: axe `aria-prohibited-attr` on the wordmark and `label-content-name-mismatch` (WCAG 2.5.3) on the top bar's search and the prompt footer's links — the visible text is now the name (`shell.test` "names"; mutation: the wordmark's `aria-label` back fails it; restored); and the covering sidebar over the status bar on WebKitGTK, positioned against the shell rather than its grid row (`narrow` now requires it to span exactly from the top bar to the status bar)
- [X] T116 Fix what exact-head CI at `fe42c5f` found on macOS (whose page is shorter by the title bar): axe `scrollable-region-focusable` on the Keyboard shortcuts panel's body, which scrolls with nothing focusable in it; the panel body is now a named, focusable region (`shell.test` asserts it). The same run's macOS TUI renderer failure (a frame-wait timeout at 60 columns, in a test this change does not touch; it passed at `871f321`) is rerun, not fixed
- [X] T117 Fix the Codex review of `95448b1` (two P2 findings): the top bar's menus are a WAI-ARIA menubar (`role="menubar"`, the menus `menuitem`s with one roving tab stop, Left/Right/Home/End between them) instead of a second navigation landmark; and an open menu closes when focus leaves the menubar (Tab, F6, a click), so Escape never meets a menu left open behind it. `shell.test` covers both (mutations: no focus-leave close; no roving tab stop — each fails; restored); `announce.test` and the `key-delivery` scenario follow the single tab stop; axe passes with a menu open
- [X] T118 Fix the Codex review of `f27540d` (one P2 finding): the sidebar's WORKSPACE/EXPLORER tabs behave as the tab widget they are announced as — one tab stop (roving `tabIndex`), Left/Right/Home/End choose a tab and move focus to it, and each tab names its panel (`aria-controls`, the panel `aria-labelledby` its tab). `shell.test` "the sidebar's tabs" covers it (mutation: no arrow-key handling fails it; restored); axe passes
- [X] T119 Fix the Codex review of `f11a717` (one P2 finding): hiding the sidebar beside the canvas while it holds the focus — by `mod+b` or from a palette opened there — gives the focus to the sidebar toggle instead of the document body. `sidebar.test` covers both paths (mutation: not moving the focus fails it; restored)
- [X] T120 Fix the Codex review of `e620dcf` (two P2 findings): each overlay — the panel, the covering sidebar, the palette — keeps its own focus-return record, so closing one in Escape's order never takes another's opener (`focus.test`: panel then covering sidebar opened from inside it; mutation: one shared record fails it; restored); and every menu, not only the folded one, is limited to the window's height and scrolls (`narrow` gains an 800 × 400 size and requires each open menu to end above the status bar with its last item usable; in the real WebView, removing the limit fails it; restored)
- [X] T121 Fix the Codex review of `8249dd2` (one P1, one P2): the palette opened over the open panel was drawn under the panel's backdrop, which took the pointer (the top bar's stacking context sat below the panel's layer); the top bar now rises above the panel while the palette is open, and the real-WebView `palette` scenario requires the palette's field to be what the pointer reaches over the panel (without the fix it fails there, covered by the backdrop; restored). And narrowing the window past 900 px while the sidebar holds the focus gives the focus to the sidebar toggle (`sidebar.test`; mutation fails it; restored)
- [X] T122 Fix the Codex review of `a9052d3` (one P2) and the rest of its kind: crossing 760 px redraws the menubar's triggers, and focus held there now moves to the corresponding trigger ("Menu" when folding; the menu whose item had it, else File, when unfolding) — `shell.test` (mutation: no focus move fails it; restored). And any change of width that hides the focused control (the prompt footer sheds its later items as it narrows) sends focus that fell to the page to the composer, FR-019's fallback, after the parts' own moves; the real-WebView `narrow` scenario focuses the footer's Shortcuts link before narrowing and requires the focus not to fall to the page (without the fallback it fails there; restored)
