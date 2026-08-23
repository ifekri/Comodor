# MCP servers

The Model Context Protocol is a way for a tool to describe itself to an agent.
Comodor speaks it, so anything with an MCP server becomes something the agent
can use.

---

## Adding one

```bash
comodor mcp catalogue          # servers Comodor can set up for you
comodor mcp add filesystem     # one of them
comodor mcp list               # what you have, and what each offers
```

Something not in the catalogue:

```bash
comodor mcp custom notes -- npx -y @some/mcp-notes
comodor mcp remote github https://mcp.example.com/sse
```

Then check it actually works before trusting it:

```bash
comodor mcp test notes
```

```
  notes            started in 0.8s
    create_note    Create a note with a title and body
    search_notes   Find notes by text
    delete_note    Delete a note by id
```

---

## Turning them on and off

```bash
comodor mcp enable notes
comodor mcp disable notes
comodor mcp remove notes       # forget it entirely
```

```
/mcp                           # the same, in the interface
```

A disabled server is not started and its tools are not offered.

---

## They are tools like any other

Whatever a server provides appears alongside the built-in tools and goes through
**exactly the same permission gate**. An MCP tool that writes a file asks the way
`write_file` asks. There is no back door here.

---

## A project may declare, not enable

A repository's `.comodor/config.json` may list the servers it uses:

```json
{
  "mcp": {
    "servers": {
      "project-db": { "command": "npx", "args": ["-y", "@acme/db-mcp"] }
    }
  }
}
```

That is useful: a new person clones the repository and can see what the project
expects.

**They arrive switched off.** Naming a server is a suggestion; starting one runs
a command on your machine, and that is your decision. Enable it once you have
looked:

```bash
comodor mcp enable project-db
```

A project cannot set `mcp.enabled`, the master switch, at all.
[Safety](safety.md#what-a-repository-may-set).

---

## Transports

| | |
|---|---|
| **stdio** | a command Comodor starts and talks to over pipes. The usual |
| **Streamable HTTP** | a server already running somewhere, over HTTP |

Both are implemented in the package — no dependency for either.

---

## When one misbehaves

A server that will not start, or that takes too long, is reported and skipped.
It does not take the session down with it.

```bash
comodor mcp test <name>        # start it and see
comodor doctor                 # includes every configured server
```

---

## See also

- [What the agent can do](tools.md) — the built-in tools these join
- [Safety](safety.md) — the gate they go through
