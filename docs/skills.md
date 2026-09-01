# Skills

A skill is a written procedure the agent follows when the work calls for it.

Not a prompt you paste each time — a file it loads by itself when the situation
matches.

---

## Getting some

`comodor setup` offers the library once, at the end. Move with the arrow keys,
press **space** to tick as many as you want, and **enter** installs all of
them. Nothing is ticked to begin with, and enter with nothing ticked takes
none — you are never given something you did not ask for.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   tab more   esc cancel
```

**One line per skill**, so the whole list fits one screen however long the
library gets, and the window follows the arrow rather than lagging behind it.
Some of these descriptions run to a paragraph — **tab** opens the full one for
whatever the arrow is on, in the same frame, and tab again closes it.

Typing filters the list, which is faster than scrolling once there are more
than a handful. Ticks are kept while you filter, so you can narrow the list,
tick something, clear the filter and tick something else.

Without a terminal it can take over — a pipe, a script, `curl | sh` — the same
question is asked as a numbered list, a page at a time:

| | |
|---|---|
| `1,3` or `1 3` | take these |
| `m` / `b` | next page, previous page |
| `/word` | show only what matches |
| `?7` | read the whole description of number 7 |
| enter | done |

The numbers are absolute: number 92 is the ninety-second skill whichever page
or search you are looking at, so a number you noted stays the number you type.

---

## Using one

```bash
comodor skills browse            # what is available
comodor skills add review        # install it
comodor skills list              # what you have
```

```
/skills                          # the same, in the interface
```

From then on, when you ask for something a skill covers, it is loaded and the
agent follows it. You are told when that happens:

```
  ▸ skill: review — Review a change for correctness before it is committed
```

A skill you cannot see being applied is a skill you cannot correct.

---

## Writing one

A folder with a `SKILL.md` in it:

```
~/.comodor/skills/our-tests/SKILL.md
```

```markdown
---
name: our-tests
description: How tests are written and run in this project.
---

# Tests in this project

- pytest, never unittest.
- One file per module, mirroring `src/`.
- Name the test after the behaviour, not the function:
  `test_an_empty_input_raises`, not `test_parse_2`.
- Never mock what you can construct.

## Running them

    uv run pytest -x -q

Not `python -m pytest` — the project needs the venv's own interpreter.
```

The **description** is what matters most. It is what Comodor matches against
your request to decide whether to load the skill at all, so write it as the
situation, not as a title.

Restart, or `/skills`, and it is there.

### Bundling files

A skill can carry files beside `SKILL.md`:

```
~/.comodor/skills/our-tests/
  SKILL.md
  references/
    fixtures.md
    conventions.md
```

`SKILL.md` points at them; the agent reads one only when it needs it. That keeps
the skill itself short — which matters, because the skill is loaded into the
turn and a long one costs tokens whether or not the detail was needed.

---

## Per project

```
./.comodor/skills/<name>/SKILL.md
```

Committed with the repository, so everyone working on it gets the same
procedures. A project's skills are loaded alongside yours.

---

## The budget

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000
  }
}
```

`top_k` is how many may be loaded for one turn; `max_tokens` is the ceiling on
what they may cost together. A skill too large to fit is skipped, and you are
told which — silence here was a real bug once, where an oversized skill quietly
displaced smaller ones.

---

## Managing them

```bash
comodor skills add review taste output    # several at once
comodor skills update                     # refresh installed ones
comodor skills remove review
comodor skills list                       # with versions
```

## When the agent writes one

The agent can save a procedure that just worked as a skill of yours
(`skill_manage`): it proposes it in conversation first, and nothing is
written until you agree. In the interface, `/skills draft` shows what it
has learned and wants to keep, and `/skills adopt NAME` saves a draft.

Every change the agent makes is recorded in a ledger, so anything can be
put back exactly as it was:

```bash
comodor skills rollback --list            # the history
comodor skills rollback --id <block>      # put one version back
```

New text is also scanned for prompt-injection patterns at write time —
a hit is reported in the conversation as a note for you; nothing is
blocked automatically.

---

## See also

## See also

- [How it learns](learning.md) — lessons it infers, rather than procedures you write
- [What the agent can do](tools.md) — the tools a skill tells it how to use
