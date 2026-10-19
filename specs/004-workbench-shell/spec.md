# Feature Specification: Workbench Shell (D2)

**Feature Branch**: `004-workbench-shell`

**Created**: 2026-10-07

**Status**: Draft

**Input**: User description: "Create the next Comodor desktop feature: D2 —
Workbench Shell. D1 already provides one conversation and a supervised Python
Core. D2 should turn that working window into a usable, professional workbench
shell: a coherent layout around the existing conversation, navigation between
the D2 surfaces, practical panel sizing and visibility, a command palette for
actions that actually exist, keyboard and mouse operation, accessible focus
behavior, and restoration of non-secret layout preferences. Specify behavior
for narrow windows, reload, Core restart, and workspace change without losing
or inventing Core state. Keep the Python Core authoritative and reuse the
existing protocol, native bridge, and shared frontend semantics. All acceptance
tests must be deterministic and offline, with no live provider or paid tokens.
Respect phase boundaries: D3 owns the editor and workspace browsing; D4 the
integrated terminal; D5 agent, task, delegate, and session panels and history
browsing; D6 installers, signing, updates, and bundled runtime. Do not present
empty placeholders as completed versions of those features. Preserve D1's
recorded limitations about physical suspend/resume and the native link dialog
without claiming they were physically verified."

## Context

This specification was written against `origin/main` at `180c3f6`, which
contains D1 merged as PR #62 (`427ecca`) and a later commit by the owner that
removed the `.specify/` directory from the tracked tree. **Current `main` has no
tracked constitution and no tracked Spec Kit scripts or templates.** The
constitution (version 2.0.0), the PowerShell scripts and the templates this
feature's Spec Kit steps use were read from the immutable commit `427ecca` and
restored, byte for byte, into this feature's worktree only, as local untracked
tooling that is never committed and is not part of the pull request. Restoring
them to `main` permanently would be a separate governance change. The facts
below were read from the repository, not assumed.

- **What D1 delivers.** `apps/desktop` is one window over one supervised Core
  (`docs/desktop-architecture.md`, `specs/003-desktop-foundation/`). The window
  is a single screen: a status strip (state, workspace as the Core reports it,
  provider, model, configured), the conversation with tool activity, question
  forms, permission cards, the mode control and a composer. Failure,
  "Closing…", no-workspace and unconfigured-provider views replace or join that
  screen. After the machine wakes from sleep, the Core is checked before the
  window may send again (`checking`).
- **What the window can do today.** Send, cancel, change mode, answer a
  question or a permission, open a shown link (after the person confirms it in
  a native dialog), change workspace, check again, try again, and Quit now
  while closing. Only Send and Cancel are registered as commands with keys;
  everything else is a button.
- **The shared command registry already exists.** `@comodor/commands` holds
  commands with ids, titles, groups, keywords, an "enabled now" rule, key
  bindings checked against the commands they name, and the palette search
  ranking. The terminal interface builds its command palette and footer on it
  (`apps/tui/src/commands.ts`, `apps/tui/src/palette.ts`).
- **"Workbench" already names something in the terminal.** In the terminal
  interface the "workbench" is the tasks and delegates panel
  (`apps/tui/src/workbench.tsx`). On the desktop those panels belong to D5. In
  this document **workbench shell** means the window's layout frame, its
  navigation, panels, palette and keyboard model — not tasks or delegates.
- **What the window persists.** The native preferences file holds a format
  version, the window geometry and the last selected folder. The window's own
  session storage keeps per-launch recovery facts (stored and live session ids,
  an interrupted turn, an unconfirmed mode choice, the workspace id). No layout
  preference exists yet.
- **The native operation set is exact.** The page can call exactly nine native
  operations (`connect`, `send_line`, `status`, `diagnostics`,
  `choose_workspace`, `retry`, `check_again`, `quit_now`, `open_external`); the
  release build grants those and nothing else, and tests assert it.
- **One theme.** The design tokens define one theme. Colours come only from
  the tokens.
- **The window's size.** The window opens at 1100 × 760 and cannot be made
  smaller than 520 × 400.
- **Recorded D1 limitations.** A real suspend and resume of a machine, and the
  native "Open link?" dialog's appearance with a real person's answer, were
  not physically verified in D1. They remain NOT VERIFIED; D2 does not change
  that and does not claim otherwise.

## Clarifications

### Session 2026-10-07

- Q: Which surfaces does the D2 navigation rail offer? → A: The existing
  conversation, a Core panel, a diagnostics panel and a keyboard shortcuts
  reference — each with a real D2 function, and no placeholder for D3–D6.
  *Binds*: FR-004–FR-006; User Stories 1 and 5; SC-012.
- Q: How long, and where, are layout preferences kept? → A: One non-secret
  layout for the whole application, kept across application launches and
  across workspaces, in the application's existing native preferences file. D2
  adds only the minimal native operations to read and write it; the native side
  validates every value and bound; the release command-manifest and
  credential-canary tests are extended to them; D1's record of its nine native
  operations stays unchanged as history. *Binds*: FR-021–FR-024, FR-030,
  FR-036, FR-037; User Story 4; SC-008, SC-016, SC-017; the Desktop,
  Persistence and Security surface rows.
- Q: Does D2 add application-level actions that need a new native operation?
  → A: No. Quit stays with the window's own close control and the operating
  system's close flow; D2 adds no reload-window, open-log-folder or quit
  operation. *Binds*: FR-031; Scope Boundaries.

### Session 2026-10-08

- Q: Which D1 tests may D2 change, given that Q2 adds two native operations?
  → A: Owner direction, with no new question and Q2 unchanged: only the two
  command-set assertions — the native operation-set test in `commands.rs` and
  the release command-manifest check in `release-manifest.mjs` — change, from
  nine to eleven; every other D1 behaviour and regression test keeps passing
  with all of its assertions, and D1's nine-operation record stays as
  history. *Binds*: SC-001, FR-033, FR-037; the Tests / Documentation surface
  row.

### Session 2026-10-15

