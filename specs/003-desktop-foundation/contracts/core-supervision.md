# Contract: Starting, Supervising and Stopping the Core

The native side's obligations toward the Core process. The Core itself is
used as it is today: `comodor core --stdio`
(`src/comodor/transport/__init__.py::serve_stdio`). Nothing here changes it.

---

## 1. Locating the Core (FR-002)

In order, stopping at the first that exists:

1. `COMODOR_BIN` (executable), with `COMODOR_ARGS` split on whitespace as
   leading arguments. This is the terminal interface's existing convention.
2. `comodor` on `PATH`.

When none is found, the failure is `not_found`, and its message lists every
location tried plus how to install Comodor or set `COMODOR_BIN`.

## 2a. Choosing the workspace at launch (FR-021, OD-3)

Per [data-model.md](../data-model.md) §8:
- a valid explicit command-line path is used without the chooser;
- otherwise the person chooses in the system folder chooser, opened at the
  last selected folder;
- no Core starts until a workspace is chosen;
- within the launch, the workspace is kept across page reloads and every kind
  of Core restart, and is never asked for again.

## 2. Starting it (FR-001, FR-003, FR-022)

- Before starting, the workspace must exist and be a readable directory;
  otherwise the failure is `workspace_unavailable`.
- Command: `<executable> [<COMODOR_ARGS>] core --stdio`.
- No shell. No console window (Windows). Working directory: the workspace.
- Environment: inherited unchanged. Arguments: exactly the list above, with no
  credential.
- All three standard streams are piped. stdin and stdout are the protocol.
  stderr goes to the `DiagnosticTail` only.
- Windows: the Core is placed in a job object that kills its members when the
  job handle closes. Linux: the Core gets a parent-death signal, and is started
  from the supervisor's long-lived thread. Linux and macOS: the Core leads its
  own process group.

## 3. Handshake (FR-009)

The native side sends `client.hello` itself, with protocol version 2 and the
capabilities the desktop window renders: `questions` and `permissions`. These
are the same two the terminal interface declares (`apps/tui/src/main.tsx`),
and both are members of `CLIENT_CAPABILITIES` in the generated protocol.
`clarification_required` is not declared, because D1 renders no
clarification-required outcome of its own. The native side caches the answer.

| Observation | Result |
| --- | --- |
| a response with `protocol_version` 2 and a whole `HelloResult` (`core` with string `name` and `version`, `capabilities` a list of strings) | `ready` |
| a response with `protocol_version` 2 that is not a whole `HelloResult` | `failed: protocol_fault` |
| a response with another version | `failed: protocol_mismatch`, naming both versions |
| an `unsupported_version` error | `failed: protocol_mismatch`, naming the Core's `supported` list |
| the process exits first | `failed: exited_before_ready`, with the diagnostic tail |
| a line on stdout that is not a protocol envelope | `failed: protocol_fault` |

There is no handshake timeout. The Core either answers, exits, or writes a
bad line, and each is observed. A hung Core stays in `handshaking` with a
visible "Starting…" state. The person can close the window (the stop sequence
of §5 applies) or choose another workspace; no separate stop action exists.

## 4. Supervision (FR-004–FR-007)

- A Core exit in `ready` means `crashed`. A bad stdout line in `ready` means
  `protocol_fault`, followed by the forced-stop sequence. A bad line is one
  the page's client would reject: not UTF-8, not a v2 envelope, missing a field the
  schema's `x-envelope` requires, or with a field of the wrong type (`id`,
  `event` a non-empty string; `params`, `result` an object; `seq` a number;
  an error's `code` a string and its `id` a non-empty string or null).
- A Core stopped for a fault is never running alongside another: whatever
  follows (the restart, "Try again", another workspace) starts its Core only
  after the faulted one has exited.
