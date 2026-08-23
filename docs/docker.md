# In Docker

The agent, its browser and everything it needs, in one container.

```bash
git clone -b docker https://github.com/ifekri/Comodor.git comodor-docker
cd comodor-docker
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

It builds the image the first time, then prints the address:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Open the link. A new token every run, so use the one from *this* run.

Or without cloning anything:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## A key is not optional here

The browser interface has no way to enter one, so without a key the container
says what is missing and stops rather than serving a URL that fails on the first
task.

Compose passes through whichever of these is set in your shell, without writing
it into the image or the compose file:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY   OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GEMINI_API_KEY      GROQ_API_KEY     XAI_API_KEY          MISTRAL_API_KEY
XIAOMI_API_KEY
```

Prefer a file to your shell history? Put it in a `.env` beside the compose file
— compose reads that, and it is git-ignored.

---

## Where it works

Everything the agent can touch is the `work/` folder beside the compose file.
Point it somewhere else:

```yaml
volumes:
  - "/path/to/your/project:/work"
```

What it learns — the brain, your corrections, session transcripts — lives in a
named volume, so it survives `docker compose down` and is forgotten by
`docker compose down -v`.

---

## Who can reach it

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

**The `127.0.0.1` on the left is the whole security model.** Drop it and the
port is on every interface of the machine — and this port is a shell.

Inside the container Comodor binds `0.0.0.0`, which is not a lapse: a container
has its own network namespace, so binding loopback inside one hides the port
from the machine running it. Who may actually reach it is decided by how the
port was published, and the banner says so.

---

## What the container may do

```yaml
cap_drop: [ALL]
security_opt:
  - no-new-privileges:true
```

It runs shell commands, so the container is what stands between those and your
machine. It is given nothing it does not need, and runs as a non-root user.

---

## Pinning a version

```yaml
args:
  COMODOR_VERSION: "0.9.0"
```

Pinned by default so a rebuild is reproducible. For the newest release instead:

```bash
docker compose build --build-arg COMODOR_VERSION=
```

---

## Running something else in it

```bash
docker compose run --rm comodor comodor doctor
docker compose run --rm comodor sh
```

No arguments, or arguments starting with a dash, mean "run the web interface
with these options". Anything else is a command to run instead.

---

## What is not in the container

**Your screen.** [Desktop control](computer.md) drives the machine Comodor is
running on, and in a container that is a machine with no display. The tool is
not offered there.

The [browser](browser.md) does work — Chromium and its fonts are in the image.

---

## If it will not start

**Nothing at `localhost:8765`** — check the port is published:
`docker compose ps`.

**It exits immediately** — read the log. Almost always no provider configured;
the message says what to set.

**`exec /usr/local/bin/comodor-start: no such file or directory`** — a CRLF
checkout. Fixed in the branch with a `.gitattributes`; if you see it, pull.

---

## See also

- [From a browser](web.md) — the interface you will be using
- [Safety](safety.md) — what the agent may do inside the container
