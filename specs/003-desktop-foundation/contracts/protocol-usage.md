# Contract: What the Desktop Uses of Protocol v2

Protocol v2 (`schemas/protocol/v2.json`) is used **unchanged** (FR-008,
FR-026). This file lists what D1 relies on and the flows it follows, so a
reviewer can check that nothing new is assumed.

## Methods used

| Method | Used for |
| --- | --- |
| `client.hello` | by the native side only, once per Core (the page's hello is answered from the cache) |
| `session.create` | the first session, and a fresh one when a crash left nothing stored |
| `session.list` | rejoining after a page reload (one session per Core in D1) |
| `session.snapshot` | rejoin and gap repair |
| `session.open` | reopening the stored conversation after a Core restart |
| `session.send` | a prompt |
| `session.cancel` | the person's cancel. On quit, the Core's own `shutdown` handling interrupts the turn |
| `session.set_mode` | the mode control. The label changes only on `mode.changed` |
| `model.get` | provider, model, `configured` |
| `workspace.get` | the workspace shown (FR-020) |
| `question.answer` | a person's answer to a form |
| `permission.reply` | a person's permission choice |
| `shutdown` | by the native side only |

Not used in D1: `session.get`, `session.history`, `model.set`, `model.list`
and `delegate.stop`. Their UI belongs to D2 and D5.

## Events rendered

`session.created`, `session.updated`, `message.*`, `tool.*`,
`question.requested`/`resolved`, `permission.requested`/`resolved`,
`mode.changed`, `model.changed`, `notification.created`, `usage.updated`.
`tasks.updated` and `delegate.updated` are folded by the reducer. D1 shows
only a one-line delegate summary; panels are D5. An unknown event is ignored.

## Flows

**First start**:

1. The native side: handshake, then `ready`.
2. The page: `connect`, then `CoreClient.start()` (local hello).
3. The page: `workspace.get` and `model.get`.
4. The page: `session.create`, then subscribe and `session.snapshot`.

**Page reload**:

1. The page: `connect` (a new generation), then `start()`.
2. The page: subscribe, then `session.list`. A `session.list` that fails
   says nothing about which sessions the Core has, so nothing is opened or
   created on its word: the window says the session could not be opened.
3. The page: `session.snapshot`, then apply events above its revision.
   A snapshot showing the session busy marks its turn as one a crash would
   interrupt.

**Core crash**:

1. The native side restarts the Core and handshakes again, then sends status
   `ready` to the page.
2. The page: `start()` again, then `session.open(stored_id)`. A `ready`
   that arrives while the previous `start()` is still failing is answered
   once that start ends.
3. If the Core refuses (nothing stored), `session.create` plus a notice.
4. An unfinished turn is shown as interrupted. Nothing is re-sent.

**Unconfigured provider**:

1. `model.get` returns `configured: false`: send is unavailable, and the page
   shows the `comodor setup` direction.
2. "Check again" calls `check_again` (a Core restart), then `model.get`.

**Question or permission**: `question.requested` or `permission.requested`
is rendered with every option. The answer is sent only on the person's
action. An unanswered request is resolved by the Core (`*.resolved`).

## Guarantees relied on (all existing)

- A request is answered before the events it caused.
- `seq` per session; the snapshot `revision`; the snapshot carries
  `interactions`.
- `model.get` never returns a credential.
- The Core exits when its stdin closes.
