# From a browser

The same agent, in a browser tab. On this machine, or on a server you reach over
SSH.

```bash
comodor web
```

```
   ______                          __
  / ____/___  ____ ___  ____  ____/ /___  _____
 / /   / __ \/ __ `__ \/ __ \/ __  / __ \/ ___/
/ /___/ /_/ / / / / / / /_/ / /_/ / /_/ / /
\____/\____/_/ /_/ /_/\____/\__,_/\____/_/

  it learns the way you correct it   0.9.0  ·  claude-sonnet-5

  Comodor is at  http://127.0.0.1:8765/?token=EYhO9St_VTy95k4gHtJytb
  Working in     /home/you/projects/api-server

  Only this machine can reach it. Ctrl-C to stop.
```

Open the link. The token is in it.

---

## Options

```bash
comodor web --port 9000
comodor web --no-browser            # do not open one for me
comodor web --token mytoken         # a fixed token
comodor web --host 0.0.0.0          # reachable from elsewhere — read below
```

---

## The token

A new one every run, so a URL from yesterday is not a way in today. It arrives
in the URL, is exchanged for a cookie, and every request after that is
authorised by the cookie.

To keep it stable across restarts:

```bash
export COMODOR_WEB_TOKEN=something-long-and-random
```

Anyone with the token has a shell on that machine. Treat it as one.

---

## Binding to more than loopback

`--host 0.0.0.0` puts the interface on every interface of the machine. **This
port is a shell.** Comodor says so rather than assuming you meant it:

```
  Listening on every address on this machine.
  Anyone who can reach this port can run commands as you.
```

Better, when the agent is on a server: leave it on loopback and tunnel.

```bash
ssh -N -L 8765:127.0.0.1:8765 you@server
```

Then open `http://127.0.0.1:8765` locally. The port is never exposed and SSH
does the authentication.

---

## Watching it use a screen

If the agent is driving a desktop, the frame it looked at appears in the
interface with a marker where it acted:

```
┌────────────────────────────────────────────┐
│                                            │
│   [ the screen the model saw ]      ✛      │
│                                            │
│   clicking Save                            │
└────────────────────────────────────────────┘
```

This is the point of it. The on-screen overlay draws on the machine being
driven, which is no use when that machine is a server or a container — the panel
is how you watch from somewhere else.

The picture is fetched once per frame from `/api/screen`, not carried in the
event stream: a screenshot is about a megabyte, and a browser re-reading the
event log would download every frame it had ever seen.

[Using your screen](computer.md).

---

## What it will not do

**Start without a provider.** It can switch between providers that are already
set up, but there is nowhere in it to type a key, and a browser tab would be a
poor place for one. Rather than serve a URL that fails on the first task, it
says what is missing and stops:

```
Comodor has no provider configured, and the browser interface has no way to
add one.

  In Docker, pass a key in as an environment variable:
    -e ANTHROPIC_API_KEY=...    -e OPENAI_API_KEY=...
  or mount a config file at ~/.comodor/config.json.
  Anywhere with a terminal, `comodor setup` asks a few questions.
```

At a terminal it asks the setup questions instead. In a container it always
prints the message — a container has a terminal whether or not anybody is
attached, and a detached one would otherwise wait forever on a question nobody
can answer.

**Widen what the agent may touch.** Auto-approval for writes and for commands
is shown in Admin and cannot be changed there. The permission prompts already
offer that choice per action, in front of the person who will live with it;
a page reachable by anyone holding the link is the wrong place to make it
standing policy. Change it where Comodor was started — see
[Safety](safety.md).

---

## What is on the screen

**The conversation**, streaming as it arrives, with fenced code kept as code
and every tool call as a row you can open to see what it actually did.

**The chat list**, on the left. Every conversation is written to
`~/.comodor/sessions` — the same folder the terminal uses, so a chat begun at
the prompt is openable in the browser and the other way round. Search looks
inside them, not just at their titles.

**Admin**, the second tab, which is the answer to "what is this thing about to
do to my machine":

| | |
|---|---|
| Model | which provider and model is answering, and switching between the ones you have keys for |
| How it runs | the mode, whether it keeps going on its own, and the four ceilings — context, steps, time, spend |
| Permissions | what it may do without asking, what it will ask about, and what has been granted this session |
| What it has learned | rules, lessons, skills, tasks, and how many of them succeeded |
| Tools | every tool it can reach, colour-coded by risk, plus your skills and any MCP servers |
| This machine | version, Python, and where the settings, chats and brain live |

**The status strip** along the bottom: whether the page is connected, the
working folder, how full the context is, what the session has cost, and how
many learned rules are in force.

**The screen panel**, when the agent is driving one — the frame it last looked
at, with a marker where it is about to click. See [Using your
screen](computer.md).

---

## Keyboard

| | |
|---|---|
| `Enter` | send |
| `Shift`+`Enter` | new line |
| `Esc` | stop the current task, or close the sidebar |
| `Ctrl`/`⌘`+`K` | search the chats |
| `Ctrl`/`⌘`+`B` | show or hide the sidebar |
| `/` | jump to the message box |

---

## On a phone

The same page. Below 900 pixels the chat list becomes a drawer over the
conversation rather than a column beside it, because 292 pixels of sidebar on
a 390-pixel screen leaves nothing wide enough to read code in. Tap outside it,
press `Esc`, or use the close button to put it away.

Reach it from your phone the way you would reach anything else on your
machine — an SSH tunnel, not a public bind. [Binding to more than
loopback](#binding-to-more-than-loopback) explains why.

---

## Writing in any language

Type in Persian, Arabic or Hebrew and the message box turns around as you
type; answers in those languages are set right-to-left when they arrive.
Nothing is configured and there is no language setting: each message is
judged on its own, so a conversation that moves between languages moves with
it.

The judgement is by counting rather than by first letter, which is what makes
the two awkward cases come out right — a Persian sentence that opens with a
package name is still Persian, and an English sentence quoting one Persian
word is still English. Code, paths and URLs are set left-to-right inside a
right-to-left paragraph, where they belong.

Arabic-script text is set in Vazirmatn, which travels inside the package
rather than being fetched from a font host: this has to work on a machine that
cannot reach the internet. It applies to Arabic-script characters and to
nothing else, so a line mixing Persian with an English identifier gets the
right face for each.

---

## Light and dark

Follows the system by default; the sun in the top right switches it and the
choice is remembered in that browser.

---

## In Docker

```bash
docker compose up
```

and open the address it prints. [Docker](docker.md).

---

## See also

- [Docker](docker.md) — the same thing in a container
- [The interface](interface.md) — the terminal version
- [Safety](safety.md) — the permissions the Admin tab reports
- [Using your screen](computer.md) — what the frame panel is showing you
