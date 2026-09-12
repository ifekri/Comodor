# The desktop application

Planned, not built. Nothing in this document exists in the repository, and
that is deliberate: the point of the F1 foundation is that adding it later
must not require redesigning the core.

This records what it will be and — more usefully — what the core must already
be true for, so that a decision made now is not one that has to be unmade.

---

## The shape

```text
                 Python Comodor Core
                          │
                Versioned protocol
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
  OpenTUI terminal                   Tauri 2 desktop
        │                                   │
     React / TS                       React / TS
        │                                   │  Monaco, xterm.js
        └─────────────────┬─────────────────┘
                          │
              @comodor/protocol   @comodor/client
              @comodor/commands   @comodor/modes
              @comodor/questions  @comodor/design-tokens
```

The desktop reuses those six packages unchanged. That is the test of whether
this foundation worked: if adding it requires editing the protocol, the
protocol was written for a terminal.

Planned stack: **Tauri 2**, React and TypeScript, **Monaco** for editing,
**xterm.js** for an integrated terminal.

---

## Why Python stays the core

Not sentiment. The agent runtime, tools, skills, memory, MCP, the GitHub
integration and the risk rules are the product; a rewrite would be months of
work whose best possible outcome is the behaviour that already exists.

Rust enters, if it does, as the Tauri shell and native services around the
core — window management, the keychain, auto-update, single-instance
behaviour. Not as a reimplementation of anything above.

---

## Process lifecycle

Three arrangements, one protocol.

| | |
|---|---|
| **Terminal alone** | the TUI spawns a private core over stdio, and it dies with the client |
| **Desktop** | Tauri owns one persistent local core for the window's lifetime |
| **Terminal while the desktop runs** | may later attach to the desktop's core over local IPC |
| **Remote** | a WebSocket to a core somewhere else |

Only the first is implemented. The others are transports, not protocols —
which is why `comodor/protocol` knows nothing about a pipe, and why
`comodor/transport` is a separate package rather than a module inside it.

### Local IPC, when it comes

| Platform | Mechanism |
|---|---|
| Windows | a named pipe |
| macOS, Linux | a Unix domain socket |

**Not TCP on loopback.** A localhost port is reachable by every process on the
machine and by anything a browser can be persuaded to fetch; a named pipe and
a Unix socket carry an operating system's own access control. If a TCP
transport is ever added it needs authentication designed for it, not the
absence of it.

---

## The security boundary

The rule the desktop is built to, stated before there is a desktop to break
it:

> **The Tauri WebView never holds a provider key, a GitHub installation
> token, an OAuth secret or signing material.**

A WebView renders content, and content is the thing that gets compromised. It
asks the core, or a native credential service, to *use* a credential; it is
never handed one to use itself.

The protocol already reflects this. `model.get` answers `configured:
true|false` and never a key — a client can show "this provider needs setting
up" without being told the secret that would let it set anything up itself.

Credentials belong in the OS keychain, reached by the native side, not in
browser storage, not in a serialized UI state, and not in a log.

---

## What the desktop must reuse

If any of these is reimplemented for the desktop, the boundary has failed:

- **Commands.** `mode.plan` must be invokable from a menu item, a button, a
  palette entry and a keyboard shortcut without four handlers. That is what
  `@comodor/commands` is for.
- **Modes.** The cycle, the labels and the summaries. The core decides what a
  mode permits; the desktop must not have an opinion.
- **Questions.** The selection reducer, with a different renderer around it.
- **Tokens.** `cssVariables()` already emits the same names as CSS custom
  properties; that function exists to prove a token is renderer-independent.

---

## Phases

```text
F1  headless core, protocol, TUI bootstrap
F2  session and streaming parity
F3  ACT / PLAN / ASK UX and questions
F4  setup wizard and GitHub
F5  tools, permissions, agent surfaces
F6  full TUI parity and performance
F7  make the OpenTUI interface the default
F8  remove the previous Rich presentation layer     ← done; F1–F8 are all merged

D1  Tauri foundation
D2  the workbench shell
D3  Monaco and the workspace
D4  the integrated terminal
D5  agent, task and session panels
D6  production hardening
```

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
