# Contract: The Native Bridge

Everything the window's content may ask of the native side. **This list is
exhaustive** (FR-030). Any other command, and every plugin command, is refused
by the application's capability configuration. A test enumerates the
registered commands and fails on any command not listed here (SC-011).

The window is granted **no plugin permissions**. The folder chooser,
single-instance handling and link opening run on the native side.

---

## Commands

| Command | Arguments | Returns | Refuses when |
| --- | --- | --- | --- |
| `connect` | an IPC channel for inbound messages | `{generation}` — this page's generation; the channel then receives status and protocol lines | — (a new page gets a new generation; the previous generation stops receiving) |
| `send_line` | `{generation, line}` — one protocol v2 request envelope as text | `{}` | the generation is not current; the line is not a JSON object with `type: "request"`; the method is `shutdown` or not a protocol v2 method; the Core is not `ready` (after a wake not yet noticed, the wake is noticed first, and the Core is then `checking`) |
| `status` | — | the current `CoreProcess` summary: `state`, `workspace` (or none chosen yet; for display, so a path that is not UTF-8 loses bytes), `workspace_id` (which workspace, losslessly: it changes exactly when the folder does and is never reused within a launch; the page tells workspaces apart by it), `failure` (class and message), `restart_count` of the three allowed (OD-1), `check_epoch` (how many checks of the Core have begun after the machine woke; it stays once a check is over, so a page that never saw `checking` still knows to read its session again), `closing` with the seconds remaining (OD-2), `stop_outcome` (`orderly` or `forced`), handshake Core name/version | — |
| `diagnostics` | — | the `DiagnosticTail` as text | — |
| `choose_workspace` | — | opens the chooser at the last selected folder; returns the chosen absolute path, or `null` if the person dismissed it. On a new choice, a running Core is stopped (10 s grace) and one is started in the new workspace (FR-021); the same command is how the person chooses after a dismissed launch chooser | a workspace change is already in progress |
| `retry` | — | `{}`; the person's "Try again": starts a Core from `failed` in the same workspace. It does not reset the restart count (OD-1) | the Core is not `failed` |
| `check_again` | — | `{}`; orderly restart of the Core, used after `comodor setup` (R11) | the Core is `starting`, `handshaking` or `stopping` |
| `quit_now` | — | `{}`; the person's "Quit now": forced stop during `stopping`, before the 10-second deadline (OD-2) | not `stopping` |
| `open_external` | `{url}` | `{}`, once the person has said yes to exactly this URL in a native dialog ("Open link?", naming the URL; one at a time) | the scheme is not `http` or `https`; the URL was not in a line relayed to the page of the current generation (refused before anyone is asked); another link is waiting for an answer; the person did not say yes. The page's call is never taken as proof of a click, and a URL's presence in a relayed line, in any field, authorizes nothing: each call is put to the person, and a yes is never remembered |

What is deliberately absent: reading files, running processes, reading
configuration, the environment or credentials, clipboard access, window
creation, and anything from a plugin.

## Inbound channel messages

One IPC channel per page, carrying:

- `{"kind": "line", "line": "<protocol envelope>"}` — responses already mapped
  back to the page's ids, and events. The page's bridge `Transport` hands the
  line to `CoreClient` unchanged.
- `{"kind": "status", ...}` — a `CoreProcess` summary on every state change.
- `{"kind": "closed", "reason": ...}` — the Core connection ended. The page's
  `Transport` ends its line stream, which `CoreClient` reports through
  `onClose`. When status is `ready` again, the page calls `connect` once more
  and builds a new `CoreClient`. Every `connect` is a new generation, so
  nothing from the previous Core or page can reach it.

## The page's `Transport`

The page implements `@comodor/client`'s `Transport` interface over this
bridge:

- `lines()` — the `line` messages, in order;
- `write(line)` — `send_line` with the page's generation; a line the native
  side refuses becomes that request's error answer on this page only
  (`not_allowed`, with `data.refused_by: "native"`, since the Core never saw
  it — the window keeps a mode change refused this way, for instance by the
  line that was the first to notice a wake, and sends it once nothing holds
  it, at most a few times in a row);
