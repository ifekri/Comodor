# Safety and permissions

What Comodor can do to your machine, what it asks about first, and what it will
not do whatever you say.

---

## The short version

- **Reading is silent.** Listing files, reading them, searching — no prompt.
- **Writing asks.** You see the diff before it happens.
- **Running a command asks louder**, and so does reaching the network or
  driving your screen.
- **Every write is checkpointed first**, so the previous contents are kept.
- **It cannot leave the project folder** unless you turn that off.
- **A repository cannot change any of the above.**

---

## Risk tiers

Every tool declares one. The tier decides what happens before it runs.

| Tier | Tools | What happens |
|---|---|---|
| **safe** | `read_file`, `list_dir`, `grep`, `glob`, `todo_write` | runs |
| **write** | `write_file`, `edit_file` | asks, with a diff |
| **dangerous** | `run_shell`, `run_python`, `web_fetch`, `web_search`, `browse`, `computer` | asks |

In **plan mode**, anything above `safe` is refused before it runs. That is
enforced at the permission layer, not by asking the model to behave.

In **chat mode** there are no tools at all.

---

## The prompt

```
  Run  pytest tests/ -x
  ────────────────────────────────────────────
  in ~/projects/api-server

  Allow   ·   Allow for this session   ·   Deny
```

Arrows move between the choices and `Enter` sends; `Esc` denies. *Allow for
this session* remembers for the session, per kind of thing — allowing writes
does not allow commands, and allowing `pytest` does not allow `rm`.

To stop being asked, choose *Allow for this session* on the card — it remembers
per kind of thing — or permanently, in your config:

```json
{
  "safety": {
    "auto_approve_writes": true,
    "auto_approve_shell": false
  }
}
```

### Denying teaches it

A refusal is the clearest preference signal the interface ever collects. It goes
to the learning engine, so the agent is less likely to propose the same thing
again. Denying is not wasted effort.

---

## Checkpoints

Every file the agent writes is checkpointed first — the previous contents, kept
under `.comodor/checkpoints/` in the project, content-addressed, with a journal
of which file each snapshot belonged to. This happens whether or not you
approved the write, and whether or not auto-approval is on.

There is no command that restores one yet; the store is there so nothing the
agent overwrote is lost, and a project under version control has its own
history beside it.

Switch it off if you must:

```json
{ "safety": { "checkpoints": false } }
```

There is no good reason to.

---

## The workspace boundary

The agent may read and write **inside the project folder and nowhere else**.

The project root is found by walking up from where you started until something
says "this is a project" — a `.git`, a `pyproject.toml`, a `package.json`. You
are shown it and asked, once per folder:

```
  Work in  /home/you/projects/api-server ?
```

Approved folders are remembered. `--cwd` names one directly and does not ask.

```json
{ "safety": { "workspace_only": true } }
```

Turning this off lets the agent touch your whole filesystem. It is off-limits to
a repository's config for exactly that reason.

---

## Commands it will not run

Some things are refused before any prompt appears, because no prompt should be
able to talk a person into them at the end of a long session:

```
rm -rf /     rm -rf ~     mkfs        dd if=      shutdown
reboot       format c:    del /f /s /q c:         :(){
> /dev/sda   chmod -R 777 /
```

The full list is `safety.deny_commands`. Add your own:

```json
{
  "safety": {
    "deny_commands": ["terraform destroy", "kubectl delete namespace"]
  }
}
```

`safety.allow_commands` is the other direction — commands that never prompt:

```json
{ "safety": { "allow_commands": ["git status", "pytest", "ls"] } }
```

---

## Your keys

**Where they live.** Your own `~/.comodor/config.json`, written with owner-only
permissions, or your environment. Nowhere else.

**Where they never go.** Not a repository's config. Not the interface. Not a log.
Not a `repr` — that one was a real bug, found and fixed: any traceback naming a
Config used to print the key, and pytest prints tracebacks constantly.

**A key in your environment stays there.** If you export `ANTHROPIC_API_KEY`
rather than saving it, `comodor setup` will not copy it into your config file. Exporting
rather than saving is a decision and it is respected.

**Redaction.** Anything that looks like one of your keys is masked in tool
output, in the transcript, and in exports. It works on text. It cannot read
pixels — see [Using your screen](computer.md#what-goes-to-the-model).

---

## What a repository may set

A `.comodor/config.json` in a project is read from whatever directory you
started in — which for a coding agent means *from a repository somebody else
wrote, immediately after cloning it*.

So it is restricted to things that cannot be turned against you:

| A project may set | |
|---|---|
| `provider`, `model` | which model to use |
| `agent` | mode, loop, the budgets, temperature, output size |
| `ui` | theme, borders, banner |
| `learning`, `skills` | whether they are on, and their limits |
| `mcp.servers` | which servers it uses — **arriving switched off** |

| A project may **not** set | because |
|---|---|
| `providers.*.base_url` | your key would go to their server on the first request |
| `safety.*` | it could stop the agent asking, or empty the deny list |
| `agent.system_prompt_extra` | instructions injected with your authority |
| `browser.executable` | it names a binary for the agent to launch |
| `computer.*` | it asks the machine it was just cloned onto for your mouse |
| `mcp.enabled` | declaring a server is a suggestion; starting one is a decision |

This is an **allow-list**, not a deny-list, so a setting added next year is
untrusted until somebody decides otherwise — the right way round to be wrong.

Refusals are said out loud:

```
config: this project cannot set safety, computer — only your own can
```

Silently ignoring somebody's file is how a config file gets a reputation for
not working.

---

## Ceilings

Three, and they apply to every task:

```json
{
  "agent": {
    "max_steps": 24,
    "max_seconds": 900,
    "max_cost_usd": 2.0
  }
}
```

**The money one only works for a model with a published rate.** For a model the
pricing table does not know, the cost meter reads zero and the limit never
fires. Comodor says so rather than letting you believe you have a ceiling:

```
the $2.00 spend limit cannot be enforced for gpt-4o — no published rate is
known, so the cost meter reads zero. The step and time limits still apply.
```

Said at the start of a session and in `comodor doctor`. See [Cost](cost.md).

---

## Sub-agents

`delegate` runs a sub-agent in a git worktree — an isolated copy of the
repository. It has no memory, cannot delegate further, and **is not given the
screen**: a sub-agent working in a worktree has no business taking your mouse.

---

## Reporting something

If you find a security problem, please do not open a public issue. See
[SECURITY.md](../SECURITY.md).

---

## See also

- [Using your screen](computer.md) — the strictest permission model here
- [Configuration](configuration.md) — where every setting lives
- [The interface](interface.md#approvals) — what the prompts look like
