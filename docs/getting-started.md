# Getting started

Five minutes, ending with the agent doing something useful.

---

## 1. Install

One line. It works out the rest.

**macOS · Linux · BSD**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows** — PowerShell

```powershell
irm get.comodor.ai | iex
```

```
Comodor — it learns the way you correct it.

  Linux x86_64
> Installing uv, a package manager Comodor needs (about 15 MB)
  from https://astral.sh/uv — it fetches a Python too, if one is missing
> Installing with uv

✓ comodor 0.9.0

  Linked into /usr/local/bin, which is on your PATH.

  comodor              start the interface
  comodor --demo       try it offline, no API key needed
  comodor doctor       check what is configured
```

**One address for both.** `get.comodor.ai` names no file. It reads which
client is asking and sends `curl` and `wget` to the shell installer, PowerShell
to the Windows one, and a browser to this page — so the line you paste is the
same line on every system, and you never have to pick.

**It finishes.** Somebody running one line from a web page has not agreed to
debug anything, so the script installs what it needs — an isolated environment,
a package manager, a Python — rather than stopping to explain what you should
have had already. Verified on a bare `debian:bookworm-slim` with no Python on it
at all.

### Nothing to type afterwards, almost always

Where it can, it puts `comodor` somewhere your shell is already looking, so it
works in the terminal you ran it from — no `export`, no new window. That covers
root, containers, CI, and any Mac with Homebrew.

Where it cannot — an ordinary Linux account, where nothing on `PATH` is
writable — no installer can help, because a child process cannot change the
environment of the shell that ran it. So it says so:

```
  Every new terminal can run comodor already.
  This one started before the install, and no installer
  can reach back into the shell that ran it. For this
  terminal only:

    export PATH="/home/you/.local/bin:$PATH"
```

Open a new terminal and it simply works. The line goes into both your shell's
rc file and your login profile, so every kind of shell finds it — interactive,
login, non-interactive, and a desktop session.

### If you would rather not pipe a script into a shell

Entirely reasonable. Both scripts are plain text you can read first — named
directly, because the short address sends anything that is not a fetcher to the
page:

```bash
curl -fsSL https://comodor.ai/install.sh  | less
curl -fsSL https://comodor.ai/install.ps1 | less
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
COMODOR_NO_MODIFY_PATH=1 curl -fsSL get.comodor.ai | sh
```

> **Not sure you want to install it yet?** `comodor --demo` runs the entire
> interface against a scripted offline provider. No key, no account, no network.

---

## 2. Choose a model

Run it. The first time, it asks six questions and never asks again.

```bash
comodor
```

```
 1/6  Which model provider?
┌─  Providers  ───────────────────────────────────────────┐
│ ›  OpenRouter        One key, hundreds of models         │
│    Anthropic         Claude, direct from the source      │
│    OpenAI            GPT models, direct                  │
│    Ollama (local)    Runs on your machine. No key        │
└──────────────────────────────────────────────────────────┘
  ↑↓ move   enter choose   tab more   esc cancel
```

Arrow keys, or type to filter. **Tab** opens the full description of
whatever the arrow is on, in the same frame — the lists show one line per
row so they fit the screen, and some of those descriptions are a paragraph.

Piped or scripted, the same questions arrive as a numbered list, so it can be
automated.

**No key and no money?** Choose **Ollama** or **LM Studio**. They run on your
machine, need no key, and cost nothing. Everything in this documentation works
with them except the parts that say otherwise.

**Already use OpenClaw or Hermes?** The first screen offers to bring your keys,
your model and your skills across. Nothing is moved and nothing already set here
is replaced. See [Coming from another agent](migrating.md).

Your answers go to `~/.comodor/config.json`, readable only by you. Change your
mind later with `comodor setup`, or one setting at a time — see
[Configuration](configuration.md).

### The last question is your phone

```
 6/6  Run it from your phone?
┌─  From your phone  ─────────────────────────────────────────────┐
│ ›  Not now    you can set either up later                        │
│    Telegram   a bot from @BotFather — set up here in a minute    │
│    WhatsApp   a Meta business number — needs an app at Meta      │
└──────────────────────────────────────────────────────────────────┘
```

**Telegram** takes a token from [@BotFather](https://t.me/botfather), checks it
against Telegram there and then, and shows a code to send the bot so it knows
which account to answer — a minute, start to finish.
See [From your phone](telegram.md).

**WhatsApp** does the same thing and takes about twenty minutes: a Meta app, a
business number, an app secret and a public HTTPS address, none of which can be
made from a terminal. Worth it only if it has to be WhatsApp — see
[From WhatsApp](whatsapp.md).

Either way it reads and plans only until you say otherwise, and declining costs
one keypress.

### And then it offers to start

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet            — `comodor` starts it whenever you want
```

Setup used to end here, back at the shell prompt with nothing running. A phone
line appears for each channel that is connected and paired, named — somebody
who set up WhatsApp is not offered "the Telegram bot".

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
