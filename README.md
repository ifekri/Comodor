<div align="center">

# Comodor

**The coding agent that stops making the same mistake.**

Fix something it wrote, and it never writes it that way again — in this project
or the next one. Not a setting you turn on. Not a file you maintain.

[![PyPI](https://img.shields.io/pypi/v/comodor?label=pypi&color=00e1fa)](https://pypi.org/project/comodor/)
[![Python](https://img.shields.io/pypi/pyversions/comodor?color=555)](https://pypi.org/project/comodor/)
[![CI](https://github.com/ifekri/Comodor/actions/workflows/ci.yml/badge.svg)](https://github.com/ifekri/Comodor/actions/workflows/ci.yml)
[![Licence](https://img.shields.io/pypi/l/comodor?color=555)](LICENSE)

[**comodor.ai**](https://comodor.ai) · [Installation](#install) · [Documentation](docs/README.md) · [Changelog](CHANGELOG.md)

</div>

---

```
                         ░█▀▀░█▀█░█▄█░█▀█░█▀▄░█▀█░█▀▄  
                         ░█░░░█░█░█░█░█░█░█░█░█░█░█▀▄  
                         ░▀▀▀░▀▀▀░▀░▀░▀▀▀░▀▀░░▀▀▀░▀░▀  
                       it learns the way you correct it
```

## Why this one

Every agent forgets. You correct the same thing on Monday and again on Friday,
because the correction went into a conversation that ended.

Comodor watches what you do to its output. Change a name it chose, rewrite a
function it wrote, tell it *no, use the existing helper* — it works out the rule
behind the correction, tells you the rule it wrote, and follows it from then on.

```
◈ learned: naming.functions Name functions in snake_case. 6 of 6 definitions
◈ learned: line.length Keep lines within about 79 characters. 95% of lines are under 79
◈ learned: quotes.style Use double quotes for string literals. 176 of 176 literals
```

Those are real, read out of a working install.

`/progress` shows whether that is actually working — corrections per turn,
falling or not. A number, not a claim.

## Everything else it does

| | |
|---|---|
| **Asks instead of guessing** | When a request reads two ways it settles what it can by reading your code, then puts the rest as one short form — before writing anything. [→](docs/questions.md) |
| **Never surprises you** | Reading is silent. Writing shows a diff. Commands ask. Every change is checkpointed and `/undo` puts it back. [→](docs/safety.md) |
| **Drives a real browser** | One that runs JavaScript, keeps cookies and can log in — not a page fetcher. [→](docs/browser.md) |
| **Uses your screen** | Mouse and keyboard in any application, with a halo showing where it is about to click before it clicks. [→](docs/computer.md) |
| **Runs on your phone** | A Telegram bot with the whole interface as buttons. Read-only until you say otherwise. [→](docs/telegram.md) |
| **Runs a model locally** | Pick one, watch it download, use it with the network unplugged. No key, no account. [→](docs/local-models.md) |
| **Lives in your editor** | Speaks ACP, so VS Code, JetBrains and Zed drive it from their own panels. [→](docs/acp.md) |
| **Follows your procedures** | Write a skill once; it loads when the work matches. 147 ready to install. [→](docs/skills.md) |
| **Works with any model** | Nineteen providers, or anything with an OpenAI-compatible URL. [→](docs/models.md) |
| **Costs less** | 86% of input tokens served from cache, measured — not estimated. [→](docs/cost.md) |

**One dependency.** The HTTP client, the SSE reader, the WebSocket that drives
Chrome, the PNG encoder for screenshots, the Telegram client — all written here.
Installing Comodor pulls in `rich` and nothing else.

## Install

### Recommended installation

#### Linux / MacOS

```bash
curl -fsSL get.comodor.ai | sh
```

#### Windows (Powershell)

```bash
irm get.comodor.ai | iex
```

The one-liner above finds a Python, builds an isolated environment, puts
`comodor` on your `PATH`, and fetches a Python if there is none. Verified on a
bare `debian:bookworm-slim` with nothing installed.

Already have a package manager you like?

### Install With [uv](https://docs.astral.sh/uv/getting-started/installation/ 'UV Installation Docs')

```bash
uv tool install comodor
```

> [!NOTE]
> can use : `uv pip install comodor`


### Install With [pip](https://pip.pypa.io/en/stable/installation/ 'pip installation docs')

```bash
pip install comodor
```

> [!NOTE]
> linux on python3 use : `pip3 install comodor`


### Install With [pipx](https://pipx.pypa.io/latest/how-to/install-pipx.html 'How to Install pipx')

```bash
pipx install comodor
```


Then `comodor`. Python 3.11 or newer. Six questions the first time, never
again.

**No API key?** `comodor --demo` runs the whole interface offline. Or pick a
local model in the setup and pay nothing, ever.

**Coming from OpenClaw or Hermes?** The first screen offers to bring your keys
and skills across. [How that works](docs/migrating.md).

## Using it

```bash
comodor                                    # the interface
comodor run "fix the failing test" --yes   # one task, no interface
comodor web                                # from a browser
comodor telegram start                     # from your phone
comodor acp                                # from your editor
comodor doctor                             # is everything alright?
```

```
/help      every command          /undo      restore the last change
/mode      act · plan · chat      /progress  proof it is improving
/cost      tokens and spend       /computer  let it use your screen
Esc        stop it                F3         cycle mode
```

## Documentation

**[docs/README.md](docs/README.md)** — organised by what you are trying to do.

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Install, choose a model, first task |
| [The interface](docs/interface.md) | Panels, keys, and all 29 commands |
| [How it learns](docs/learning.md) | Corrections, rules, and the evidence |
| [What it can do](docs/tools.md) | The 13 tools, and when it uses each |
| [Safety and permissions](docs/safety.md) | What it asks, and what it never does |
| [From your phone](docs/telegram.md) | The Telegram bot, and who it answers |
| [Models on your machine](docs/local-models.md) | Downloading one, running it offline |
| [Configuration](docs/configuration.md) | Every setting, and what wins |
| [Cost](docs/cost.md) | Caching, budgets, paying less |
| [Troubleshooting](docs/troubleshooting.md) | When something is wrong |

## Development

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
uv venv && uv pip install -e ".[dev]"
uv run pytest -q
uv run ruff check .
```

Both pass on Linux and Windows before anything is pushed.
[CONTRIBUTING.md](CONTRIBUTING.md)

## Licence

MIT — [LICENSE](LICENSE).
Security: [SECURITY.md](SECURITY.md), please not a public issue.
