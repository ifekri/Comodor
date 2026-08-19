# Security

## Reporting a vulnerability

Please report privately through GitHub's
[security advisories](https://github.com/ifekri/Comodor/security/advisories/new)
rather than opening a public issue. Include what you did, what happened, and
what an attacker could achieve with it.

Expect an acknowledgement within a few days.

## What Comodor holds, and where

| | |
|---|---|
| `~/.comodor/config.json` | your provider API keys — written atomically, and `0600` on Unix |
| `~/.comodor/brain.db` | learned rules and lessons, including snippets of the code they came from |
| `~/.comodor/sessions/` | transcripts, redacted |
| `~/.comodor/checkpoints/` | file snapshots taken before edits, so `/undo` can restore them |

`%APPDATA%\Comodor\` on Windows. Nothing is sent anywhere except to the model
provider you configured; there is no telemetry and no other network call the
agent makes on its own.

## The boundaries that matter

Comodor edits files and runs commands, so its safety model is worth stating
plainly rather than implying:

- **Reads never prompt. Writes show a diff and ask. Shell commands and network
  calls always ask.** `--yes` removes the prompts and exists for CI; it is not a
  default anywhere.
- **A deny list no prompt can talk past**, for a small set of commands that are
  never acceptable regardless of what the model or the user asks for.
- **Workspace confinement.** Writes outside the project directory are refused
  unless `workspace_only` is turned off deliberately.
- **Redaction.** API keys and tokens are stripped from logs, transcripts and
  exports by pattern, before anything is written.

## What is not defended against

Being explicit about this is more useful than a reassuring sentence:

- **Prompt injection.** Content the agent reads — a file, a web page, a tool's
  output — can contain instructions. The approval prompts are the mitigation:
  they are what stops an injected instruction from becoming an executed command.
  Running with `--yes`, or with `auto_approve_shell` enabled, removes that
  protection. Do not point an auto-approving agent at content you do not trust.
- **A malicious model provider.** Whatever endpoint you configure sees your
  prompts, and its responses drive the tools. Configure providers you trust.
- **Other software on your machine.** The config file is `0600`, but anything
  running as your user can read it. Rotate a key you think has been exposed.
