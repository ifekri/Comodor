# Skills

A skill is a written procedure the agent follows when the work calls for it.

Not a prompt you paste each time — a file it loads by itself when the situation
matches.

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

---

## See also

- [How it learns](learning.md) — lessons it infers, rather than procedures you write
- [What the agent can do](tools.md) — the tools a skill tells it how to use
