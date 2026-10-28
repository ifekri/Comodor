# Feature Specification: Workspace Explorer and Read-Only Viewer (D3a)

**Feature Branch**: `005-workspace-explorer`

**Created**: 2026-10-28

**Status**: D3a implemented in this branch; D3b (editing and saving) specified, not started

**Input**: the owner's D3 decisions (2026-10-19 to 2026-10-24), recorded in
the D3 decision draft (revisions 1–5), and the owner's instruction of
2026-10-28: carry D3 forward on the current Tauri + Python Core architecture,
settle the editor question with a repeatable spike without weakening the CSP
or `freezePrototype`, then implement D3a — browsing the workspace tree and
showing files read-only through the Core.

## Context

D3 is "Monaco and the workspace" in the roadmap (`docs/desktop-architecture.md`).
It is delivered as one specification and two pull requests:

- **D3a (this branch)**: the EXPLORER tree, paged listing, and a read-only
  viewer, every byte coming from the Core.
- **D3b (later)**: editing and saving, the unsaved-changes guard on the native
  stop path, and the save protocol (FR-D3-040…055 and section 5 of the
  decision draft).

## Owner decisions

| # | Decision |
| --- | --- |
| OD-D3-1 | One specification, two pull requests: the explorer and viewing first, then editing and saving. |
| OD-D3-2 | File access goes through the Core, by methods confined to the workspace. Paths outside it, symlinks that escape it, and Comodor's credential store are refused. |
| OD-D3-3 | The person's own edits are allowed in ACT, PLAN and ASK; that never extends to the agent's tools. |
| OD-D3-4 | Ctrl/Cmd+S saves (D3b). |
| OD-D3-5, 11, 14, 17 | The unsaved-changes guard runs in the native side before any stop begins, asks the page afresh (generation, request id, edit version), and treats no answer or a stale answer as Cancel; Discard only by the person's choice; a deadline measures only silence (D3b). |
| OD-D3-6 | CSP: test, then decide; `'unsafe-inline'` is not pre-approved. |
| OD-D3-7 | A simple explorer and syntax colouring first; the editor's own base needs are kept. |
| OD-D3-8 | Files suspected of holding secrets are never opened in the WebView. |
| OD-D3-9, 12 | Non-UTF-8 files are read-only; no encoding conversion in D3; BOM and line endings are kept exactly (D3b). |
| OD-D3-10 | The first increment shows files read-only, after a real CSP and worker spike. |
| OD-D3-13 | Comodor's credential paths, the project's `.comodor/`, and sensitive names are refused by explicit rules; a content scan is only an aid, never called a guarantee. |
| OD-D3-15 | A workspace that is Comodor's own data folder is handled safely and understandably, not by excluding a few names. |
| OD-D3-16 | Large folders are paged with a continuation cursor. |
| 2026-10-28 | Stay on Tauri + Python Core (not a Code - OSS fork); do not weaken the CSP or `freezePrototype` for the product. |

## The editor decision: CodeMirror 6

**Decision**: the read-only viewer is CodeMirror 6, mounted inside a shadow
root. Monaco is not used.

**Why**: measured in the test build's real WebView on Windows, Linux and
macOS, with the window's CSP (`style-src 'self'`, no `'unsafe-inline'`) and
`freezePrototype` unchanged. Branch `spike/d3-editor-csp` (throwaway, never
merged, no pull request); runs 40688554176 (`f1a13b3`), 40689586236
(`cef1e5d`) and 40692073881 (`3bbb631`); earlier Monaco spike runs
40104167702…40107595583 (`spike/d3-monaco-csp-dialog`).

