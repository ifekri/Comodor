# Quickstart: Validating the Workbench Shell (D2)

How to prove D2 works, end to end, offline, on Windows, Linux and macOS. Every
D2 command below is **planned**: the implementation creates it, and `tasks.md`
fixes the exact file and script names. Nothing here calls a model provider,
spends tokens or needs a credential (FR-033, SC-013).

## 1. Prerequisites

The same as D1 (`specs/003-desktop-foundation/quickstart.md` §1): Python ≥ 3.11
with the repository installed editable in a per-worktree virtual environment;
Node ≥ 22.6 and `npm ci`; Bun; a Rust toolchain with Tauri 2's platform
prerequisites (WebView2 on Windows; WebKitGTK 4.1 and `xvfb` on Linux; Xcode
command-line tools on macOS; on Linux also `xdotool` for the platform
key-delivery evidence); an offline Core home whose only provider is
`fake`. D2 adds one development dependency to `apps/desktop`: `axe-core`,
pinned to an exact version, used only by the test build (research R12).

## 2. Gates that must stay unchanged (SC-001, SC-014)

```sh
python -m ruff check src tests tools
python -m pytest -q
python -m pytest -m performance -n 0 -q
python tools/protocol-codegen.py --check
python tools/capability-map.py --check
python tools/check-wheel-contents.py
npm run lint && npm run typecheck && npm test && npm run build
bun test apps/tui/test/bun/renderer.test.tsx
bun test apps/tui/test/bun/orphan.test.ts
bun tools/build-tui-distribution.ts && git status --porcelain   # prints nothing
git diff --check
```

Expected: the same results as on `main`. D2 changes no Python file and no
schema.

D1's own desktop tests run on the same commit and pass with every one of
their existing assertions (SC-001): every `apps/desktop/test/*.test.ts(x)`
file, every D1 scenario in `apps/desktop/e2e/scenarios/`, `lifetime`,
`canary`, `chooser-evidence`, and the native unit and integration tests.
Exactly two existing D1 assertions change, both command-set assertions, from
nine to eleven for the two approved layout operations (FR-030, FR-037;
research R6): the `CONTRACT` constant in `src-tauri/src/commands.rs` and the
count (with its comments) in `e2e/release-manifest.mjs`. Otherwise D1's test
files and test infrastructure only gain additions that change no existing
assertion: new D2 tests and `#[cfg(test)]` modules, scenarios with their
`index.ts` registrations and `setups.mjs` entries, harness acts and
checkpoints (including the explicit Linux virtual-display size and the
relaunch with the same data folder), the D2 flows in `canary-full.mjs`, and
the layout answers in `test/fake-native.ts`. No D1 test is deleted, skipped,
loosened or rewritten; the review of the final diff checks this file by
file. The shell therefore keeps the page details
those tests read: one element with `data-testid="status-strip"` and its
`data-state`, the `.status-state` and `.status-workspace` labels, the
"Change workspace…" button text, D1's `data-testid` values in the main area,
and a `read_layout` answer that is not a valid layout (the D1 test double
answers `{}`) leading to the defaults without an error. D1's `*.test.ts(x)` files and D1's scenario files are not edited.

## 3. Desktop gates (all three platforms)

