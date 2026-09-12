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
                    Versioned protocol  (schemas/protocol/v2.json)
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
history, open, send, cancel, set mode, choose a model, list models, answer a
question, reply to a permission, stop a background delegate. It knows nothing
about JSON.

Each session gets a deep copy of the config, so two sessions in one core keep
their own modes — setting one to Plan must not quietly disarm the other's Act.

**The workbench state is core state.** The agent's task list (`todo_write`)
and its background delegates (`BackgroundDelegates`) were already truths the
core kept; the application layer is where they became transportable. The
relay maps `Kind.TODO` to `tasks.updated` and `Kind.DELEGATE` to
`delegate.updated` through an allow-list — a field the internal records grow
later does not ride to every client by accident — and the session journal
folds both, so `session.snapshot` re-describes a mid-job session completely:
plan, delegated work, and a delegate that was running when the process died
comes back as `lost` rather than vanishing or pretending to run. The journal
folds delegates forward-only, the same rule the manager's own announcements
obey, because the snapshot is what a reconnecting client believes.

**Usage is core state, on the same rule.** The loop already knew how full the
context was and what the conversation cost; the relay maps that through the
same allow-list to `usage.updated`, and the snapshot's `usage` carries the
latest report whole — not merged, because the numbers describe a moment and a
fill and a cost from two moments were never true together. Sessions also
persist: every turn boundary appends to the shared store the terminal and the
browser already used, `session.history` lists it, and `session.open` reopens
a stored conversation with its transcript, plan and title restored — and the
stored delegates it had stay lost on their own record.

`assemble(..., delegates=True)` is opt-in and means "somebody will deliver a
finished background answer at a turn boundary". A served session says yes; a
headless run says nothing and keeps the delegate tool's refusal — background
work whose completion nobody drains is work whose answer is dropped. Where a
session has a manager, the turn worker drains completions after its turn ends
and runs each as a turn of its own, which is the same boundary rule the
terminal and the web session follow. `stop_delegate` is the only control: it
asks the manager, answers honestly when there was nothing running to stop,
and leaves every state transition to the manager's own announcements — a
client that painted `stopped` from its own request would be claiming an
outcome the core has not reported.

### `comodor/transport` — how they travel

Line framing, stdout ownership, and the server that binds a protocol message
to an application verb. Swap the channel for a socket and the same verbs
answer.

### `packages/` — what every client shares

| Package | Owns |
|---|---|
| `@comodor/protocol` | generated types, envelope builders, the reader |
| `@comodor/client` | the handshake, correlation, events, closing notification, spawning a core |
| `@comodor/session` | the session projection, snapshot reconciliation, the queue of what is waiting on the person, the task list and delegate records with their forward-only lifecycle, the tool-output bound, mode intent, follow policy |
| `@comodor/commands` | one action however it was reached |
| `@comodor/modes` | the cycle, labels and summaries a client draws |
| `@comodor/questions` | the selection state behind a question card |
| `@comodor/design-tokens` | semantic names, and a mapping per renderer |

Seven, because seven are used. There is no empty package here waiting for a
desktop client to arrive. `@comodor/session` is the newest, and exists because
correlating a delta to its message, keeping two tools' output apart, deciding
a snapshot is stale, replacing a task list whole, refusing a delegate
announcement that would move a stopped one backwards, and sequencing mode
intent are decisions a desktop client would otherwise reimplement slightly
differently — none of it is about a terminal. The workbench needed no eighth
package for exactly that reason: tasks and delegates are session state, and
the session projection is where session state lives. What a renderer keeps for
itself is presentation — which row the cursor is on, which finished tool was
clicked open, whether the panel is a column or an overlay at this width.

---

## Modes are core policy

`act`, `plan`, `ask`, `chat`. **Plan is the mode that may look; Ask is the
mode that talks.** Ask gets no tools at all — giving it the read-only set made
it and Plan the same mode with two labels, which is the failure a mode exists
to prevent. One consequence worth knowing: `propose_mode`, the tool a
restricted mode uses to offer the switch when a conversation turns into a
request for changes, is a tool — so Ask cannot offer it, and leaving Ask is
the person's move.

**An unrecognised mode denies everything.** `policy_for` raises on an explicit
unknown so it is caught where the value enters; the two enforcement points use
`enforced`, which cannot raise and falls to a deny-all policy. A config file
saying `"paln"` keeps that value, is complained about at load, and grants
nothing — rather than being corrected into `act`, which is the default and
therefore the one correction an authorization setting must never make.

The rule is in one table,
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

- **The web session assembles its own agent** — and it is a genuinely different lifecycle
  owner: `change_folder` rebuilds the agent in place for a new workspace, with
  its own conversation, checkpoints and delegates, which `assemble` does not
  model.
- **The cron runner and the delegate spawner deliberately differ.** A
  scheduled run has nobody at the keyboard, so it builds no learning engine
  and no cron-recursion; a spawned child gets no memory and pinned limits.
  Both are policy, and both say so in their own comments.
- **ACP no longer assembles its own.** `AcpSession` now builds on
  `application.assemble` — its seam is the JSON-RPC surface, not the
  construction underneath it. It keeps its own session store and transcript
  persistence, which are lifecycle, not wiring.
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
