# How it learns

Most agents forget the moment a session ends. This one watches what you change
about its output and keeps it.

---

## The idea

Praise is cheap and corrections are expensive, so corrections are what it learns
from.

When you edit a file it wrote, or tell it plainly that it was wrong, that
becomes a **lesson**: a short rule with a confidence that rises each time it
holds and decays when it goes unused. Lessons are recalled when the situation
looks similar, and injected into that turn — never into the system prompt, which
would cost the prompt cache.

Nothing leaves your machine. The brain is a SQLite file under your config
directory.

---

## The two lanes

### Reflex — free, immediate, always on

No model call, no tokens, no delay.

- **Corrections.** You edit `"` to `'` in a file it wrote. That is a diff, and a
  diff is a fact.
- **Rules.** It reads your existing code once, at the start, and draws
  conventions from it — indentation, quote style, how tests are named.
- **Announcements.** When a rule is applied, it says so, in one line. A rule you
  cannot see is a rule you cannot correct.
- **Prefetch.** Recall starts while you are still typing.

This lane is on even when reflection is switched off, because it costs nothing.

### Reflection — a model call, after a task

At the end of a task it looks at what happened and writes down what it should
remember. This one costs a call. Use a cheaper model for it if you like:

```json
{ "learning": { "reflect_model": "claude-haiku-4-5" } }
```

Or switch it off, keeping Reflex:

```json
{ "learning": { "reflect": false } }
```

---

## Teaching it, deliberately

| | |
|---|---|
| `/good` | that answer was right |
| `/bad` | that answer was wrong |
| `/teach we use pytest, never unittest` | remember this |

`/good` and `/bad` take one keystroke and are the cheapest thing you can do for
it.

Denying a permission prompt teaches it too. A refusal is the clearest preference
signal the interface collects, and it is treated as one.

---

## Seeing what it knows

```
/memory
```

A searchable list — each lesson with what triggers it, what it says, its kind
and its current confidence:

```
┌─  Memory (23)  ────────────────────────────────────────────────────┐
│ ›  #41 writing Python strings                                      │
│      Use single quotes for string literals.  [style 91%]           │
│    #38 adding a test                                               │
│      Tests go in tests/, mirroring the src layout.  [layout 84%]   │
│    #29 adding a dependency                                         │
│      Ask before adding one; this project has exactly one.  [78%]   │
│    #12 parsing empty input                                         │
│      Raise, do not return an empty list.  [behaviour 62%]          │
└────────────────────────────────────────────────────────────────────┘
  ↑↓ move   enter open   type filter   esc close
```

`/memory <text>` searches. Opening one lets you pin it, so it stops decaying, or
delete it if it was wrong.

```
/rules
```

The house rules it drew from your code rather than from you telling it.

---

## Seeing whether it is working

```
/progress
```

```
◈ Corrections per task down 100% since the first tasks in this project.

metric                trend                       now  vs first
Steps per task        ▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇█▁▃▅▇    6.1      ↑10%
Corrections per task  ████████▅▅▅▅▅▅▅▅▁▁▁▁▁▁▁▁    0.0     ↓100%
Approvals asked       ▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅    2.0         —
Tokens per task       ▁▁▁▂▂▂▃▃▃▄▄▄▅▅▅▆▆▆▇▇▇███  12.0K      ↑40%
First-try success     ▁██████▁██████▁██████▁██    86%         —

brain    7 rules · 812 lessons · 24 corrections learned from
history  24 tasks over 8 days
success  83% overall
```

**The line at the top is the one that matters.** If corrections per task are not
falling, the learning is not working — and the panel leads with that either way,
rather than burying it under activity. Everything else in the table is effort;
that one is outcome.

---

## Recall, and why it is not in the system prompt

Recalled lessons ride on the turn, as part of the user message, not in the
system prompt.

This is a cost decision. Prompt caching only works on a byte-identical prefix,
and the system prompt is the prefix. Putting anything query-dependent in there
invalidates the cache on every single turn. Moving recall onto the turn took
measured cache hit rates from 72% to 87%. See [Cost](cost.md).

---

## Words it learns from you

It also learns which of *your* words go together, from your own finished tasks
— that "the parser" and "tokenise" belong to the same corner of your codebase.
This costs no tokens and no model call; it is counting.

That is what lets a lesson recorded about "the tokeniser" surface when you ask
about "the lexer".

```json
{ "learning": { "associative": true } }
```

---

## Scope

```json
{ "learning": { "share_scope": "project" } }
```

`project` keeps lessons to the repository they were learned in — the right
default, since a convention in one codebase is wrong in another. `global` shares
them everywhere.

---

## Forgetting

A lesson that goes unused decays. `half_life_days` (45 by default) sets how
fast, and `min_confidence` (0.15) is the floor below which it stops being
recalled.

This matters: a codebase changes its mind, and an agent that holds a two-year-old
convention with total confidence is worse than one that forgot.

---

## Switching it off

```json
{ "learning": { "enabled": false } }
```

Everything still works. It just starts every session as a stranger.

---

## Where it lives

```
~/.comodor/brain.db
```

SQLite. Yours. `comodor uninstall` removes it and says how much it was.

---

## See also

- [Skills](skills.md) — procedures you write, rather than lessons it infers
- [Cost](cost.md) — why recall is on the turn and not in the prefix
