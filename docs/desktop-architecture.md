# The desktop application

D1 — the desktop foundation — is built: `apps/desktop`, a Tauri 2 window
that owns one Comodor Core and holds one conversation with it. It runs from
source on Windows, Linux and macOS; it is not packaged yet. Everything past
the foundation (the workbench, Monaco, the terminal, panels, packaging) is
D2–D6 and does not exist yet.

This records what the desktop is, what the Core had to be true for, and what
remains.

---

## The shape

```text
                 Python Comodor Core   (unchanged by D1)
                          │  protocol v2 over its own stdin/stdout
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
  OpenTUI terminal                 Tauri 2 desktop (apps/desktop)
        │                          native side (Rust): supervisor, relay
     React / TS                    window content: React / TS
        │                                   │
        └─────────────────┬─────────────────┘
                          │
              @comodor/protocol   @comodor/client
              @comodor/commands   @comodor/modes
              @comodor/questions  @comodor/session
              @comodor/design-tokens
```

The window reuses those packages unchanged — `CoreClient` runs over the
bridge exactly as it runs over a pipe in the terminal. D1 changed nothing in
`src/`, `schemas/` or `packages/`: the foundation's test was that adding a
desktop needs no protocol change, and it did not.

---

## Why Python stays the Core

Not sentiment. The agent runtime, tools, skills, memory, MCP, the GitHub
integration and the risk rules are the product; a rewrite would be months of
work whose best possible outcome is the behaviour that already exists.

Rust is the Tauri shell and the native services around the Core — the
process, its lifetime, the window, single-instance behaviour. Not a
reimplementation of anything above.

---

## What the native side does

**Locating and starting the Core.** `COMODOR_BIN` (with `COMODOR_ARGS` split
on whitespace), else `comodor` on `PATH`. Started directly — no shell — as
`<program> [<args>] core --stdio`, in the workspace, with the environment
inherited unchanged and all three streams piped. stderr goes to a bounded
diagnostic tail (200 lines, 64 KiB) shown only as text on a failure.

**The handshake.** The native side sends `client.hello` itself (protocol 2,
capabilities `questions` and `permissions`) and caches the answer; a page's
own hello is answered from that cache. Every failure before `ready` has its
own named view: `not_found`, `spawn_failed`, `workspace_unavailable`,
`exited_before_ready`, `protocol_mismatch`, `protocol_fault`. There is no
handshake timeout: the Core answers, exits, or writes a bad line.

**Supervision** is a pure state machine (`src-tauri/src/supervisor.rs`) fed
one observed input at a time — a spawn result, a line, an exit, a person's
action, a deadline — and answering with effects. One long-lived thread runs
it and owns every Core process, so the Linux parent-death signal follows the
right thread.

**The relay** (`relay.rs`) is the page's only way to the Core:

- every page load or reconnect is a new *generation*; a page id `7` becomes
  `g<generation>:7` on the way in and is restored on the way out, and an
  answer for an older generation or an unknown id is dropped;
- `shutdown` and any method outside protocol v2 are refused, as is any line
  that is not a request;
- envelopes are byte-identical after relaying except their `id`;
- the protocol version and method list come from `schemas/protocol/v2.json`
  at build time.

It reads — never changes — only what the restart count needs: the
`session.send` result's `turn_id`, `message.completed` `turn_id` and
`status`, `session.updated` busy, `notification.created` level, and a
relayed `session.cancel`.

**The bridge commands** are exactly nine, from one constant
(`command_names.rs`) that feeds both the handler list and the build's app
manifest: `connect`, `send_line`, `status`, `diagnostics`,
`choose_workspace`, `retry`, `check_again`, `quit_now`, `open_external`.
The `main` capability grants exactly their allow permissions; no plugin and
no `core:` permission. The folder chooser, the confirmation dialog, single
instance and link opening run on the native side only.

---

## The three owner decisions

**OD-1 — restarts.** A crash of a Core that had reached `ready` restarts it in
the same workspace, with a fresh handshake; the page is told its connection
closed and reconnects. Crashes 1 and 2 restart; the third waits for "Try
again". Only a *completed* turn resets the count — one that ended
(`busy: false`) after a completed message with nothing uncertain: no
cancelled or failed message, no warning or error notification, no relayed
cancel. "Try again" and time never reset it. A protocol fault of a ready
Core counts as a crash. Nothing interrupted is replayed: an accepted turn the
Core never finished is shown as interrupted and not saved.

**OD-2 — stopping.** Closing, quitting, changing workspace and "Check again"
share one sequence: `shutdown`, stdin closed, then the wait for the process
to exit — at most 10 seconds, with "Closing…" and "Quit now" in the window.
Then the Core and everything it started are ended (the job object on Windows,
the process group elsewhere). A forced stop is logged as "stopped before it
finished" and is never reported as saved. Abrupt death of the application is
covered too: the job closes (Windows), the parent-death signal fires (Linux),
and stdin reaches EOF (everywhere).

**OD-3 — the workspace.** A path on the command line is used directly.
Otherwise every fresh launch opens the system folder chooser at the folder
last chosen; no Core starts before a choice, and a dismissal offers "Choose
workspace…". The workspace is kept for the whole launch, through reloads and
every kind of restart. A second launch focuses the window; another folder is
switched to only after a native confirmation, through the stop sequence, and
never as a second Core.

