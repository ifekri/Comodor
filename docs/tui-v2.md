# TUI v2

The new terminal interface: OpenTUI, React and TypeScript, driving a Python
core over [the protocol](protocol.md).

**It does not replace anything yet.** `comodor` is still the Rich interface,
and remains so until this one is proven at parity. A migration that swaps the
default first is one where every gap is found by somebody trying to work.

```sh
comodor tui-v2          # from a source checkout
```

A first run with no provider configured asks the same setup questions `comodor`
asks — in the same invocation, before the renderer, through the same setup path
— and starts only once they are answered. It will not spawn a core that has
nothing to talk to; cancelling setup leaves nothing started. This does not make
`comodor tui-v2` the default, which is still `comodor`.

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

The header says where you are and what answers; the footer says what it costs
and what you can press; the middle is the work.

```
┌──────────────────────────────────────────┬───────────────────────┐
│ Comodor   ~/work/my-project  fake-1      │ Agents         1 live │
│                                          │  ● d1 running    12.3s│
│  You                                     │    survey the retries │
│  fix the failing parser test             │ Tasks            2/5  │
│                                          │  ◐ write the tests    │
│  Comodor                                 │  ● read the code      │
│  The test expects parse("") to raise, …  │  ○ run the suite      │
│  ✓ read_file  tests/test_parser.py  0.2s │                       │
│  ● run_shell  pytest tests/…     running…│                       │
│      collected 12 items                  │                       │
│                                          │                       │
├──────────────────────────────────────────┴───────────────────────┤
│ ▌ask for anything                                                │
├──────────────────────────────────────────────────────────────────┤
│  [ACT]   PLAN    ASK    Reads, writes and runs commands…         │
│ ● 1 agent  tab Mode  ctrl+b Work  ctrl+k Commands      42% ctx  │
└──────────────────────────────────────────────────────────────────┘
```

A header (project, and the provider and model that answer), the conversation
with its tool timeline, the workbench panel, a composer, the mode switcher, a
footer with the usage the core reports, a command palette, a question card and
two pickers — the model chooser and the session picker. Not an IDE in a
terminal — that is later phases, and building it now would mean building it
against a protocol nobody had used.

---

## The header and what answers

The right side of the header names the provider and the model the core is
answering with. It is never a guess from a config file: the client asks
`model.get` at connect and moves only on the core's own `model.changed`,
whichever side made the change. A provider with no key is marked, not dropped
— `(no key)` is how a chooser elsewhere says the same thing — and a core too
old to answer simply shows nothing.

**Switching is a picker, never a config write.** `ctrl+k` → "Choose the
model" asks the core for `model.list` at the moment of opening — a catalogue
is the provider's to change, and a cached list would offer models that no
longer exist. The query narrows, `↑↓` moves, `Enter` asks, `Esc` closes, and
a click chooses the row it lands on. A refusal leaves the header alone and
says why. The model in use opens marked rather than hidden, and a blocking
prompt outranks the chooser exactly as it outranks the palette.

---

## Earlier conversations

Every session the core serves persists at its turn boundaries into the same
store the terminal and the browser write to — one store, one account of
earlier conversations. `ctrl+k` → "Open an earlier conversation" lists the
store newest-first (title, message count, age); `Enter` reopens it through
`session.open` with the transcript, the plan and the title restored, and a
click opens the row it lands on. Reopening the same stored session hands back
the live one, because two live handlers appending to one transcript file
would interleave their lines into a record neither said.

A switch is a remount against another session: the composer's draft, the
workbench cursor, the tool expansions and the scroll position all start
clean, because none of them is true of the conversation just opened. Work
that was running when its process died stays `lost` on its own record — an
open restores what was said, never what was running.

---

## When the core stops answering

A dead core is news, not something the next send trips over: the moment the
pipe closes, the client is told and the screen says so — what is still true
(the transcript the core confirmed before it stopped), and what to do next
(`ctrl+d` quits). A message caught mid-stream does not keep drawing its
spinner against a dead pipe; the composer stops listening rather than
accepting input that goes nowhere; and nothing that was in flight is
preserved as live — a restarted client rebuilds only from the core's
snapshot, which is the only truth that survives.

---

## The workbench

The conversation says what Comodor is *saying*; the workbench says what it is
*doing*. Three kinds of work, three treatments, and none of them invented by
the interface — every fact on screen arrived as a protocol event or a
snapshot field the core owns.

**Tools live in the timeline**, interleaved with the messages exactly where
they ran, because a tool call belongs to the sentence that caused it. Each
card is one row: a mark (`●` running, `✓` done, `×` failed), the name, the
core's own one-line summary, and on the right either `running…` or what it
cost in time. A running tool shows the last few lines of its streamed output;
a finished one collapses to its row — a long autonomous run leaves dozens of
calls behind, and a wall of kept output is a transcript nobody can scan.
Clicking a finished tool opens a deeper tail of what the core still holds
(the same bounded copy a remount would restore), and clicking again closes
it. A failure always shows the head of its error, collapsed or not: a
failure you have to open to find is a failure half-hidden. Output that the
core shortened says so — `… earlier output is not kept` — rather than
presenting the tail as the whole.

**Agents and Tasks live in the panel.** It is drawn beside the conversation
from 100 columns up, and only when there is something in it or it was asked
for — a chat that never delegates keeps every column of its transcript. Below
100, `ctrl+b` opens it as an overlay and `Esc` closes it; the footer's
`● N agents` count says when background work exists while the panel does not.
The palette (`ctrl+k`) reaches both commands too, so nothing here is
mouse-only or key-only.

