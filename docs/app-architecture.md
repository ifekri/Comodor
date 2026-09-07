# The application architecture

Comodor is a Python agent with several interfaces. This describes the boundary
that separates them, why it was drawn where it is, and what is still on the
wrong side of it.

For the wire format see [protocol.md](protocol.md). For the terminal client
see [tui-v2.md](tui-v2.md). For the future desktop application see
[desktop-architecture.md](desktop-architecture.md).

---

## The shape

```text
                      Python Comodor Core
                              │
                    Versioned protocol  (schemas/protocol/v1.json)
                              │
              ┌───────────────┴───────────────┐
              │                               │
        OpenTUI terminal                Future Tauri desktop
              │                               │
           React / TS                      React / TS
              └───────────────┬───────────────┘
                              │
                  Shared frontend packages
```

Dependencies point one way:

```text
frontend  →  protocol client  →  application  →  domain / infrastructure
```

Never the other. The core does not import a renderer, does not ask for
terminal dimensions, and does not know whether anything is watching.

---

## Why this, and why now

The agent already ran behind an event bus that a terminal, a browser and an
editor each subscribed to. `src/comodor/events.py` says so in its first
paragraph: *"swap the subscriber and the same loop drives a JSON stream
instead of a terminal."* The separation was intended from the start.

What was missing was an owner for the verbs. `AgentLoop(...)` was constructed
in **seven** places — `cli.py`, `ui/app.py`, `web/session.py` twice,
`acp/agent.py`, `cron/runner.py`, `agent/spawn.py` — each assembling the same
eight objects in the same order. Nothing was wrong with any one copy. What was
wrong is that "open a session" had no owner, so a fifth interface meant an
eighth copy and a change to how a session is built meant finding all of them.

`ui/app.py` is 2,346 lines, and much of it is application wiring rather than
presentation. That is the boundary problem this phase addresses; it does not
finish moving it.

---

## The layers

### `comodor/protocol` — what the messages are

Envelope shapes, method and event names, error codes, a shallow validator.
Generated from the schema. **No dependency on the rest of Comodor**, and no
knowledge of a pipe. Standard library only, because Comodor installs one
dependency and this does not add a second.

### `comodor/application` — the verbs

`assemble(config)` builds the agent for one session, once, in one place. It is
the block that used to live inside `cli.py`, lifted out rather than rewritten
— and `cli.py` now calls it, so the two cannot drift while both exist.

`CoreService` owns sessions and the operations on them: create, get, list,
send, cancel, set mode, choose a model, answer a question, reply to a
permission. It knows nothing about JSON.

Each session gets a deep copy of the config, so two sessions in one core keep
their own modes — setting one to Plan must not quietly disarm the other's Act.

### `comodor/transport` — how they travel

Line framing, stdout ownership, and the server that binds a protocol message
to an application verb. Swap the channel for a socket and the same verbs
answer.

### `packages/` — what every client shares

| Package | Owns |
|---|---|
| `@comodor/protocol` | generated types, envelope builders, the reader |
| `@comodor/client` | the handshake, correlation, events, spawning a core |
| `@comodor/commands` | one action however it was reached |
| `@comodor/modes` | the cycle, labels and summaries a client draws |
| `@comodor/questions` | the selection state behind a question card |
| `@comodor/design-tokens` | semantic names, and a mapping per renderer |

Six, because six are used. There is no empty package here waiting for a
desktop client to arrive.

---

## Modes are core policy

`act`, `plan`, `ask`, `chat` — with the rule in one table,
[`safety/modes.py`](../src/comodor/safety/modes.py), read by both places that
enforce it:

- **`ToolRegistry.for_mode`** decides what the model is *offered*. A model
  that cannot see a tool does not plan around it, so a plan produced in Plan
  mode reads like a plan rather than a thwarted attempt to edit files.
- **`ToolRegistry.invoke` and `PermissionEngine`** decide what actually
  *runs*. This is the boundary: a model can name a tool it was never offered,
  and so can a client driving the core.

Two layers, one rule. Before this the rule was written twice, in two shapes,
in two files — and two copies of a security rule is one rule and one thing
that will disagree with it later, invisibly, because both files look correct
on their own. `test_mode_policy.py` asserts the two layers cannot disagree.

---

## What has *not* moved

Stated plainly, because a migration that hides its remainder is one that never
finishes:

- **The Rich TUI still assembles its own agent.** `ui/app.py` does not use
  `application.assemble`. It works, it is the interface people use, and
  changing it is F2 rather than a foundation change.
- **The web session and the ACP agent likewise.** Same reasoning.
- **ACP has its own JSON-RPC stack.** `acp/jsonrpc.py` implements NDJSON
  framing and stdout capture, and `transport/jsonl.py` implements them again.
  They are not merged because ACP is somebody else's specification with its
  own batch semantics, and because refactoring a working protocol surface to
  remove thirty lines of duplication is the kind of opportunistic change that
  belongs in its own review. The duplication is recorded here so it is a
  decision rather than an oversight.
- **`session.send` runs one turn at a time per session.** A second send is
  refused rather than queued: two turns interleaving their events would be
  indistinguishable to a client correlating on a message id.

---

## Adding a client

1. Speak the handshake. Refuse to proceed on a version mismatch.
2. Call `session.create`, then `session.send`.
3. Render events. Ignore the ones you do not use.
4. Ask for state changes; wait for the event before showing them.
5. Never re-implement a rule the core owns. If you find yourself deciding
   whether something is allowed, the decision is in the wrong process.