---

## The window

One screen, driven by the unchanged `@comodor/session` reducer: a status
strip (workspace, provider, model, configured), the conversation with tool
activity, forms through `@comodor/questions`, permissions, the mode control
from `@comodor/modes` (its label changes only on `mode.changed`), and a
composer whose Send and Cancel are `@comodor/commands` commands. Colours come
only from `cssVariables()`.

Outside text is inert: messages, tool output, file names, model names and
errors render as text, control characters as visible symbols (`␛`), and only
`http`/`https` links are clickable — opened through `open_external`, which
accepts only a link the current page was shown. The window refuses
navigation away from its own pages and new windows. An unconfigured provider
shows the direction to run `comodor setup` in a terminal, with Send
unavailable, and "Check again" restarts the Core to read it.

---

## Process lifecycle

| | |
|---|---|
| **Terminal alone** | the TUI spawns a private core over stdio, and it dies with the client |
| **Desktop** | the native side owns one Core per window, over stdio, for the window's lifetime |
| **Terminal while the desktop runs** | may later attach to the desktop's core over local IPC |
| **Remote** | a WebSocket to a core somewhere else |

The first two exist. The others are transports, not protocols — which is why
`comodor/protocol` knows nothing about a pipe, and why `comodor/transport` is a
separate package rather than a module inside it.

### Local IPC, when it comes

| Platform | Mechanism |
|---|---|
| Windows | a named pipe |
| macOS, Linux | a Unix domain socket |

**Not TCP on loopback.** A localhost port is reachable by every process on the
machine and by anything a browser can be persuaded to fetch; a named pipe and
a Unix socket carry an operating system's own access control. D1 listens on
nothing: the test build reports the application's TCP listening and bound UDP
sockets, and the set is empty.

---

## The security boundary

> **The Tauri WebView never holds a provider key, a GitHub installation
> token, an OAuth secret or signing material.**

A WebView renders content, and content is the thing that gets compromised. It
asks the core, or a native credential service, to *use* a credential; it is
never handed one to use itself. `model.get` answers `configured: true|false`
and never a key. D1 enters no credential at all — setup stays in the
terminal — and the test build proves the boundary with a credential canary:
a unique key in the Core's home must appear in no IPC message, no bridge
command's arguments or result, no Core argument, nothing the page holds, and
not in the application's output, log or preferences, across every flow.

The application log records typed facts only — states, failure classes,
exits, the workspace — never a message the Core wrote.

---

## How it is tested

| Layer | Where | What |
|---|---|---|
| Native unit | `src-tauri/src/*` | the state machine with an injected clock, the relay, restart policy, stop sequence, workspace rules, preferences, the command list |
| Native integration | `src-tauri/tests/` | real processes: the real Core, a scripted Core and misbehaving doubles; startup failures, the relay, recovery, stopping, orphans |
| Window | `test/` | the React views over an in-memory native side and Core |
| Scenarios | `e2e/` (`npm run e2e`) | the test build in a real WebView, driven from the page |
| Lifetime | `npm run lifetime` | close, quit mid-turn, Quit now, kill, second launches — no Core left after any |
| Canary | `npm run canary` | every flow with a unique credential |
| Release list | `npm run release-manifest` | the release build grants exactly the nine commands |

All of it runs offline: no provider is ever called. CI runs every layer on
Windows, Linux and macOS.

---

## What the desktop must reuse

If any of these is reimplemented for the desktop, the boundary has failed:

- **Commands.** One action is one command, reached by button and key.
  That is what `@comodor/commands` is for.
- **Modes.** The cycle, the labels and the summaries. The core decides what a
  mode permits; the desktop has no opinion.
- **Questions.** The selection reducer, with a different renderer around it.
- **Session.** The projection, its gap detection and its resync.
- **Tokens.** `cssVariables()` emits the same names as CSS custom properties.

---

## Phases

```text
F1–F8  terminal foundation and parity            ← done
D1     Tauri foundation                          ← this
D2     the workbench shell
D3     Monaco and the workspace
D4     the integrated terminal
D5     agent, task and session panels
D6     production hardening: packaging, signing, updates, keychain
```

What D1 deliberately leaves to them: packaging and installers, history
browsing, several sessions, credential entry in the window, a remote Core,
the editor and terminal panes.

---

## Extension points, and why they are empty

Comodor will gain capabilities meant to get more out of whatever model is
connected: context packing, a semantic index, task decomposition, sub-agent
orchestration, model routing, verification loops, cross-session knowledge.

None of them exist, and **no empty class has been created for any of them.**
A placeholder for a feature nobody has designed is a constraint on the design,
plus a name that will be wrong.

What the architecture provides instead is the shape such a capability takes
when it arrives:

```text
core capability  →  protocol state / event / method  →  every client
```

rather than a feature built into one interface. A capability added that way is
usable from the terminal, the desktop, the web and a headless script on the
day it lands, because none of them implement it.

The protocol's version field and its forgiving capability negotiation are what
make that possible without a coordinated release: a core that gains an event
can send it to a client that has never heard of it, and the client ignores it.
