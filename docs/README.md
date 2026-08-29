# Comodor documentation

A terminal coding agent that learns the way you correct it.

New here? **[Getting started](getting-started.md)** takes about five minutes and
ends with the agent doing something useful.

---

## By what you are trying to do

### Get going

| | |
|---|---|
| [Getting started](getting-started.md) | Install, choose a model, first task |
| [Coming from another agent](migrating.md) | Bring keys and skills from OpenClaw or Hermes |
| [Choosing a model](models.md) | Which provider, which model, what it costs |

### Use it

| | |
|---|---|
| [The interface](interface.md) | Panels, keys, modes, and all 29 commands |
| [From the terminal](cli.md) | Every command and flag, with examples |
| [What the agent can do](tools.md) | The 13 tools it has, and when it uses each |
| [Skills](skills.md) | Procedures you write once and it follows |

### Let it reach further

| | |
|---|---|
| [The real browser](browser.md) | A browser that runs JavaScript and can log in |
| [Using your screen](computer.md) | Mouse and keyboard, in any application |
| [From a browser](web.md) | The web interface, locally or on a server |
| [In your editor](acp.md) | Drive Comodor from Zed or any Agent Client Protocol client |
| [In Docker](docker.md) | One command, in a container |
| [MCP servers](mcp.md) | Tools from the Model Context Protocol |

### Understand it

| | |
|---|---|
| [From your phone](telegram.md) | The Telegram bot: pairing, the buttons, and who it answers |
| [From Slack](slack.md) | Socket Mode — five minutes, no public address, and it answers in threads |
| [From WhatsApp](whatsapp.md) | The Cloud API — about twenty minutes and technical. Telegram does the same in one |
| [Models on your machine](local-models.md) | Downloading one, running it offline, adding to the list |
| [Questions](questions.md) | The form it puts up when a request reads two ways |
| [How it learns](learning.md) | Corrections, lessons, rules, and the proof |
| [Safety and permissions](safety.md) | What it can do, what it asks, what it never does |
| [Cost](cost.md) | Caching, budgets, and paying less for the same work |
| [Configuration](configuration.md) | Every setting, where files live, what wins |

### When something is wrong

| | |
|---|---|
| [Troubleshooting](troubleshooting.md) | `doctor`, common problems, and how to report one |

---

## The shortest possible version

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux
irm get.comodor.ai | iex           # Windows

comodor                  # it asks a few questions, once
```

Then type what you want. Correct it when it is wrong — edit the file, or just
say so — and it learns. `/progress` shows you whether that is actually working.

```bash
comodor run "fix the failing test in tests/test_parser.py"   # one task, no interface
comodor web                                                  # from a browser
comodor doctor                                               # is everything alright?
comodor help                                                 # the written help page
```

## What makes it different

**It learns from corrections, not from praise.** Most agents forget the moment
a session ends. Comodor watches what you change about its output and turns that
into a lesson with a confidence that rises when it holds and falls when it does
not. [How it learns](learning.md) explains the mechanism; `/progress` shows the
evidence.

**It asks before it acts, and everything is reversible.** Reading is silent.
Writing asks. Running a command asks louder. Every write is checkpointed, and
`/undo` puts the last one back. [Safety and permissions](safety.md).

**One dependency.** The HTTP client, the SSE reader, the WebSocket for the
browser, the PNG encoder for screenshots — all part of the package. Installing
Comodor pulls in `rich` and nothing else.

**It can use a real browser and a real desktop.** Not a text fetcher: a browser
that runs JavaScript and keeps cookies, and — on Windows — the mouse and
keyboard, with a halo on screen showing you where it is about to click.
[Browser](browser.md), [screen](computer.md).

---

## Also in the repository

| | |
|---|---|
| [CHANGELOG](../CHANGELOG.md) | What changed, and why |
| [CONTRIBUTING](../CONTRIBUTING.md) | Working on Comodor itself |
| [SECURITY](../SECURITY.md) | Reporting something sensitive |
| [RELEASING](../RELEASING.md) | How a release is cut |
