# The Comodor benchmark

Thirteen coding tasks in thirteen small repositories, judged by programs.

It exists because the test suite answers "are the parts wired together" and
nothing answered "is it any good at the job". Without that second number, every
change to the system prompt, the tool descriptions or the agent loop is a guess
with a story attached.

## Running it

```
python -m bench --provider xiaomi --model mimo-v2.5-pro
python -m bench --provider anthropic --model claude-sonnet-5 --tries 3
python -m bench --only fix- --tries 1          # one category, one attempt
python -m bench --dry-run                      # list the suite, run nothing
```

The API key comes from the environment, or from a `.env` beside the source.
Nothing reads your Comodor config: every attempt gets its own `COMODOR_HOME`,
its own copy of the task's repository, and the learning engine switched off.

Results land in `results/` as JSON and as a Markdown table, named for the model
and the date.

## What a task is

```
tasks/fix-off-by-one/
  task.md      the prompt, verbatim — nothing else is sent
  repo/        the starting state, copied fresh for every attempt
  check.py     the judge, and the step and time budget
  hidden/      tests added after the run, for `feature` tasks only
```

## Categories

| | What it measures |
| --- | --- |
| `fix` | make a failing test pass, without changing the test |
| `feature` | build to a written spec, judged by tests held back |
| `find` | search and read — run in plan mode, so it cannot write |
| `refactor` | change across files, keeping behaviour and leaving nothing behind |
| `careful` | does *not* do the wrong thing |

`careful` is the one nobody else measures and the reason this suite is worth
having. It contains a request with a real ambiguity in it — passed only by
asking *before* the first edit, not after; a fix in one file with the identical
bug sitting in the file next door, which must be left alone; and a task that
cannot be completed honestly, where the only passing answer says so instead of
inventing the data that would make the suite green.

## How the numbers are reported

Every task is run three times and reported as a rate — `3/3`, `1/3` — never as
a single boolean. Agents are not deterministic and a single run presented as
"it passes" is a made-up number with a real one's face on.

Every published result names the model, the provider, the date and the machine.
Nothing is estimated, projected or rounded up from a partial run.

## Adding a task

Every bug found in Comodor from now on becomes one. That is the only way the
suite is meant to grow — a task written to make a number look good is a task
that measures nothing.

A new task needs the four files above, and two things must be true before it
counts: a reference solution passes it, and `tests/test_bench.py` still passes
— it checks that every `fix` task starts red, every `refactor` task starts
green, every `feature` task's hidden tests fail before the work, and that each
judge refuses the specific shortcut its task invites.
