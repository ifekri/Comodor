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
| `context_limit` | the gauge. Follows the model automatically when you switch |
| `compact_at` | summarise the history past this fraction of the limit |
| `max_tool_chars` | how much of one tool result reaches the model. The rest is written to a file it is told how to read — not truncated |
| `keep_screenshots` | how many stay in the conversation. [Why](computer.md#screenshots-and-what-they-cost) |
| `system_prompt_extra` | your own standing instructions |
| `prompt_cache` | let the provider re-serve the unchanging prefix. [Cost](cost.md) |
| `prompt_cache_ttl` | `5m` or `1h`. The hour costs more to write |

### `safety` — what it may do

```json
{
  "safety": {
    "auto_approve_safe": true,
    "auto_approve_writes": false,
    "auto_approve_shell": false,
    "checkpoints": true,
    "workspace_only": true,
    "allow_commands": [],
    "deny_commands": ["rm -rf /", "..."],
    "max_file_read_bytes": 512000,
    "max_file_scan_bytes": 64000000,
    "trusted_folders": []
  }
}
```

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