The **Tasks** section is the model's own plan as `todo_write` last wrote it:
`○` pending, `◐` active, `●` done, `✗` blocked, a `done/total` count, the
active item first, and a `+N more` when the list is longer than the panel.
It is a reader, not a task manager — the list belongs to the model, updates
replace it whole, and the panel has no way to edit it.

The **Agents** section is the background delegates: two rows each, the state
spelled in words (`running`, `stopping`, `done`, `failed`, `stopped`,
`lost`) next to its mark, a live clock while one runs, the final count when
it settles, the label — or the reason, when it failed or was lost. A
delegate that was running when the core's process died comes back as `lost`
from the first snapshot; nothing here can dress it as work in flight.

**Stopping one is deliberate, and the core's.** `ctrl+b` gives the panel the
cursor (the composer blurs and says so with its border), `↑↓` select a row,
and `Enter` asks the core to stop it — but only a row the lifecycle says can
be stopped, and the panel never paints the outcome itself. The request goes
out as `delegate.stop`; the row moves to `stopping` when the core announces
it and to its terminal state when the worker settles. A stop that races a
completion shows whatever the core reports, and a press on a row that
already settled produces at most an honest "was not running" — never a
second stop, and never a state the client decided. Clicking a row only
selects it; the stop is a named control (`enter Stop d1`), clickable in its
own right. `Esc` leaves the panel and cannot stop anything.

The panel takes four keys while focused — `↑ ↓ enter esc` — and nothing
else. `Tab` still cycles the mode, `ctrl+c` still stops the turn, and a
permission or question card still owns the whole keyboard while it is up:
the workbench is below the blocking interactions in precedence, and
delegate events arriving behind a card update the panel without touching
the card.

All of it is gated on the handshake: a core that does not advertise `tasks`
or `delegates` gets the screen this client drew before them — no empty
panel, no dead command — and chat, streaming, modes, questions and
permissions are untouched either way.

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

## Terminals that are not generous

The floor is the Rich layout's own: 40×12. Below it the screen says so —
"Too small — resize to at least 40×12 — ctrl+d Quit" — instead of letting
columns share cells. A blocking decision outranks the floor: a permission or
a question the core is waiting on replaces the notice, because a tiny
terminal cannot be a reason the person cannot answer it. Overlay lists bound
their rows against the actual height, so a short terminal never pushes the
hint row off the bottom, and growing past the floor brings the whole screen
back.

Resizing is not one render that fits: the side panel becomes an overlay, the
header keeps the model and drops the provider at narrow widths, and a
permission card measures its header and choices against the columns it has —
suffixes fall off in the order they matter least rather than wrapping mid-word
into each other.

Renderer-verified at 160×50, 120×40, 100×30, 80×24, 60×20, at the too-small
floor, and through a live narrow↔wide resize.

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

- **Sessions, models and recovery are in.** A picker reopens an earlier
  conversation by title; a chooser switches the model by name; and a core
  that dies while you are idle tells you plainly instead of freezing the good
  state it was showing. A remount reopening a session still restores what was
  waiting, not just the transcript, exactly as before.
- No scroll-back search, no file attachment, no slash commands. Session
  history search is through the store (`Open an earlier conversation` lists
  every stored title), not through the scroll buffer.
- A resolved permission leaves no trace. The turn carries on and the tool's
  outcome is in the transcript, but there is no history of who allowed what:
  the core does not retain resolved prompts in a snapshot, and inventing a
  local record would be a client claiming knowledge it does not have.
- The usage corner shows only what the provider measured. A local model has
  no honest cost, and showing `$0.00` for "unmeasured" would be a lie of a
  different kind.
- Mouse support is partial, and the three states are worth telling apart:

  | | |
  |---|---|
  | Mode segments | clickable, and **verified in the renderer** — each of ACT, PLAN and ASK, plus that a refused change leaves the label alone |
  | Wheel over the conversation | scrolls, pauses follow, raises the marker — **verified in the renderer** |
  | Permission choices | clickable, and **verified in the renderer** — a click decides, and cannot decide twice |
  | Question option rows | clickable, and **verified in the renderer** — single and multiple choice |
  | Palette rows | clickable, and **verified in the renderer** — a click runs the row it landed on |
  | A finished tool's heading | clickable, and **verified in the renderer** — opens the output the core still holds, closes it again |
  | A delegate row | clickable, and **verified in the renderer** — selects, and *only* selects: the stop is its own control, verified separately |
  | The workbench's stop control | clickable, and **verified in the renderer** — one click, one `delegate.stop`, and the row still waits for the core's word |
  | The new-output marker | clickable, and **verified in the renderer** — it returns to the newest line and follows it again |
  | The model chooser's rows | clickable, and **verified in the renderer** — a click chooses the row it lands on |
  | The session picker's rows | clickable, and **verified in the renderer** — a click opens the conversation it lands on |
  | Everything else | no mouse behaviour at all — a message, the composer and the custom-answer field ignore a click |

  "Wired" and "proven" are not the same claim, and neither is "proven in the
  renderer" and "proven in a terminal": these run OpenTUI's real renderer
  against synthetic pointer events, which is evidence about the code and not
  about any particular terminal's mouse reporting.
