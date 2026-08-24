# In your editor

Comodor speaks the [Agent Client Protocol](https://agentclientprotocol.com), so
an editor that supports it can drive Comodor directly — its own panel, its own
permission prompts, its own file view — with the same agent, the same learned
rules and the same transcripts as the terminal.

```bash
comodor acp
```

You will not usually type that. The editor launches it.

---

## Setting it up

Comodor prints the block your editor is asking for:

```bash
comodor acp --print-config
```

```json
{
  "agent_servers": {
    "Comodor": {
      "command": "/home/you/.local/bin/comodor",
      "args": ["acp"],
      "env": {}
    }
  }
}
```

Where it goes depends on the editor. Three that were set up and checked on a
real machine while writing this:

**JetBrains** — PyCharm, IntelliJ, WebStorm and the rest, through the AI
Assistant plugin. Put the block in `~/.jetbrains/acp.json`, or use *Add Custom
Agent* from the AI Chat window's menu, which opens the same file. Comodor then
appears in the agent picker at the bottom of the chat panel. No JetBrains AI
subscription is needed for this — ACP agents work without one.

**VS Code** — install an ACP client extension; [ACP
Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client)
is the one this was checked against. The block goes under `acp.agents` in
`settings.json`, and Comodor appears in the ACP panel's agent list.

**Zed** — `settings.json`, and Comodor appears in the agent panel.

Also reported to work, though not checked here: Neovim (CodeCompanion,
avante.nvim, agentic.nvim), Emacs (agent-shell.el), Qt Creator, Obsidian and
Visual Studio.

The protocol is the same everywhere; only the settings file differs.

Set Comodor up first, in a terminal:

```bash
comodor setup
```

An editor has nowhere to ask which provider to use, so a Comodor that has never
been configured refuses to start a session and says which command to run. That
is a clear message in the editor rather than a failure on the first task.

---

## What the editor gets

| | |
|---|---|
| Streaming replies | as the model writes them |
| Tool calls | each one named, with what it did, and marked read / edit / execute so the editor can pick an icon |
| Permission prompts | asked in the editor, answered in the editor |
| Plans | when Comodor writes a task list, the editor draws it |
| Cancellation | the editor's stop button interrupts the turn |
| Sessions | listed, resumed and deleted — the same transcripts `comodor` resumes |

The working folder comes from the editor: whichever project you have open is
where the agent reads and writes, and it is confined to it.

---

## What it does not do

**Take a model provider from the editor.** Comodor's provider, model, rules,
skills and permissions are its own, configured with `comodor setup` or in the
browser interface. An editor that also wants to configure a model would be a
second source of truth for the same setting.

**Log in.** Comodor authenticates to a model provider, not to your editor, so
it advertises no authentication methods and a client will not offer you a
login.

---

## When something is wrong

The protocol reserves standard output for messages, so Comodor's logs go to
standard error. Editors usually show that somewhere — in Zed it is the agent
server's log.

```
comodor acp — speaking ACP v2 on stdio
```

A common one, and it looks like a broken agent rather than what it is: the
provider refusing your key. It arrives in the editor as `Error during prompt
turn`, or as the provider's own words — `OpenRouter: User not found`, for
instance, which means the key has been revoked. `comodor doctor` says which
provider is configured; the browser interface will take a new key, or sign you
in.

If the agent connects and then does nothing, run `comodor doctor` in a terminal
first: an unreachable provider looks the same from an editor as a broken agent.

---

## See also

- [From a browser](web.md) — the same agent, in a browser tab
- [The interface](interface.md) — the terminal version
- [Safety](safety.md) — what it asks before, and what it never does
