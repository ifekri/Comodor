# Quickstart: Validating the Desktop Foundation (D1)

How to prove D1 works, end to end, offline. Every command below is
**planned**: the implementation creates it, and `tasks.md` fixes the exact
script names. Nothing here calls a model provider, spends tokens or needs a
credential (FR-034).

## 1. Prerequisites

- Python ≥ 3.11 with the repository installed editable (`pip install -e
  ".[dev]"`); a separate virtual environment per worktree.
- Node ≥ 22.6 and `npm ci` at the repository root.
- Bun (for the terminal interface's suites, which must stay green).
- A Rust toolchain and the platform prerequisites for Tauri 2 (**external**):
  - Windows: the WebView2 runtime;
  - Linux: WebKitGTK 4.1 and its development headers, plus a virtual display
    (`xvfb`) for the in-application scenarios;
  - macOS: Xcode command-line tools.
- An offline Core home: a temporary `COMODOR_HOME` holding a `config.json`
  whose only provider is the offline `fake` provider. This is the shape
  `apps/tui/test/bun/orphan.test.ts` writes. For the canary run, its
  `api_key` is a unique string (§5).

## 2. Gates that must stay unchanged (SC-012)

```sh
python -m ruff check src tests tools
python -m pytest -q
python -m pytest -m performance -n 0 -q
python tools/protocol-codegen.py --check
python tools/capability-map.py --check
npm run lint && npm run typecheck && npm test && npm run build
bun test apps/tui/test/bun/renderer.test.tsx
bun test apps/tui/test/bun/orphan.test.ts
bun tools/build-tui-distribution.ts && git status --porcelain   # prints nothing
git diff --check
```

Expected: the same results as on `main`. The desktop adds no Python test and
changes no schema.

## 3. Desktop gates (all three platforms)

| Layer | Planned command | Proves |
| --- | --- | --- |
| Native unit | `cargo test` in `apps/desktop/src-tauri` | the state machine; the restart policy and the conservative completion rule (crashes 1 and 2 restart, 3 stops; only a completed turn resets — a `session.send` result with its `turn_id`, then `message.completed` all `completed`, then `busy: false`, with no `warning` or `error` notification and no relayed `session.cancel`; none of these reset: a cancelled or failed message, cancel or failure between messages, a clarification stop, any warning or error notification, a turn with no `message.completed`, a turn the Core started itself, a crash, "Try again" or time; a failure before ready is never restarted); the shutdown sequence with an injected clock (forced stop at exactly 10 s and on "Quit now", no "saved" claim on any forced path); launch workspace resolution (a valid explicit path, an invalid one, no path, a dismissed chooser); relay id mapping and stale-generation drop; the method allowlist; discovery order; the exact preferences schema |
| Native integration | the same, integration target | a real Core via `COMODOR_BIN`: handshake, `not_found`, `spawn_failed`, `exited_before_ready`, `protocol_mismatch` and `protocol_fault`; crash and restart, with the sequenced double for crash → completed turn → crash; uncertain turns that do not reset; an orderly stop with no kill; a non-cooperating double force-stopped at the grace bound; a question and a permission from the scripted Core relayed intact. Every mid-turn case uses the hold-mid-turn scenario |
| Window logic | the desktop workspace's `test` script | the view against `CoreClient` over an in-memory transport: streaming order, forms with the write-your-own row, the permission choice sent only on click, the mode label only after `mode.changed`, the unconfigured state, the interrupted-turn notice, and the adversarial strings of SC-010 |
| In-application scenarios | the desktop workspace's `e2e` script (test build) | the real WebView, bridge and Core: ready window, conversation, reload during streaming (workspace kept, no chooser), crash during and between turns (workspace kept), the third crash waiting for "Try again", `check_again`, "Closing…" and "Quit now", canary search |
| Process lifetime | the desktop workspace's `lifetime` script | normal close, quit during a held turn (`hold-mid-turn`), "Quit now", abrupt kill of the application: no Core process remains; a second launch leaves one window and one Core; a second launch naming a different workspace switches only after the confirmation, and keeps the workspace when declined |
| Release command list | native unit, plus `npm run -w apps/desktop release-manifest` in CI | the `COMMANDS` constant names no command outside [native-bridge.md](./contracts/native-bridge.md) (early), then exactly its nine (final); the release build's generated `gen/schemas/acl-manifests.json` (`__app-acl__`) and `gen/schemas/capabilities.json` show exactly nine allow/deny pairs, only the `main` capability, exactly the nine allow identifiers plus the recorded `core:` minimum, and no plugin permission; the `e2e` build differs only by `e2e_report` and its `e2e-test` capability |

## 4. Walkthrough (manual, optional)

1. Point `COMODOR_HOME` at the offline home and launch a development build
   with no path. The folder chooser opens (at the last selected folder, from
   the second launch onward). Choose a folder. The window shows the workspace,
   `fake`, `fake-1`, "configured", and "ready" (US1). Launching with a valid
   folder path as the argument skips the chooser.
2. Send "hello". The echoed reply streams, and the turn ends (US2).
3. Kill the Core process with the operating system's task manager (it runs as
   `comodor core --stdio`). The window reports it, restarts, and shows the
   earlier turn again (US3).
4. Reload the window's content. The same conversation appears, with no
   duplicates (US3).
5. Close the window. "Closing…" appears with "Quit now", and the application
   exits once the Core has. No Core process remains (US4).
6. Remove the provider from the offline home and relaunch. The window shows
   "not configured" and the `comodor setup` direction. Restore it, then click
   "Check again": the window shows "configured" with no application restart
   (US6).

## 5. The credential canary (SC-009)

The in-application scenario run uses a Core home whose provider `api_key` is
a unique random string. After the run, all of the following must contain
**zero** occurrences:

- every inbound IPC message of every kind (`line`, `status`, `closed`), and
  every bridge command's arguments and return value — all recorded by the
  test build;

- the WebView's own storage (read by the scenario runner inside the page):
  local storage, session storage, IndexedDB databases and the document text;
- the application's log file and the preferences file;
- the diagnostic tail as served to the page.

## 6. Adversarial display (SC-010)

The window logic suite and the scripted Core both deliver messages, tool
output, file names, model names and error messages that contain:

- `<script>`, `<img onerror>` and `javascript:` links;
- `\x1b[2J`, `\x1b[H` and an OSC window-title sequence;
- the literal text `[Connected]` and `[Ready]`.

Expected: all of it appears as text, with control characters shown as
visible symbols. No script runs, the page does not navigate, and the
connection and status indicators do not change.

## 7. Recording evidence

Record each run against the exact commit: platform, command, counts and
result. Runs during development use `workflow_dispatch` on the pushed branch.
Evidence for the **exact final SHA** goes in the PR description and the owner
report, never in a repository commit made after the final validation round.

The real folder chooser (SC-017) is checked by hand on each platform. A
screenshot or screen recording shows the dialog opening at the folder the
application passed, and is attached to the PR description.

A layer or platform without recorded evidence is reported as **NOT
VERIFIED**, and D1 is then **incomplete**. NOT VERIFIED is never a pass and is
never waived silently (FR-033, Constitution X, XII).
