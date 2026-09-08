# TUI v2

The new terminal interface: OpenTUI, React and TypeScript, driving a Python
core over [the protocol](protocol.md).

**It does not replace anything yet.** `comodor` is still the Rich interface,
and remains so until this one is proven at parity. A migration that swaps the
default first is one where every gap is found by somebody trying to work.

```sh
comodor tui-v2          # from a source checkout
```

---

## It needs Bun

Not a preference. OpenTUI draws through native code bound with `bun:ffi`, and
Node has no equivalent: `node:ffi` is not a module in any released version,
including 26.x, and OpenTUI's own loader falls back to a backend whose every
method throws *"OpenTUI native FFI is not available for this runtime yet"*.

Verified rather than assumed — on Node 24.19.0 and on Node 26.8.1, both fail
identically, and `require('module').builtinModules` contains no `ffi` entry on
either.

So:

| Runs on | |
|---|---|
| `apps/tui` | **Bun ≥ 1.3** |
| every `packages/*` | Node ≥ 22.6, or Bun |
| the core | Python ≥ 3.9 |

The requirement belongs to the renderer, not to the protocol, and the split is
deliberate: the packages a desktop client would reuse are plain TypeScript and
are tested under Node.

Install Bun from <https://bun.sh>, then:

```sh
bun run apps/tui/src/main.tsx
```

**CI installs it, so contributors do not have to.** The `renderer` job pins
Bun 1.4.2 through `oven-sh/setup-bun` and runs the real renderer suite and a
real core process; every other job runs on Node and Python alone.

```sh
bun test apps/tui/test/bun/renderer.test.tsx   # a real renderer, keys and clicks
bun test apps/tui/test/bun/orphan.test.ts      # a real core, and no orphan
bun apps/tui/test/bun/measure.tsx              # what it costs
```

---

## What is on the screen

Enough to prove the architecture, and no more.

```
┌──────────────────────────────────────────────────────────┐
│ Comodor   ~/work/my-project                              │
│                                                          │
│  You                                                     │
│  fix the failing parser test                             │
│                                                          │
│  Comodor                                                 │
│  The test expects parse("") to raise, but…               │
│  ✓ read_file  tests/test_parser.py                       │
│  ● run_shell  pytest tests/test_parser.py                │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ ▌ask for anything                                        │
├──────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands… │
│ tab Mode   ctrl+k Commands   ctrl+d Quit                 │
└──────────────────────────────────────────────────────────┘
```

A header, the conversation, a composer, the mode switcher, a footer, a command
palette and a question card. Not an IDE in a terminal — that is later phases,
and building it now would mean building it against a protocol nobody had used.

---

## Modes

`Tab` forward, `Shift+Tab` back, through **ACT → PLAN → ASK**. `chat` exists
and is reachable by name; landing on it by pressing Tab would surprise
somebody who only knows the three.

The segments are clickable. Keyboard, mouse, palette and a programmatic
`session.set_mode` all reach the same command, so there is one path into the
core and one place a mode change can go wrong.

The switcher is a segmented control and the mode is **spelled out**, never
signalled by colour alone.

Pressing Tab does not change the label. It sends `session.set_mode` and waits
for `mode.changed`. The core is the authority, and a client that moved first
would show the wrong mode for as long as a refusal took to arrive.

Presses do accumulate, though. The bar keeps two things apart:

```text
confirmed   what the core last said — the only thing drawn in brackets
desired     where the presses so far point — drawn in parentheses
in flight   the one request allowed to be outstanding
```

So three Tabs inside one round trip ask once, for where the third press
pointed, and the bar reads `[ACT]  (PLAN)  ASK   asking the core for PLAN…`
until the answer comes. A bracket is a fact about the session; parentheses are
a request that has not landed. A refused change says so in words —
`refused: <the core's reason>` — and falls back to what the core has, rather
than asking again in a loop against a settled no.

