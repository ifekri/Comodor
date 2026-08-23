# Troubleshooting

## Start here

```bash
comodor doctor
```

It checks the config file and its permissions, the provider, the model, the
spend limit, the brain, the search index, your skills, leftover files, MCP
servers, and whether there is a newer release.

```bash
comodor doctor --fix
```

repairs what is repairable. It never changes anything it did not report first.

---

## It will not start

**`comodor: command not found`, right after installing** — the installer put it
on your `PATH`, but a child process cannot change the environment of the shell
that started it. Every *new* terminal already works. For the one you are in, the
installer printed the line to paste; or:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`comodor: command not found`, in a new terminal** — that is a real problem.
`python -m comodor` confirms whether it is installed at all, and
`ls ~/.local/bin/comodor` where it should be.

**`No provider is configured`** — run `comodor setup`, or export a key:

```bash
export ANTHROPIC_API_KEY=sk-ant-…
```

**Python too old.** Comodor needs 3.11 or newer. Check with `python --version`.

---

## A setting seems to do nothing

Comodor tells you when it refuses one:

```
config: agent.max_steps must be a whole number; keeping 0
config: this project cannot set safety, computer — only your own can
```

If nothing is said and it still has no effect, check which layer wins:

```
/settings          # what is actually loaded
```

```bash
comodor doctor     # the same, plus where every file is
```

A `--model` on the command line beats your config file, and a key in your
environment beats one in the file. That is deliberate —
[Configuration](configuration.md#what-wins).

---

## `/save` did not save what I expected

By design. It writes **only what you chose** — not a repository's settings, not
a key you keep in your environment, not a flag you passed for one run.

To make a repository's setting yours, set it yourself first (`/model x`) and
then save.

---

## Requests fail

**`401` or `invalid api key`** — the key is wrong, expired, or belongs to a
different provider. `comodor doctor` shows which provider is active.

**`404 model not found`** — that provider does not serve that model id. `/model`
lists what it actually offers.

**Timeouts.** A local model on a modest machine can genuinely take minutes.
Raise `providers.<name>.timeout`.

**It stops early.** Look at `stopped`. `max_steps` and `budget` are ceilings
doing their job, not failures. Raise them for one run with `--max-steps`, or
permanently under `agent`.

---

## The spend limit is not working

It probably cannot be, and Comodor says so. See
[Cost — when the limit cannot fire](cost.md#when-the-limit-cannot-fire).

---

## The browser tool

**"no browser found"** — install Chrome, Chromium, Edge or Brave, or set
`browser.executable`. Without one, `browse` falls back to a text browser that
still answers most questions about a page.

**I want to watch it work** — `browser.headless: false`.

**It needs a login I already have** — start your own browser with a DevTools
port and set `browser.port`, so it uses that session instead of being handed
your profile.

---

## The screen tool

**It is not in the tool list.** Either this platform has no backend — Windows
only so far — or `computer.enabled` is false. Ask it:

```
/computer
```

**Clicks land in the wrong place.** This should not happen: DPI awareness is set
before any screen metric is read. If it does, please report it with your display
scaling and resolution. That is a real bug.

**It stopped by itself.** The mouse went into a corner of the screen, which ends
the grant on purpose. `/computer 15m` starts another.

**The text that arrived is not the text it typed.** The application rewrote it —
Windows 11's Notepad autocorrects as you type. Not a Comodor bug, and it says so
on every `type`. [More](computer.md#typed-is-not-the-same-as-arrived).

---

## The web interface

**It refuses to start.** No provider is configured, and the browser interface
has no way to add one. The message names what to set.

**"Unauthorised".** A new token is generated each run — use the URL from *this*
run, or set `COMODOR_WEB_TOKEN` to keep it stable.

**In Docker, nothing at `localhost:8765`.** Check the port is published as
`127.0.0.1:8765:8765`. [Docker](docker.md).

---

## Something is slow

**The first request of a session.** Nothing is cached yet; the second is much
faster.

**Reflection after each task.** One model call. Use `learning.reflect_model` for
a cheaper one, or `reflect: false`.

**Screenshots.** Around 80 ms to take, plus the model looking at them. Lower
`computer.screenshot_tokens` if you can still read the result.

---

## Starting over

```bash
comodor uninstall --dry-run     # what would go, named
comodor uninstall               # do it
```

Or just the brain, keeping your settings:

```bash
rm ~/.comodor/brain.db
```

---

## Reporting a problem

Include:

```bash
comodor --version
comodor doctor
```

`doctor` masks your key. Please read the output before pasting it anyway.

- Issues: <https://github.com/ifekri/Comodor/issues>
- Something sensitive: [SECURITY.md](../SECURITY.md)
