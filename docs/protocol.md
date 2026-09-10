# The Comodor protocol

What a Comodor core and a Comodor client say to each other. Version 2.

This is the contract a client is written against. If you are adding a client —
a terminal, a desktop window, a browser tab, something nobody has thought of —
this document and [`schemas/protocol/v2.json`](../schemas/protocol/v2.json) are
what you need, and nothing in `src/comodor/` should be reached into directly.

---

## One definition, two languages

The schema is the source of truth. Both sides are generated from it:

```sh
python tools/protocol-codegen.py           # write both
python tools/protocol-codegen.py --check   # fail if either is stale
```

| Generated | From |
|---|---|
| `src/comodor/protocol/_generated.py` | `schemas/protocol/v2.json` |
| `packages/protocol/src/generated.ts` | the same file, the same run |

Neither is edited by hand, and `tests/test_protocol_schema.py` regenerates
both and fails on a difference. That is the whole mechanism behind the claim
that Python and TypeScript cannot silently disagree about the wire — not a
convention, a test.

It proves the committed types match the committed schema. It does not prove
the schema is *right*; that is what the protocol tests are for.

---

## Envelopes

One JSON object per line, UTF-8, no embedded newlines. Four shapes, told apart
by `type`.

```json
{"version": 2, "type": "request",  "id": "7", "method": "session.send", "params": {}}
{"version": 2, "type": "response", "id": "7", "result": {}}
{"version": 2, "type": "error",    "id": "7", "error": {"code": "...", "message": "..."}}
{"version": 2, "type": "event",    "event": "message.delta", "seq": 41, "params": {}}
```

`id` is the client's, echoed back. An error caused by a line that could not be
read far enough to have one carries `"id": null` — honest about the fact that
there is nothing to correlate it to.

### Ordering

**A request is answered before the events it caused.** `session.create`
returns the session, *then* `session.created` arrives. Without that guarantee a
client is told about a session before it is told it made one, and an ordering
that happens to work is not one a second client can be written against.

Events from a turn — `message.delta` and the rest — are not part of any
request and arrive as they happen.

### Sequence numbers, and rebuilding from a snapshot

Every event carries `seq`, the sending session's own counter, starting at 1
and numbered under the same lock that updates the core's projection. A client
that has applied everything through 41 knows an event numbered 42 continues
the story, an event numbered 41 or lower is a duplicate, and an event numbered
43 means something never arrived.

`session.snapshot` answers with the whole visible session — messages, tools,
the task list, the background delegates, the pending question or permission —
and the `revision` its contents reach.
A client joins, applies the snapshot, and applies only the events above that
revision, so a snapshot and the live stream cannot disagree about what
happened: whichever arrives first, the result is the same. A detected gap is
repaired by asking for another snapshot, never by carrying on with a hole in
the conversation.

Three properties a snapshot has to have for that to mean anything:

**It carries one ordering, not two lists.** Every message and every tool has
`started_seq`: the session sequence of the event that put it in the timeline.
Merging on that number reproduces the interleaving the live stream had —
answer, the tool it called, the answer that follows. A client left to merge two
arrays in turn draws every message before every tool, which reads as a summary
above the work it summarises. Where two items share a number, the tie is
broken by kind and then by recording order, so the person's prompt stays above
the answer to it.

**It says when a message is unfinished.** A message that has started and not
ended is `streaming`. Reporting it as `completed` — which is what an empty
internal status serialised to — tells a rebuilt client to stop listening to an
answer that is still arriving, and the rest of that answer is then dropped on
the floor.

**It carries what is waiting.** `interactions` lists every blocking request
the session is holding, oldest first, each tagged with its `kind`; the singular
`question` and `permission` fields remain as the first of each kind for a
client that presents one at a time. A client that mounts into a session
mid-question can answer it. Without that, the agent waits out its timeout on a
form the person has no way to reach, and the rebuilt client shows a composer
for a session that is blocked on an answer.

Two can be waiting at once — a batch of read-only tools runs in parallel and
each may ask a question, and a delegate shares its parent's bus — so a
snapshot with one slot would silently strand whichever arrived second.

**It carries the workbench state.** `tasks` is the agent's plan as `todo_write`
last recorded it — the whole list, because that is the tool's own semantics:
every update replaces the list, so a task the model removed is gone and a
reorder is the reorder it wrote. `delegates` is every background delegate the
session knows, terminal ones included, in the lifecycle's own words
(`running`, `stopping`, `done`, `failed`, `stopped`, `lost`). A delegate that
was running when the core's process died is `lost` in the first snapshot a
restarted core can answer — the honest state of work whose answer no longer
exists, never a panel that quietly forgets it or pretends it is in flight.
Both fields are optional on the wire: a core too old to keep them omits them,
and a client too old to know them ignores them.


---

## The handshake

`client.hello` must be first. Every other method is refused with
`not_initialized` until it succeeds.

