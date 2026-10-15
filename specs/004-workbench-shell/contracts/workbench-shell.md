# Contract: the workbench shell (window)

What the window presents and how a person operates it (spec User Stories 1–6,
FR-001–FR-029, FR-032). The shapes behind it are in
[data-model.md](../data-model.md).

## Regions

| Region | Accessible role and name | Present |
| --- | --- | --- |
| Navigation rail | `navigation` "Workbench" | always, from the first status |
| Main area | `main` — D1's existing `<main data-testid="window">`; the shell adds no second `main` | always |
| Side panel | `complementary`, named after its surface ("Core", "Diagnostics", "Keyboard shortcuts") | when open |
| Status bar | `contentinfo`, with a `status` live region for the Core state | always |

The rail offers exactly: Conversation, Core, Diagnostics, Keyboard shortcuts,
and the palette control. Nothing for an editor, workspace browsing, a terminal,
agents, tasks, delegates, session panels, history, installers, updates or
credential entry — no entry, no disabled entry, no empty panel (FR-005).

D1's views keep their content and behaviour and appear in the main area:
conversation, failure (every class), no workspace, unconfigured provider,
"Closing…". The status bar replaces D1's status strip with the same values and
the same "Change workspace…" action.

D1's tests read the page, and every one of their assertions must keep
passing (SC-001), so the shell keeps — with the status bar rendering D1's
`StatusStrip` once, with the props D1 passes today, and `SessionView` and the
non-ready branch of `App` no longer rendering their own:
exactly one element with `data-testid="status-strip"` (the status bar) with
D1's `data-state` values; the `.status-state` and `.status-workspace` labels
and their text; the "Change workspace…" button text; every `data-testid` D1's
views and cards use; D1's composer, mode control, form and permission card
structure. A new region adds its own `data-testid` values and never reuses
D1's.

## Commands

One registry (`@comodor/commands`) per window. Every button, shortcut and
palette entry for the same action is the same command. `gated` is D1's gate
(`session.gated`: the Core is not ready, a wake check is pending, the session
is being read again, or the connection is not ready).

| Id | Title | Group | Keys | Enabled when |
| --- | --- | --- | --- | --- |
| `palette.open` | Commands | Workbench | mod+K | the palette is closed |
| `conversation.send` | Send | Conversation | Enter (in the composer) | D1's Send rule: not `gated`, model configured, text present |
| `conversation.cancel` | Cancel | Conversation | Escape (in the composer, nothing covering it) | D1's Cancel rule: busy and not `gated` |
| `composer.focus` | Go to the message box | Conversation | — | a session is shown |
| `view.tail` | Jump to the newest output | Conversation | — | a session is shown |
| `mode.act` | Mode: ACT | Mode | — | not `gated` and the confirmed mode is not ACT |
| `mode.plan` | Mode: PLAN | Mode | — | not `gated` and the confirmed mode is not PLAN |
| `mode.ask` | Mode: ASK | Mode | — | not `gated` and the confirmed mode is not ASK |
| `mode.next` | Next mode | Mode | mod+Shift+M | not `gated` |
| `mode.previous` | Previous mode | Mode | — | not `gated` |
| `workspace.change` | Change workspace… | Core | — | D1: starting, handshaking, restarting, ready, checking, failed or no workspace; not stopping |
| `core.check_again` | Check again | Core | — | D1: the Core reports the provider unconfigured and `check_again` applies |
| `core.retry` | Try again | Core | — | D1: the Core state is `failed` |
| `app.quit_now` | Quit now | Core | — | D1: the Core state is `stopping` |
| `view.conversation` | Show the conversation | Workbench | mod+1 | always |
| `view.core` | Show the Core panel | Workbench | mod+2 | always |
| `view.diagnostics` | Show diagnostics | Workbench | mod+3 | always |
| `view.shortcuts` | Show keyboard shortcuts | Workbench | mod+/ | always |
| `diagnostics.refresh` | Refresh diagnostics | Workbench | — | the diagnostics panel is shown |
| `panel.close` | Close the side panel | Workbench | Escape (covering mode only; see Escape below) | the side panel is open |
| `panel.wider` | Widen the side panel | Workbench | Left on the focused panel edge | the side panel is open beside the main area and below its maximum |
| `panel.narrower` | Narrow the side panel | Workbench | Right on the focused panel edge | the side panel is open beside the main area and above its minimum |
| `layout.reset` | Reset layout | Workbench | — | always |
| `region.next` | Next region | Workbench | F6 | always |
| `region.previous` | Previous region | Workbench | Shift+F6 | always |

Rules:

- `mod` is Command on macOS and Control on Windows and Linux; the shortcuts
  reference and the palette show the platform's own name.
