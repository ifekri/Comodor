# Configuration

One JSON file you never have to hand-edit — but here is everything in it.

---

## Where things live

| | |
|---|---|
| `~/.comodor/config.json` | yours. The wizard writes it; owner-only permissions |
| `~/.comodor/brain.db` | what it has learned |
| `~/.comodor/sessions/` | every conversation |
| `~/.comodor/skills/` | skills you installed or wrote |
| `./.comodor/config.json` | the project's. Safe to commit — see [what it may set](safety.md#what-a-repository-may-set) |
| `./.comodor/checkpoints/` | the previous contents of every file it changed |

On Windows, `~/.comodor` is `%APPDATA%\Comodor`. `COMODOR_HOME` overrides it
everywhere.

```bash
comodor doctor      # tells you exactly where all of these are
```

---

## What wins

Four layers. Later beats earlier.

```
1. built-in defaults
2. ~/.comodor/config.json         yours
3. ./.comodor/config.json         the project's — restricted
4. environment variables          ANTHROPIC_API_KEY, COMODOR_MODEL, …
5. the command line               --model, --mode, … for one run
```

### What `/save` writes

**Only what you chose.** This matters more than it sounds.

The configuration the agent runs on is all four layers merged. Writing that back
into your file would make a cloned repository's spend ceiling your permanent
global default, and would copy an API key you deliberately kept in your
environment onto disk.

So `/save` remembers where each value came from. A value that still holds
whatever a borrowed layer supplied goes back to what *your* file said; a value
you changed during the session is yours and is written.

- `/model x` then `/save` → persists `x`
- `/save` in a repository that pins `max_cost_usd: 500` → persists nothing of
  the sort
- `/save` with `ANTHROPIC_API_KEY` exported → the key stays in your environment

---

## Every setting

### `provider` and `model`

```json
{ "provider": "anthropic", "model": "claude-sonnet-5" }
```

See [Choosing a model](models.md).

### `agent` — how it works

```json
{
  "agent": {
    "mode": "act",
    "loop": true,
    "max_steps": 0,
    "max_seconds": 3600.0,
    "max_cost_usd": 2.0,
    "context_limit": 1000000,
    "compact_at": 0.75,
    "temperature": 0.3,
    "max_output_tokens": 8192,
    "max_tool_chars": 12000,
    "keep_screenshots": 2,
    "system_prompt_extra": "",
    "prompt_cache": true,
    "prompt_cache_ttl": "5m"
  }
}
```