- Q: How should the D2 window look, given the owner's reference design for
  the desktop window? → A: Owner direction: look only, within D2's scope. The
  window takes the reference design's colours, typefaces (IBM Plex Sans,
  JetBrains Mono, Material Symbols Outlined), sizes, radii, scrollbars and
  the look of its status bar, palette, side panels, conversation, question
  and permission cards and prompt area, applied to D2's existing surfaces
  only; no region the reference shows beyond them (menus, sessions, agents,
  tasks, explorer, editor, terminal) is added. The colours are a second,
  additive mapping of the shared design tokens (`desktop`), with the finer
  roles the window needs in a window-only list beside the shared tokens; the
  terminal mapping, and so the TUI and its committed bundle, are unchanged. The fonts are pinned dependencies bundled into the page; the
  Content Security Policy is unchanged. Where the reference's text colours
  fall below WCAG 2.1 AA on their grounds, the nearest passing value is used
  (SC-006 wins). The reference itself stays in the owner's checkout and is
  never published. *Binds*: FR-018, FR-020, SC-006; the TUI and
  Tests / Documentation surface rows.

### Session 2026-10-16

- Q: What does the 520 × 400 minimum mean on macOS, where Tauri counts the
  title bar inside the window's inner size? → A: Owner decision after D2's
  CI: 520 × 400 describes the native window. On macOS the WebView page may
  be shorter by the title bar — 520 × 368 when the measured offset is 32 px —
  provided that offset is measured, is the same at every size, and is at
  most 40 px; on Windows and Linux the offset must be zero. At every tested
  size the composer, Send, the Core state, the palette control and the other
  essential actions (the rail, the mode control, "Change workspace…") are
  visible, reachable by the pointer, and work, with no horizontal scrolling.
  *Binds*: FR-027, SC-007.
- Q: Does an already enabled macOS reduced-motion preference prove that the
  window follows a change of it? → A: Owner decision: no. It shows the
  window honouring the preference while it is on. A separate macOS check
  switches the preference off, then on, confirms the operating system's
  effective value and `matchMedia` each time, requires the shell's
  transitions to be zero-duration when it is on (and present when it is off),
  and restores the exact original setting — including an originally absent
  key — confirmed by reading it back. A runner that cannot perform or expose
  either transition leaves this NOT VERIFIED with its reason; the already-on
  result never counts as off-to-on evidence. Windows and Linux keep their
  criteria. *Binds*: FR-020.

### Session 2026-10-17

- Q: What is the binding visual reference for the IDE window, and how far
  does it reach? → A: Owner correction, superseding the "look only, within
  D2's four surfaces" decision of 2026-10-15: the HTML, CSS and scripts of
  the owner's `_ide_ui` reference (kept unpublished in the owner's checkout)
  bind the whole visible window — composition, proportions, spacing,
  typography, colours, borders, the top area, the left navigation, the
  central canvas, the conversation and question states, the prompt area, the
  menus and the bottom status area. The reference is never committed or
  bundled. *Binds*: FR-001–FR-007, FR-011, FR-025–FR-027, SC-002, SC-007,
  SC-012, SC-018.
- Q: How do later-phase (D3–D5) elements of the reference appear before
  their phase? → A: They may establish the reference's visual structure, but
  only as truthful unavailable or empty states: a control of a later phase is
  marked unavailable (`aria-disabled`), says so when chosen ("… arrives in a
  later version"), and never runs anything; a list of a later phase (agents,
  tasks, sessions, files) shows only what the Core reported, or an honest
  empty state. No session, agent, task, file, activity or result is
  invented, and no visible control may appear to work when it does not. The
  palette and the shortcuts still list only real commands. *Binds*: FR-005,
  FR-012, SC-012.
- Q: What stays fixed? → A: D1's behaviour and tests (SC-001's rule), the
  Core's authority, the eleven native operations and their capabilities, the
  layout preference's stored format, and the 520 × 400 minimum window.

### Conflicts with the earlier D2 scope (resolved 2026-10-17)