The mode can also change without anybody pressing Tab: `propose_mode` is a
tool, and accepting its card writes the session's mode. The core announces that
as a `mode.changed` in the middle of the turn rather than leaving the bar
showing the old mode until the turn ends — a bar that says PLAN while the
session runs under ACT is not a stale label, it is a wrong answer to "what may
this agent do right now".

---

## Every advertised shortcut exists

The footer is printed from the same binding list the key handler reads, and
`CommandRegistry.bind` throws when a key names a command that is not
registered. A hint cannot outlive the key it names.

This rule is here because the previous interface shipped a footer advertising
`ctrl+s` and `esc` for things that did nothing. Nobody had lied; the label and
the binding were simply written in different files.

| Key | Does |
|---|---|
| `Tab` / `Shift+Tab` | next / previous mode |
| `Ctrl+K` | the command palette |
| `Ctrl+C` | stop the work; quit when there is none |
| `Ctrl+D` | quit |
| `Enter` | send |
| `Esc` | close the palette, or cancel a question |
| `PageUp` / `PageDown` | read the history |
| `End` | back to the newest line |
| `Ctrl+R` | send the last unsent prompt again |

`Ctrl+C` is context-sensitive on purpose. Killing the client mid-turn would
leave a core running with nobody attached.

### While something is waiting on you

A permission card or a question form owns the keyboard, because a key meant
for a decision must not do something else as well. `Enter` on a card answers
the card and never sends a chat message; typing on a card never reaches the
composer.

| Key | On a permission card | On a question form |
|---|---|---|
| `←` `→` `↑` `↓` | move between the choices | move between options and questions |
| `Enter` | send the highlighted choice | send the form |
| `Esc` | **take the safe option** | leave the typed field, or cancel the form |
| `Space` | nothing | choose an option / open the write-your-own field |
| `Ctrl+C` | stop the turn | stop the turn |
| `Ctrl+D` | quit | quit |
| `Tab` / `Shift+Tab` | change mode | change mode |
| anything else | nothing | nothing |

`Esc` takes the request's **own** safe option — the last one it offered, which
is the same answer a timeout gives — and the card names it, so the key never
means something the screen did not say. For a permission that is `deny`; for a
request to use the screen it is `no`; for a proposal to change mode it is the
current mode, because silence means "no change", never a switch. It is a
decision and not a dismissal: the core is told, the prompt stops waiting, and
the tool fails cleanly. A key that merely hid the card would leave the agent
blocked on a decision nobody could reach any more. It never allows.

There is no single-letter shortcut for allow. A key pressed for any other
reason must not be able to authorise a shell command, so allowing costs one
deliberate move to the choice and one to confirm it.

Mode keys stay live while a card is up, because the core accepts a mode change
with a prompt outstanding and moving to Plan while deciding whether to let
something run is a reasonable thing to want. The command palette does not: a
launcher over a blocking prompt hides the thing that must be answered.

---

## Questions

`question.requested` is a protocol primitive, not a numbered list in prose —
and it carries a **form**, because the `ask` tool exists to put several short
questions before a person in one round trip rather than several.

A card renders it: `↑↓` moves between options, `←→` between questions, `space`
chooses, `enter` sends the whole form, `esc` cancels. Every question gets a
write-your-own row, which the tool appends itself.

The selection logic is in `@comodor/questions` and has no rendering in it, so
a browser form and a terminal card agree about what is selected because there
is one reducer. An answer names its question by `header`, never by position:
a reordered form would otherwise silently reattach every answer to the wrong
question.

A form of several says where you are in it — `Question 2 of 4`, a marker per
question showing which are answered and which is being answered, and a count.
"3 of 4" alone does not say *which* one you skipped.

**What you have typed and chosen survives the turn running behind the form.**
A stream delta, tool output, a notification, a mode change or a resync that
redelivers the same request leaves the draft alone; the draft is keyed to the
request's id, so only a *different* request starts clean. Somebody halfway
through a four-question form does not lose three answers because the agent
kept talking.

---

## Permissions

