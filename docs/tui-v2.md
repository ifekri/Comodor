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

`Ctrl+C` is context-sensitive on purpose. Killing the client mid-turn would
leave a core running with nobody attached.

---

## Questions

`question.requested` is a protocol primitive, not a numbered list in prose. A
card renders it, `↑↓` moves, `space` chooses, `enter` confirms, `esc` cancels,
and the answer travels back as `question.answer` naming the question id.

The selection logic is in `@comodor/questions` and has no rendering in it, so
a browser form and a terminal card agree about what is selected because there
is one reducer.

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

## What is not here yet

- Sessions are not resumed; `session.get` exists and nothing calls it on
  reconnect.
- `tool.output` is carried and not drawn.
- No sidebar, no scroll-back search, no file attachment, no slash commands.
- Mouse support is not wired, though OpenTUI offers it.
- The renderer is not exercised by an automated test on this machine, because
  Bun is not installed here. The state reducer, the command registry, the
  question logic and the client are all tested under Node; what is untested is
  the drawing.