| | |
|---|---|
| `mode` | `act`, `plan` (read-only), `chat` (no tools) |
| `loop` | keep working until done, or answer once |
| `max_steps` | **`0` — no limit, and that is the default.** A refactor across a dozen files ran out of twenty-four steps mid-thought, and a step count has no relationship to harm. Set a number to bring it back |
| `max_seconds` | an hour. `0` for no limit |
| `max_cost_usd` | the ceiling that maps onto what going wrong costs — [where the model has a published rate](cost.md#when-the-limit-cannot-fire). `0` for no limit |
| `context_limit` | your ceiling on the window. The agent works to whichever is **smaller**, this or what the model actually takes — so a leftover `1000000` against a 32k model no longer stops compaction from firing. `comodor doctor` says which number is in force and where it came from |
| `compact_at` | summarise the history past this fraction of the limit |
| `max_tool_chars` | how much of one tool result reaches the model. The rest is written to a file it is told how to read — not truncated |
| `keep_screenshots` | how many stay in the conversation. [Why](computer.md#screenshots-and-what-they-cost) |
| `verify_command` | your build or test command, run at the end of any turn that changed a file. See below |
| `system_prompt_extra` | your own standing instructions |
| `prompt_cache` | let the provider re-serve the unchanging prefix. [Cost](cost.md) |
| `prompt_cache_ttl` | `5m` or `1h`. The hour costs more to write |

#### `verify_command` — making "done" mean "it still works"

The system prompt asks the model to run the tests after a change. Asking is not
getting. Set this and it happens:

```json
{ "agent": { "verify_command": "pytest -q" } }
```

It runs once, at the end of a turn that changed a file — not after every edit,
and not at all for a turn that only read things. If it fails, the agent is
shown the output and given **one** turn to fix it. One, not a loop: a model
that cannot fix a failing suite on its first try will not fix it on its fifth,
and you are better told than billed.

A command that cannot be run at all — mistyped, missing, no permission — is
reported once and the turn ends as it would have. It never turns a finished
task into an error.

Empty by default, and deliberately: running somebody's whole suite after every
turn is minutes and money they did not ask to spend, and the right command
differs in every project.

### `safety` — what it may do

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "verify_edits": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

`verify_edits` parses a file after writing it and tells the model what it
broke, in the same tool result — so a syntax error is found in the turn that
made it rather than by you, later. Python, JSON and TOML are parsed in
process; JavaScript uses `node --check` when `node` is on your path; anything
else is left alone. It never refuses a write, so half a refactor is still
possible.

Full explanation: [Safety and permissions](safety.md).

### `learning` — what it remembers

```json
{
  "learning": {
    "enabled": true,
    "top_k": 6,
    "max_playbook_tokens": 800,
    "reflect": true,
    "reflect_model": "",
    "min_confidence": 0.15,
    "half_life_days": 45.0,
    "share_scope": "project",
    "associative": true,
    "corrections": true,
    "rules": true,
    "announce": true,
    "prefetch": true
  }
}
```

| | |
|---|---|
| `top_k` | lessons recalled per turn |
| `max_playbook_tokens` | hard cap on what recall may inject |
| `reflect` | distil lessons after a task — this one costs a model call |
| `reflect_model` | a cheaper model for that, if you like |
| `half_life_days` | how fast an unused lesson fades |
| `share_scope` | `project` or `global` |
| `corrections`, `rules`, `announce`, `prefetch` | the fast lane — free, no model call, on even when `reflect` is off |

Full explanation: [How it learns](learning.md).

### `ui` — how it looks

```json
{
  "ui": {
    "theme": "ember",
    "ascii_borders": false,
    "mouse": true,
    "max_fps": 20,
    "show_timestamps": false,
    "sidebar": true,
    "banner": true,
    "syntax_theme": ""
  }
}
```

`banner: false` turns off the wordmark for good; `COMODOR_BANNER=0` does it for
one run.

### `skills` — procedures

```json
{
  "skills": {
    "enabled": true,
    "top_k": 2,
    "max_tokens": 12000,
    "install_examples": true
  }
}
```

Full explanation: [Skills](skills.md).

### `telegram` — from your phone

```json
{
  "telegram": {
    "enabled": false,
    "token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300
  }
}
```

| | |
|---|---|
| `enabled` | whether `comodor telegram start` runs the bot |
| `token` | from [@BotFather](https://t.me/botfather). The first-run setup asks for it, or `comodor telegram connect` |
| `allowed` | the numeric Telegram user ids it answers, and nobody else. Filled by `comodor telegram pair`, never from Telegram itself |
| `allow_writes` | whether a turn started from a phone may edit files and run commands. Off holds it in plan mode however the terminal is set |
| `pair_window` | seconds a pairing code stays good |

**A project's `.comodor/config.json` may not set any of this.** A repository
that could add an account to `allowed` would be a backdoor, and unlike the
browser or the screen there would be nothing visible while it happened.

Full explanation: [From your phone](telegram.md).

### `slack` — from a Slack workspace

```json
{
  "slack": {
    "enabled": false,
    "bot_token": "",
    "app_token": "",
    "allowed": [],
    "allow_writes": false,
    "pair_window": 300,
    "team": ""
  }
}
```

| | |
|---|---|
| `bot_token` | `xoxb-…` from OAuth & Permissions. Does everything the bot does |
| `app_token` | `xapp-…` from Basic Information, scope `connections:write`. Opens the Socket Mode websocket, and nothing else |
| `allowed` | The Slack user ids it answers. Not display names: a display name can be changed by the person holding it |
| `allow_writes` | Whether a Slack turn may edit files and run commands |
| `pair_window` | Seconds a pairing code stays good |
| `team` | The workspace it was connected to, remembered so `status` can name it without a round trip |

**A project's `.comodor/config.json` may not set any of this**, for the same
reason as the others: a repository that could add an account to `allowed` would
be a backdoor.

Full explanation: [From Slack](slack.md).

### `whatsapp` — from a WhatsApp number

```json
{
  "whatsapp": {
    "enabled": false,
    "token": "",
    "phone_number_id": "",
    "app_secret": "",
    "verify_token": "",
    "allowed": [],
    "allow_writes": false,
    "host": "127.0.0.1",
    "port": 8770,
    "path": "/whatsapp",
    "public_url": "",
    "api_version": "v21.0"
  }
}
```

| | |
|---|---|
| `token` | A Meta access token. A System User token does not expire; the dashboard's own lasts 24 hours |
| `phone_number_id` | The numeric id Meta shows beside the number, not the number |
| `app_secret` | Every webhook is signed with it. Without one, nothing is verified |
| `verify_token` | Echoed back during Meta's one-time handshake. Generated, not chosen |
| `allowed` | The numbers it answers, compared as digits. Everyone else gets silence |
| `allow_writes` | Whether a WhatsApp turn may edit files and run commands |
| `host`, `port`, `path` | Where the webhook listens. Localhost, behind something that terminates TLS |
| `public_url` | The address Meta delivers to, remembered so `whatsapp webhook` can print it |
| `api_version` | Pinned, because Meta deprecates versions on their calendar rather than yours |

**A project's `.comodor/config.json` may not set any of this**, for the same
reason as `telegram`: a repository that could add a number to `allowed` would
be a backdoor with nothing on screen to show it happening.

Full explanation: [From WhatsApp](whatsapp.md).

### `browser` — the real browser

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

`headless: false` is how you watch it work. `port` attaches to a browser you
started yourself, so it can use a session you are already logged into rather
than being handed your profile.

Full explanation: [The real browser](browser.md).

### `computer` — your screen

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

Full explanation: [Using your screen](computer.md).

### `gateway` — routing across providers

```json
{
  "gateway": {
    "enabled": false,
    "policy": "quality",
    "chain": [],
    "failure_threshold": 3,
    "cooldown_seconds": 60.0
  }
}
```

`policy` is `cost`, `speed` or `quality`. With `enabled: true` it picks from
`chain` and steps past a provider that keeps failing. `F5` or `/gw` in the
interface.

### `mcp` — Model Context Protocol servers

```json
{
  "mcp": {
    "enabled": true,
    "servers": { }
  }
}
```

Managed with `comodor mcp`, not by hand. [MCP servers](mcp.md).

---

## Environment variables

| | |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, … | one per provider |
| `<PROVIDER>_BASE_URL`, `<PROVIDER>_MODEL` | override an endpoint or model |
| `COMODOR_PROVIDER`, `COMODOR_MODEL` | force either |
| `COMODOR_HOME` | where everything lives |
| `COMODOR_BANNER=0` | no wordmark |
| `COMODOR_NO_IMPORT=1` | do not offer to import from another agent |
| `COMODOR_WEB_TOKEN` | a fixed token for the web interface |
| `NO_COLOR` | no colour |

---

## When a setting does not take effect

Comodor says so rather than ignoring you:

```
config: agent.max_steps must be a whole number; keeping 24
config: this project cannot set safety, computer — only your own can
```

A value of the wrong type is coerced where that is unambiguous, refused where it
is not, and the refusal names the key and what was expected. `null` does not
quietly replace a string with `None`.

If a setting still seems to do nothing:

```bash
comodor doctor          # what it actually loaded
```

```
/settings               # the same, in the interface
```
