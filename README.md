# Comodor

**It learns the way you correct it.** — [comodor.ai](https://comodor.ai)

A terminal coding agent that reads and edits your files, runs your tests,
searches the web, and works through multi-step tasks on its own — inside a Rich
interface that reflows cleanly from a 40-column SSH window to an ultrawide
monitor.

What makes it different is **Reflex**: Comodor watches what you *do* — the code
you rewrite, the edits you undo, the commands you refuse — and turns that into
rules, with no model call and no perceptible delay. Fix something once, and the
next answer already obeys.

```
› create defaults.py with 6 string constants
◈ learned: Use single quotes for string literals.   (/rules forget 1 to undo)
```

That is a real transcript. The turn before it, Comodor wrote double quotes and
the file was edited by hand. Nobody told it anything.

```
┌─ History ──────────────┐ ┌─ Chat ───────────────────────────────────────────────┐
│ TASKS 2/4 ──────────── │ │ › add a health endpoint and a test for it            │
│ ● read the app factory │ │ ◈ recalled 3 lessons · skill: review                 │
│ ● add the /health rou… │ │                                                      │
│ ◐ write the test       │ │ I'll add the route, then a test.                     │
│ ○ run the suite        │ │                                                      │
│                        │ │ ⚙ edit src/app.py  0.2s                              │
│                        │ │   + @app.get('/health')                              │
│                        │ │ ⚙ run: pytest -q  3.4s                               │
│                        │ │   4 passed in 0.42s                                  │
└────────────────────────┘ └──────────────────────────────────────────────────────┘
┌────────────────────────┐ ┌──────────────────────────────────────────┐
│ Context:1M GW: Disable │ │ Prompt Here ...                          │    SEND
│ Mode : Act Loop : On   │ │ ──────────────────────────────────────── │
│ ███░░░░░░░░░░░░░░░░░░░ │ │ Provider : Openrouter | Model : …        │   ATTACH
│ 143K used $0.041  ◈7   │ │                                          │
│ ┌────────────────────┐ │ │                                          │    MODE
│ │      Settings      │ │ └──────────────────────────────────────────┘
└────────────────────────┘
```

---

## Install

**macOS / Linux**

```bash
curl -fsSL https://comodor.ai/install.sh | sh
```

**Windows**

```powershell
irm https://comodor.ai/install.ps1 | iex
```

**The installer finishes the job.** It uses `uv` or `pipx` if you have them,
builds an isolated environment if you have a working Python, and downloads what
it needs if you have neither — then puts `comodor` on your PATH and runs it once
to prove it works. It will not leave you with a half-install or a wall of
Python packaging errors.

In particular it handles the case that stops most one-line installers: a
distribution or tool-managed Python that refuses `pip install` under
[PEP 668](https://peps.python.org/pep-0668/). It builds an environment instead,
and it never passes `--break-system-packages`.

If you would rather run one yourself:

```bash
uv tool install comodor          # fastest; fetches a Python if you have none
pipx install comodor             # isolated and on your PATH
pip install comodor              # into the current environment
```

Requires Python 3.11 or newer — or nothing at all, since the installer can fetch
one. **`rich` is the only dependency**: the HTTP client, the streaming reader
and the configuration loader are all part of the package.

## First run

Type `comodor`. It asks four questions and writes the answers down. There is
nothing to prepare first: no dotfile to copy, no environment variable to export,
no documentation to read before your first task.

```
 1/4  Which model provider?      18 to choose from, numbered
 2/4  API key                    masked, with a link to the page that issues one
 3/4  Which model?               read live from the provider you just chose
 4/4  How much should it ask?    ask first · writes allowed · full autonomy
```

That is the whole setup, and you are not asked again. Press Enter at any
question to take the sensible default; enter something invalid and it asks
again rather than quietly choosing for you.

To change your mind later: `/settings` inside the interface, or `comodor setup`
to run the questions again.

No key yet? `comodor --demo` runs the entire interface against a scripted
offline provider — every panel, every command, no account required.

## Providers

Pick one during setup and switch whenever you like. Comodor speaks the
OpenAI-compatible protocol and the native Anthropic Messages API, so the list is
open-ended rather than a fixed integration for each.

| | |
|---|---|
| **Hosted** | OpenRouter · Anthropic · OpenAI · Google Gemini · DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot (Kimi) · Z.AI (GLM) · Qwen · Together · Fireworks · Xiaomi MiMo |
| **Local** | Ollama · LM Studio — no key, no cost, no network |
| **Anything else** | any OpenAI-compatible endpoint; you supply the URL |

Each entry knows its own endpoint, its model list and where to get a key, so
choosing one is a single number. Switch with `/provider` in the interface, with
`comodor setup`, or per-run with `comodor --provider groq --model …`.

## Configuration

One JSON file, written by setup and safe to edit by hand:

| | |
|---|---|
| Linux / macOS | `~/.comodor/config.json` |
| Windows | `%APPDATA%\Comodor\config.json` |

```json
{
  "version": 1,
  "provider": "deepseek",
  "model": "deepseek-reasoner",
  "agent":    { "mode": "act", "loop": true, "max_steps": 24, "max_cost_usd": 2.0 },
  "learning": { "enabled": true, "corrections": true, "announce": true },
  "skills":   { "enabled": true, "top_k": 2 },
  "safety":   { "auto_approve_writes": false, "workspace_only": true },
  "providers": {
    "deepseek": { "configured": true, "api_key": "sk-…", "model": "deepseek-reasoner" }
  }
}
```

Setup writes every section, defaults included, so the file doubles as the
reference for what can be changed. It is written atomically and, on Unix, with
owner-only permissions, because it holds your key.

**Per project.** A `.comodor/config.json` in a repository is merged over your
personal file — pin the mode, the step budget or a house theme for everyone
working on it. Keep keys out of it; that file is meant to be committed.

**For CI.** Provider environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY`, …) are still honoured and take precedence, so a build
agent needs no config file at all. `COMODOR_HOME` relocates everything.

## Use

```bash
comodor                                     # the interface
comodor --demo                              # offline walkthrough, no key needed
comodor run "fix the failing test" --yes    # one task, headless, for scripts
comodor run "audit this module" --json      # machine-readable result
comodor setup                               # change provider, model or approvals
comodor doctor                              # check everything; --fix repairs it
comodor mcp catalogue                       # MCP servers Comodor can set up
```

### Keys

| Key | Action |
|---|---|
| `Enter` | send · `Ctrl+J` newline |
| `Esc` | stop the agent |
| `F1` … `F5` | help · sidebar · mode · loop · gateway |
| `Ctrl+O` | attach a file |
| `PgUp` / `PgDn` | scroll the transcript |
| `Ctrl+C` | stop; twice to quit |

`!command` runs a shell command directly. `@path` attaches a file to your
message. Buttons and the sidebar are clickable where the terminal supports it.

### Commands

`/help` `/model` `/provider` `/mode` `/loop` `/gw` `/rules` `/progress` `/memory`
`/teach` `/skills` `/search` `/mcp` `/good` `/bad` `/undo` `/cost` `/export`
`/theme` `/settings` `/approve` `/save` `/attach` `/clear` `/resume` `/quit`

## The three switches

**Mode** decides what the agent may touch.

- **Act** — the full tool set; it can change your project.
- **Plan** — read-only. Write tools are not merely blocked, they are never shown
  to the model, so you get a plan rather than a thwarted attempt to edit.
- **Chat** — no tools at all.

**Loop** decides whether it keeps going. On, the agent iterates until the task is
done or a guard trips (steps, wall clock, spend). Off, it answers once.

**GW** is the model gateway. Disabled — the default — every request goes to the
provider you picked, so what the status bar says is what answered. Enabled, it
ranks healthy providers by cost, speed or quality and fails over when a call
breaks. A stream that has already produced output is never retried elsewhere:
duplicating half an answer is worse than reporting the failure.

## Skills

A skill is a Markdown file that says how *you* want a kind of work done — the
review checklist your team actually uses, your commit-message conventions, the
deployment steps nobody remembers. Comodor loads one only when the request calls
for it, so twenty skills cost no more per turn than one.

| | |
|---|---|
| `~/.comodor/skills/` | yours, in every project |
| `.comodor/skills/` | this project's, committed with it — wins on a name clash |

A skill is either a single Markdown file, or a folder holding a `SKILL.md` — the
[Agent Skills](https://agentskills.io) open format. That means a skill written
for another agent runs here unchanged, and one you write here runs there. The
folder form can also bundle files:

```
~/.comodor/skills/pdf-processing/
├─ SKILL.md              the instructions, loaded when the skill matches
├─ references/           documents read only when the task calls for one
├─ scripts/              code the agent can run
└─ assets/               templates and data
```

Bundled files are **named in the prompt, never inlined**. A skill can carry a
thousand-line API reference and cost nothing until the one turn that needs it,
at which point the agent asks for it by name. Nothing outside a loaded skill's
own folder is reachable that way.

```markdown
---
name: review
description: Review a change for correctness before it is committed
triggers: [review, diff, pull request, pr]
tools: [read_file, grep, glob, run_shell]
---

Read the whole change before saying anything about it.

Look for, in this order:

1. **Correctness** — off-by-one errors, unhandled failure paths, a condition
   that is inverted.
2. **Silent failures** — an exception swallowed, an error return ignored.
3. **Tests that assert the implementation** rather than the behaviour.

Report only what would genuinely block a merge. A review that lists twenty
nitpicks buries the one thing that mattered.
```

| field | |
|---|---|
| `name` | required; lowercase letters, digits and single hyphens |
| `description` | required; what the skill does **and when to use it** — this is what gets matched against your request |
| `triggers` | extra words that should select it |
| `always` | `true` to apply it to every turn — house rules, style guides |
| `enabled` | `false` to keep the file but stop using it |
| `license` `compatibility` `metadata` | optional, from the open format |

A skill that departs from the format still loads — it is your file, and Comodor
can run it perfectly well. What `/skills` tells you is where another agent would
disagree, before you have shared it with anyone.

The description and triggers are matched against what you asked; nothing
relevant means nothing injected, and the transcript names any skill that was
used. `/skills` lists what is loaded and where from, `/skills reload` re-reads
the folder after an edit, and a file with a broken header is reported by name
rather than silently ignored.

Three worked examples are written into your skills folder the first time
Comodor runs, so there is something to read before there is something to write.

### Skills it drafts for you

Comodor also notices when it has solved the same shape of problem several times.
Once a procedure has worked at least three times, `/skills draft` offers it back
as a finished `SKILL.md` — with the evidence attached, and the exact text it
would write:

```
### add-a-rest-endpoint
worked 4 of 5 times

/skills adopt add-a-rest-endpoint  to keep it.
```

**Nothing is written until you say so.** A skill shapes every future answer it
matches, so an agent quietly authoring its own instructions would be changing
its behaviour in a way you never agreed to and would struggle to find. What it
writes is an ordinary file in your folder, marked `origin: learned`, and yours
to edit or delete.

## When something is wrong: `comodor doctor`

```
Checks
  ok    config file     ~/.comodor/config.json
  ok    provider        Anthropic · claude-sonnet-4-5
  warn  session search  the index is corrupt
              → delete it — it is a cache built from the transcripts
  ok    skills          4 loaded
  ok    mcp servers     2 enabled and reachable

1 of these can be repaired automatically: comodor doctor --fix
```

`--fix` applies them and re-checks, so what it prints afterwards is the state
now rather than the state that prompted the repair.

**It repairs what it can rebuild, and refuses the rest.** A corrupt search
index is deleted, because it is a cache derived from your transcripts. A
corrupt *config* is reported and left alone, because it holds your API key —
the one thing on the machine that cannot be regenerated. Same for the brain,
and for a skill file you wrote: doctor names the file and the first problem
rather than guessing at what you meant.

Every repair is safe to run twice.

## Tools from elsewhere: MCP

Comodor's own tools are built in and audited. The
[Model Context Protocol](https://modelcontextprotocol.io) is the other
arrangement — a separate program offering capabilities Comodor never has to
implement: a browser, a database, an issue tracker.

```bash
comodor mcp catalogue                    # twelve servers, ready to set up
comodor mcp add filesystem --path ~/work
comodor mcp add github --env GITHUB_PERSONAL_ACCESS_TOKEN=…
comodor mcp list                         # what you have, and what is on
comodor mcp test github                  # start it and list what it offers
```

| | |
|---|---|
| **Files and code** | Filesystem · Git · GitHub |
| **Data** | SQLite · PostgreSQL |
| **The web** | Fetch · Brave Search · Browser (Puppeteer) |
| **Other** | Memory (knowledge graph) · Sequential thinking · Slack · Time |

Anything else in the ecosystem works too — the catalogue is a shortcut, not a
limit:

```bash
comodor mcp custom my-server uvx my-mcp-package --flag value
```

Four things worth knowing:

- **Nothing starts until it is used.** Servers connect the first time a tool
  list is asked for, so one you never use costs nothing and a slow one does not
  delay startup.
- **They go through the same permission gate as everything else.** An MCP tool
  that says it writes, deletes or posts is treated as a write; one that
  mentions the network is treated like a shell command. The description is all
  there is to judge by, so it is read generously — an unnecessary prompt costs
  a keypress, the opposite runs somebody else's code unannounced.
- **A server that will not start is dropped, once, with the reason.** Its own
  stderr is what gets shown, because you did not write it and that is the only
  thing that explains it. The rest of the session carries on.
- **What each one can reach is stated before you enable it.** "Only the
  directory you name" and "everything your token can reach" are different kinds
  of permission, and the difference belongs in front of the person deciding.

`/mcp` inside the interface shows what is connected and every tool it brought.

## Reflex — a two-speed brain

Skills are what you write down. Reflex is what you never got round to writing
down. Most agents remember what you *tell* them; Comodor learns from what you
*fix*.

**Reflex is the fast lane.** Deterministic, model-free, sub-millisecond, always
on. It reads five signals, all of them free because you produce them just by
working:

| signal | what it means |
|---|---|
| you rewrite a file the agent wrote | the diff *is* the preference — quotes, indentation, annotations, verbosity |
| you `/undo` a change | an outright rejection |
| you deny a permission | one command this user does not want run |
| you ask the same thing twice | the answer missed |
| a tool fails the same way twice | a pitfall in this environment, verified |

Each becomes a **rule** with its evidence attached — not "I think you prefer
single quotes" but `31 of 34 literals` — and how much evidence a rule needs
depends on where it came from. Watching your codebase is weak proof, so it takes
four agreeing observations. You editing the agent's output is a deliberate
statement, so it takes two. Telling it outright takes one.

Detection runs at the *start* of a turn, not the end. That is what makes the
correction land immediately rather than a task later.

**Reflection is the slow lane** — an LLM pass that distils prose lessons from a
finished episode. It runs in the background and it is optional. Switch it off,
work offline, use a cheap model: Reflex keeps learning either way, because it
never needed a model at all.

Everything is inspectable and reversible:

```
/rules              browse rules with their evidence; pin, disable or drop one
/rules teach Never add comments unless asked.
/rules export       writes .comodor/house-rules.md for the team to commit
/memory             the distilled lessons, same controls
/teach  /good  /bad
```

## Everything you have ever asked

Rules are what Comodor generalises. Transcripts are what actually happened, and
they are searchable:

```
/search cursor pagination

  you · 12 Apr · 20260412-090000
  > add cursor pagination to the results endpoint
```

The agent can search them too, and does so on its own when you refer to earlier
work — "like we did last time", "that bug from last week". Nothing from history
enters the context until it decides a question needs it, so four hundred stored
sessions cost nothing on the turns that do not.

The index is a cache built from the transcripts already on disk. Delete
`search.db` and the next search rebuilds it; delete a session and it leaves
search with it. There is no second copy of anything to keep in step.

## Proof, not claims: `/progress`

"Gets better over time" is what every tool says. Comodor shows the numbers.

```
◈ Steps per task down 40% since the first tasks in this project.

metric                trend                            now  vs first
Steps per task        ▇██▇▇▆▇▅▅▅▅▆▄▅▄▅▄▄▂▄▂▁▂▂▂▁▁▁▁▁   5.3      ↓40%
Corrections per task  ████▆▇▆█▆▆▆▇▆▆▅▃▃▅▆▆▅▃▆▃▆▃▂▁▁▃   0.9      ↓65%
Approvals asked       █▇▇▇▇▇▇▇▇▇▅▅▅▅▅▅▅▅▅▅▃▃▃▃▃▃▃▃▃▁   0.8      ↓73%
Tokens per task       █▇████▇▇▆▆▆▆▆▆▅▅▄▄▅▃▃▄▄▃▂▂▂▂▂▁  6.4K      ↓29%
First-try success     ██▁███████████████████████████  100%      ↑8pp

brain  7 rules · 23 lessons · 70 corrections learned from
history  40 tasks over 2 days
```

The panel is built to be honest, which is what makes it worth showing: with too
little history it says so, a metric that has not moved is reported as unchanged,
a rate moves in percentage points rather than as a percentage of a percentage,
and a fall from 0.4 to 0 is never allowed to headline as "down 100%".

## Speed

Memory sits between pressing Enter and the first token, so it is measured and
budgeted rather than assumed. On an ordinary laptop, against a deliberately
worst-case corpus:

| operation | corpus | time |
|---|---|---|
| recall | 3,000 lessons | 0.38 ms |
| recall | 20,000 lessons | 0.38 ms — flat |
| deduplication | 3,000 lessons | 0.25 ms |
| pinned-rule lookup | 20,000 lessons | 0.10 ms |
| recording reinforcement | — | 0.001 ms |

Three things get it there. A **RAM mirror** holds every lesson with its tokens
pre-computed and an inverted index over them, so a lookup touches only the
documents sharing a word with the query — and the candidate set is capped, which
is why the cost stops growing with the corpus. A **background writer** batches
commits, so nothing user-facing ever waits on the disk. And **speculative
recall** runs the whole ranking while you are still typing, so on the turn
itself it costs nothing at all.

`tests/test_performance.py` enforces these as ceilings. A change that makes
memory slow fails the suite.

## Safety

- **Risk tiers.** Reads never prompt. Writes show a coloured diff and ask.
  Commands and network calls always ask.
- **Checkpoints.** Files are snapshotted before any change; `/undo` restores them.
- **A deny list** no prompt can talk past, for the handful of commands that are
  never acceptable.
- **Workspace confinement.** Writes outside the project are refused by default.
- **Redaction.** API keys and tokens are stripped from logs, transcripts and
  exports.
- `--yes` exists for CI. Headless runs refuse to change anything without it.

## Any terminal, any size

The layout is recomputed every frame from the terminal size, so resizing just
works.

| Width | Layout |
|---|---|
| `< 60` | one column; sidebar on `F2` |
| `60–99` | narrow sidebar, compact status |
| `100–139` | the reference design |
| `≥ 140` | wide sidebar, roomier transcript |

Below 40×12 it says so plainly rather than drawing a corrupted screen. `--ascii`
drops box-drawing glyphs for terminals that cannot render them, and a monochrome
terminal gets a monochrome theme automatically.

## Development

```bash
git clone https://github.com/ifekri/comodor && cd comodor
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest -q
```

```
src/comodor/
├─ net/         zero-dependency HTTP client + SSE reader
├─ providers/   OpenAI-compatible, Anthropic, offline fake, and the gateway
├─ agent/       the reason/act loop, context budgeting, prompts
├─ tools/       files, search, shell, python, web, task list
├─ safety/      permissions, checkpoints, redaction
├─ mcp/         the Model Context Protocol client, and a server catalogue
├─ learning/    the brain: hot index, async writer, signals, rules, progress
├─ skills/      authored skills: the open format, matching, drafts
├─ session/     persistence, export, and full-text search over transcripts
└─ ui/          layout, theme, widgets, raw input, the app loop
```

The suite runs the whole agent against a scripted provider — no network, no
spend — and renders the interface at a range of terminal sizes to prove the
responsive layout holds.

```bash
comodor preview 120x34            # render one frame at a fixed size
comodor preview 60x20 --svg out.svg
```

## Contributing

Bug reports, especially about terminals — please include `comodor doctor`.
[CONTRIBUTING.md](CONTRIBUTING.md) covers the setup and the two conventions
that get a change merged quickly. Security issues go
[here](SECURITY.md), privately.

[CHANGELOG.md](CHANGELOG.md) records what changed in each release.

## Licence

MIT — see [LICENSE](LICENSE).