| Criterion | CodeMirror 6 (shadow root) | Monaco 0.57.0 |
| --- | --- | --- |
| Loads under `freezePrototype` | verified, unmodified, 3/3 | failed unmodified; loads only with a build transform rewriting 5 sites (4 `toString` namespace assignments, Monarch's keyword table) — one of them data-driven |
| Prototype-name file content (`constructor`, `toString`, `__proto__` … in 6 languages, typed, searched) | verified, no error, 3/3 | verified with the transform, no error, 3/3 |
| Colouring under the CSP | verified: keyword `#5fd4e8` as themed, 3/3; styles through a constructable stylesheet (99 rules) | failed: no colours (`<style>` blocked); colours return only when its rules are re-delivered through the CSSOM |
| Selection drawn | verified, 3/3 | **failed**, 3/3: `.selected-text` is 0×0 — its geometry is an inline `style` attribute the CSP blocks; no static stylesheet can supply per-element geometry (also line numbers, decorations, indent guides) |
| CSP violations | 0 while loading, colouring, selecting, searching, typing into an editable instance; 14 `style-src-attr` when a key is typed into the read-only viewer (the browser's own contenteditable insertion), 0 with no editor | 246–291 per session |
| Worker | none needed | verified (base editor worker, from `'self'`) |
| OS-level typing (editable) | verified, 3/3 | verified (spike 1) |
| Read-only: a typed key changes nothing | verified, 3/3 | not measured |
| 2,000,000-byte file | verified: first frames 47–66 ms, 46 lines rendered of 26,667 | verified: 60–426 ms (spike 1) |
| Line endings, BOM in the model | CRLF, CR and mixed become LF in the document; a BOM stays as a character | CR and mixed become CRLF; the BOM is removed |
| axe (WCAG 2.1 A/AA) | verified, 0 violations, 3/3 | verified, 0, 3/3 |
| Credential canary | verified, no leak, 3/3 | verified, no leak, 3/3 |
| Mounted in the document instead of a shadow root | 1 `style-src-elem` violation and no colours: the shadow root is required | — |

Consequences carried into D3a and D3b:

- The viewer cancels `beforeinput` so a key typed into it inserts nothing and
  trips no CSP check; the `explorer` e2e scenario requires zero violations.
- CodeMirror normalises line endings in its document, so the Core reports the
  file's own line ending and BOM (`eol`, `bom`) and D3b re-applies them on
  save; CRLF/CR/mixed and BOM files stay exactly as on disk (D3b, FR-D3-031).
- Syntax colours are design-token roles (`text.keyword` …, window-only), every
  one reaching WCAG AA on the code ground and on a selection.

## D3a scope

### Core and protocol (additive, protocol v2)

- **FR-001** `workspace.list` returns one page (at most 500) of one folder of
  the workspace: folders first, then names case-insensitively, ties by exact
  name; `cursor` continues with the entries after the last one shown, so a
  page never repeats an entry and never skips one that existed throughout.
- **FR-002** `workspace.stat` reports a path's kind, size and modification
  time; `workspace.read` returns a file's text with how it was decoded
  (`encoding`, `bom`, `eol`, `replaced`, `lines`, `hash`), or `unavailable`
  (`binary`, `too_large`) with no text. Open limit: 2,000,000 bytes, checked
  before the file is read.
- **FR-003** The Core advertises `workspace_files`; a Core without it leaves
  the explorer saying so.
- **FR-004** Refusals are `not_allowed` (policy) or `invalid_params` (the
  request), each with a machine-readable `data.reason`: `bad_path`,
  `outside_workspace`, `comodor_data`, `workspace_is_comodor_data`,
  `sensitive_name`, `secret_content`, `permission_denied`, `not_found`,
  `not_a_directory`, `not_a_file`, `bad_cursor`.
- **FR-005** The methods are protocol methods, not agent tools: the agent
  cannot call them and they change no mode, grant or approval.

### What is refused (checked on the resolved path, before any byte is read)

- **FR-010** Paths are workspace-relative; `.`/`..` segments, absolute and
  drive paths are refused; a path, symlink or junction resolving outside the
  workspace is refused, and such a link is listed but never followed.
- **FR-011** Comodor's data, deny-by-default: the active data folder
  (`COMODOR_HOME` or the platform default, per profile) and the folder that
  holds every profile are hidden and refused wherever they lie; the project's
  `.comodor/` is refused except `skills/`. A workspace that is, or lies inside,
  that data folder is refused whole (`workspace_is_comodor_data`) with an
  explanation and "Open folder…"; files Comodor adds there later are refused
  the same way, since nothing is decided by name.
- **FR-012** Sensitive names (`.env*`, keys, `.ssh/`, credential files …) are
  listed locked with the reason and never read.
- **FR-013** A file whose decoded text holds a known credential shape is
  refused (`secret_content`). This reduces, and does not guarantee against,
  a secret reaching the window.
- **FR-014** `.gitignore` and the Core's built-in ignore list hide entries.

### Window

- **FR-020** EXPLORER shows the workspace as a WAI-ARIA tree (one tab stop;
  arrows, Home, End, Enter), folders loaded only when opened, "Show more" for
  the next page, refused entries locked with their reason, names as inert text
  (RTL-aware), Refresh and Collapse all.
- **FR-021** Opening a file adds a tab after the thread (one tab per file);
  closing the shown tab shows its neighbour or the thread; tabs keep paths
  only, for the launch, in the window's session storage; a workspace change
  closes them. "Show the conversation" returns to the thread.
- **FR-022** The viewer is read-only CodeMirror 6 in a shadow root, coloured
  from design tokens; the breadcrumb states the path, language, line count,
  encoding (with BOM), line ending and "Read-only", and "Path" copies the
  workspace-relative path. A refused, binary or oversized file says why and
  shows no text.

### Deliberate deviations from the decision draft

- **COMODOR_HOME above the workspace.** The draft proposed browsing an
  ordinary folder inside the data folder, using a registry of every entry
  Comodor creates there. That registry needs dynamic names (sessions,
  channels) and an enforcement test of its own; D3a refuses any workspace
  inside the data folder instead (safer, simpler). The allowance can come
  later with the registry.
- **"Ask about file" and a chat code block's "Open"** are not in D3a: the
  conversation has no code blocks yet, and pre-filling the composer belongs
  with D5's context work. The viewer has "Path" only.
- **The 30 s guard deadline, paging cursor format and the unsaved-changes
  guard** are D3b.

## Success criteria and evidence

- **SC-001** `tests/test_workspace_files.py`: every refusal on its own, paging
  (1,201 entries in 3 pages, each once; entries added between pages never
  twice), decoding (UTF-8, BOM, cp1252, Persian/emoji/combining, LF/CRLF/CR/
  mixed), binary, the limit (a file over it is never read), the protocol seam,
  mode isolation. Mutation-checked: removing confinement, dot-segment
  refusal, the data-folder rule, the whole-workspace rule, the `.comodor/`
  rule, sensitive names, the content scan, cursor continuation, the binary
  sniff or the pre-read size check each fails the suite.
- **SC-002** `apps/desktop/test/explorer.test.tsx`: the tree, keyboard,
  paging, refusals, tabs and what reaches the Core, over an in-memory Core.
- **SC-003** e2e `explorer` (real WebView, real Core, Windows, Linux, macOS in
  CI): root order and a locked `.env`; 600 entries in two pages; a TypeScript
  file coloured as themed in a shadow root; a key typed into the viewer
  changes nothing; BOM and CRLF reported; binary and oversized unavailable; a
  token-bearing file refused; `.env` opens nothing; no workspace secret in the
  page; axe 0; **zero CSP violations**; credential canary clean.
- **SC-004** D1/D2 behaviour unchanged except one named test: the D2
  "explorer says browsing arrives later" test now checks the "this Core does
  not offer the workspace's files" state. The native operation set is still
  eleven; the CSP and `freezePrototype` are unchanged.

## Surface Impact

| Surface | Status | Evidence / Notes |
| --- | --- | --- |
| TUI | UNCHANGED BUT VERIFIED | additive methods and capability; the TUI does not call them; the committed TUI bundle rebuilds identically |
| Web UI | UNCHANGED BUT VERIFIED | the Web server does not expose the methods; full pytest suite passes |
| CLI / Headless | UNCHANGED BUT VERIFIED | no CLI change |
| API / Protocols | REQUIRED | `workspace.list` / `stat` / `read`, capability `workspace_files`, `data.reason`; schema → codegen |
| Desktop | REQUIRED | EXPLORER tree, file tabs, read-only CodeMirror viewer |
| Channels / Integrations | NOT APPLICABLE | none |
| Docker / Packaged Runtime | UNCHANGED BUT VERIFIED | page bundle grows by CodeMirror (languages load on demand); packaging is D6 |
| Persistence / Shared State | REQUIRED | open tab paths in the window's session storage (paths only) |
| Security / Authorization | REQUIRED | Core-side confinement, data-folder and secret refusals; CSP and `freezePrototype` unchanged; canary extended to a workspace `.env` |
| Tests / Documentation | REQUIRED | new Core, window and e2e tests; this specification; `docs/desktop-architecture.md` |
