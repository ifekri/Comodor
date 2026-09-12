# The interface

What you see, what you press, and where everything on the screen comes from.

```bash
comodor          # start it
comodor --demo   # the whole interface, offline, no key
```

The interface runs on [Bun](https://bun.sh) — `comodor doctor` says whether it
is there. Without it, `comodor run "..."` does one task with no interface and
`comodor web` serves one to a browser.

For how it is built — the core it drives, the protocol between them, and why
every fact on screen is the core's rather than the screen's — see
[tui-v2.md](tui-v2.md). This page is the short version for the person using
it.

---

## The screen

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

**The header** names the project and the provider and model that are
answering. It is what the core reports, not what a config file says: when
the model changes — from here, from another client, or by the core itself —
the header follows.

**The conversation** carries the tool timeline inside it. Every tool call
sits where it happened, as one row: a mark (`●` running, `✓` done, `×`
failed), the name, a one-line summary, and how long it took. A running tool
shows the last lines of its output; a finished one collapses, and clicking
it opens what the core still holds.

**The workbench** — `Ctrl+B` — is the work outside the conversation: the
task list the agent keeps for itself, and any background agents it has
started, each with its state. On a narrow terminal it opens over the
conversation instead of beside it, and the same key closes it.

**The footer** prints what you can press, from the same list the keys are
read from, and what this session has cost where the provider measures it.

---

## Keys

| Key | Does |
|---|---|
| `Enter` | send what you typed |
| `Tab` / `Shift+Tab` | next / previous mode |
| `Ctrl+K` | the command palette — every action, searchable |
| `Ctrl+B` | open or close the workbench |
| `End` | back to the newest output after scrolling up |
| `PageUp` / `PageDown` | scroll the conversation |
| `Ctrl+R` | send again a message the core refused |
| `Ctrl+C` | stop what it is doing; quit when it is idle |
| `Ctrl+D` | quit |
| `Esc` | close the palette, leave a field, or take a card's safe option |

Every shortcut the footer shows exists; a hint cannot be printed for a key
that is not bound.

---

## Modes

```
ACT    reads, writes and runs commands, asking before it changes things
PLAN   reads and plans; cannot write, run or change anything
ASK    talks it through; no tools at all
```

`Tab` cycles them. The label moves when the core confirms, not when the key
goes down: presses inside one round trip accumulate — three Tabs ask once,
for where the third pointed — and a refused change says so in words rather
than moving the label.

---

## When it asks you something

A permission card or a question form takes the keyboard while it is up, so a
key meant for a decision cannot also send a message.

- **Arrows** move between the choices or the questions; **Enter** sends.
- **Esc** takes the request's own safe option — for a permission that is
  *deny*, for a proposed mode change it is *no change* — and the card says
  which. It never allows anything.
- There is no single-key shortcut for *allow*. Allowing costs one move to the
  choice and one to confirm it, so a key pressed for any other reason cannot
  authorise a command.
- A question that offers a write-your-own row opens a field for it on
  `Space`; `Esc` leaves the field before it cancels the form.

Two things can be waiting at once — two parallel tools may each ask — and
they are shown in the order they arrived, none of them lost.

Mode keys still work while a card is up. The palette does not: a launcher
over a decision would hide the thing that has to be answered.

---

## Following along

A long answer keeps the newest line in view. Scroll up and it stops
following; new output does not pull you back down, and a marker says there is
more below. `End` returns to the live tail, and sending a new message does
the same.

---

## Sessions

`Ctrl+K` → *Open an earlier conversation* lists what the core has kept, and
opens one in place. The same store serves the browser, so a conversation
begun here can be reopened there.

`comodor --resume` reopens the most recent one at startup; `--resume ID`
names one.

---

## Copying text out

Select with the mouse as your terminal allows. The `--theme` and `--ascii`
flags apply to what the commands print — `setup`, `doctor`, `help` — not to
the interface, which draws from its own design tokens.

---

## Right-to-left text

Persian, Arabic and mixed lines are passed to the terminal as written, never
reversed by the program. How well a mixed line is shaped is the terminal's
doing, and the ones that shape it well do so here.

---

## See also

- [tui-v2.md](tui-v2.md) — how the interface is built, and what it can and
  cannot do yet
- [questions.md](questions.md) — the forms the agent puts to you
- [safety.md](safety.md) — what asks, what does not, and why
- [computer.md](computer.md) — letting it use your screen
