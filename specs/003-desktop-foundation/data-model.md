# Data Model: Desktop Foundation (D1)

Entities the desktop application owns. Session content — messages, tools,
questions, permissions, mode, usage, tasks, delegates — is **not** modelled
here: it is Core state, projected by the unchanged `@comodor/session`
reducer (FR-014, FR-023).

---

## 1. CoreProcess (native side)

One per window. Owned only by the supervisor.

| Field | Meaning |
| --- | --- |
| `state` | one of the states below |
| `workspace` | absolute path the Core was started in |
| `pid` | the Core's process id while it exists |
| `handshake` | the cached `client.hello` result: protocol version, Core name and version, capabilities |
| `failure` | the failure class and message, when `state` is `failed` |
| `diagnostics` | a `DiagnosticTail` (§4) |
| `restarts` | a `RestartPolicy` counter (§3) |

### States and transitions

```text
absent ──start──▶ starting ──spawned──▶ handshaking ──hello ok──▶ ready
   ▲                 │                      │                      │
   │           spawn error            exit / bad line /       exit or bad line
   │          (not_found,           version mismatch          (crashed,
   │           spawn_failed,        (exited_before_ready,      protocol_fault)
   │           workspace_           protocol_fault,                │
   │           unavailable)         protocol_mismatch)             ▼
   │                 ▼                      ▼               restart allowed?
   │               failed ◀─────────────── failed            │yes        │no
   │                 │                                        ▼           ▼
   │           "Try again" (person)                      restarting     failed
   │                 └──────────────▶ starting                │
   │                                                          └──▶ starting
   │
ready / failed ──quit, close or workspace change──▶ stopping ──exit──▶ stopped
                                                        │
                                               grace expired or
                                               "Quit now" (person)
                                                        ▼
                                              forced stop ──exit──▶ stopped
```

Rules:

- Exactly one transition per observed event: process spawned or failed to
  spawn, a line read, the handshake answer, the process exited, a person's
  action, or one of the two explicit bounds (§3, §6).
- `ready` is reached only by a handshake whose `protocol_version` equals the
  desktop's (FR-009); otherwise `failed` with `protocol_mismatch`, naming both
  versions.
- A non-protocol line on the Core's stdout moves `handshaking` or `ready` to
  failure with `protocol_fault` (FR-007).
- Automatic restart applies only from `ready` (R4). Every failure before
  `ready` waits for "Try again".
- `stopping` begins with the orderly sequence in
  [core-supervision.md](./contracts/core-supervision.md) §5. `stopped` is
  reached only on the observed process exit.

---

## 2. BridgeConnection (native side)

The relay between one page and the Core ([native-bridge.md](./contracts/native-bridge.md)).

| Field | Meaning |
| --- | --- |
| `generation` | a positive integer, incremented on every `connect` (a page load, or a reconnect after a Core restart); the current one is the only live one |
| `in_flight` | a map from native request id `"g<generation>:<page id>"` to the page id, for the current generation |

Rules:

- A response or error whose id carries an older generation is dropped.
- An id the map does not hold (a late answer to a stale generation) is
  dropped.
- `client.hello` from a page is answered locally from `CoreProcess.handshake`
  and never reaches the Core.
- `shutdown` from a page is refused. Any method outside the protocol v2
  method list is refused.
- Nothing in an envelope is changed except `id`. Only the fields listed in
  §3 are read, without changing them, to observe completed turns.
- On a Core restart, the page receives `closed`: its `CoreClient` rejects
  whatever it had pending, as it does for any closed connection, and
  `in_flight` is emptied. The page reconnects with `connect` — a new
  generation — once the status is `ready`.

---

## 3. RestartPolicy (native side)

| Field | Meaning |
| --- | --- |
| `limit` | 3 — the crash at which automatic restarts stop (OD-1) |
| `count` | consecutive crashes of a ready Core since the last completed turn |

Rules (OD-1):

- A crash of a Core that had reached `ready` increments `count`. At
  `count < limit` the Core is restarted automatically. At `count == limit` it
  is not: the state is `failed` and the application waits for "Try again".
- `count` resets to 0 only when a turn is **completed** under the conservative
  rule below. "Try again", time, and every uncertain outcome leave it
  unchanged.
- A failure before `ready` never counts and is never restarted automatically.
- No restart replays interrupted work.

**TurnObservation** (one per `turn_id` the relay saw start):

