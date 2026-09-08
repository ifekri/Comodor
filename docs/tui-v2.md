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
- **Permission prompts are carried but not drawn.** The protocol delivers
  them, the projection holds a pending one across a snapshot, and nothing
  here renders a card for it yet — so a permission request waits for the
  core's timeout. This client still announces the `permissions` capability;
  drawing the card is the next piece of work, and until then the honest
  description is that the request is not lost, only unanswered.
- Sessions are resumed when the client starts with a session id; automatic
  reconnection after a lost core is not built yet.
- No sidebar, no scroll-back search, no file attachment, no slash commands.
- Mouse support is partial, and the three states are worth telling apart:

  | | |
  |---|---|
  | Mode segments | clickable, and **verified in the renderer** — each of ACT, PLAN and ASK, plus that a refused change leaves the label alone |
  | Wheel over the conversation | scrolls, pauses follow, raises the marker — **verified in the renderer** |
  | Palette rows | clickable, **not renderer-verified** |
  | Question option rows | clickable, **not renderer-verified** |
  | Everything else | no mouse behaviour at all — a message, a tool row, the composer and the custom-answer field ignore a click |

  "Wired" and "proven" are not the same claim. The two unverified handlers go
  through the same code paths their keyboard equivalents do, which is a reason
  to expect them to work and not evidence that they do.
