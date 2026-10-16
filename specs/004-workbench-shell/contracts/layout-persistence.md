# Contract: layout persistence (`read_layout`, `write_layout`)

The two native operations D2 adds (spec FR-021–FR-024, FR-030, FR-036, FR-037).
The stored shape is [data-model.md](../data-model.md) §1–§2.

## `read_layout`

| | |
| --- | --- |
| Arguments | none |
| Returns | `{ "layout": LayoutPreference, "stored": boolean }` |
| Refuses | never |

- `layout` is the stored layout if one is stored and valid; otherwise the
  defaults (`{"version":1,"panel_open":false,"panel_surface":"core","panel_width":320}`).
- `stored` is `true` only when the value came from the file.
- It reads the in-memory preferences the application loaded at start (and
  updated on each accepted write); it performs no file write, ever.
- It returns nothing else from the preferences file: never the window
  geometry, never the last selected folder.

## `write_layout`

| | |
| --- | --- |
| Arguments | `{ "layout": <object> }` |
| Returns | `{ "layout": LayoutPreference }` — exactly what was stored |
| Refuses | with a reason naming the first problem (below) |

Validation, all of it before any file operation, in this order:

1. the `layout` argument, serialised as compact JSON (`serde_json::to_vec`), is at most 1024 bytes;
2. `layout` is a JSON object;
3. it has exactly the fields `version`, `panel_open`, `panel_surface`,
   `panel_width` — an unknown field or a missing one is refused;
4. `version` is the integer `1`;
5. `panel_open` is a boolean;
6. `panel_surface` is one of `core`, `diagnostics`, `shortcuts`;
7. `panel_width` is an integer from 240 to 960 inclusive.

On refusal:

- no file operation of any kind is performed;
- the in-memory preferences are unchanged;
- therefore the preferences file — including `version`, `window` and
  `last_selected_folder` — is byte-for-byte what it was (spec SC-017).

On acceptance:

- under the preferences lock that D1's saves take, the in-memory preferences
  get the new `layout`, and the whole file is saved through D1's temporary
  file and rename;
- if the save fails, the in-memory preferences keep their previous `layout`
  and the operation reports the failure; the file is the old one or the new
  one, never a mix (rename is atomic on all three platforms);
- the result is the stored value.

## What the window does with them

- It calls `read_layout` once per page load, before showing the side panel,
  and independently of the connection: the read never delays or reorders
  `connect`. An answer that is not exactly `{layout, stored}` with a valid
  layout (a refusal, an error, or D1's test double's `{}`) means the defaults,
  without an error.
- It calls `write_layout` after each completed change: open or close, choose a
  surface, finish a drag, each keyboard resize step, Reset layout.
- A refused or failed write leaves the window's layout as the person set it,
  says so once in a quiet notice, and the next change writes again.
- Nothing about the layout is ever sent to the Core.

## Verification

| Proof | Where | What |
| --- | --- | --- |
| Validation | native unit | each rule 1–7 refused with its reason; each boundary accepted (240, 960, every surface, both booleans) |
| Byte-identical on refusal | native unit and integration | the file is seeded with bytes any save would change (compact formatting, an unknown top-level field, a trailing newline); for every refused case of SC-017 (unknown field, wrong type, out-of-range width, unknown surface, another version, over 1 KiB, not an object, missing field), the file's bytes before and after are equal, and the directory holds no temporary file; mutation check: performing the save before validating fails the test |
| Lenient load | native unit | a file whose `layout` is malformed, of another version or out of range loads with `layout` absent and `window` and `last_selected_folder` intact |
| Atomic save | native unit | an accepted write round-trips; no temporary file remains; a failing save leaves the in-memory layout unchanged |
| No other value exposed | native unit | `read_layout`'s result has exactly `layout` and `stored`, and `layout` exactly its four fields |
| Through the real bridge | scenario, test build | a refused `write_layout` from the page leaves `preferences.json` byte-identical between two in-run checkpoints taken immediately before and after it — before D1's geometry save on close, which legitimately changes the file; a layout written from the page is in `preferences.json` after the application exits and is restored by a relaunch with the same data folder; a pre-seeded valid layout is restored on launch; a pre-seeded invalid one yields the defaults with D1's values intact |
| Canary | canary flows | `read_layout` and `write_layout` — both handlers wrap every result, refusals included, in the test build's `recorded(...)` — appear in the recorded commands; the canary credential appears in neither their arguments, their results, nor the preferences file |