| Earlier D2 requirement | The reference | Resolution |
| --- | --- | --- |
| FR-001 four regions: rail, main area, side panel, status bar | A 64 px top bar, a left sidebar (236–250 px) with a toolbar, WORKSPACE/EXPLORER tabs and SESSION/AGENTS/TASKS sections, a central canvas over a prompt area, and a 31 px status bar | The reference's regions replace the rail and the side panel (FR-001 as amended) |
| FR-004/FR-006/FR-007 a rail listing the four D2 surfaces | No rail; actions live in menus, the sidebar toolbar, the prompt footer and the status bar; settings-like content opens in a centred modal panel | The Core panel, diagnostics and keyboard shortcuts open as the reference's modal panel, from the menus, the status bar, the prompt footer, the palette and their shortcuts; the conversation is the canvas |
| FR-005/SC-012 no entry, tab or disabled placeholder for later phases | Menus, sidebar sections, tabs, tiles and actions for sessions, agents, tasks, files, loops, skills, memory, MCP, a terminal | Allowed as truthful unavailable or empty states only (Session 2026-10-17); palette and shortcuts unchanged |
| FR-003 the status bar holds the palette control | The status bar holds activity, folder, branch, context, terminal and debug cells; the command control is in the prompt footer ("Command [/]") | The status bar keeps D1's strip in the reference's cells; the palette control moves to the prompt footer ("Command [Ctrl+K]") |
| FR-011 a centred palette dialog | A search field in the top bar with a results list below it, and a slash-command list above the prompt | The palette is the top bar's search: its field takes the search box's place and its results drop below in the reference's result rows |
| FR-025/FR-026 a resizable side panel, beside from 900 px and covering below | No side panel; a fixed-width collapsible sidebar, beside the canvas at every width the reference draws (down to its `min-width` of 760 px) | Side-panel resizing is withdrawn (with its edge and its wider/narrower commands). The sidebar is beside the canvas from 760 px up, as in the reference — 899 px included (corrected 2026-10-18; it was first hidden below 900, which no approved criterion asked for). Below 760 px see "Open decisions for the owner" |
| FR-021/FR-022 the stored layout is the side panel's state and width | — | The stored format is unchanged (version, `panel_open`, `panel_surface`, `panel_width`); `panel_open`/`panel_surface` now name the open modal panel, restored after a reload, a Core restart and a relaunch; `panel_width` is kept and validated as before but no longer drawn |
| The composer with Send and Cancel beside the field; the mode control above the conversation | A prompt field over a 33 px footer: model chip, attachments, Agentic, an Ask/Plan/Build segmented control, "Send Message [ENTER]", "Command [/]", "Sub-Agents [Ctrl+S]" | The footer in the reference's order with truthful content: the model the Core reports; attachments and Agentic unavailable; the Core's modes (shown Act/Plan/Ask, the Core's own labels in title case, not "Build"); Send (still labelled "Send"); "Command [Ctrl+K]"; "Shortcuts [Ctrl+/]" |
| The 520 × 400 minimum window | `min-width: 760px` | The minimum stays; below 760 px see "Open decisions for the owner" |
| Demo content in the reference (named agents, tasks, sessions, files, terminal output, models) | Seeded for design review only | Never shown; every value is the Core's or the native side's, or a stated empty state |

### Open decisions for the owner (2026-10-18)

Below 760 px the reference cannot be matched without breaking an approved
criterion. The reference's root has `min-width: 760px`: in a narrower window
it keeps its full layout and the page scrolls sideways, cutting off the
right-hand side — the search, the actions, the prompt footer's right half and
the status bar's end. FR-027 (approved in D2) requires that from the minimum
window (520 × 400) up the essentials are visible and usable and nothing
scrolls horizontally. Until the owner decides otherwise, the window keeps
FR-027 and differs from the reference below 760 px:

| Below 760 px | The reference | This window (keeps FR-027) |
| --- | --- | --- |
| Menus | The eight menus, unchanged; the page scrolls sideways | Folded into one "Menu" control holding every item ("File · Open Folder", …) |
| Search | Full field; partly or wholly off-screen | Its icon; the palette spans the top bar when open |
| Sidebar | Beside the canvas (250 px), leaving the canvas narrower than the window allows | Hidden; its chevron opens it over the canvas (Escape or a click outside closes it) |
| Horizontal scroll | Yes | None |

Both renderings, at 759 × 600 and 520 × 400, are in the visual comparison.
The owner may instead accept horizontal scrolling below 760 px (amending
FR-027 and SC-007), which would let the window match the reference there.

**Reading the rest of this specification.** Where a user story, an
acceptance scenario, an entity or a scope line below still names the
navigation rail, the side panel, its edge or its width, it is read through
this table: the rail's entries are the menus, the status-bar cells and the
prompt-footer controls; the side panel is the modal panel (opened, closed,
restored and focused exactly as the side panel was, but not resized); the
region cycle runs top bar → sidebar → canvas → status bar (and the panel
while open); and the covering behaviour below the threshold is the sidebar's.
Every other requirement keeps its meaning.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Work in a coherent workbench around the conversation (Priority: P1)

A developer opens the desktop application and sees a workbench: a navigation
rail that names the surfaces the window offers, a main area that holds the
conversation, a side panel that shows a supporting surface when asked, and a
status bar that shows what the Core reports. Every D1 capability is still
there and works exactly as before; it is now arranged so the conversation has
the room it needs and nothing overlaps or is cut off.

**Why this priority**: The shell is the frame every later phase (D3–D5) adds
to. Without it, D2's other stories have nowhere to live, and each later phase
would invent its own layout.

**Independent Test**: Launch against the offline scripted Core and verify that
the rail, main area, side panel and status bar are present, that the
conversation is in the main area, and that every D1 acceptance flow (send,
streamed reply, cancel, mode change, question, permission, failure views,
"Closing…", unconfigured provider) passes inside the shell with D1's
behaviour unchanged.

**Acceptance Scenarios**:

1. **Given** the Core is ready, **When** the window shows, **Then** the
   navigation rail, the main area with the conversation, and the status bar
   are visible, and the side panel is in the state the person last left it
   (or closed on a first launch).
2. **Given** the conversation is in the main area, **When** the person sends a
   prompt, answers a question or a permission, cancels or changes mode,
   **Then** each behaves exactly as in D1.
3. **Given** the Core fails before or after ready, **When** the failure view
   shows, **Then** it shows inside the shell, and the rail, the status bar and
   the palette stay usable for the actions that apply to a failure.
4. **Given** the rail, **When** the person looks for the editor, a terminal,
   tasks, delegates, agents or session history, **Then** none is offered: no
   entry, no empty panel, no disabled placeholder.

---

### User Story 2 — Find and run any action from a command palette (Priority: P1)

The person opens a command palette from the keyboard or with the mouse, types
a few letters, and runs any action the window can actually perform right now —
send focus to the composer, cancel, change mode, change workspace, show a
panel, reset the layout, show the keyboard shortcuts. The palette never lists
an action that does nothing or that belongs to a later phase.

**Why this priority**: A palette is the way a professional tool makes every
action reachable without hunting; it is also the honest index of what the
window can do. Building it on the existing shared registry keeps the button,
the key and the palette entry the same action.

**Independent Test**: Open the palette, verify that it lists exactly the
commands enabled now, that typing narrows and ranks them, that Enter runs the
highlighted one with the same effect as its button or key, and that Escape
closes it and returns focus where it was. Repeat in the failure state and in
the unconfigured state and verify the list changes to what applies there.

**Acceptance Scenarios**:

1. **Given** the Core is ready, **When** the person presses the palette
   shortcut or clicks the palette control, **Then** the palette opens with the
   input focused and every currently available command listed with its
   shortcut, if any.
2. **Given** the palette is open, **When** the person types part of a command's
   title or one of its keywords, **Then** the list narrows to matching commands
   and the best match is highlighted first.
3. **Given** a highlighted command, **When** the person presses Enter or clicks
   it, **Then** the palette closes and the command runs with exactly the effect
   of its button or shortcut.
4. **Given** the Core is not ready (starting, checking, restarting, failed,
   stopping), **When** the palette opens, **Then** commands that need a ready
   Core are not listed, and commands that apply (for example "Try again" after
   a failure) are.
5. **Given** the palette is open, **When** the person presses Escape or clicks
   outside it, **Then** it closes without running anything and focus returns
   to the element that had it before.

---

### User Story 3 — Operate everything with the keyboard, accessibly (Priority: P1)

A person who uses only the keyboard, or a screen reader, can reach every
region and every action, always sees where focus is, never gets stuck, and is
told what changed. Shortcuts follow each platform's conventions and are
listed in one place.

**Why this priority**: Accessibility and keyboard operation are not polish; a
shell that traps focus or hides it fails people outright, and retrofitting
focus order after D3–D5 add surfaces is far harder than getting the frame
right.

**Independent Test**: With only the keyboard, move through every region,
open and close every panel and the palette, run every command, and verify
visible focus at every step, no trap, and focus returning to its origin after
every overlay closes. Run an automated accessibility check on every window
state and verify no violation.

**Acceptance Scenarios**:

1. **Given** any window state, **When** the person presses Tab and Shift+Tab
   repeatedly, **Then** focus moves through every interactive element of every
   visible region in a stable, logical order, is always visibly indicated, and
   never stays stuck.
2. **Given** the person presses the shortcut that moves between regions,
   **When** they press it repeatedly, **Then** focus moves rail → main area →
   side panel (when open) → status bar and around again.
3. **Given** any panel or overlay, **When** it opens, **Then** focus moves into
   it; **When** it closes, **Then** focus returns to the element that opened
   it, or to the composer if that element no longer exists.
4. **Given** the keyboard shortcuts reference, **When** the person opens it,
   **Then** it lists every bound shortcut with the command it runs, using the
   platform's modifier name, and every listed shortcut works.
5. **Given** a screen reader, **When** the Core's state changes or a panel
   opens, **Then** the change is announced once, and regions and controls have
   names that say what they are.
6. **Given** the composer has focus, **When** the person types, **Then** no
   workbench shortcut steals a character a person types as text.

---

### User Story 4 — Arrange panels, and find them as left (Priority: P2)

The person opens, closes and resizes the side panel with the mouse or the
keyboard, picks which supporting surface it shows, and on the next reload,
Core restart, workspace change or launch finds the layout exactly as they left
it.
"Reset layout" returns everything to the default. Nothing in what is kept
includes a message, a credential or anything the Core reported.

**Why this priority**: Practical sizing and persistent layout are what make a
workbench usable day to day, but the window is already usable without them.

**Independent Test**: Change the panel width, visibility and selected surface;
reload the window, restart the Core, change workspace and relaunch the
application, and verify the layout is restored exactly each time. Corrupt the
stored layout and verify the default layout appears without an error; send an
invalid layout write and verify it is refused and the stored preferences are
unchanged. Search everything stored for the
canary credential and for conversation text and find neither.

**Acceptance Scenarios**:

1. **Given** the side panel, **When** the person drags its edge or uses the
   resize shortcut, **Then** it resizes within its allowed range and the main
   area keeps at least its minimum width.
2. **Given** a layout the person arranged, **When** the window's content
   reloads, the Core restarts, or the workspace changes, **Then** the layout is
   restored exactly as it was.
3. **Given** a layout the person arranged, **When** the application is closed
   and launched again, in the same or another workspace, **Then** the layout is
   restored exactly as it was.
4. **Given** a stored layout that is unreadable, from another format version,
   or out of range for the current window, **When** the window starts, **Then**
   the default layout (or the nearest valid one) is used and nothing fails.
5. **Given** "Reset layout", **When** the person runs it, **Then** every layout
   preference returns to its default at once.

---

### User Story 5 — See the Core and its diagnostics as reported (Priority: P2)

From the rail, the person opens a Core panel that shows what the native side
and the Core report — the Core's state, its workspace, its identity and
protocol version, the provider, model and configured state, and the restart
count — with the actions that apply now (change workspace, check again, try
again). A diagnostics panel shows the Core's recent diagnostic output as inert
text and can be refreshed. Neither panel ever shows a value the Core did not
report, or a value from before a restart or workspace change as if it were
current.

**Why this priority**: Today this information is squeezed into a status strip
or appears only on failure. A workbench gives it a home, but the conversation
works without it.

**Independent Test**: Open the Core panel and compare every value with what the
native side and the Core reported. Restart the Core and change workspace while
the panel is open and verify every value is replaced by the new report or by
"not reported yet", never kept from before. Feed the diagnostics adversarial
text and verify it is inert.

**Acceptance Scenarios**:

1. **Given** the Core is ready, **When** the person opens the Core panel,
   **Then** it shows the state, workspace, Core identity, protocol version,
   provider, model, configured state and restart count exactly as reported.
2. **Given** the Core panel is open, **When** the Core restarts or the
   workspace changes, **Then** values from before are cleared at once and each
   is shown again only when newly reported.
3. **Given** the diagnostics panel, **When** the person opens or refreshes it,
   **Then** it shows the native side's current diagnostic tail as inert text,
   with control characters visible and no clickable links.
4. **Given** the Core panel, **When** an action shown there does not apply in
   the current state, **Then** it is not offered there, in the palette, or by
   its shortcut.

---

### User Story 6 — Use the workbench in a narrow window (Priority: P3)

When the window is narrow — down to its minimum size — the workbench adapts:
the side panel no longer squeezes the conversation but covers it and can be
dismissed, the rail stays reachable, and the composer, Send and the status
remain visible. Nothing requires horizontal scrolling.

**Why this priority**: People tile windows and work on small screens, but the
default window is wide enough for the full layout.

**Independent Test**: Resize the window to the minimum, to just below and just
above the compact threshold, and to a wide size, and verify at each that no
horizontal scrolling appears, the composer and status remain visible, and every
command remains reachable.

**Acceptance Scenarios**:

1. **Given** a window narrower than the compact threshold, **When** the person
   opens the side panel, **Then** it covers the main area instead of shrinking
   it, and can be dismissed with Escape or a click outside it.
2. **Given** the window at its minimum size, **When** the person uses the
   window, **Then** the composer, Send, the Core state and the palette control
   are visible and nothing scrolls horizontally.
3. **Given** a window that grows past the compact threshold with the side
   panel covering the main area, **When** the width crosses it, **Then** the
   panel returns beside the main area at its remembered width.

---

### Edge Cases

- **Core restart while the palette is open.** The list updates to what applies
  in the new state; a command that stops applying disappears; nothing runs by
  itself.
- **Workspace change while a panel is open.** The panel stays open; every Core
  value in it is cleared and shown again only when the new Core reports it; the
  conversation follows D1's rules for a new workspace.
- **Window content reload.** Layout, open panel and focus target come back; no
  Core value is restored from before the reload; the conversation follows D1's
  reload rules.
- **Wake from sleep.** While the Core is being checked, the shell stays
  usable for layout and navigation, but every command that would reach the
  Core is unavailable in buttons, shortcuts and the palette, exactly as D1
  gates them. (Physical suspend and resume remain NOT VERIFIED.)
- **"Closing…".** While the Core stops, only Quit now and the shell's own
  layout, navigation and diagnostics commands apply; nothing new is sent to
  the Core.
- **A shortcut that collides.** A shortcut that the platform or the WebView
  already uses for something essential (copy, paste, select all, undo, close
  window, system shortcuts) is not reassigned.
- **An invalid layout write.** The native side refuses it with a reason; the
  stored preferences, including D1's values, stay as they were, and the window
  keeps its current layout.
- **A stored panel width wider than the current window.** It is limited to the
  allowed range for the current width, without changing what is stored until
  the person resizes.
- **Very long values.** A long workspace path, model name or Core identity in
  the status bar or Core panel is truncated visually with the whole value
  available on focus or hover, never wrapped over another control.
- **Right-to-left and mixed text.** Persian and mixed-direction text in the
  conversation, panels and palette results is shown as the platform renders
  it, in its own direction; the layout does not mirror.
- **Several displays and scaling.** A stored layout opened on a display with a
  different scale or size stays within the allowed ranges.
- **Reduced motion.** When the operating system asks for reduced motion, panels
  open and close without animation. On macOS a change of the preference is
  shown from off to on, each state confirmed by the operating system and the
  WebView, with the original setting restored exactly (Clarifications,
  2026-10-16).
- **Untrusted text.** Command titles are the application's own; any Core- or
  native-reported text shown in panels, the status bar or palette results is
  inert, as in D1.

## Requirements *(mandatory)*

### Functional Requirements

**The shell**

- **FR-001**: The window MUST present the reference's regions (Clarifications,
  2026-10-17) whenever a Core exists or is starting: a top bar, a left
  sidebar, a central canvas holding the conversation over the prompt area,
  and a status bar; the Core panel, diagnostics and keyboard shortcuts open as
  a modal panel over them. The failure,
  no-workspace, "Closing…" and unconfigured-provider views of D1 MUST appear in
  the main area of that shell.
