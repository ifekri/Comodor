# Comodor in Docker

The agent, its browser and everything it needs, in one container. It starts the
web interface and prints the address to open.

```bash
docker compose up
```

That is the whole thing. It builds the image the first time, then:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Open the link it printed. The token is in it, and a new one is generated every
run, so use the URL from *this* run's output.

---

## Before the first run

One thing: a key for whichever model you use. Comodor reads it from the
environment, and compose passes yours through without writing it anywhere.

```bash
export ANTHROPIC_API_KEY=…      # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

If you would rather not set one now, it still starts — the interface will say
no provider is configured.

## Where it works

Everything the agent can touch is the `work/` folder beside this file. Put your
project there, or point somewhere else:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

What it learns — the brain, your corrections, session transcripts — lives in a
named volume and survives `docker compose down`. `docker compose down -v`
forgets it.

## Without compose

One command, no files:

```bash
docker run --rm -it \
  -p 127.0.0.1:8765:8765 \
  -v "$PWD:/work" \
  -e ANTHROPIC_API_KEY \
  ghcr.io/ifekri/comodor
```

Or build it yourself from this branch: `docker build -t comodor .`

## Other things to run

Anything after the image name runs instead of the web interface:

```bash
docker compose run --rm comodor doctor
docker compose run --rm comodor run "read the tests and tell me what is missing"
docker compose run --rm comodor sh
```

---

## Two things worth knowing

**This port is a shell.** Comodor runs commands and edits files, so anyone who
can reach the port and has the token can run things on this machine, inside the
container. The `127.0.0.1:` at the front of the port mapping is what keeps that
to you, and it is not decoration:

```
-p 127.0.0.1:8765:8765     only this machine        ← what compose does
-p 8765:8765               anyone who can route to it
```

There is no TLS here. To use it on a remote server, run it there bound to
loopback and reach it through a tunnel:

```bash
ssh -N -L 8765:127.0.0.1:8765 you@your-server
```

**Chromium runs without its own sandbox in here**, and says so on the first
page it opens. It isolates each renderer in a user namespace, which Docker's
default seccomp profile does not allow. The alternative is to relax the
container's seccomp so the browser's inner sandbox can work, and that is the
worse trade: it weakens the strong outer boundary to enable the weaker inner
one. So the container keeps its confinement — non-root, no capabilities, no new
privileges — and the browser gives up its own.

On your laptop, outside a container, the browser keeps its sandbox. Nothing
here changes that.

## What is in the image

Python 3.13, Comodor from PyPI, Chromium, git, ripgrep. About 1.4 GB, most of
it the browser — which is there because the browser tool drives one the machine
already has, and a container has none.

It runs as an ordinary user, not root, so a command the agent runs cannot
rewrite the ownership of your files through the mount.