A tool that writes, runs or reaches the network stops and asks. `permission.requested`
is a protocol primitive like a question, and until now this client carried it
without drawing it — which left the core blocked on a decision the person was
never shown, and read as a hung agent.

The card shows what the core actually said and nothing invented:

```text
┌────────────────────────────────────────────────────────────┐
│ Permission needed  run_shell  runs commands                │
│ run: npm test                                              │
│ $ npm test                                                 │
│  Allow   Allow for this session  [Deny]                    │
│ ←→ choose   enter confirm   esc deny                       │
└────────────────────────────────────────────────────────────┘
```

The tool name and the risk tier come from the engine's own record; a prompt
with nothing truthful to say omits them rather than guessing, because a
made-up tier on the wrong prompt trains somebody to stop reading it. The
choices are the core's list in the core's order — `allow`, `allow_always`,
`deny` — and "allow for this session" is a real grant the engine keeps, not a
label this client invented. The detail is clipped to a few lines and says so,
and every line is clipped to the terminal width, because a path with no spaces
in it cannot be wrapped and a card that grows until the choices are off the
bottom is a decision nobody can reach.

**Deny is where the cursor starts.** A card that opened on Allow would hand it
to an Enter pressed for any other reason — a form habit, a key repeat, a
person who meant to dismiss the thing. The accidental keystroke does the
reversible thing, and allowing costs one deliberate move.

### One decision, and the core's word on whether it landed

A reply is latched the moment it is sent, synchronously, so a second Enter, a
click while a key is in flight, and a key that arrives after the core resolved
it all produce **one** `permission.reply`. The card then says `sending…` and
stays: whether the request is still live is the core's to say. It goes when
`permission.resolved` arrives.

If the reply is refused — the request had already timed out, or was answered
elsewhere — the card stays up with the reason and can be retried or denied. A
card that vanished on an error would strand the prompt the core is still
holding, and pretending the core accepted a decision it rejected is worse than
showing the failure.

Nothing here holds authorization. A press produces a reply; the grant, the
session-scoped memory of it and the refusal all belong to the core.

### Restored, not lost

A prompt raised before this client existed is answerable by it: the snapshot
carries what is waiting, the card is drawn from that, and answering it reaches
the same request. A prompt the core resolved while nobody was watching is not
restored, and a resolved prompt cannot be answered by a late keystroke.

A prompt nobody answers is resolved by the core — as a denial — and says so on
the wire, so the card stops being actionable at the moment the core stopped
waiting. No countdown is drawn, because the core does not send a deadline and
a client inventing "30 seconds" from a duplicated constant would be a guess
dressed as a fact.

---

## When two things are waiting

Two blocking interactions can be live at once. A batch of read-only tools runs
in parallel and each may ask a question, and a delegate shares its parent's
event bus, so its question arrives while the parent waits on a permission.
Two mutating tools cannot prompt at once — the core only parallelises a batch
in which every call is read-only — but that is a property of the scheduler,
not something a client should assume.

So the projection keeps a **queue** of what is waiting, in arrival order,
keyed by request id, and presents the oldest. One is drawn at a time; the card
says `+1 more waiting` when there is another behind it. Resolving one reveals
the next rather than dropping it, and a redelivery of the same request
replaces itself instead of doubling.

A queue and not a priority, because nothing here knows that a permission
matters more than a question — both block a worker — and "oldest first" is the
order the core lists them in and the one a person expects.

---

## Colour

Every colour is a semantic token — `surface.raised`, `border.focused`,
`mode.act` — resolved by `@comodor/design-tokens`. No component knows a hex
value, and the frontend lint refuses one outside the token package.

That is what makes "the same design in two renderers" mechanical: a browser
maps the same names to CSS variables.

---

## Lifecycle

```text
comodor tui-v2
  → spawn `comodor core --stdio`
  → client.hello, and refuse to proceed on a version mismatch
  → take the terminal only after the handshake
  → session.create
  → render
  → on quit: unmount, release the terminal, shutdown the core
```