- **FR-002**: Every D1 capability MUST remain available and behave as D1
  specifies inside the shell: the conversation, tool activity, questions,
  permissions, mode, cancel, links, workspace change, check again, try again,
  Quit now, recovery after reload and restart, and the wake check.
- **FR-003**: The status bar MUST show the Core's state, the workspace as the
  Core reports it, the provider, the model and the configured state, from the
  same reports D1's status strip uses, in the reference's cells; the palette
  control is in the prompt footer (Clarifications, 2026-10-17).
- **FR-004**: The top bar MUST show the reference's menus (File, Model,
  Memory, Skills, Context, Agent, Option, MCP), its search (the palette's
  place, FR-011) and its actions; the sidebar its toolbar, its WORKSPACE and
  EXPLORER tabs and its SESSION, AGENTS and TASKS sections. Every item either
  runs a real D2 command or is a truthful unavailable or empty state.
- **FR-005**: Elements of a later phase (an editor, workspace browsing, a
  terminal, agents, tasks, sessions, loops, skills, memory, MCP, providers,
  installers, updates, credential entry) MAY appear only as the reference's
  structure in a truthful unavailable or empty state: unavailable controls are
  marked so, say so when chosen and run nothing; lists show only what the Core
  reported or an honest empty state. No palette command or shortcut is
  offered for them (Clarifications, 2026-10-17).

