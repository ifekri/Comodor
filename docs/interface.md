# The interface

What you see, what you press, and all 29 commands.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

---

## The layout

```
┌────────────────────────────────────────────────────────────────────────┐
│  Comodor                              Anthropic · claude-sonnet-5      │
│  ────────────────────────────────────────────────────────────────────  │
│                                                                        │
│  TASKS                    > fix the failing parser test                │
│  ● read the test          ▸ read_file  tests/test_parser.py     0.1s   │
│  ◐ find the cause         ▸ run_shell  pytest tests/test_pa…    2.3s   │
│  ○ fix it                                                              │
│                           The test expects `parse("")` to raise, but…  │
│                                                                        │
│  ────────────────────────────────────────────────────────────────────  │
│  ▌Type a task, or / for commands                                       │
│                                                                        │
│  act · loop on · 12% of 1M · $0.03      ⏎ send  ^O attach  F3 mode     │
└────────────────────────────────────────────────────────────────────────┘
```

**The sidebar** is the plan, when there is one. `F2` hides it — worth doing on a
narrow terminal.

**The status line** shows the mode, whether it is iterating, how full the
context is, and what this session has cost. The context figure is real: it
follows the model, so switching from a million-token model to a 128k one changes
it immediately.

It works from about 60 columns upward. Below that the sidebar folds away by
itself. `comodor preview 80x24` renders it at any size without starting a
session.

---

## Modes

| Mode | What the agent may do | |
|---|---|---|
| **act** | Everything, asking before writes and commands | the default |
| **plan** | Read only. No writes, no commands, no network | for "what would you do?" |
| **chat** | No tools at all | for a question about code you paste |

`F3` cycles them. `/mode plan` sets one directly.

Plan mode is genuinely read-only — it is enforced at the permission layer, not
by asking the model nicely. A tool with a risk above "safe" is refused before it
runs.

---

## Keys

| | |
|---|---|
| `Enter` | send |
| `Ctrl+J` | newline inside a message |
| `Esc` | stop what it is doing |
| `Ctrl+C` | stop; twice to quit |
| `F1` | help |
| `F2` | the sidebar |
| `F3` | mode |
| `F4` | loop on/off |
| `F5` | the gateway |
| `Ctrl+O` | attach a file |
| `Ctrl+L` | clear the conversation |
| `PgUp` `PgDn` | scroll |
| `Ctrl+↑` `Ctrl+↓` | earlier and later messages |
| `!command` | run a shell command directly, without asking the model |

`!` is worth remembering. `!git status` runs it and shows you the output; the
model never sees the question. Cheaper and faster than asking.

---

## Commands

Type `/` and the list filters as you go.

### Ask it to change what it is doing

| | |
|---|---|
| `/mode [act\|plan\|chat]` | what it is allowed to do |
| `/loop` | keep working until done, or answer once |
| `/model [id]` | choose the model — a list, or name one |
| `/provider [name]` | choose the provider |
| `/gw` | the gateway: route across providers by cost, speed or quality |

### Teach it

| | |
|---|---|
| `/good` | that answer was right |
| `/bad` | that answer was wrong |
| `/teach <text>` | remember this |
| `/memory` | what it has learned |
| `/rules` | the house rules it drew from your code and your edits |
| `/progress` | the evidence that it is improving |
| `/skills` | procedures it follows when the work matches |

`/good` and `/bad` are the cheapest thing you can do for it. See
[How it learns](learning.md).

### Undo and look back

| | |
|---|---|
| `/undo` | restore the last file it changed |
| `/clear` | start a fresh conversation |
| `/resume [id]` | reopen an earlier session |
| `/search <text>` | find something in an earlier conversation |
| `/export [path]` | write this session to a file |

### Let it reach further

| | |
|---|---|
| `/computer [15m\|1h this app\|stop]` | let it use your screen — [guide](computer.md) |
| `/mcp` | MCP servers and their tools — [guide](mcp.md) |
| `/attach <path>` | add a file to the next message |

### Settle it

| | |
|---|---|
| `/settings` | what is configured right now |
| `/approve [writes\|shell\|all]` | stop asking before those |
| `/theme [name]` | ember, midnight, matrix, mono |
| `/save` | write the current settings to your config file |
| `/cost` | tokens, spend, and what the cache saved |
| `/copy [all\|task]` | the last answer, or everything, to the clipboard |
| `/mouse [on\|off]` | mouse tracking, so you can select text yourself |
| `/help` | all of this, inside the interface |
| `/quit` | leave |

**`/save` writes only what you chose.** Not the repository's settings, not a key
you keep in your environment, not a `--model` you passed for one run. See
[Configuration](configuration.md#what-save-writes).

---

## Approvals

When the agent wants to write a file or run a command:

```
  Write  src/parser.py
  ────────────────────────────────────────────
   - def parse(text):
   -     return text.split(",")
   + def parse(text):
   +     if not text:
   +         raise ValueError("nothing to parse")
   +     return text.split(",")

  [a] allow   [A] allow always this session   [d] deny
```

`A` remembers for the session, per kind of thing — allowing writes does not
allow commands.

Denying is not wasted. A refusal is the clearest preference signal the interface
ever collects, and it goes to the learning engine: the agent is less likely to
propose that again.

To stop being asked at all:

```
/approve writes      files, yes; commands, still ask
/approve all         everything
```

Everything is still checkpointed. `/undo` works regardless.

---

## Copying text out

While the mouse is being tracked, a drag belongs to Comodor and the terminal
never sees it — so the usual select-and-copy does not work. Three ways round it:

```
/copy              the last answer
/copy all          the whole conversation
/copy task         the last thing you asked for
/mouse             mouse tracking off, so selection works as usual
```

`/copy` needs nothing installed on Windows or macOS. On Linux it uses
`wl-copy`, `xclip` or `xsel`, whichever is there, and says which is missing if
none is.

Over SSH it falls back to an escape sequence that asks *your* terminal to set
*your* clipboard — so text from an agent on a server lands where you can paste
it, rather than on a server that has no clipboard.

Most terminals also let you select with **Shift** held down, which bypasses
mouse tracking without turning it off.

---

## Who is speaking

Each turn sits on a quiet band — one shade behind what you typed, another
behind the answer:

```
▌ › why does the parser drop the last field?              ← warm

▌   Because split is called with a maxsplit of 2 …        ← neutral
▌
▌   ┌─ python ────────────────────────┐
▌   │ return text.split(',', 2)       │
▌   └─────────────────────────────────┘
```

Deliberately muted. This is behind body text you read for minutes at a time,
and a background with any presence of its own competes with the words. Each
theme has its own pair, a few percent from its background; `mono` has none,
because a theme whose premise is no colour does not want two.

They cost no vertical space — the change of colour is the boundary.

---

## Right-to-left text

Persian, Arabic and Hebrew are set to the right, where their lines begin, with
a font stack that suits them. Mixed paragraphs — an English identifier inside a
Persian sentence — are handled per line rather than per file, which is what
actually happens in a technical conversation.

---

## Themes

```
/theme midnight
```

`ember` (the default, warm amber), `midnight` (cool blue), `matrix` (green),
`mono` (no colour at all).

`--ascii` swaps the box-drawing characters for ASCII, for terminals without
them. `NO_COLOR` in your environment is honoured.

---

## See also

- [From the terminal](cli.md) — the same power without the interface
- [What the agent can do](tools.md) — the tools behind those `▸` rows
- [Safety](safety.md) — what the approval prompts are protecting
