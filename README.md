# Comodor

**A coding agent that lives in your terminal — and learns the way you correct it.**

[![PyPI](https://img.shields.io/pypi/v/comodor?label=pypi&color=c4441e)](https://pypi.org/project/comodor/)
[![Python](https://img.shields.io/pypi/pyversions/comodor)](https://pypi.org/project/comodor/)
[![CI](https://github.com/ifekri/Comodor/actions/workflows/ci.yml/badge.svg)](https://github.com/ifekri/Comodor/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/pypi/l/comodor?color=555)](LICENSE)

[comodor.ai](https://comodor.ai) · [Install](#install) · [What it can do](#what-it-can-do)

---

## What this is

Comodor is a program you run in your terminal and talk to in plain language.
You describe a job — *fix the failing test*, *add a health endpoint*, *work out
why the deploy broke* — and it does the work: reads your files, writes changes,
runs your tests, searches the web, and keeps going until the job is done or it
needs you.

It asks before it changes anything, shows you exactly what it is about to do,
and can undo it.

What makes it different from every other tool of this kind is what happens
afterwards. **When you fix something it wrote, it notices, and it does not make
that mistake again.** Not because you configured it. Because it watched.

```
› create defaults.py with 6 string constants
⚙ write src/defaults.py — 6 constants

  … you open the file and change "30s" to '30s' …

› now add the timeout constants
◈ learned: Use single quotes for string literals.   (31 of 34 literals)
⚙ write src/defaults.py — '30s', '5m'
```

That is a real transcript. Nobody told it anything.

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
```

---

## Install

**macOS and Linux**

```bash
curl -fsSL https://comodor.ai/install.sh | sh
```

**Windows**

```powershell
irm https://comodor.ai/install.ps1 | iex
```

**The installer finishes the job.** It finds a Python or fetches one, builds an
isolated environment so nothing on your machine is disturbed, puts `comodor` on
your PATH, and runs it once to prove it worked. You do not need Python
installed, and you will not be handed a wall of packaging errors.

Already have a package manager? Any of these work:

```bash
uv tool install comodor
pipx install comodor
pip install comodor
```

Then type `comodor`.

---

## First run

Four questions, once. Nothing to create beforehand — no config file, no
environment variable, no documentation to read first.

```
 ✓ provider  Ollama (local)
 ✓ api key   not needed

 3/4 Which model?
┌─  Models  ──────────────────────────────────────────────┐
│ ›  qwen2.5-coder:14b  recommended                       │
│    llama3.3                                             │
│    deepseek-r1:14b                                      │
└─────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   type filter   esc cancel
```

One question per screen, answered with the arrow keys. Where a provider offers
sixty models, typing filters them. Piped or scripted, the same questions arrive
as a numbered list, so it can still be automated.

Then it shows you the directory it is about to work in and asks once — the
project root is found by walking upwards, and the answer is occasionally a
surprise worth seeing before anything reads it. Approved folders are
remembered.

You are not asked again. Change your mind later with `comodor setup`.

**No API key?** `comodor --demo` runs the whole interface offline — every
panel, every command, no account required.

---

## What it can do

### It learns from your corrections

Most assistants remember what you *tell* them. Comodor learns from what you
*fix*. It reads five things, all of which you produce just by working:

| what you did | what it means |
|---|---|
| you rewrote a file it wrote | the diff is the preference — quotes, indentation, verbosity |
| you pressed `/undo` | an outright rejection |
| you refused a command | one thing you do not want run |
| you asked the same thing twice | the answer missed |
| a tool failed the same way twice | a real pitfall in this environment |

Each becomes a **rule with its evidence attached** — not *"I think you prefer
single quotes"* but `31 of 34 literals`. How much evidence a rule needs depends
on where it came from: four agreeing observations to trust your codebase, two
for an edit you made, one for something you said outright.

It happens with **no extra model call and no waiting**, and it is announced
rather than silent. `/rules` shows every rule, what convinced it, and lets you
drop any of them.

### It follows procedures you write down

A **skill** is a plain Markdown file describing how you want a kind of work
done — your review checklist, your commit conventions, the deploy steps nobody
remembers.

```markdown
---
name: review
description: Review a change for correctness before it is committed
---

Read the whole change before saying anything about it.
Report only what would block a merge.
```

Drop it in `~/.comodor/skills/` for everywhere, or `.comodor/skills/` to commit
it with the project so your whole team gets it. Comodor loads one only when the
request calls for it, so twenty skills cost no more than one.

It uses the [Agent Skills](https://agentskills.io) open format, so a skill
written for another tool works here, and yours work there.

**It also writes them for you.** When it has solved the same shape of problem
three times, `/skills draft` offers the procedure back as a finished file — with
the evidence — and writes nothing until you say yes.

### It remembers every session

Everything you have ever asked is searchable.

```
/search cursor pagination

  you · 12 Apr · 20260412-090000
  > add cursor pagination to the results endpoint
```

The agent searches it too, on its own, when you refer to earlier work — *"like
we did last time"*, *"that bug from last week"*.

### It can browse, not just fetch

Most agents get one page at a time: download a URL, strip the markup, and the
links go with it — so the only way onward is guessing another URL. Comodor
browses.

```
› find out how the GitHub MCP server handles rate limits

⚙ search: github mcp server rate limit          1.2s
⚙ browse https://github.com/modelcontextprotocol/servers   0.8s
    Links on this page:
      1. src/github  →  …/tree/main/src/github
⚙ follow link 1                                  0.6s
⚙ find "rate limit" on the page                  0.0s
```

The links come back numbered and resolved, so the next move is `follow 4`
rather than a guess — and links inside the content rank above the navigation
bar that every page of a documentation site repeats. It is one session, so
cookies, redirects and consent pages survive the hop. Long pages are handed
over a screenful at a time with `find` to jump, instead of being cut off at
40,000 characters. Moving around a page it has already fetched touches no
network and asks no permission; a new host does.

There is no JavaScript engine, and there is not going to be one — that means a
real browser, which means a real dependency. A page that draws itself in the
client says so and points at the Puppeteer server below rather than pretending.

### It connects to other tools

Comodor speaks the [Model Context Protocol](https://modelcontextprotocol.io),
so it can use capabilities it does not implement itself: a browser, a database,
your issue tracker.

```bash
comodor mcp catalogue                      # twelve servers, ready to go
comodor mcp add filesystem --path ~/work
comodor mcp add github --env GITHUB_PERSONAL_ACCESS_TOKEN=…
comodor mcp custom my-server uvx my-package   # anything else
```

| | |
|---|---|
| **Files and code** | Filesystem · Git · GitHub |
| **Data** | SQLite · PostgreSQL |
| **The web** | Fetch · Brave Search · Browser (Puppeteer) |
| **Other** | Memory · Sequential thinking · Slack · Time |

Each entry says **what it can reach** before you enable it. Nothing starts
until it is used.

### It fixes itself

```
$ comodor doctor

Checks
  ok    provider        Anthropic · claude-sonnet-4-5
  warn  session search  the index is corrupt
              → delete it — it is a cache built from the transcripts
  ok    mcp servers     2 enabled and reachable

1 of these can be repaired automatically: comodor doctor --fix
```

`--fix` repairs what it can rebuild and **refuses what it cannot**. A corrupt
cache gets deleted. A corrupt config is reported and left exactly as it was,
because it holds your API key — the one thing on your machine that cannot be
regenerated.

### It updates itself

```
$ comodor update

Comodor 0.2.3
  0.3.0 is available.  https://pypi.org/project/comodor/0.3.0/
  installed as a uv tool
  uv tool upgrade comodor

  updating…
  now on 0.3.0
```

It uses whatever put it there — uv, pipx, pip, or the environment the installer
built — because guessing wrong is worse than not offering the command: a `pip
install --upgrade` inside a uv environment appears to work and leaves uv's
record pointing at a version that is gone.

Afterwards it runs the new one and asks what it is, and *that* is what gets
printed. An upgrade that reports success by echoing the number it was aiming at
is how a silently failed install goes unnoticed for a week. `--check` says
what is available and changes nothing, and `comodor doctor` mentions a new
release without ever installing one.

A source checkout is left alone: `git pull` is the upgrade, and overwriting a
working tree with a release throws away work that was never committed.

### It leaves when you ask it to

```
$ comodor uninstall

Your data
  everything it has learned and everything you told it   14 MB
    ~/.comodor
    settings and your API key · learned rules and lessons · 62 sessions · 4 skills

In your projects
  api-server                                            1.2 MB
    ~/work/api-server/.comodor

The program
  the isolated environment                               112 MB
    ~/.local/share/comodor

Your shell
  the PATH line the installer added
    ~/.bashrc

127 MB across 5 places. None of it can be undone.

Type uninstall to confirm, or anything else to stop.
```

It shows the list before it touches anything, and `--dry-run` stops there. What
goes is the data directory, the `.comodor` folder in every project it was used
in, the environment the installer built, the `comodor` command, and the line
the installer put in your shell profile. Afterwards there is nothing of it left
on the machine.

It knows which projects to clean because every session records where it ran —
not by searching your disk. Three things it will not do: touch a source
checkout, take a directory off your PATH that other programs are still using,
or claim to have deleted a file the operating system would not let go of.

---

## You stay in control

- **Reads never interrupt you. Writes show a coloured diff and ask. Commands
  and network calls always ask.**
- **Checkpoints.** Every file is snapshotted before it changes; `/undo`
  restores it.
- **A deny list no prompt can talk past**, for commands that are never
  acceptable — whatever the model, or you, may ask for in the moment.
- **It stays inside your project.** Writes outside it are refused by default.
- **Your keys never appear** in logs, transcripts or exports.

Three switches decide how much rope it gets:

| | |
|---|---|
| **Act** | the full tool set — it can change your project |
| **Plan** | read-only, and the write tools are hidden from the model entirely, so you get a plan rather than a thwarted attempt to edit |
| **Chat** | no tools at all |

**Loop** decides whether it keeps going by itself until the job is done or a
budget trips — steps, wall clock, or money. **Gateway** can spread work across
providers and fail over when one breaks.

---

## Bring your own model

| | |
|---|---|
| **Hosted** | OpenRouter · Anthropic · OpenAI · Google Gemini · DeepSeek · xAI · Mistral · Groq · Cerebras · Moonshot · Z.AI · Qwen · Together · Fireworks · Xiaomi MiMo |
| **On your machine** | Ollama · LM Studio — no key, no cost, no network |
| **Anything else** | any OpenAI-compatible endpoint |

Each knows its own endpoint, model list and where to get a key, so choosing one
is a single number. Switch any time with `/provider`, or per run:

```bash
comodor --provider groq --model llama-3.3-70b-versatile
```

---

## Everyday use

```bash
comodor                                     # the interface
comodor --demo                              # offline walkthrough, no key needed
comodor run "fix the failing test" --yes    # one task, headless, for scripts
comodor run "audit this module" --json      # machine-readable, for pipelines
comodor doctor                              # check everything; --fix repairs it
comodor update                              # move to the newest release; --check first
comodor uninstall                           # remove it completely; --dry-run first
```

| Key | |
|---|---|
| `Enter` | send · `Ctrl+J` for a newline |
| `Esc` | stop the agent |
| `F1` … `F5` | help · sidebar · mode · loop · gateway |
| `Ctrl+O` | attach a file |
| `Ctrl+C` | stop; twice to quit |

`!command` runs a shell command directly. `@path` attaches a file.

**Commands** — `/help` `/model` `/provider` `/mode` `/loop` `/rules`
`/progress` `/memory` `/skills` `/search` `/mcp` `/undo` `/cost` `/export`
`/settings` `/resume` `/quit`

---

## Configuration

One JSON file, written for you and safe to edit by hand.

| | |
|---|---|
| Linux and macOS | `~/.comodor/config.json` |
| Windows | `%APPDATA%\Comodor\config.json` |

It is written atomically and, on Unix, readable only by you, because it holds
your key. A `.comodor/config.json` inside a repository is merged over your
personal one, so a team can pin settings without sharing secrets. Provider
environment variables still take precedence, which keeps CI working with no
file at all.

---

## Persian, Arabic and Hebrew

Right-to-left text is set to the right of its column, where a Persian or Arabic
reader's line begins, and left-to-right text is left exactly where it was. A
code block inside a right-to-left answer stays on the left, because code is
left-to-right in every language there is.

The part that needs saying: **a terminal application cannot choose a font.** It
writes characters; the terminal emulator picks the glyphs. If Persian or Arabic
comes out as boxes, the fix is in your terminal's own settings — set **Tahoma**,
or any face with Arabic-script coverage. `comodor doctor` says so when it sees
that writing in your history.

What Comodor does do is stop the bidirectional algorithm reaching across
boundaries it should not. A line is usually half ours and half yours —
`learned` then a rule you wrote, `edit` then a path — and the neutral
characters between the two halves resolve against whichever side wins, which is
how `افزودن مسیر /health` ends up with the path in the wrong place. Each field
is fenced in a Unicode isolate, which costs nothing: the marks are zero-width,
so every column in the layout still lines up.

## Any terminal, any size

The layout is recomputed every frame, so resizing just works — from a
40-column SSH window to an ultrawide monitor. Below the floor it says so
plainly rather than drawing a corrupted screen, `--ascii` covers terminals
without box-drawing glyphs, and a monochrome terminal gets a monochrome theme
automatically.

Recall — the wait between pressing Enter and the first token — is **0.38 ms and
stays there** whether the agent has learned three thousand things or twenty
thousand. That is measured, not asserted: `tests/test_performance.py` enforces
it as a ceiling, so a change that makes it slow fails the build.

---

## Development

```bash
git clone https://github.com/ifekri/Comodor && cd Comodor
python -m venv .venv
.venv/Scripts/activate        # Windows;  source .venv/bin/activate elsewhere
pip install -e ".[dev]"
pytest -q                     # 472 tests, no network, no spend
```

```
src/comodor/
├─ agent/       the reason/act loop, context budgeting, prompts
├─ learning/    the brain: rules, lessons, signals, progress
├─ skills/      authored skills: the open format, matching, drafts
├─ mcp/         the Model Context Protocol client and server catalogue
├─ providers/   every backend, and the gateway between them
├─ safety/      permissions, checkpoints, redaction
├─ session/     persistence, export, full-text search
├─ tools/       files, search, shell, python, web, task list
└─ ui/          layout, theme, widgets, raw input, the app loop
```

The suite runs the whole agent against a scripted provider — no network, no
spend — and renders the interface at a range of terminal sizes to prove the
responsive layout holds.

```bash
comodor preview 120x34            # render one frame at a fixed size
```

---

## Contributing

Bug reports welcome — please include `comodor doctor`, which prints everything
we would otherwise have to ask for. [CONTRIBUTING.md](CONTRIBUTING.md) covers
the setup. Security issues go [here](SECURITY.md), privately.
[CHANGELOG.md](CHANGELOG.md) records what changed in each release.

## Licence

MIT — see [LICENSE](LICENSE).