- `close()` — detaches the page only. It never stops the Core: Core lifetime
  is the native side's (FR-001), and `CoreClient.close()`'s `shutdown` request
  is refused by the relay.

`CoreClient` runs **unchanged** over it (FR-025).

## Relay guarantees

1. Order is preserved in both directions. The Core's rule that a request is
   answered before the events it caused therefore still holds at the page.
2. Nothing in an envelope is ever changed except its `id`, which gains or
   loses the generation prefix. The relay **reads**, without changing, only
   what the restart counter needs (FR-005, [data-model.md](../data-model.md)
   §3):
   - the `session.send` result's `turn_id`;
   - `message.completed` → `turn_id` and `status`;
   - `session.updated` → `session.busy`;
   - `notification.created` → `level`;
   - the method name `session.cancel` of a request it forwards.

   No other field is read.
3. `client.hello` is answered locally from the cached handshake, with the
   page's request id.
4. An answer for a non-current generation is not delivered (what it reports, such as a started turn, still counts for the restart policy). An unknown id is dropped.
5. No message the Core did not send reaches the page as a protocol line.

## Capability configuration (release build)

- `tauri.conf.json` sets `app.security.capabilities` to `["main"]`, so no
  other capability is used.
- The `main` capability (window `main`) grants exactly the nine generated
  `allow-<command>` permissions, plus only the `core:` permissions the IPC
  channel requires, as recorded for the pinned version. Measured on
  tauri 2.12.1 / tauri-build 2.7.1 (T003, `apps/desktop/README.md`): the
  identifiers turn underscores into hyphens (`allow-send-line`), and the
  `core:` minimum is empty — the IPC channel needs no `core:` permission.
- Every plugin permission: none.
- Content Security Policy: application scripts and styles only; no inline
  script, `eval` or remote origin; IPC as the only connection.
- Navigation away from the application's own origin: refused. New windows:
  refused. Developer tools: off.

## One source for the command list

The nine names live in one constant, `COMMANDS`, in
`src-tauri/src/command_names.rs`. It feeds:

- **the build's app manifest**: `build.rs` calls
  `tauri_build::AppManifest::new().commands(&names)`, where `names` is
  `COMMANDS`, plus `e2e_report` only when the `e2e` cargo feature is on. The
  build then generates an `allow-<command>`/`deny-<command>` pair per command
  (tauri-build 2.x), and a command is usable only where an enabled capability
  grants its allow permission. Without the app manifest, Tauri 2 allows every
  registered command to every window; that default is not used.
- **the handler registration** in `main.rs`: only names from `COMMANDS`,
  each added by the task that implements it, and all nine by the final test.
  `e2e_report` is added under `#[cfg(feature = "e2e")]` only.

Verification:
- **Early unit test** — the constant names no command outside the table
  above.
- **Final unit test** — once every command exists, the constant equals the
  table.
- **CI, release configuration** (no feature, no config override, no
  bundling) — reads the generated `gen/schemas/acl-manifests.json` (app
  permissions under `__app-acl__`) and `gen/schemas/capabilities.json`, and
  asserts:
  - exactly nine allow/deny pairs and nothing for `e2e_report`;
  - only the `main` capability;
  - `main` grants exactly the nine allow identifiers plus the recorded
    `core:` minimum;
  - no plugin permission.

  Identifiers are read from the generated files, matched by command name.
- **Pinned version** — each of these facts is verified against the pinned
  Tauri version when the crate is created. `gen/` is not committed.

## Test build only

A compile-time feature, `e2e`, adds:
- one command, `e2e_report {result}`;
- a scenario runner page;
- a recorder of every inbound IPC message and every command's arguments and
  return value;
- a report of the Core's pid and of the application's network listeners;
- test doubles for the folder chooser (it records the start directory it was
  given) and for the second-launch confirmation.

The `e2e` build also loads `tauri.e2e.conf.json`, whose inline capability
`e2e-test` grants only `e2e_report`'s allow permission. No capability file for
it exists under `capabilities/`, so the release configuration can never load
one. None of these exists in a release build. CI asserts that the `e2e` build's
command list is the release list plus `e2e_report` and nothing else.
