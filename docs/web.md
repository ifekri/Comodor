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

**Start without a provider.** The browser interface can change the mode and
nothing else — there is no way to enter an API key from it. Rather than serve a
URL that fails on the first task, it says what is missing and stops:

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

---

## What you get

Everything the terminal interface has, except the keyboard shortcuts:

- Streaming replies
- The tool rows, with what each one did
- Approval prompts, answered in the page
- The mode buttons — act, plan, chat
- Stop
- Right-to-left text, set correctly

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
- [Using your screen](computer.md) — what the frame panel is showing you
