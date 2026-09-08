# The Comodor protocol

What a Comodor core and a Comodor client say to each other. Version 1.

This is the contract a client is written against. If you are adding a client —
a terminal, a desktop window, a browser tab, something nobody has thought of —
this document and [`schemas/protocol/v1.json`](../schemas/protocol/v1.json) are
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
| `src/comodor/protocol/_generated.py` | `schemas/protocol/v1.json` |
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
{"version": 1, "type": "request",  "id": "7", "method": "session.send", "params": {}}
{"version": 1, "type": "response", "id": "7", "result": {}}
{"version": 1, "type": "error",    "id": "7", "error": {"code": "...", "message": "..."}}
{"version": 1, "type": "event",    "event": "message.delta", "seq": 41, "params": {}}
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
the pending question or permission — and the `revision` its contents reach.
A client joins, applies the snapshot, and applies only the events above that
revision, so a snapshot and the live stream cannot disagree about what
happened: whichever arrives first, the result is the same. A detected gap is
repaired by asking for another snapshot, never by carrying on with a hole in
the conversation.

---

## The handshake

`client.hello` must be first. Every other method is refused with
`not_initialized` until it succeeds.

```json
→ {"version":1,"type":"request","id":"1","method":"client.hello",
   "params":{"protocol_version":1,
             "client":{"name":"comodor-tui","version":"0.0.0"},
             "capabilities":["questions","permissions"]}}

← {"version":1,"type":"response","id":"1",
   "result":{"protocol_version":1,
             "core":{"name":"comodor-core","version":"1.2.1"},
             "capabilities":["streaming","questions","permissions","modes","tool_events"]}}
```

A version the core does not speak is refused at this message, with the
versions it does speak in `error.data.supported`. Failing here rather than at
whatever message first does not fit is the entire reason the field exists.

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
| `shutdown` | acknowledgement, then the core exits |

There are fourteen. The list is short because a method exists when something
calls it — the way to get a hundred speculative operations is to write them
before anything needs them, and then to keep them working forever.

`session.send` returns as soon as the turn is accepted. The answer arrives as
events, because a turn is a loop of model calls and tool runs that may take
minutes, and a request that waited for it would be a request that times out.

---

## Events

```
session.created      session.updated
message.started      message.delta       message.completed
tool.started         tool.output         tool.completed      tool.failed
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

`tool.output` carries the `call_id` of the invocation it belongs to, tagged
where the output was produced — a tool is handed a view of its context that
knows which call it is, so two tools running at once stream interleaved
without either borrowing the other's lines. A client matching output to
"whichever tool started most recently" would be right most of the time and
quietly wrong under parallel execution; the id exists so it never has to
guess.

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