- The palette lists `registry.search(query, context)`: enabled commands only,
  ranked by the shared search; the highlight returns to the first result on
  every query change; Enter or a click runs the highlighted command through
  `registry.run` and closes the palette; Escape or a click outside closes it.
- Every binding resolves to a command (the registry enforces it), and every
  command with a binding is also reachable with the mouse (a rail button, a
  panel button, a composer button or a palette entry).
- Reserved and never bound: Tab, Shift+Tab, unmodified printable keys, Enter
  outside the composer, mod+A/C/X/V/Z/Y and mod+Shift+Z, every text-editing
  movement and selection key (arrows, Home, End, Page Up/Down, with or without
  mod or Shift), the platform's window and application shortcuts (mod+W,
  mod+Q, mod+M, mod+H, Cmd+. on macOS, Alt+F4), the desktop environments'
  workspace keys (Ctrl+Alt+arrows), and the WebView's reload and zoom keys
  (mod+R, F5, mod+plus, mod+minus, mod+0).
- The side panel's edge is a focusable window splitter (`separator` with its
  current, minimum and maximum width); with it focused, the arrow keys resize
  in 32 px steps, Home and End go to the minimum and maximum. Arrow keys act
  only there, never globally.
- Inside a text field only modified keys and F6 reach the shell, except Enter
  and Escape in the composer, which keep their D1 meaning.
- A shortcut whose command is not enabled does nothing.
- **Escape**, one press, at most one action, in this order: (1) the palette is
  open → it closes; (2) otherwise the side panel covers the main area →
  `panel.close`; (3) otherwise focus is in the composer → D1's Cancel, handled
  by the composer itself. The shell's dispatcher ignores an event the composer
  has handled (`defaultPrevented`) and never handles Enter or Escape whose
  target is the composer. In the registry, D1's `enter` and `escape` bindings
  stay first, so the composer's `forKey("escape")` still resolves to Cancel.
- Punctuation keys are named by `event.key` and match whether or not the
  keyboard layout needed Shift to produce them (`mod+/` on a layout where `/`
  is Shift+7); letters and digits keep their Shift state (`mod+shift+m`).
- Every command that reaches the Core goes through the window's existing
  session functions (`send`, `cancel`, `chooseMode`, `decide`) and native
  operations, which already apply D1's gates; no command bypasses them.

## Focus

- Every interactive element shows a visible focus ring drawn with the
  `border.focused` token.
- Tab order: rail, main area (conversation, cards, composer), side panel,
  status bar; stable for a given state.
- F6 and Shift+F6 move focus to the first focusable element of the next or
  previous region; the side panel is skipped when closed.
- Opening the palette or a side panel moves focus into it; closing it returns
  focus to the element that opened it, or to the composer if that element is
  gone, or to the main area.
- The palette is a modal dialog with a combobox and a listbox; the side panel
  is not modal; nothing traps focus.
- Announcements: the Core state (status bar live region), a panel opening
  (its name), and the palette's result count — each once.
- With the operating system's reduced-motion preference, panels and the
  palette appear and disappear without animation.

## Sizes

| Value | Default | Rule |
| --- | --- | --- |
| Compact threshold | 900 logical px | judged on the shell root's measured width (`ResizeObserver` `contentRect.width`, fractional, unrounded): below 900 uses the covering panel; the root exposes it as `data-width` and the mode as `data-mode` |
| Side panel width | 320 | 240 to half the window, and never below the main area's 360 |
| Main area minimum | 360 | beside mode only |
| Window minimum | 520 × 400 | unchanged from D1 |

- Beside mode: the panel sits to the right of the main area (the layout does
  not mirror), so moving its edge left widens it; dragging its edge or
  `panel.wider`/`panel.narrower` (32 px steps, from the focused edge or the
  palette) resizes it within the rule; the change is written when the drag
  ends or after each step.
- Covering mode (compact): the panel covers the main area, with Escape and a
  click outside closing it; the rail and status bar stay visible.
- At every size from the minimum, the composer, Send, the Core state and the
  palette control are visible and nothing scrolls horizontally.

## Core values

The Core panel and the status bar show only values reported for the current
Core (data-model §5): state, workspace, Core name and version, protocol
version, provider, model, configured state, restart count of the limit, and
the failure when failed. A restart, a workspace change or a new connection
clears them at once; each reads "not reported yet" until it is reported again.
The diagnostics panel shows the native diagnostic tail as inert text (control
characters visible, no links), fetched when it opens, on refresh, and whenever
the Core fails.

## Layout

The window reads the layout once per page load and writes it after each
completed change ([layout-persistence.md](./layout-persistence.md)). A reload,
a Core restart and a workspace change keep it; Reset layout writes the
defaults once.