| Layer | Planned command | Proves |
| --- | --- | --- |
| Native unit | `cargo test` in `apps/desktop/src-tauri` | `COMMANDS` equals the eleven of [native-operations.md](./contracts/native-operations.md); the main capability grants exactly those; layout validation rules 1–7 and every boundary; a refused write leaves the file byte-identical and leaves no temporary file, for each SC-017 case; the lenient `layout` load keeps `window` and `last_selected_folder`; an accepted write round-trips through the lock and the temporary-file rename; a failed save leaves the in-memory layout unchanged; `read_layout` returns exactly `layout` and `stored` |
| Native integration | the same, integration target | D1's integration tests passing with all their assertions; the preferences file read from disk after `write_layout` has D1's values intact |
| Window logic | `npm run -w apps/desktop test` | the shell in happy-dom against the D1 doubles: four regions and their landmarks; no D3–D6 entry (SC-012); the palette lists exactly the enabled commands in each of the eight states of SC-004 and runs them through `registry.run`; ranking and the first-three-letters rule (SC-003); the highlight back to the first result after each query change; every binding resolves and has a mouse path (SC-002); focus return and the region cycle (SC-005); Core values cleared on restart, workspace change and new client (SC-010); inert diagnostics and Core text; the layout function at every boundary; the layout read once, written after each completed change, a refused write leaving the window's layout and showing one notice |
| In-application scenarios | `npm run -w apps/desktop e2e` (test build) | the real WebView, bridge and Core: the shell around every D1 flow; the palette and every command by key and by click; keyboard-only traversal of every state with visible focus, with key events dispatched in the page (recorded as such); the `resize` act at four sizes computed in physical pixels from the scale factor `s` read through the test-build `window` query — the minimum `ceil(520·s)` × `ceil(400·s)`, widths `ceil(900·s) − 1` and `ceil(900·s)` either side of the threshold (exactly 899 and 900 at an integer scale), and a wide size fitted to the monitor's work area (at most 1280, at least 1000 logical) — each applied as a Tauri `PhysicalSize`, confirmed by waiting until the query reports it, with the page's size and the shell's measured width within 1 px of physical ÷ `s` — on macOS the page's height less the title-bar offset measured once at the default size (constant, at most 40 px; zero required on Windows and Linux; recorded as `titleBarInInner`) — and the compact mode judged by that measured width (only no monitor or a display too small is capability-unavailable), with no horizontal scroll, the composer, Send, Core state, palette control, rail, mode control and "Change workspace…" in view and reachable by the pointer at their centres, a draft making Send available, the palette opening inside the window and Escape closing it, and focus (F6 cycle, covering-panel focus in and out, Escape return) checked at each size (SC-007, FR-034); covering and beside modes; keyboard resize on the focused panel edge; `axe-core` WCAG 2.1 A/AA with zero violations in every state (SC-006); reload with the layout kept; Core crash and restart, and workspace change, with the layout kept and the Core values cleared (SC-008, SC-010); a write refused through the real bridge with `preferences.json` byte-identical between in-run checkpoints immediately before and after it; a pre-seeded invalid layout yielding the defaults (SC-009) |
| Process lifetime | `npm run -w apps/desktop lifetime` | D1's cases passing with all their assertions; plus the relaunch cases (setups marked `lifetime`, with a relaunch using the same data folder): arrange a layout, quit, launch again in the same workspace and in another one, and find it restored (SC-008); the preferences file on disk after exit holds the layout and D1's values |
| Credential canary | `npm run -w apps/desktop canary` | every D1 flow and every D2 flow; zero canary occurrences in every IPC message, every bridge command's arguments and results, WebView storage, document text, the log and the preferences file; `read_layout` and `write_layout` appear in the recorded commands; the stored `layout` has exactly its four fields and no conversation text (SC-011) |
| Release command list | native unit, plus `npm run -w apps/desktop release-manifest` in CI | exactly eleven allow/deny pairs, only the `main` capability, the eleven allow identifiers plus the recorded `core:` minimum, no plugin permission, and the `e2e` build differing only by `e2e_report` (SC-016) |
| Platform key delivery | `npm run -w apps/desktop e2e` (scenario `key-delivery`; operating-system steps only with `COMODOR_E2E_OS_LEVEL=1`, set in the CI `desktop` job) | after preflight (injection tool, `focus-window` confirmed through the `window` query, on macOS Accessibility trust and post-event access) and a plain-letter delivery probe into a test-only field, the operating system delivers F6, Shift+F6, mod+K and Escape to the real window — Windows `SendInput` with the foreground pid checked before every send, macOS `CGEventPostToPid`, Linux `xdotool windowfocus --sync`, with `getwindowfocus` checked before each key and `xdotool key` sent without `--window`, on the harness's window-manager-less `xvfb` display — and the page observes the region focused, the palette opened and closed, and focus returned; outcome `verified`, `product-failure` or `capability-unavailable` (FR-011, FR-017, FR-018, FR-034) |
| Reduced motion | `npm run -w apps/desktop e2e` (scenario `reduced-motion`; preference steps only with `COMODOR_E2E_OS_LEVEL=1`) | on each platform the stylesheet's `prefers-reduced-motion: reduce` rule removes the shell's transitions; with the operating system's preference recorded, set (Windows without `SPIF_UPDATEINIFILE`, macOS `defaults`, Linux per-run GTK settings), its effective value read back (on macOS through a Swift helper reading `NSWorkspace.shared.accessibilityDisplayShouldReduceMotion`, since a `defaults` write alone is not enough), and restored in a `finally` confirmed by the same effective read-back, `matchMedia` reports it and the panel and palette have no transition; outcome `verified`, `product-failure` or `capability-unavailable` (FR-020). Where the preference was already on before the run (the macOS CI runner), this shows it honoured, not a change |
| Reduced motion, macOS off → on | `npm run -w apps/desktop e2e` (scenario `reduced-motion-transition`; macOS only, N/A elsewhere; preference steps only with `COMODOR_E2E_OS_LEVEL=1`) | the original setting recorded (present or absent, its `defaults` type and value, and the `NSWorkspace` effective value); reduced motion switched **off**, the effective value confirmed off, a launch in which `matchMedia` reports no reduced motion, the shell is not marked for it and the panel eases in; then switched **on**, the effective value confirmed on, a fresh launch in which `matchMedia` reports it, the shell is marked and the panel and palette have zero-duration motion; in a `finally` the original put back exactly (same type and value, or the key deleted if it was absent) and confirmed by reading presence, type, value and effective value again. Outcome `verified`, `product-failure` (the WebView reports the state and the shell does not follow it) or `capability-unavailable` (the setting could not be switched, the operating system did not apply it, or the WebView did not report it) — NOT VERIFIED, never a pass, and the already-on result above is never counted as this evidence (FR-020) |