```json
→ {"version":2,"type":"request","id":"1","method":"client.hello",
   "params":{"protocol_version":2,
             "client":{"name":"comodor-tui","version":"0.0.0"},
             "capabilities":["questions","permissions"]}}

← {"version":2,"type":"response","id":"1",
   "result":{"protocol_version":2,
             "core":{"name":"comodor-core","version":"1.2.1"},
             "capabilities":["streaming","questions","permissions","modes",
                             "tool_events","tasks","delegates"]}}
```

A version the core does not speak is refused at this message, with the
versions it does speak in `error.data.supported`. Failing here rather than at
whatever message first does not fit is the entire reason the field exists.

### Versions

**Version 2 is the contract described here.** Version 1 was the first one: the
same envelopes and methods, but events carried no `seq`, `session.send`
answered with a `message_id` rather than a `turn_id`, tool output was not
tagged with the call it came from, and there was no `session.snapshot`.

Those are not additions an older peer can ignore — a client that cannot see
`seq` cannot tell a duplicate from a gap, and a client that correlates tool
output by recency mixes two parallel tools together. So the version moved
rather than the wire quietly changing underneath it.

A core speaks one version and refuses the rest, in both directions:

| Peer | Result |
|---|---|
| v2 client, v2 core | handshake succeeds |
| v1 client, v2 core | refused — `unsupported_version`, with `supported: [2]` |
| v2 client, v1 core | refused by the client, before it opens a session |

A line stamped with a version the reader does not speak is refused where it is
read, which for a request is before any method is dispatched: nothing is
created, sent or cancelled on a connection that never agreed what it is.

There is no multi-version negotiation, because there is nothing to negotiate
with. The core and its clients ship together; a mismatch means one of them was
installed from somewhere else, and the useful answer is a refusal that names
the version it wanted.

**Capabilities are additive and forgiving.** A name the other side has never
heard of is ignored, never refused — otherwise every core release would break
every older client. A capability that is absent is not supported, and must not
be assumed.

---

## Methods

| Method | Answers |
|---|---|
| `client.hello` | the handshake |
| `session.create` | a new session |
| `session.get` | one session, authoritatively |
| `session.snapshot` | the whole visible session, and the sequence number it reaches |
| `session.list` | every session this core holds |
| `session.send` | that the turn was accepted, and the `turn_id` that names everything it causes |
| `session.cancel` | whether there was anything to stop |
| `session.set_mode` | the session, with its new mode |
| `model.get` / `model.set` | provider, model, and whether it is configured |
| `workspace.get` | the directory the agent is pointed at |
| `question.answer` | acknowledgement |
| `permission.reply` | acknowledgement |
| `delegate.stop` | whether there was a running background delegate to stop |
| `shutdown` | acknowledgement, then the core exits |

There are fifteen. The list is short because a method exists when something
calls it — the way to get a hundred speculative operations is to write them
before anything needs them, and then to keep them working forever.

`session.send` returns as soon as the turn is accepted. The answer arrives as
events, because a turn is a loop of model calls and tool runs that may take
minutes, and a request that waited for it would be a request that times out.

`delegate.stop` is the only control the workbench adds, and its answer is
deliberately modest: `{"stopped": true}` says a running delegate was asked to
stop, and `{"stopped": false}` is an honest "there was nothing running to
stop" — not an error. What the delegate actually becomes arrives as
`delegate.updated` events, `stopping` first and then the terminal state the
worker settles on. A client must not paint `stopped` because its request was
accepted; the core owns that transition, and a stop that races a completion
resolves to whichever the worker reports. Stopping *every* delegate at once
is not a protocol operation: one deliberate stop is the surface the product
promises, and a bulk stop belongs to the interfaces that already had one
(`comodor`'s `/delegates stop`, the web session's).

---

## Events

```
session.created      session.updated
message.started      message.delta       message.completed
tool.started         tool.output         tool.completed      tool.failed
tasks.updated
delegate.updated
question.requested   question.resolved
permission.requested permission.resolved
mode.changed         model.changed       notification.created
```

`message.delta` carries a `channel`, so extended thinking can be shown or
hidden by name rather than guessed at from the prose.

`question.requested` carries a **form** — several questions at once, each with
its own options and its own `multiple` flag — because that is what the agent
asks. An answer names each question by its `header` rather than its position,
so a reordered form cannot silently reattach answers to the wrong questions.
Every question carries exactly one option marked `free`: the write-your-own
row, which the core appends and which a client should render as a text field.

`permission.requested` carries the `options` the engine will accept — today
`allow`, `allow_always` and `deny`, where `allow_always` is a session-scoped
grant the core remembers — plus `tool` and `risk`, the capability asking and
the tier it declared. Both are optional and omitted rather than guessed: a
client shows what the core knows, and a tier invented at the display layer
would be a security label with nothing behind it. The risk arrives as a word
(`safe`, `write`, `dangerous`) rather than the engine's integer, so no client
has to know a Python enum's numbering to tell a write from a shell command.

