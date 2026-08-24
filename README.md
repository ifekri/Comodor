# Comodor

**A coding agent that lives in your terminal — and learns the way you correct it.**

[![PyPI](https://img.shields.io/pypi/v/comodor?label=pypi&color=c4441e)](https://pypi.org/project/comodor/)
[![Python](https://img.shields.io/pypi/pyversions/comodor)](https://pypi.org/project/comodor/)
[![CI](https://github.com/ifekri/Comodor/actions/workflows/ci.yml/badge.svg)](https://github.com/ifekri/Comodor/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/pypi/l/comodor?color=555)](LICENSE)

**[Documentation](docs/README.md)** · [comodor.ai](https://comodor.ai) · [Changelog](CHANGELOG.md)

---

Describe a job — *fix the failing test*, *add a health endpoint*, *work out why
the deploy broke* — and it does the work: reads your files, writes changes, runs
your tests, searches the web, and keeps going until the job is done or it needs
you.

It asks before it changes anything, shows you exactly what it is about to do,
and can undo it.

What makes it different from every other tool of this kind is what happens
afterwards. **When you fix something it wrote, it notices, and it does not make
that mistake again.** Not because you configured it.

---

## Install

**macOS · Linux**

```bash
curl -fsSL get.comodor.ai | sh
```

**Windows**

```powershell
irm get.comodor.ai | iex
```

That is the whole thing. It finds a Python, installs an isolated environment,
puts `comodor` on your `PATH`, and tells you what to do next — and if there is
no Python at all it fetches one. Verified on a bare `debian:bookworm-slim` with
nothing installed.

Already have a package manager you like?

```bash
uv tool install comodor       # or: pipx install comodor, or: pip install comodor
```

Then:

```bash
comodor
```

Python 3.11 or newer. It asks five questions the first time and never asks
again.

No key yet? `comodor --demo` runs the whole interface offline. Or choose
**Ollama** in the setup and pay nothing, ever.

Already use OpenClaw or Hermes? The first screen offers to bring your keys and
skills across. [How that works](docs/migrating.md).

---

## What it can do

| | |
|---|---|
| **Ask before it guesses** | When a request reads two ways, it settles what it can by reading and puts the rest to you as one short form — before it writes anything. [More](docs/questions.md) |
| **Learn from your corrections** | Edit what it wrote, or say so, and the next answer follows. `/progress` shows whether that is actually working — falling correction rates, not a claim. [More](docs/learning.md) |
| **Ask before it acts** | Reading is silent, writing shows a diff, commands ask. Every write is checkpointed; `/undo` puts it back. [More](docs/safety.md) |
| **Use a real browser** | One that runs JavaScript, keeps cookies and can log in — not a page fetcher. [More](docs/browser.md) |
| **Use your screen** | Mouse and keyboard, in any application, with a halo on screen showing where it is about to click. Windows so far. [More](docs/computer.md) |
| **Follow your procedures** | Write a skill once; it loads it when the work matches. [More](docs/skills.md) |
| **Run anywhere** | Terminal, browser, editor, or a container. [Web](docs/web.md) · [Editor](docs/acp.md) · [Docker](docs/docker.md) |
| **Work with any model** | Seventeen providers, or anything with an OpenAI-compatible URL. Including ones on your own machine. [More](docs/models.md) |
| **Cost less than it should** | 86% of input tokens served from cache, measured. [More](docs/cost.md) |

**One dependency.** The HTTP client, the SSE reader, the WebSocket for the
browser, the PNG encoder for screenshots — all part of the package. Installing
Comodor pulls in `rich` and nothing else.

---

## Everyday use

```bash
comodor                                    # the interface
comodor run "fix the failing test" --yes   # one task, no interface
comodor web                                # from a browser
comodor acp                                # from your editor (ACP)
comodor doctor                             # is everything alright?
comodor help                               # a written help page, not a flag dump
```

```
/help      every command          /undo      restore the last change
/mode      act · plan · chat      /progress  proof it is improving
/cost      tokens and spend       /computer  let it use your screen
Esc        stop it                F3         cycle mode
```

---

## Documentation

**[docs/README.md](docs/README.md)** — everything, organised by what you are
trying to do.

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Install, choose a model, first task |
| [The interface](docs/interface.md) | Panels, keys, and all 29 commands |
| [From the terminal](docs/cli.md) | Every command and flag |
| [What the agent can do](docs/tools.md) | The 13 tools, and when it uses each |
| [Safety and permissions](docs/safety.md) | What it can do, and what it never does |
| [How it learns](docs/learning.md) | Corrections, lessons, and the evidence |
| [Using your screen](docs/computer.md) | Mouse and keyboard, watched |
| [Configuration](docs/configuration.md) | Every setting, and what wins |
| [Cost](docs/cost.md) | Caching, budgets, paying less |
| [Troubleshooting](docs/troubleshooting.md) | When something is wrong |

---

## Development

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run ruff check .
```

Both must pass before anything is pushed, on Linux and on Windows.
[CONTRIBUTING.md](CONTRIBUTING.md).

---

## Licence

MIT. See [LICENSE](LICENSE).

Security: [SECURITY.md](SECURITY.md) — please do not open a public issue.