**Surfaces and navigation**

- **FR-006**: The D2 surfaces are exactly: the conversation (main area), the
  Core panel (User Story 5), the diagnostics panel (User Story 5), and the
  keyboard shortcuts reference (User Story 3). Each has a real D2 function; the
  rail offers nothing else.
- **FR-007**: Choosing a surface from a menu, the status bar, the prompt
  footer, its shortcut or the palette MUST show it: the conversation in the
  canvas, the others in the modal panel. Choosing the surface already shown
  MUST close the panel.
- **FR-008**: The Core panel MUST show only values the native side or the Core
  reported for the current Core: state, workspace (as the Core reports it),
  Core name and version, protocol version, provider, model, configured state
  and restart count of the allowed limit. A value not yet reported MUST be
  shown as "not reported yet", never as a guess or a value from a previous Core.
- **FR-009**: The diagnostics panel MUST show the native side's current
  diagnostic tail as inert text, MUST refresh on request and whenever the Core
  fails, and MUST be available in every state, not only on failure.
- **FR-010**: Actions shown in the Core panel (change workspace, check again,
  try again) MUST be the same commands as their status-bar, failure-view and
  palette forms, offered only when they apply.

**Command palette**

- **FR-011**: The window MUST provide a command palette, opened by a shortcut
  and by visible controls (the top bar's search and the prompt footer's
  "Command"), shown as the reference's search with its results below,
  built on the shared command registry: every
  palette entry, button and shortcut for the same action is one command.
- **FR-012**: The palette MUST list exactly the commands enabled in the current
  state, with their group and shortcut; it MUST NOT list a command that would
  do nothing, a command of a later phase, or a command that needs a native
  operation the window does not have.
- **FR-013**: Typing in the palette MUST narrow and rank results with the
  shared registry's search, highlight the best match, and keep the highlight
  on the first result after every change to the query.
- **FR-014**: Enter or a click on a result MUST close the palette and run that
  command with exactly the effect of its button or shortcut; Escape or a click
  outside MUST close it without running anything.
