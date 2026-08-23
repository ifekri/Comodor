# Getting started

Five minutes, ending with the agent doing something useful.

---

## 1. Install

One line. It works out the rest.

**macOS · Linux · BSD**

```bash
curl -fsSL https://comodor.ai/install.sh | sh
```

**Windows** — PowerShell

```powershell
irm https://comodor.ai/install.ps1 | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Added /root/.local/bin to your PATH in /root/.profile
```

**It finishes.** Somebody running one line from a web page has not agreed to
debug anything, so the script installs what it needs — an isolated environment,
a package manager, a Python — rather than stopping to explain what you should
have had already. Verified on a bare `debian:bookworm-slim` with no Python on it
at all.

It gives up only when it genuinely cannot proceed, and then it names exactly one
thing to do next.

### If you would rather not pipe a script into a shell

Entirely reasonable. Both scripts are plain text you can read first:

```bash
curl -fsSL https://comodor.ai/install.sh | less
```

Or use a package manager you already have:

```bash
uv tool install comodor      # isolated, and the fastest
pipx install comodor         # isolated
pip install comodor          # into whatever environment you are in
```

Comodor needs **Python 3.11 or newer** and nothing else.

### Check it arrived

```bash
comodor --version
```

If the shell cannot find it, the installer added a directory to your `PATH` that
this terminal does not know about yet. Open a new one, or run the `export` line
the installer printed.

### Options the installers understand

| | |
|---|---|
| `COMODOR_FORCE_TOOL` | pin the method: `uv`, `pipx`, `venv` or `pip` |
| `COMODOR_NO_BOOTSTRAP` | never download a tool; fail instead |
| `COMODOR_NO_MODIFY_PATH` | do not touch your shell profile |
| `COMODOR_INSTALL_REF` | install from a git ref or a local path instead of PyPI |

```bash
COMODOR_NO_MODIFY_PATH=1 curl -fsSL https://comodor.ai/install.sh | sh
```

> **Not sure you want to install it yet?** `comodor --demo` runs the entire
> interface against a scripted offline provider. No key, no account, no network.

---

## 2. Choose a model

Run it. The first time, it asks five questions and never asks again.

```bash
comodor
```

```
 1/5  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   type filter   esc cancel
```

Arrow keys, or type to filter. Piped or scripted, the same questions arrive as a
numbered list, so it can be automated.

**No key and no money?** Choose **Ollama** or **LM Studio**. They run on your
machine, need no key, and cost nothing. Everything in this documentation works
with them except the parts that say otherwise.

**Already use OpenClaw or Hermes?** The first screen offers to bring your keys,
your model and your skills across. Nothing is moved and nothing already set here
is replaced. See [Coming from another agent](migrating.md).

Your answers go to `~/.comodor/config.json`, readable only by you. Change your
mind later with `comodor setup`, or one setting at a time — see
[Configuration](configuration.md).

---

## 3. It asks which folder

```
  Work in  /home/you/projects/api-server ?
```

Asked once per folder. Everything the agent may touch is under it — it cannot
read or write outside without you turning that off deliberately. Approved
folders are remembered.

---

## 4. Ask for something

Type it and press Enter.

```
> the tests in tests/test_parser.py are failing, work out why and fix it
```

It will read files, run the tests, and change something. Before it writes a file
you get a diff and a choice:

```
  Write  src/parser.py
    - 12 lines removed, 8 added
  [a] allow   [A] allow always this session   [d] deny
```

Answer `a` once, or `A` if you would rather it stopped asking for the rest of
the session. Every write is checkpointed either way: `/undo` puts the last one
back.

---

## 5. Correct it — this is the part that matters

When it gets something wrong, tell it. Two ways, and both teach it the same
thing:

**Edit the file yourself.** Comodor notices what you changed about its output.

**Say so.**

```
> no — we use single quotes in this codebase, not double
```

Either way it becomes a lesson: recalled next time the situation looks similar,
with a confidence that rises when it holds and decays when it does not.

After a few sessions:

```
> /progress
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

That is evidence, not a claim. If the correction rate is not falling, the
learning is not working, and the panel says so rather than hiding it.

[How it learns](learning.md) explains the mechanism.

---

## 6. The things worth knowing on day one

```
/help          every command
/mode          act · plan (read-only) · chat (no tools)     F3 cycles
/undo          restore the last file it changed
/cost          tokens, spend, what the cache saved
Esc            stop it, mid-thought
Ctrl-C twice   leave
```

---

## Where to go next

| You want to | Read |
|---|---|
| Use it without the interface, in a script | [From the terminal](cli.md) |
| Know exactly what it can do to your machine | [Safety and permissions](safety.md) |
| Pay less | [Cost](cost.md) |
| Let it use a browser | [The real browser](browser.md) |
| Let it use your mouse and keyboard | [Using your screen](computer.md) |
| Write a procedure it follows every time | [Skills](skills.md) |
| Run it on a server, or in Docker | [From a browser](web.md), [In Docker](docker.md) |

---

## If something went wrong

```bash
comodor doctor
```

It checks everything it can and tells you what to do about anything it finds.
`comodor doctor --fix` repairs what is repairable. See
[Troubleshooting](troubleshooting.md).
