# Coming from another agent

If you already use **OpenClaw** or **Hermes**, Comodor offers to bring your
setup across the first time you run it.

You have already found your API keys and pasted them somewhere. Doing it again
is a poor first impression.

---

## On the first run

```
 1/6  You already use OpenClaw
  OpenClaw  1 API key, the model (claude-sonnet-5), 1 skill
  /home/you/.openclaw

  Nothing is moved and nothing already set here is replaced.
  Keys are copied into your config; the other tool keeps working.

  1.  bring it over   keys, model and skills
  2.  keys only       leave the skills and the model
  3.  start fresh     import nothing
```

The question only appears when there is something to import.

---

## Afterwards

Installed one of them later, or answered "start fresh" and changed your mind:

```bash
comodor import              # bring it across
comodor import --dry-run    # say what it would take, change nothing
comodor import --keys-only  # leave the skills and the model
```

Running it twice is safe — the second time it says there is nothing new.

---

## What comes over

| | |
|---|---|
| **API keys** | the whole of the tedium. From their `.env`, and from OpenClaw's inlined JSON |
| **The model** | if Comodor can host it |
| **Skills** | both tools write the same open format, so these are files to copy |

Three rules throughout, because this reads another program's files:

- **Nothing is overwritten.** A key already configured here wins; the import
  fills gaps.
- **Nothing is moved.** Every read is a read. The other tool keeps working
  exactly as it did.
- **A malformed file is skipped, not fatal.** Half the value is that it runs on
  a machine whose other agent is in an odd state.

---

## What does not, and why

**Their memory.** Said out loud rather than skipped in silence:

```
not imported: MEMORY.md — its memory is prose; this agent's is lessons with
confidence and evidence, and inventing those would poison recall
```

Comodor's brain is lessons with a confidence, evidence and a decay, learned from
corrections. A `MEMORY.md` is prose. Importing one as the other would invent
confidences nobody measured and fill recall with entries that were never earned.
You would get a worse agent that looked like a better-informed one.

**Personas, messaging, text-to-speech.** Comodor has no equivalent, and a
setting imported into nothing is worse than no setting.

**A key stored somewhere else.** OpenClaw lets a key be a reference to a file or
a command. Those mean something on the machine they were written for and nothing
here, so they are reported rather than guessed at.

---

## Skills, and one thing worth knowing

Imported skills are namespaced — `review` becomes `openclaw-review` — so an
import can never quietly replace one of your own.

A skill folder is copied file by file, and **a folder containing a link out of
itself is refused**. A skill is a file whose contents are read into a prompt, so
a symlink to `~/.ssh/id_rsa` sitting in another program's skills directory would
otherwise have been copied in and sent to a model. Refused, and named:

```
not imported: the skill sneaky — it contains a link out of that folder
```

---

## Where it looks

| | |
|---|---|
| OpenClaw | `~/.openclaw`, `~/.clawdbot`, `~/.moltbot` |
| Hermes | `~/.hermes` |

The older OpenClaw directories are still on real machines — it was renamed
twice — so all three are checked.

To stop it looking at all:

```bash
export COMODOR_NO_IMPORT=1
```

---

## See also

- [Getting started](getting-started.md) — the rest of the first run
- [Configuration](configuration.md) — where the imported settings end up
- [Skills](skills.md) — what to do with the ones that came across