**A request that nobody answers is still resolved.** The core waits a bounded
time and then takes the safe fallback — the last option, which is a denial for
a permission and a cancellation for a form — and emits the matching
`*.resolved` event. A client is therefore never left holding a prompt the core
has stopped waiting on, and a reply that arrives after that point is refused
with `unknown_request` rather than answered with a resolution nothing acted
on. Cancelling a session resolves whatever it was holding the same way,
because an interrupt is a flag a worker parked in a prompt never reads.

`tool.output` carries the `call_id` of the invocation it belongs to, tagged
where the output was produced — a tool is handed a view of its context that
knows which call it is, so two tools running at once stream interleaved
without either borrowing the other's lines. A client matching output to
"whichever tool started most recently" would be right most of the time and
quietly wrong under parallel execution; the id exists so it never has to
guess.

`tasks.updated` carries the agent's **whole task list**, exactly as
`todo_write` recorded it: `tasks` is an array of `{text, state}` with `state`
one of `pending`, `active`, `done`, `blocked` — the tool's own vocabulary, and
a client renders those four and invents no others. The semantics are
replacement, never addition: a task the new list does not carry is gone, and
the order is the order the model wrote. Tasks carry no ids, deliberately — the
list is small, it is replaced whole, and an index is not an identity across a
replacement. Nothing a client can do to one task needs to name it; a future
operation on a single task would need a real core-owned id rather than a
positional guess.

`delegate.updated` carries one background delegate's **whole record** — `id`,
`label`, `state`, `steps`, `tool_calls`, `tokens`, `elapsed`, `started_at`,
and `error` when there is one — so a client replaces what it holds for that id
rather than merging fields. The state moves forward only: `running` and
`stopping` are live, `done`, `failed`, `stopped` and `lost` are terminal, and
a late announcement can never walk a delegate backwards. `lost` is the state
of a delegate that was running when the core's process died; after a restart
it is what the first snapshot says, because the alternative — showing work
nobody is doing any more — is the exact lie the lifecycle exists to prevent.
The metrics are what the worker recorded, which for a running delegate is
nothing yet: zeros until it settles, and no invented percentage in between.
`started_at` is the core's epoch seconds so a client can tick a running
delegate's own clock; a terminal record's `elapsed` is final.

Both ride the session's sequence like every other event, fold into
`session.snapshot`, and are gated by a handshake capability (`tasks`,
`delegates`) so a client only draws a panel the core actually feeds. An older
v2 client ignores both events by name and keeps working; a newer client
pointed at an older core sees neither capability and draws the screen it drew
before them.

An event a client does not use should be ignored, not treated as an error.
That is how a newer core stays usable by an older client.

---

## Errors

| Code | Means |
|---|---|
| `parse_error` | not JSON, or not an object |
| `invalid_envelope` | JSON, but not one of the four shapes |
| `unsupported_version` | the client asked for a version this core does not speak |
| `not_initialized` | something arrived before `client.hello` |
| `already_initialized` | `client.hello` arrived twice |
| `unknown_method` | no such method |
| `invalid_params` | the method exists; the parameters do not fit |
| `unknown_session` | no session with that id |
| `unknown_request` | no question or permission waiting under that id |
| `not_allowed` | the mode or the permission policy refused it |
| `internal_error` | a fault in the core |

`error.message` is written to be shown to a person. Anything that would only
help somebody debugging the core goes to stderr and never into an envelope.

---

## Modes are enforced, not displayed

`act`, `plan`, `ask`, `chat`. A client draws them; the core decides what they
permit, in [`src/comodor/safety/modes.py`](../src/comodor/safety/modes.py),
consulted by both the tool registry and the permission engine.

A client cannot get a write past a core in Plan mode. Not because the button
is hidden — a client can send whatever it likes — but because
`ToolRegistry.invoke` refuses by name before anything runs.

The client's job is to *ask* and to render what comes back. Pressing Tab sends
`session.set_mode` and waits for `mode.changed`; a client that moved its own
label first would show the wrong mode for as long as a refusal took, and
forever if the refusal was final.

---

## Transport

Today: newline-delimited JSON over a pipe, `comodor core --stdio`.

**stdout is protocol. stderr is everything else.** A client parses every line
it is given, so a stray `print` is a parse error and a banner is several. The
core takes stdout away from the rest of the program before it reads its first
line and points `sys.stdout` at stderr; `tests/test_core_stdio.py` decodes
every line the process emits and fails if one is not a message.

Nothing in `comodor/protocol` knows about a pipe. A named pipe, a Unix socket
or a WebSocket is a different `Transport` around the same messages — which is
why the split exists at all: a protocol defined in terms of its pipe acquires
stdio assumptions and then a socket cannot be added without a second protocol.

---

## What never crosses

No provider key, no GitHub installation token, no OAuth secret, no signing
material, no environment.

`model.get` answers `configured: true|false` and never the key — which is how
a client shows "this provider needs setting up" without being handed the
secret that would let it set anything up itself.