- After the machine sleeps (spec: Machine sleep and wake): a sleep is read
  from two platform clocks, one that runs while the machine sleeps and one
  that does not (Linux `CLOCK_BOOTTIME` and `CLOCK_MONOTONIC`; macOS
  `CLOCK_MONOTONIC_RAW` and `CLOCK_UPTIME_RAW`; Windows `QueryInterruptTime`
  and `QueryUnbiasedInterruptTime`). It is looked for every second and
  before every line the window sends. A sleep of a second or more moves a
  `ready` Core to `checking`: the native side sends it `session.list` with
  an id of its own, and refuses the window's lines until any answer to it
  arrives (`ready` again). Each check raises `check_epoch` in the status,
  and it stays raised: the window reads its session afresh for every epoch
  newer than the last it read, even when `checking` and `ready` reached it
  before it rendered again, and
  offers neither Send nor Cancel from the check until that read has
  settled; a session the window had not finished opening when the check
  began is opened again from the start). An
  exit or a bad line meanwhile is handled as from `ready`; no answer within
  10 seconds counts as a crash (`crashed`, "did not answer after the
  computer woke from sleep"), and the Core is ended and restarted under
  OD-1.
- Completed turns are observed read-only from relayed events, under the
  conservative rule of [data-model.md](../data-model.md) §3. Only a completed
  turn resets the crash count.
- Restart per `RestartPolicy` (OD-1): after crashes 1 and 2 of a ready Core
  without a completed turn, restart in the same workspace with a fresh
  handshake, and tell the page through its status channel. After crash 3, do
  not restart; wait in `failed` for "Try again". Only a completed turn resets
  the count, and nothing interrupted is replayed.
- stderr is always read, whatever the state, into the bounded tail.

## 5. Stopping (FR-017, FR-018)

The orderly sequence, for every `ShutdownRequest` reason:

1. The native side does not depend on the page for this step: the page may
   already be gone.
2. Send `shutdown`. The Core answers, closes its channel and runs its own
   `close()`: it interrupts a running turn, refuses pending prompts, joins
   workers for up to 5.0 s, and flushes and releases the assembly. That
   interrupt is the cancellation through the Core that FR-017 requires.
3. Close the Core's stdin.
4. Keep the window open showing "Closing…" with "Quit now" (a close request is
   held until this step ends), and wait for the **process exit**. At
   `deadline` — **10 seconds** after the stop request (OD-2) — or on "Quit
   now", force the stop: terminate the job (Windows) or signal the process
   group (Linux, macOS), then wait for the exit. Record the outcome `forced`,
   log "stopped before it finished", and show it in the window if the window
   stays open. Never report a forced stop as saved.
5. `stopped`. For `quit` and `window_closed` the application then exits; for
   `workspace_change` and `check_again` a new Core starts.

One stop runs at a time. A close or quit that arrives while a
`workspace_change` or `check_again` stop is in progress replaces its reason,
so the application exits when the Core has stopped and no new Core starts;
any other second stop is refused. A stop requested while a faulted Core is
still ending waits for that Core's exit, and the deadline and "Quit now"
force it as they would any other.

Abrupt application death (FR-018): Windows, the job closes; Linux and
macOS, a watchdog started with each Core (the application's own executable
in a process group of its own) waits on the application's or the Core's
exit — `kqueue` on macOS, `pidfd` on Linux — and then, whichever went
first, signals the Core's whole group (the parent-death signal can end the
Core a moment before the application's exit is seen); Linux
also arms the parent-death signal; all platforms, stdin reaches EOF and the
Core's `serve()` loop ends into `close()`. (The watchdog was added for a
review finding on PR #62: the parent-death signal reaches the Core alone,
and macOS has none. On Linux and macOS a Core never runs without its
watchdog: the Core is held between fork and exec until its watchdog reports
that it is watching, and if the watchdog cannot start — or exits before it
reports — the Core never runs and the start fails.)

## 6. Single instance (FR-019)

A second launch forwards its arguments to the running instance, which
focuses its window. It is not a fresh launch: the current workspace stays. If
the second launch carried an explicit workspace path different from the
current one, the running instance asks the person in a native confirmation
dialog, shown by the native side and never by the window, before changing
workspace. It switches only on confirmation, through the stop sequence of §5;
on a decline or no answer it keeps the current workspace. No second Core is
started.