The renderer is taken **after** the handshake so that a core which cannot
start prints a plain error to an ordinary terminal instead of a traceback into
a half-initialised alternate screen.

The child does not outlive the parent: the exit handler is registered at
spawn, not at close, because the case it exists for is the parent ending
without the chance to tidy up.

---

## Following the newest line

A long answer scrolls itself while the viewport is at the bottom, and **stops**
the moment it is not. Scrolling away — `PageUp` or the mouse wheel — pauses
following; new output then raises a `↓ new output` bar naming `end` as the way
back, and the viewport is not dragged down to it. Reaching the tail again,
pressing `End`, or sending a new prompt all resume the follow. The policy is
renderer-independent (`@comodor/session`); the scrolling is the scroll box's,
and the pause, the marker and the return are proved against the real renderer.

Prompted text is never lost. A prompt is drawn at once as *pending*; if the
core refuses it — the session is busy, say — the line stays on screen saying
so, with `ctrl+r` to send it again. Only prompts the core never accepted are
retried: a turn it accepted and then failed is not resent, because the tools
it already ran would run twice.

## What is not here yet

- **Streaming, tools and recovery are in.** A turn's messages and tools draw
  interleaved in arrival order, tool output lands under the call that
  produced it, and a client that remounts rebuilds itself from
  `session.snapshot` — the same session, not a second one — and continues
  from the sequence the snapshot names.
- **A remount restores what was waiting, not just the transcript.** A
  question the core asked before this client existed is drawn as a form and
  can be answered — navigation, a written answer and all. A message caught
  mid-answer comes back as still streaming and keeps taking its deltas. The
  order of a rebuilt turn is the order it happened in, because both lists are
  numbered in one domain rather than merged messages-then-tools.
- **A remount also restores the mode it is aiming from.** Intent starts at
  the resumed session's confirmed mode, so the first Tab advances from Plan
  rather than from a default Act. A resync caused by a gap is different and
  is treated differently: the core's mode is adopted, but an aim the person
  already had is kept rather than thrown away with the hole in the stream.
- Rapid mode switching no longer collapses: presses accumulate as *intent*
  and one coordinator asks the core for the current aim, so a key repeat that
  outruns the round trip still lands where the last press pointed.
- **Permission prompts are drawn and answerable.** The card, its keyboard and
  mouse, the single-reply latch, the failure path, the restoration from a
  snapshot and the queue behind it are all in, and all renderer-verified. The
  `permissions` capability this client announces is now one it can honour.
- Sessions are resumed when the client starts with a session id; automatic
  reconnection after a lost core is not built yet.
- No sidebar, no scroll-back search, no file attachment, no slash commands.
- A resolved permission leaves no trace. The turn carries on and the tool's
  outcome is in the transcript, but there is no history of who allowed what:
  the core does not retain resolved prompts in a snapshot, and inventing a
  local record would be a client claiming knowledge it does not have.
- Mouse support is partial, and the three states are worth telling apart:

  | | |
  |---|---|
  | Mode segments | clickable, and **verified in the renderer** — each of ACT, PLAN and ASK, plus that a refused change leaves the label alone |
  | Wheel over the conversation | scrolls, pauses follow, raises the marker — **verified in the renderer** |
  | Permission choices | clickable, and **verified in the renderer** — a click decides, and cannot decide twice |
  | Question option rows | clickable, and **verified in the renderer** — single and multiple choice |
  | Palette rows | clickable, and **verified in the renderer** — a click runs the row it landed on |
  | The new-output marker | clickable, **not renderer-verified** |
  | Everything else | no mouse behaviour at all — a message, a tool row, the composer and the custom-answer field ignore a click |

  "Wired" and "proven" are not the same claim, and neither is "proven in the
  renderer" and "proven in a terminal": these run OpenTUI's real renderer
  against synthetic pointer events, which is evidence about the code and not
  about any particular terminal's mouse reporting. The one handler still
  unverified goes through the same code path as the `End` key, which is a
  reason to expect it to work and not evidence that it does.
