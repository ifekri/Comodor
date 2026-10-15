# Data Model: Workbench Shell (D2)

D1's entities (`specs/003-desktop-foundation/data-model.md`) are unchanged
except where §1 extends `DesktopPreferences` additively. Nothing here is Core
state: the Core keeps owning sessions, modes, permissions and everything it
reports.

---

## 1. DesktopPreferences (native side, persisted) — extended

D1's file, `preferences.json` in the application's per-user configuration
directory, gains one optional field. Its own `version` stays `1`.

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | integer | the file's schema version: `1` (D1, unchanged) |
| `window` | object or absent | D1's window geometry (unchanged) |
| `last_selected_folder` | string, platform path, or absent | D1's last chosen folder (unchanged) |
| `layout` | `LayoutPreference` or absent | **D2**: the one application-wide layout (§2) |

Load rules:

- D1's rules hold for `version`, `window` and `last_selected_folder`.
- `layout` is read on its own: if it is absent, not an object, of another
  format version, has an unknown or missing field, a wrong type or a value out
  of range, it loads as absent. It never makes the rest of the file count as
  malformed (research R2).
- An unknown top-level field is still ignored and never written back (D1).

Save rules: unchanged from D1 — the whole file, from the in-memory copy, under
the preferences lock, through a temporary file and a rename.

Native shape: D1's `prefs::Preferences` type, `prefs::load` and `prefs::save`
keep their fields, signatures and behaviour, because D1's tests in
`src-tauri/src/prefs.rs` build `Preferences` as a struct literal and assert
it has exactly three fields; a fourth field would force an edit to those tests,
which SC-001 does not allow. The layout is carried beside it: a new
`prefs::Stored { preferences: Preferences, layout: Option<LayoutPreference> }`,
loaded by `prefs::load_stored` (D1's `load` rules for the three fields, plus
the lenient `layout` read from the same text) and written by
`prefs::save_stored` through the same temporary file and rename. Every runtime
writer — D1's geometry, folder and launch saves and `write_layout` — goes
through `Stored`, so a D1 save never drops a stored layout.

## 2. LayoutPreference (native side, persisted; page copy in memory)

| Field | Type | Allowed values | Default |
| --- | --- | --- | --- |
| `version` | integer | exactly `1` | `1` |
| `panel_open` | boolean | `true`, `false` | `false` |
| `panel_surface` | string | `core`, `diagnostics`, `shortcuts` | `core` |
| `panel_width` | integer, logical pixels | 240–960 inclusive | 320 |

Validation (native, on `write_layout`; contracts/layout-persistence.md):

- exactly these four fields, no other;
- each of the type and range above;
- the `layout` argument, serialised as compact JSON (`serde_json::to_vec`), is at most 1024 bytes;
- any failure refuses the whole write, names the first problem, and performs
  no file operation.

Invariants:

- Presentation only: never a message, tool output, prompt, credential, Core
  identity, workspace path or anything the Core reported (FR-022).
- One value for the whole application: not keyed by workspace (FR-024).
- The conversation is the main area and is never a `panel_surface`.

The page holds the last value it read or successfully wrote. The width it shows
is `min(panel_width, room)` where `room` comes from §4; showing less never
rewrites the stored width.

## 3. Workbench surfaces and regions (page)

| Region | Landmark | Holds |
| --- | --- | --- |
| Navigation rail | navigation, named "Workbench" | one button per surface, the palette control |
| Main area | main | the conversation, or D1's failure, no-workspace, "Closing…" and unconfigured views |
| Side panel | complementary, named after its surface | the Core panel, the diagnostics panel, or the shortcuts reference |
| Status bar | contentinfo, with a polite live status | Core state, workspace (Core-reported), provider, model, configured, palette control |

| Surface | Where | Content |
| --- | --- | --- |
| `conversation` | main area | D1's conversation, unchanged |
| `core` | side panel | §5's Core values and the actions that apply |
| `diagnostics` | side panel | the native diagnostic tail, inert, refreshable |
| `shortcuts` | side panel | every binding of the registry, with its command title, from the registry itself |

Region focus order (F6 forward): rail → main area → side panel (when shown) →
status bar → rail.

## 4. ShellLayout (page, derived each render)

A pure function of the window's measured width `w` — the shell root's
`ResizeObserver` `contentRect.width`, a fractional number of logical pixels,
never rounded — and the `LayoutPreference`:

| Value | Rule |
| --- | --- |
| `compact` | `w < 900` |
| `room` | `compact` ? `w` minus the rail : `max(0, w - rail - 360)`, capped at `w / 2` |
| `panel_mode` | closed; `beside` (not compact); or `covering` (compact) |
| shown width | `clamp(panel_width, 240, room)`; in `covering` mode, `min(panel_width, w - rail)` |

Transitions:

```text
closed ──open / choose surface──▶ open(beside | covering by compact)
open ──choose same surface / close / Escape (covering)──▶ closed
open(beside) ──width drops below 900──▶ open(covering)
open(covering) ──width rises to 900 or more──▶ open(beside) at remembered width
any ──Reset layout──▶ defaults (§2), written once
```

## 5. CoreReport (page view of native and Core reports)

| Value | Reporter | Shown when |
| --- | --- | --- |
| state | native status `state` | always |
| workspace | Core (`workspace.get`), else native `workspace` until it answers | a Core exists |
| Core name and version | handshake (`client.handshake.core`), native status `core` | after ready |
| protocol version | handshake (`client.handshake.protocol_version`) | after ready |
| provider, model, configured | Core (`model.get`, `model.changed`) | after ready |
| restart count and limit | native status | always |
| failure class and message | native status `failure` | failed |
| diagnostic tail | native `diagnostics` | on open, refresh, failure |

Rules:

- A value is shown only for the current native status and the current client.
  A new client, a status naming another Core (restart), or a new
  `workspace_id` clears every Core value; each reappears only when reported
  again; until then it reads "not reported yet" (FR-008, FR-028).
- No value is computed, guessed or carried from a previous Core.

## 6. WorkbenchCommand (page; shared registry)

A `Command` of `@comodor/commands` with: `id`, `title`, `group`, `keywords`,
`enabled(context)`, `run(context)`, and zero or more bindings. The full
catalogue, its bindings and its `enabled` rules are in
contracts/workbench-shell.md. Every command that reaches the Core is enabled
only when D1's gate is open (`ready`, the wake check settled, the session read,
the connection ready: `session.gated` is false) and when its D1 precondition
holds.

## 7. PaletteState (page; additive shared export)

| Field | Meaning |
| --- | --- |
| `query` | what the person typed |
| `results` | `registry.search(query, context)` — enabled commands only, ranked |
| `index` | the highlighted result; `0` after every query change, `-1` when empty |
| `opener` | the element that had focus before the palette opened (focus return) |

## 8. FocusReturn (page)

A stack of the elements that opened each panel or overlay. Closing pops it and
returns focus to that element if it is still in the document, otherwise to the
composer, otherwise to the main area.
