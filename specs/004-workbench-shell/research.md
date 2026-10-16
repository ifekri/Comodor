# Research: Workbench Shell (D2)

Every decision below was taken from the repository at `origin/main` `180c3f6`
(D1 merged as PR #62, `427ecca`) and from the clarified spec. Nothing in the
Technical Context was left as NEEDS CLARIFICATION; the entries record why each
choice was made and what was rejected.

---

## R1. Where the layout lives on disk

**Decision**: An optional `layout` object inside the existing native
preferences file (`preferences.json`, `src-tauri/src/prefs.rs`), beside
`version`, `window` and `last_selected_folder`. The file's own `version` stays
`1`; the layout carries its own format version.

**Rationale**: The owner chose the existing native preferences file (Q2).
Adding an optional field is backward compatible (Principle I): a D1 build
reading a D2 file ignores the unknown field (D1 ignores unknown fields), and a
D2 build reading a D1 file finds no layout and uses the defaults. Bumping the
file version would make a D1 build treat nothing differently (it does not check
the version) but would imply a migration that does not exist.

**Alternatives considered**: a second file (rejected: the owner chose the
existing file, and two files can disagree after a crash); WebView storage
(rejected by the owner's decision; also outside the native validation the
spec requires).

## R2. A bad layout must not cost D1's values

**Decision**: The `layout` field is deserialized leniently and on its own: a
layout that is missing, malformed, of another format version, or out of range
loads as "no layout" while `window` and `last_selected_folder` load exactly as
D1 loads them.

**Rationale**: D1's `prefs::load` treats any file that fails to parse as
absent, so a strict `layout` field would turn one bad layout into the loss of
the window geometry and the last folder. FR-023 and FR-036 require invalid
saved data to fall back to defaults without an error; they do not allow
collateral loss.

The layout is not a new field of D1's `Preferences` type: D1's tests build
that type as a struct literal and pin its three fields, so the layout travels
in a wrapper (`prefs::Stored`, data-model §1) and every runtime save writes the
wrapper.

**Alternatives considered**: a strict field (rejected: collateral loss);
repairing a bad layout on load and writing it back (rejected: a read must
never write); a fourth field on `Preferences` (rejected: it would require
editing D1's preferences tests, outside SC-001's two allowed changes).

## R3. Exactly two native operations

**Decision**: `read_layout` and `write_layout`, added to the one constant
`COMMANDS` in `src-tauri/src/command_names.rs`, which then holds eleven names.
`read_layout` takes no argument and returns the stored layout, validated, or
the defaults. `write_layout` takes one layout object, validates it completely
before touching anything, and on success stores it and returns what was
stored; on any failure it returns a refusal and changes nothing.

**Rationale**: The owner asked for the minimal native read/write operations.
One read and one write is the minimum that lets the window restore a layout at
start and record a change; a single "update" operation that also returned the
current value would merge two different authorities (asking and changing) into
one call and make the refusal path harder to prove. Names follow D1's verb
style (`send_line`, `choose_workspace`, `open_external`).

**Alternatives considered**: per-field operations (`set_panel_width`, …)
(rejected: more operations, each a new permission); returning the whole
preferences file (rejected: the page must never see D1's folder or geometry
through this path).

## R4. Strict validation, on the native side

**Decision**: `write_layout` accepts a JSON object of at most 1 KiB (the
`layout` argument serialised as compact JSON, `serde_json::to_vec`, because
Tauri has parsed the IPC message before the handler runs) with exactly these fields and no others: `version` (must be `1`),
`panel_open` (boolean), `panel_surface` (one of `core`, `diagnostics`,
`shortcuts`), `panel_width` (an integer from 240 to 960 inclusive). Anything
else — an unknown or missing field, a wrong type, a value out of range, another
version, a larger payload — is refused with a reason naming the first problem.

**Rationale**: FR-036 requires native validation of version, fields, types,
width range, surface and size. The native side cannot know the window's width
at the moment of a later read, so it stores within a fixed absolute range
(240–960) and the window limits the width it shows to its current room without
rewriting what is stored (spec edge case "a stored panel width wider than the
current window"). The surface set is exactly FR-006's side-panel surfaces; the
conversation is the main area and never a side-panel value.

**Alternatives considered**: clamping out-of-range values on write (rejected:
FR-036 says an invalid write is refused, and a silent clamp would hide a page
bug); validating in the page (rejected: the window's content is the less
trusted side).

## R5. A refused write leaves the file byte-identical

**Decision**: Validation happens entirely before any file operation; a refused
write performs no file I/O at all. An accepted write takes the preferences lock
that D1's saves already take, builds the new preferences from the in-memory
copy, and saves through D1's existing temporary-file-and-rename path. If the
save fails, the in-memory copy is left as it was and the operation reports the
failure.

**Rationale**: SC-017 requires the stored file, including D1's values, to be
byte-for-byte unchanged after each refused write; doing no I/O on refusal makes
that true by construction, and the test reads the file's bytes before and
after. Reusing D1's lock and save keeps one writer and one atomic write path
(Principle XVIII) and serialises layout writes with D1's geometry and folder
saves.

**Alternatives considered**: a separate writer for the layout (rejected: two
writers to one file race); writing first and rolling back (rejected: a crash in
between leaves a changed file).

## R6. The release manifest and D1's record

**Decision**: The release command-manifest check (`e2e/release-manifest.mjs`)
reads the names from `COMMANDS` but also pins the count (`commands.length !==
9`, and its comments say "nine"); that pin and its comments move to eleven,
citing D2's contract. The unit test that pins the exact set
(`commands.rs`, `CONTRACT: [&str; 9]`) is updated to D2's contract of eleven,
written out, citing
`specs/004-workbench-shell/contracts/native-operations.md`. These two pins are
the only D1 test code D2 changes, because FR-030 and FR-037 (the owner's Q2
decision) change the exact set they guard; SC-001, as corrected on
2026-10-08, names exactly these two and requires every other D1 test to keep
all of its assertions. The capability
`capabilities/main.json` grants the two new allow permissions. D1's
specification, contracts, tasks and quickstart in `specs/003-desktop-foundation/`
are not edited: their nine-operation record stays as history.

**Rationale**: FR-030 and FR-037; the owner asked to extend the manifest from
nine to eleven without rewriting D1's record. The unit test's constant is code
that guards the current contract, so it follows the current contract; the D1
documents are history.

**Alternatives considered**: keeping a nine-entry test alongside an eleven-entry
test (rejected: a test that asserts the old set would fail by design).

## R7. The credential canary

**Decision**: The canary flows gain the D2 flows (open and use each surface,
open the palette, resize, reset, relaunch with a stored layout). The canary
already searches every bridge command's arguments and results and every file
in the application's data folder, which includes `preferences.json`; the plan
adds an explicit assertion that `read_layout` and `write_layout` appear in the
recorded commands of the canary run (so the search provably covered them) and
that the stored `layout` object has only the four fields of R4.

**Rationale**: FR-037 and SC-011. Coverage must be shown, not assumed: a canary
search over a record that never contained a layout call proves nothing about
the layout calls.

**Alternatives considered**: a separate canary harness (rejected: duplicates
D1's search).

## R8. The command palette and the shared registry

**Decision**: The window keeps one `CommandRegistry` (`@comodor/commands`) and
registers every D2 command there with an id, title, group, keywords, an
`enabled` rule that encodes D1's gates, and its key bindings. The palette lists
`registry.search(query, context)` — which already drops commands whose
`enabled` is false — and runs the chosen one through `registry.run`, the same
path a button and a key use. The palette's selection rule ("the highlight goes
back to the first result whenever the query changes") is added to
`@comodor/commands` as an additive, pure export, so a second client can share
it.

**Rationale**: FR-011–FR-015 and Principle XVIII. The registry already holds
search ranking and binding validation; the window must not grow a second
search.

**Alternatives considered**: a desktop-only palette search (rejected:
duplicates the shared ranking). Moving the terminal interface's own
`apps/tui/src/palette.ts` onto the shared export is not done in D2: the spec
classifies the terminal interface as not changed, and Principle V keeps that
refactor to its own change. The terminal's copy and the shared export then
coexist until that change — recorded in Complexity Tracking.

## R9. Keyboard model

**Decision**: Bindings use a `mod` prefix that the window resolves to Command
on macOS and Control elsewhere. The binding list (contracts/workbench-shell.md)
keeps Tab and Shift+Tab for focus, never binds an unmodified printable key,
never reassigns copy, cut, paste, select all, undo, redo or the platform's
window shortcuts, and uses F6/Shift+F6 to move between regions and Escape to
close the topmost overlay. Text-editing movement keys, macOS's mod+M, mod+H and
Cmd+., the desktop environments' Ctrl+Alt+arrow workspace keys and the
WebView's reload and zoom keys are never bound. The side panel is resized from
its focused edge with the arrow keys (the window-splitter pattern), not by a
global chord. A shortcut fires only when its command is enabled;
inside a text field only modified keys reach the shell. Enter in the composer
keeps its D1 meaning.

**Rationale**: FR-016–FR-019; the terminal's Tab-for-mode binding cannot be
copied because Tab must move focus in a desktop window; Ctrl+K for the palette
matches the terminal.

**Alternatives considered**: mode on Tab as in the terminal (rejected: breaks
focus navigation and accessibility).

## R10. Narrow windows, without a layout engine in unit tests

**Decision**: The compact threshold (900 logical pixels), the panel range
(240 to half the window, 320 default) and the main-area minimum (360) are
enforced by a pure layout function the window calls with the measured width;
the window measures its width with a `ResizeObserver` on the shell root — its
`contentRect.width`, a fractional number of logical pixels, never rounded —
and re-evaluates on every change, so at a fractional scale factor a width of
899.2 is compact and 900.0 is not. The
pure function is unit-tested at every boundary; the rendered result is checked
in the real WebView by scenarios that resize the test build's window.

**Rationale**: FR-025–FR-027, SC-007. The window tests run in happy-dom, which
has no layout engine, so they can check structure and state but not geometry;
geometry is checked where it exists.

**Alternatives considered**: CSS-only breakpoints (rejected as the only
mechanism: the "covering" panel state also changes focus and Escape handling,
which CSS cannot express); asserting geometry in happy-dom (impossible).

## R11. Resizing the window in scenarios

**Decision**: The test build's checkpoint reply gains one act, `resize`, that
sets the main window's inner size from the harness; it exists only under the
`e2e` feature, like D1's `close-window` and `quit` acts. Acts are asynchronous
— they run on their own thread after the reply and return nothing — so the
test build also gains one query, `window`, in `e2e_report`'s existing query
branch: the window's inner and outer size in physical pixels with its scale
factor and the same sizes in logical pixels rounded to whole numbers, its
monitor's work area likewise with the monitor's own scale factor (or no
monitor), and whether it is focused. `resize` sets a Tauri `PhysicalSize`
computed from the scale factor, so every size is representable: the threshold
is tested at the physical widths `ceil(900·s) − 1` and `ceil(900·s)`, judged by
the shell's measured fractional width, and only a missing monitor or a display
too small is capability-unavailable. A scenario reads the work area
before choosing sizes, sends `resize`, and waits until the query reports the
requested inner size; it never assumes a display and never sleeps. A second
act, `focus-window`, brings the window to the foreground for the platform
key-delivery evidence, and the query confirms focus before any key is
injected. No release operation is added.

**Rationale**: Scenarios run inside the page, which has no permission to resize
its own window; the harness already asks the test build to act on the window.

**Alternatives considered**: granting a window-resize permission to the page
(rejected: a new permission in the release build for a test need).

## R12. Accessibility checking

**Decision**: The test build runs an automated rule-based accessibility checker
(`axe-core`, pinned to an exact version, a dev dependency of `apps/desktop`
only, bundled into the test build's scenario runner) against every window state
in the real WebView, restricted to WCAG 2.1 A and AA rules, and fails on any
violation. Keyboard-only scenarios check focus order, visibility and return.

**Rationale**: SC-006 asks for zero violations of the WCAG 2.1 A/AA rules an
automated checker can test; a checker that runs in the real WebView on all
three platforms gives deterministic, offline evidence. A manual screen-reader
pass is not claimed (spec Assumptions).

**Alternatives considered**: checking in happy-dom (rejected: colour contrast
and focus visibility need the real rendering).

**Found during implementation**: the window keeps Tauri's `freezePrototype`,
and the colour library bundled in `axe-core` 4.14.0 adds its methods to a
class prototype by plain assignment, `toString` among them, which throws once
`Object.prototype` is frozen. The test build's Vite configuration (`--mode
e2e` only) rewrites that one assignment into the equivalent
`Object.defineProperty` and fails the build if the pinned version no longer
has it exactly once; no rule changes, and the release build is untouched
(rejected alternatives: turning `freezePrototype` off for the test build,
which would test a different window; running the checker in a frame, which
the Content Security Policy refuses). The checker waits for running
animations to finish, so a panel is judged in the colours it settles on.

## R13. Core values in the shell

**Decision**: The Core panel and the status bar read only: the native status
(`state`, `workspace`, `workspace_id`, `failure`, `restart_count`,
`restart_limit`, `core`, `check_epoch`), the Core's own reports through the
session projection (`workspace.get`, `model.get`), and the handshake that
`CoreClient` keeps (`protocol_version`, `core`, `capabilities`), which the
native side answers from the Core's cached handshake. Each value is shown only
for the current client and status; a status change to another Core (restart,
workspace change) or a new client clears what the shell shows, and "not
reported yet" stands in until a new report arrives.

**Rationale**: FR-008, FR-028, SC-010. Every value has a reporter; nothing is
derived or cached across Cores.

**Alternatives considered**: keeping the last values during a restart for
continuity (rejected: shows another Core's state as current).

## R14. Layout state in the window

**Decision**: The window reads the layout once per page load with
`read_layout`, keeps it in its own state (it survives Core restarts and
workspace changes because it is not tied to a client or a session), and writes
it with `write_layout` after each completed change (a toggle, a surface choice,
a finished drag, each keyboard resize step, a reset). Until the read answers,
the panel is closed. A refused write leaves the window's layout as the person
set it and is reported as a quiet notice; the next change writes again.

**Rationale**: FR-021–FR-024, User Story 4. One read per load keeps a reload
consistent with the file; writing after completed changes avoids a write per
pointer move.

**Alternatives considered**: writing on every pointer move (rejected: needless
I/O); caching in session storage as well (rejected: a second store that can
disagree with the file).