- **FR-015**: The commands in D2 MUST include at least: open the palette;
  focus the composer; send; cancel; each mode, and the next and previous mode;
  change workspace; check again; try again; Quit now (while closing); show
  each D2 surface; open and close the panel; show and hide the sidebar; reset
  the layout;
  jump to the newest message; and show the keyboard shortcuts. Each is listed
  only when it applies (FR-012).

**Keyboard, mouse and focus**

- **FR-016**: Every action reachable with the mouse MUST be reachable with the
  keyboard alone, and every action reachable with a shortcut MUST also be
  reachable with the mouse.
- **FR-017**: Shortcuts MUST use the platform's primary modifier (Command on
  macOS, Control on Windows and Linux), MUST NOT take over a key the platform or
  text editing needs (Tab and Shift+Tab move focus; copy, paste, cut, select
  all, undo and redo keep their meaning), and MUST NOT act on a key typed into a
  text field unless it carries a modifier. Every binding MUST resolve to a
  command, as the shared registry enforces.
- **FR-018**: Focus MUST be visibly indicated at all times with the design
  tokens' focus styling; Tab order MUST be stable and logical; a region-cycling
  shortcut MUST move focus between the regions of FR-001; no state may trap
  focus.
- **FR-019**: Opening a panel or overlay MUST move focus into it; closing it
  MUST return focus to the element that opened it, or to the composer if that
  element no longer exists. Escape MUST close the topmost overlay (an open
  menu, the palette, the modal panel) or the covering sidebar.
- **FR-020**: Regions and controls MUST have accessible names; state changes
  the person needs to know (Core state, a panel opening, the palette's result
  count) MUST be announced once to assistive technology; motion MUST follow
  the operating system's reduced-motion preference.

**Layout preferences**

- **FR-021**: The application MUST keep one set of layout preferences — side
  panel open or closed, its width, and which surface it shows — across window
  reloads, Core restarts, workspace changes and application launches, in the
  application's existing native preferences file, beside the values D1 keeps
  there.
- **FR-022**: Stored layout preferences MUST contain only presentation values:
  never a message, tool output, a prompt, a credential, a Core identity, a
  workspace path or anything else the Core reported.
- **FR-023**: Stored layout preferences that are unreadable, of another format
  version, or out of range MUST be ignored or limited to the valid range
  without an error, and "Reset layout" MUST return every layout preference to
  its default.
- **FR-024**: Layout preferences MUST be the same for every workspace in a
  launch; a workspace change MUST NOT reset or replace them.

**Narrow windows**

- **FR-025**: *Withdrawn 2026-10-17* — the reference has no resizable side
  panel. The stored `panel_width` keeps its validation (FR-036) and is not
  drawn.
- **FR-026**: From 760 logical px — the reference's minimum width — up, the
  sidebar MUST sit beside the canvas, as in the reference; below it (pending
  the owner's decision above), the sidebar MUST be hidden and, when opened,
  cover the canvas instead of shrinking it, dismissible with Escape or a
  click outside, with focus returned to its opener.
- **FR-027**: At every window size from the minimum (520 × 400) upward, the
  composer, Send, the Core state, the palette control and the other essential
  actions (the menus or the "Menu" control, the sidebar toggle, the mode
  control, "Change workspace…") MUST be visible,
  reachable and usable, and nothing in the window may scroll horizontally.
  The minimum describes the native window: on macOS the page is shorter by
  the title bar that Tauri counts inside the window's inner size (a measured
  offset, the same at every size, at most 40 px — 32 px on the CI runner, so
  520 × 368 at the minimum); on Windows and Linux the offset is zero
  (Clarifications, 2026-10-16).

**Core state and boundaries**

- **FR-028**: The shell MUST NOT keep, cache, derive or display a Core value
  that the Core or the native side did not report for the current Core. On a
  Core restart or workspace change, every Core value shown in the shell MUST be
  cleared and shown again only when newly reported.
- **FR-029**: Every command that reaches the Core MUST pass the same gates as
  in D1 — the Core must be ready, the wake check settled, the session read —
  whether it is run from a button, a shortcut or the palette.
- **FR-030**: D2 MUST NOT change the Core, the protocol, or the shared packages'
  behaviour for the terminal interface; additions to shared packages MUST be
  additive. D2 adds exactly two native operations — one that reads the stored
  layout preferences and one that writes them — and no other; the window's
  native operation set becomes D1's nine plus these two, declared in one place
  and granted, in the release build, exactly as D1's are. D1's specification
  and contracts keep their record of nine operations unchanged, as history;
  D2's own contract states the new exact set.
- **FR-031**: D2 MUST NOT add an application-level action that needs a native
  operation beyond FR-030's two: no quit, reload-window or open-log-folder
  operation. Quitting stays with the window's own close control and the
  operating system's close flow, through D1's stop sequence.
- **FR-032**: All text from outside the application shown anywhere in the
  shell — status bar, panels, palette results that include it — MUST be inert
  exactly as D1 requires, and the credential boundary of D1 MUST hold for every
  D2 surface and for stored layout preferences.

**Verification**

- **FR-033**: Every D2 behaviour MUST be covered by deterministic tests on
  Windows, Linux and macOS, run offline with the scripted Core, with no provider
  call, no credential and no paid tokens; every D1 behaviour and regression
  test MUST still pass on the same commit, with only the two command-set
  assertions that SC-001 names changed, from nine to eleven.
- **FR-034**: Layout and focus behaviour MUST be verified in the real WebView on
  all three platforms at the minimum size, just below and just above the
  compact threshold, and a wide size; a platform without recorded evidence
  leaves D2 incomplete, and NOT VERIFIED is never a pass.
- **FR-035**: D2 MUST keep D1's recorded limitations — physical suspend and
  resume, and the native link dialog's appearance and a real person's answer —
  as NOT VERIFIED, and MUST NOT describe them as verified.