| Field | Set when |
| --- | --- |
| `turn_id` | the `session.send` result the relay forwarded |
| `completed_messages` | a `message.completed` for this `turn_id` with `status: completed` arrives |
| `uncertain` | any of the below arrives before the turn's `busy: false` |

`uncertain` is set by:
- a `message.completed` for this `turn_id` with another status;
- a `notification.created` for the session at level `warning` or `error`;
- a relayed `session.cancel` for the session.

The Core sends a warning for a cancellation (`_relay` on `CANCELLED`), for a
turn that stopped for a decision (`_relay_clarification`), and for any other
stop. It sends an error for a provider or worker failure.

The turn is **completed** when `session.updated` with `busy: false` arrives
and `completed_messages ≥ 1` and `uncertain` is false. A crash, or a turn the
relay did not see start, never completes.

Tests exercise:
- crash 2 (restarted) and crash 3 (stopped);
- the reset;
- each uncertain case: cancel between messages, failure between messages, a
  clarification stop, a warning or error notification, and a Core-started
  turn.

---

## 4. DiagnosticTail (native side)

A bounded ring of the Core's stderr lines. It holds at most 200 lines and at
most 64 KiB, dropping the oldest first. It is read continuously on its own
thread so the Core never blocks on stderr (FR-006). It is exposed to the page
only as plain text, when a failure is shown. It is never parsed as protocol.

*The bounds are a technical choice with no product consequence beyond
display. They are recorded here and asserted by a test that writes past both.*

---

## 5. DesktopPreferences (native side, persisted)

A JSON file in the application's own per-user configuration directory.

| Field | Type | Meaning |
| --- | --- | --- |
| `version` | integer | schema version, starting at 1 |
| `window` | `{width, height, x, y, maximized}` | window geometry |
| `last_selected_folder` | string or absent | the folder the person last chose; it only decides where the chooser opens (OD-3) and never starts a Core by itself |

Validation:

- An unknown field is ignored.
- A malformed file is treated as absent and replaced on the next save,
  written to a temporary file and renamed.
- The file never holds a credential, a token, the Core's environment or any
  session content (FR-032). A test asserts the serialised type has exactly
  these fields.

---

## 6. ShutdownRequest (native side, transient)

| Field | Meaning |
| --- | --- |
| `reason` | `window_closed`, `quit`, `workspace_change`, `check_again`, `os_session_end` |
| `grace` | 10 seconds after the stop request (OD-2) |
| `deadline` | when the forced stop happens, from an injected clock |
| `outcome` | `orderly` (the Core exited by itself) or `forced` (deadline or "Quit now") |

After a `forced` outcome the application records "stopped before it
finished" in its log, and in the window when the window stays open
(`workspace_change`, `check_again`). No forced path produces a "saved"
message.

---

## 7. WindowView (page, not persisted)

What the page adds to the `@comodor/session` projection. It holds only
presentation and connection facts. `stored_id`, `live_id`, `unsent_turn` and
`workspace` are kept in the window's session storage, so a reload of the
window keeps them and a new launch does not (R13); a change of workspace
clears the first three:

| Field | Meaning |
| --- | --- |
| `core_status` | the last `CoreProcess.state` and `failure` the native side reported |
| `stored_id` | the conversation to reopen after a restart (R12) |
| `live_id` | the live session of the Core the page last held, which a reload finds in `session.list` |
| `workspace` | the workspace `stored_id` belongs to |
| `unsent_turn` | the `turn_id` the Core accepted and never completed, shown as interrupted after a crash |
| `composer_text` | the unsent prompt |
| `interaction_cursor` | which option of the pending form is focused; question selection state comes from `@comodor/questions` |

Nothing in `WindowView` decides a mode, a permission or whether a tool may
run (FR-024).

---

## 8. LaunchWorkspace (native side, per launch)

How the workspace is decided at launch (OD-3). It is held in memory for the
whole launch and never re-asked within it.

| Field | Meaning |
| --- | --- |
| `source` | `command_line` or `chooser` |
| `path` | the chosen absolute path |

Resolution on a fresh launch:

1. A command-line path that exists and is a readable directory: use it; no
   chooser.
2. A command-line path that does not: report it, then go to 3.
3. Open the chooser at `last_selected_folder`, or at the system default if
   that folder is gone. On a choice, store `last_selected_folder` and use it.
   On a dismissal, start no Core and offer "Choose workspace…".

A reload of the window's content, an automatic restart, "Try again" and
"Check again" all reuse `path`. Only `choose_workspace` changes it.
