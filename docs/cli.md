# From the terminal

Every command and flag, with something you can paste.

```bash
comodor help              # the written help page
comodor help computer     # one topic in more detail
```

---

## Starting it

```bash
comodor                              # the interface
comodor --demo                       # the interface, offline, no key needed
comodor --resume                     # reopen the last session
comodor --resume 2026-08-22-a4f1     # reopen one by id
comodor --cwd ~/projects/api         # work somewhere other than here
comodor --model claude-sonnet-5      # a different model, this run only
comodor --mode plan                  # start read-only
```

### Options

| | |
|---|---|
| `--provider NAME` | `openrouter`, `anthropic`, `openai`, `ollama`, … |
| `--model ID` | override the model for this run |
| `--mode act\|plan\|chat` | plan is read-only; chat has no tools |
| `--no-loop` | answer once instead of working until done |
| `--cwd PATH` | the folder it may touch |
| `--theme NAME` | `ember`, `midnight`, `matrix`, `mono` |
| `--ascii` | ASCII borders |
| `--no-mouse` | leave the mouse to the terminal |
| `--resume [ID]` | the last session, or one by id |
| `--demo` | scripted offline provider |
| `--version` | which version this is |
| `-h`, `--help` | the written help page |

None of these are written to your config. They apply to the one run. To make a
change stick, use `/save` inside the interface or edit the config file —
[Configuration](configuration.md).

---

## `comodor run` — one task, no interface

```bash
comodor run "fix the failing test in tests/test_parser.py"
comodor run "add type hints to src/parser.py" --yes
comodor run "what does this project do?" --json
comodor run "refactor the parser" --max-steps 40
```

| | |
|---|---|
| `--yes` | approve writes and commands automatically |
| `--json` | a machine-readable result on stdout |
| `--max-steps N` | override the step limit for this run |

Without `--yes` it will ask, on stderr, and refuse rather than assume if nothing
can answer. That is deliberate: a script that silently self-approves is a script
that does something you did not expect at three in the morning.

`--json` gives you:

```json
{
  "text": "Fixed. The parser raised on empty input rather than returning [\"\"] …",
  "ok": true,
  "stopped": "done",
  "steps": 6,
  "tool_calls": 11,
  "error": "",
  "usage": {
    "input_tokens": 18422,
    "output_tokens": 640,
    "cost_usd": 0.031
  },
  "elapsed": 24.71
}
```

`stopped` says why it finished — one of:

| | |
|---|---|
| `done` | it decided it was finished |
| `max_steps` | it hit `agent.max_steps` |
| `budget` | it hit `agent.max_cost_usd` or `agent.max_seconds` |
| `cancelled` | you interrupted it |
| `error` | something went wrong; `error` says what |

`ok` is true for `done` and `max_steps` — running out of steps is not a failure,
it is a ceiling doing its job — so check `stopped` too if you need the
difference:

```bash
comodor run "update the changelog for this release" --yes --json > result.json
jq -e '.stopped == "done"' result.json
```

It still learns from a headless run. A correction you make afterwards teaches
the same lesson an interactive one would.

---

## `comodor setup` — choose a provider and model

```bash
comodor setup
```

Five questions, or six if another agent is installed and it offers to import.
Runs automatically on a first run; use this to change your mind later.

Answers go to `~/.comodor/config.json`.

---

## `comodor import` — from OpenClaw or Hermes

```bash
comodor import             # bring keys, model and skills across
comodor import --dry-run   # say what it would take, change nothing
comodor import --keys-only # leave the skills and the model
```

Nothing is moved and nothing already set here is replaced. See
[Coming from another agent](migrating.md).

---

## `comodor doctor` — is everything alright?

```bash
comodor doctor
comodor doctor --fix
```

```
  ok    config file         ~/.comodor/config.json
  ok    config permissions  0o600
  ok    provider            Anthropic · claude-sonnet-5
  ok    model               claude-sonnet-5
  ok    spend limit         $2.00 per task
  ok    brain               ~/.comodor/brain.db
  ok    skills              4 loaded
  warn  version             0.8.9 installed; 0.9.0 is out
```

`--fix` repairs what is repairable — a stale provider name, a missing directory,
a broken search index. It never changes anything it did not report first.

Exit code is non-zero if anything failed, so it works in a health check.

---

## `comodor web` — from a browser

```bash
comodor web                       # here, on 127.0.0.1:8765
comodor web --port 9000
comodor web --host 0.0.0.0        # reachable from elsewhere — read the warning
comodor web --no-browser          # do not open one
comodor web --token mytoken       # a fixed token instead of a fresh one
```

Full guide: [From a browser](web.md).

---

## `comodor skills` — procedures it follows

```bash
comodor skills browse             # what is available
comodor skills list               # what you have
comodor skills add review taste   # install some
comodor skills update             # refresh installed ones
comodor skills remove review
```

Full guide: [Skills](skills.md).

---

## `comodor mcp` — Model Context Protocol servers

```bash
comodor mcp list                  # what you have, and what it offers
comodor mcp catalogue             # what is available
comodor mcp add filesystem        # from the catalogue
comodor mcp custom NAME -- CMD    # a command of your own
comodor mcp remote NAME URL       # an HTTP server
comodor mcp enable NAME
comodor mcp disable NAME
comodor mcp remove NAME
comodor mcp test NAME             # connect and list its tools
```

Full guide: [MCP servers](mcp.md).

---

## `comodor update` — move to the newest release

```bash
comodor update --check     # what is out there, change nothing
comodor update             # do it
```

It works out how this copy was installed — `uv`, `pipx`, `pip`, or a source
checkout — and uses the right thing. A source checkout is left alone: that one
is yours.

---

## `comodor uninstall` — remove it completely

```bash
comodor uninstall --dry-run    # list what would go
comodor uninstall              # ask, then do it
comodor uninstall --yes        # for scripts
```

```
Your data
  everything it has learned and everything you told it     4.2 MB
    ~/.comodor
    settings and your API key · 812 lessons · 47 sessions · 4 skills

In your projects
  api-server                                               128 KB
    ~/projects/api-server/.comodor
    checkpoints, project settings, project skills

The program
  the uv installation
    ~/.local/share/uv/tools/comodor

4.3 MB across 3 places. None of it can be undone.
```

It names everything before it removes anything, and says what it cannot find —
a `.comodor` folder in a project you used but whose session history has been
cleared cannot be named, and it tells you so rather than pretending.

---

## `comodor preview` — the interface at a given size

```bash
comodor preview 80x24
comodor preview 200x50 --svg wide.svg
```

Renders one frame and exits. Useful for checking a narrow terminal, or for a
screenshot.

---

## Environment variables

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, … | a key, per provider |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | force a provider or model |
| `COMODOR_HOME` | where config, brain and sessions live |
| `COMODOR_BANNER=0` | no wordmark this run |
| `COMODOR_NO_IMPORT=1` | do not offer to import from another agent |
| `COMODOR_WEB_TOKEN` | a fixed token for the web interface |
| `NO_COLOR` | no colour, honoured everywhere |

A key in the environment is **never written to your config file**. Exporting one
rather than saving it is a decision, and `/save` respects it. See
[Configuration](configuration.md).

---

## Exit codes

| | |
|---|---|
| `0` | it worked |
| `1` | it did not |
| `130` | you interrupted it |

---

## See also

- [The interface](interface.md) — the same power, interactively
- [Configuration](configuration.md) — making a flag permanent
- [Troubleshooting](troubleshooting.md) — when a command does not do what it says