- **FR-036**: The native side MUST validate every layout write before storing
  it: the format version, only the known fields, their types, the side panel
  width within its allowed range, the surface among FR-006's, and a bounded
  size. An invalid write MUST be refused with a reason and MUST leave the stored
  preferences, including D1's values, unchanged. A read MUST return only valid
  values, with defaults for anything missing or invalid.
- **FR-037**: The release command-manifest test MUST assert the exact set of
  FR-030 (D1's nine plus the two layout operations, and nothing else), and the
  credential-canary test MUST cover both layout operations — their arguments,
  their results and the stored preferences file — across every D2 flow.

### Key Entities

- **Workbench shell**: the window's layout frame — navigation rail, main area,
  side panel, status bar — and its keyboard and focus model. It presents; it
  decides nothing the Core owns.
- **D2 surface**: something the rail can show: the conversation, the Core
  panel, the diagnostics panel, the keyboard shortcuts reference.
- **Command**: one action with an id, a title, a group, keywords, an "applies
  now" rule and optional shortcuts, held in the shared registry and reached the
  same way from a button, a shortcut or the palette.
- **Command palette**: an overlay that searches and runs the commands that
  apply now.
- **Layout preferences**: one set of non-secret presentation values for the
  whole application — side panel open or closed, its width, the surface it
  shows — with a format version and safe defaults, kept in the existing native
  preferences file beside D1's window geometry and last selected folder, and
  read and written only through the two layout operations (FR-030, FR-036).
  They never hold Core state, conversation content or credentials.
- **Compact threshold**: the window width below which the side panel covers the
  main area instead of sitting beside it.
- **Core report**: a value the native side or the Core stated for the current
  Core (state, workspace, identity, protocol version, provider, model,
  configured state, restart count, diagnostic tail). The shell shows reports;
  it never makes them up.

### Surface classification (Constitution XI)

| Surface | Status | Evidence / Notes |
| --- | --- | --- |
| TUI | UNCHANGED BUT VERIFIED | The terminal interface in `apps/tui/` is not changed. D2 reuses `@comodor/commands` (and may add to shared packages only additively, FR-030); verified by `bun test apps/tui/test/bun/renderer.test.tsx` and `npm test` passing unchanged, and by the terminal's palette (`apps/tui/src/palette.ts`) and command list (`apps/tui/src/commands.ts`) behaving as before. |
| Web UI | UNCHANGED BUT VERIFIED | `src/comodor/web/` is not changed, embedded or served by the desktop application; verified by `tests/test_web.py` and `tests/test_real_web_ui.py` passing unchanged. |
| CLI / Headless | UNCHANGED BUT VERIFIED | The desktop application keeps starting `comodor core --stdio` unchanged (`src/comodor/transport/__init__.py::serve_stdio`); verified by `tests/test_core_stdio.py` and `tests/test_transport_commands.py` passing unchanged. |
| API / Protocols | UNCHANGED BUT VERIFIED | Protocol v2 (`schemas/protocol/v2.json`) is used unchanged; every Core value the shell shows comes from existing methods and events (FR-008, FR-028); verified by `python tools/protocol-codegen.py --check` and the protocol test suites. |
| Desktop | REQUIRED | The desktop application gains the workbench shell, the D2 surfaces, the command palette, the keyboard and focus model, narrow-window behaviour and layout preferences (FR-001–FR-037). The native operation set grows from D1's nine by exactly two layout operations (read, write) and nothing else (FR-030, FR-031). The computer-control backend in `src/comodor/desktop/` is unchanged, verified by `tests/test_desktop.py` passing unchanged. |
| Channels / Integrations | NOT APPLICABLE | Channel integrations (`src/comodor/channels/`) run their own sessions and never reach a desktop window; D2 adds no channel and no integration. |
| Docker / Packaged Runtime | UNCHANGED BUT VERIFIED | The container image and the Python wheel and sdist do not include the desktop application (`pyproject.toml` `[tool.hatch.build]`); verified by the wheel-contents guard (`python tools/check-wheel-contents.py`). Desktop packaging belongs to D6. |
| Persistence / Shared State | REQUIRED | One non-secret layout, kept across launches and workspaces in the existing native preferences file beside D1's values, with a format version, native validation and reset (FR-021–FR-024, FR-036). Session persistence stays the Core's; the window's per-launch recovery facts are unchanged. |
| Security / Authorization | REQUIRED | Every D2 surface and the stored layout preferences stay inside D1's credential boundary and inert-text rule (FR-032); every Core-bound command keeps D1's gates whatever reaches it (FR-029); the two new native operations accept only validated presentation values (FR-036) and are pinned by the release command-manifest and credential-canary tests (FR-037); no other native operation is added (FR-031). Modes and permissions stay in the Core. |
| Tests / Documentation | REQUIRED | Deterministic window, scenario and accessibility tests on Windows, Linux and macOS (FR-033, FR-034); the release command-manifest and credential-canary tests extended to the layout operations (FR-037), with the two command-set assertions moving from nine to eleven and every other D1 test keeping all of its assertions (SC-001); `docs/desktop-architecture.md` updated with the workbench shell and the new native operation set; D1's NOT VERIFIED limitations carried forward unchanged (FR-035). |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every D1 behaviour and every D1 regression test passes on the
  exact commit under review, on Windows, Linux and macOS. Exactly two existing
  D1 assertions change, both command-set assertions, and only from nine to
  eleven operations for the two approved layout operations (FR-030, FR-037):
  the native operation-set test in `apps/desktop/src-tauri/src/commands.rs`
  and the release command-manifest check in
  `apps/desktop/e2e/release-manifest.mjs`. Every other existing D1 assertion
  stays as it is; no D1 test is deleted, skipped, loosened or rewritten.
  Otherwise D1's test files and test infrastructure may only gain additions
  that change no existing assertion: new D2 tests and test modules, scenarios
  with their registrations and setups, harness acts and checkpoints (including
  an explicit virtual-display size and a relaunch with the same data folder),
  credential-canary flows, and answers for the two layout operations in the
  window tests' native double. D1's specification and contracts keep their
  nine-operation record as history; the current release build exposes exactly
  eleven (SC-016).
- **SC-002**: 100% of the actions reachable with the mouse are reachable with
  the keyboard alone, and 100% of shortcuts and palette entries reach an action
  that is also reachable with the mouse, in the full-coverage keyboard test.
- **SC-003**: For every command in the palette, typing at most the first three
  letters of a word in its title puts it among the first three results, and
  Enter runs the highlighted result, in 100% of the palette tests.
- **SC-004**: In every window state tested (ready, starting, checking,
  restarting, failed, unconfigured, closing, no workspace), the palette lists
  exactly the commands that apply — zero that do nothing and zero missing — in
  100% of the tests.
- **SC-005**: After every panel or overlay closes, focus is on the element that
  opened it (or the composer if that element is gone), and Tab cycling reaches
  every interactive element with no trap, in 100% of the focus tests.
- **SC-006**: An automated accessibility check of every window state reports
  zero violations of the WCAG 2.1 Level A and AA rules it can test, on all three
  platforms.
- **SC-007**: At the minimum size, just below and just above the compact
  threshold, and a wide size, the composer, Send, the Core state, the palette
  control and the other essential actions are visible, reachable by the
  pointer and usable (a draft makes Send available; the palette opens inside
  the window and Escape closes it), and the window has no horizontal
  scrolling, in 100% of the layout checks on all three platforms — judged on
  macOS against the page that remains after the measured title-bar offset
  (FR-027).
- **SC-008**: The layout a person arranged is restored exactly after a window
  reload, a Core restart, a workspace change and an application relaunch, in
  100% of the tests on all three platforms.
- **SC-009**: A stored layout that is unreadable, of another format version, or
  out of range yields a valid layout without an error in 100% of the tests.
- **SC-010**: After a Core restart or workspace change, zero values from the
  previous Core are shown as current anywhere in the shell, in 100% of the
  tests.
- **SC-011**: A canary credential appears zero times in the shell's surfaces,
  palette, announcements and stored layout preferences, and conversation text
  appears zero times in stored layout preferences, across every D2 flow.
- **SC-012**: Zero palette commands or shortcuts refer to a later phase, and
  every later-phase element shown (FR-005) is unavailable or empty in 100% of
  the checks: it is marked unavailable, runs nothing when chosen, and shows no
  value the Core did not report.
- **SC-013**: Every acceptance test runs without network access to a model
  provider, without a credential and without paid tokens.
- **SC-014**: The terminal interface's renderer suite, the frontend tests, the
  Python test suite and the protocol code-generation check pass unchanged on
  the exact commit under review.
- **SC-015**: D2's documentation and pull-request evidence list physical
  suspend and resume, and the native link dialog's appearance with a real
  person's answer, as NOT VERIFIED, as D1 recorded them.
- **SC-016**: The release build grants exactly D1's nine native operations plus
  the two layout operations, and no other, in 100% of the release
  command-manifest runs.
- **SC-018**: Screenshots of the real desktop WebView — not DOM checks — on
  Windows, Linux and macOS, at the reference viewport (1440 × 900), the
  minimum window, either side of the 900 px threshold and either side of the
  reference's 760 px minimum width, in the normal,
  menu, question, palette and panel states, are compared section by section
  with the reference rendered at the same sizes and states; every material
  difference is either corrected or listed with its reason (a truthful state
  where the reference shows demo content, the Core's own labels, a platform's
  title bar or font rendering). The appearance is not accepted while a
  material difference remains unlisted.
- **SC-017**: 100% of invalid layout writes in the tests (unknown fields, wrong
  types, out-of-range width, an unknown surface, another format version,
  oversized input) are refused, and the stored preferences file, including
  D1's values, is byte-for-byte unchanged after each.

## Scope Boundaries

**In D2**: the workbench shell around D1's conversation — navigation rail, main
area, side panel, status bar; the Core panel, the diagnostics panel and the
keyboard shortcuts reference; the command palette over the shared registry;
keyboard, mouse and focus behaviour; narrow-window behaviour; non-secret
layout preferences with reset; deterministic cross-platform tests.

**Not in D2**, each kept for its phase or for its own specification:

- an editor, file tree or any workspace browsing (D3);
- an integrated terminal (D4);
- agent, task, delegate and session panels, several sessions, and history
  browsing or reopening earlier conversations (D5);
- installers, code signing, auto-update, a bundled Python runtime, release and
  deployment (D6);
- credential entry of any kind in the desktop application;
- any native operation beyond the two layout operations, including quit,
  reload-window and open-log-folder commands (quitting stays with the window's
  close control and the operating system);
- choosing the model from the window, theme switching or a second theme;
- a change to the Core, the protocol, or the terminal interface's behaviour;
- attaching the terminal interface to the desktop's Core, and remote Cores;
- physical verification of suspend and resume or of the native link dialog,
  which remain NOT VERIFIED as D1 recorded.

## Assumptions

- D1 (PR #62) is the base; its behaviour, tests and recorded limitations are
  unchanged by D2 except where this specification says otherwise.
- The compact threshold is 900 logical pixels of window width; the side panel
  is between 240 logical pixels and half the window width, 320 by default; the
  main area is at least 360 logical pixels wide. The plan may refine these
  values; the behaviour of FR-025–FR-027 is what is required.
- The palette shortcut is the primary modifier with K, matching the terminal
  interface's Ctrl+K; the region-cycling shortcut is F6 and Shift+F6, the
  common desktop convention. The plan fixes the full binding list within
  FR-017.
- The window keeps its current minimum size (520 × 400) and default size
  (1100 × 760).
- Layout preferences are one set for the whole application, not per workspace
  (FR-024), as the owner decided (Clarifications, 2026-10-07).
- The window uses the design tokens' `desktop` mapping, added additively
  beside the terminal one (Clarifications, 2026-10-15); every text colour in
  it meets WCAG 2.1 AA on the grounds it is drawn on, and its focus colour
  meets the contrast the accessibility check requires.
- The offline scripted Core already used by D1's tests is sufficient for every
  D2 acceptance test.
- Accessibility is checked with an automated rule-based checker in the real
  WebView plus keyboard-only scenario tests; a manual screen-reader pass may be
  recorded as additional evidence but is not claimed unless performed.
