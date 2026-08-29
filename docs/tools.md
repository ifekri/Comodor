# What the agent can do

Thirteen tools. Each declares a risk tier, which decides whether it asks first —
see [Safety](safety.md#risk-tiers).

---

## Files

| | Risk | |
|---|---|---|
| `read_file` | safe | Read a text file. Streams, so a slice of a large log is reachable |
| `list_dir` | safe | Entries of a directory, with sizes |
| `glob` | safe | Find files by name pattern — `src/**/*.py` |
| `grep` | safe | Search contents with a regular expression |
| `write_file` | write | Create a file or replace it entirely |
| `edit_file` | write | Replace an exact string in a file |

Everything is confined to the project folder unless you turn
`safety.workspace_only` off.

`edit_file` is preferred over `write_file` for a change to an existing file: it
is smaller, it is reviewable as a diff, and it cannot silently lose the rest of
the file.

**`edit_file` finds the text you meant.** Exact match first, always. If that
finds nothing it tries again ignoring line endings, then trailing whitespace,
then indentation — and says which one worked:

```
Edited src/api/routes.py (+2/-1). Matched after normalising line endings.
```

Never silently: an edit that landed somewhere slightly different from what was
asked for and said nothing is worse than one that refused. And if relaxing the
match turns one target into several, that step is abandoned rather than
guessed at — the information that told them apart is what was just dropped.

When nothing matches, the error names the closest few places and diffs the
nearest, so the next attempt can be right instead of another guess.

**Both check what they wrote.** The file is parsed straight after the write and
anything wrong with it goes back to the model in the same tool result:

```
Edited src/api/routes.py (+3/-1).

WARNING  SyntaxError at line 42: unexpected indent. The file was written as
given — read it and fix it.
```

So a broken file is found in the turn that broke it rather than by you, an hour
later. Python, JSON and TOML are parsed in process and cost microseconds;
JavaScript uses `node --check` when `node` is on your path; anything else is
left alone, because a warning that is usually wrong is worse than no warning.

It never refuses the write — half a refactor leaves a file inconsistent, and
the second edit of the pair has to be possible. `safety.verify_edits: false`
turns it off.

---

## Running things

| | Risk | |
|---|---|---|
| `run_shell` | dangerous | A shell command in the workspace |
| `run_python` | dangerous | A short Python snippet, in a subprocess |

Both ask before running, both are subject to `safety.deny_commands`, and both
have their output bounded — see [When output is too big](#when-output-is-too-big).

In the interface you can skip the model entirely:

```
!git status
```

Runs it, shows you the output, and never mentions it to the model. Faster and
cheaper than asking.

---

## The web

| | Risk | |
|---|---|---|
| `web_fetch` | dangerous | Download a URL and return its readable text |
| `web_search` | dangerous | Search, and return titles, URLs and snippets |
| `browse` | dangerous | A real browser — JavaScript, cookies, logins |

`web_fetch` is the cheap one: it strips the page to text. Use it when the page is
a document.

`browse` is for when it is an application — something that needs JavaScript, a
login, or a click. [Full guide](browser.md).

---

## The machine

| | Risk | |
|---|---|---|
| `computer` | dangerous | Mouse, keyboard and screen, in any application |

Off unless you switch it on, and then still not allowed until granted.
[Full guide](computer.md). Windows only so far.

---

## Keeping track

| | Risk | |
|---|---|---|
| `todo_write` | safe | The task list you see in the sidebar |

The agent writes its own plan here. It is not decoration — it is how a long task
stays coherent, and how you can see where it is.

---

## Sometimes there, sometimes not

Comodor only offers a tool the model could actually use. A tool it can see and
can never use successfully invites a wasted call on every turn.

| | Appears when |
|---|---|
| `read_skill_file` | a skill you have installed bundles files |
| `search_history` | there are past sessions to search |
| `delegate` | a sub-agent could be spawned |
| `computer` | the platform has a backend **and** you enabled it |
| MCP tools | a server is configured and enabled |

`browse` has two implementations: the real browser when Chrome, Chromium, Edge
or Brave is installed, and a text browser when none is. Both are called
`browse`, because choosing between two things called "browser" is a turn the
model should not have to spend.

---

## When output is too big

A command that prints fifty thousand lines does not get truncated into
uselessness and it does not blow up the context.

What fits goes to the model — the head and the tail, since that is where the
answer usually is. The rest is written to a file under `~/.comodor/output/`, and
the model is told the path and how to read it. So it can go and look if it needs
to, and pays nothing if it does not.

```json
{ "agent": { "max_tool_chars": 12000 } }
```

---

## Sub-agents

`delegate` runs a second agent in a **git worktree** — an isolated checkout of
the same repository. It works there, and its changes come back as a patch
applied with a three-way merge.

It has no memory, cannot delegate further, and is not given the screen. It
inherits the parent's cancellation, so `Esc` stops it too.

Useful for something genuinely separate — "port this module to the new API while
I keep working" — and wasteful for anything else.

---

## MCP tools

Anything an enabled Model Context Protocol server provides appears alongside the
built-in tools and goes through exactly the same permission gate.

```bash
comodor mcp list
```

[Full guide](mcp.md).

---

## See also

- [Safety and permissions](safety.md) — what each tier means in practice
- [The interface](interface.md) — watching tools run
- [Skills](skills.md) — teaching it *how* to use these for a particular job