## 4. Mutation checks (each must make its test fail, then be restored)

| Mutation | Test that must fail |
| --- | --- |
| save before validating in `write_layout` | the byte-identical refusal test (SC-017) |
| drop the size limit, the unknown-field rule, the width range or the surface set | the matching validation test |
| make the `layout` field strict in `prefs::load` | the lenient-load test |
| add a twelfth name to `COMMANDS` | the native contract tests (`CONTRACT`) and the release-manifest check (SC-016) |
| remove `allow-write-layout` from the capability | D1's `the_main_capability_grants_only_the_commands` and the release-manifest check (SC-016) |
| let a palette entry ignore `enabled` | the eight-state palette test (SC-004) |
| run a Core-bound command without D1's gate | the gate test (FR-029) |
| keep Core values across a restart | the clearing test (SC-010) |
| skip focus return when an overlay closes | the focus-return test (SC-005) |
| bind an unmodified printable key | the reserved-key test (FR-017) |
| omit a layout operation from the canary flows | the canary coverage assertion (SC-011) |

## 5. Walkthrough (manual, optional)

1. Launch a development build against the offline home. The window shows the
   rail, the conversation, the status bar ("ready", `fake`, `fake-1`,
   "configured"); the side panel is closed.
2. Press mod+K, type "dia", press Enter: the diagnostics panel opens. Press
   mod+2: the Core panel replaces it, showing the reported values.
3. Drag the panel's edge; then Tab to the edge and press Left twice. Reload
   the window: the panel is open, on the Core surface, at the width left.
4. Narrow the window below 900: the panel covers the conversation; Escape
   closes it and focus returns to the rail button that opened it.
5. Change workspace: the Core values read "not reported yet", then the new
   ones; the layout is unchanged. Quit and launch again: the layout is back.
6. Run "Reset layout": the panel closes and the defaults are stored.

## 6. Recording evidence

Record each run against the exact commit: platform, command, counts and
result. Evidence for the **exact final SHA** goes in the PR description and the
owner report, never in a repository commit made after the final validation
round. A layer or platform without recorded evidence is **NOT VERIFIED**, and
D2 is then **incomplete**; NOT VERIFIED is never a pass (FR-034, Constitution
X, XII).

Dispatched and delivered keys are different evidence. Key events dispatched
inside the page prove the shell's handling in the real WebView; they do not
prove that the operating system and the WebView deliver the key. That is
proven only by the `key-delivery` scenario, after its delivery probe.

Operating-system-level steps — key injection and the reduced-motion
preference — run only when `COMODOR_E2E_OS_LEVEL=1`, which only the CI
`desktop` job sets. A local run reports `key-delivery` and `reduced-motion`
as `not-run`; that is recorded as "not run locally" and is never evidence.

Each of these scenarios (`key-delivery`, `reduced-motion`,
`reduced-motion-transition`), and the wide-size choice in `narrow`, reports one
outcome: `verified`; `product-failure` (the shell did not do what the
requirement says, with the capability proven present); or
`capability-unavailable` with a reason (the runner could not inject keys,
focus the window, set or expose the preference, or fit the sizes). Only
`verified` passes. `capability-unavailable` is **NOT VERIFIED** and an
acceptance blocker for the requirements it covers (FR-011/FR-017/FR-018/
FR-034, FR-020, SC-007), reported apart from a product failure; D2 is not
complete on that platform. In CI the `desktop` steps after `e2e` run with
`if: ${{ !cancelled() }}`, so the other layers' evidence is still produced
while the failed `e2e` step keeps the job failed.

Carried forward from D1, unchanged and **NOT VERIFIED** (FR-035, SC-015):
physical suspend and resume of a machine; the native "Open link?" dialog's
appearance with a real person's answer. D2 neither tests nor claims them.

The real-folder-chooser evidence (`chooser-evidence`) is D1's and keeps running
unchanged; D2 adds nothing to it.
