# In Docker

The agent, its browser and everything it needs, in one container.

```bash
git clone https://github.com/ifekri/Comodor.git
cd Comodor
export ANTHROPIC_API_KEY=…        # or OPENAI_API_KEY, OPENROUTER_API_KEY, …
docker compose up
```

It builds the image the first time, then prints the address:

```
  Comodor is at  http://127.0.0.1:8765/?token=…
  Working in     /work
```

Open the link. A new token every run, so use the one from *this* run — and if
you started it detached, `docker compose logs comodor` prints it again.

Or without cloning anything:

```bash
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -e ANTHROPIC_API_KEY \
  -v "$PWD:/work" \
  ghcr.io/ifekri/comodor:latest
```

---

## A key, or the page will ask for one

Set one and it is ready the moment you open the link. Without one it still
starts, and the page asks — the browser interface can take a key now, and a
container that refused to start was unreachable for exactly the person most
likely to want it: somebody whose Comodor is on a server, with no terminal in
front of them.

The logs say so before you open anything:

```
No provider is configured yet — the page will ask when you open it.
```

Compose passes through whichever of these is set in your shell, without writing
it into the image or the compose file:

```
ANTHROPIC_API_KEY   OPENAI_API_KEY    OPENROUTER_API_KEY   DEEPSEEK_API_KEY
GOOGLE_API_KEY      GROQ_API_KEY      XAI_API_KEY          MISTRAL_API_KEY
MOONSHOT_API_KEY    ZAI_API_KEY       DASHSCOPE_API_KEY    TOGETHER_API_KEY
FIREWORKS_API_KEY   CEREBRAS_API_KEY  XIAOMI_API_KEY
```

Prefer a file to your shell history? Put it in a `.env` beside the compose file
— compose reads that, and it is git-ignored.

---

## Where it works

Everything the agent can touch is the `work/` folder beside the compose file.
Point it somewhere else without editing anything:

```bash
COMODOR_WORKDIR=/path/to/your/project docker compose up
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

**Nothing is pinned by default.** A build installs the newest release, so the
image cannot fall behind the project — which is what happened when these files
lived on a branch of their own and spent eleven releases describing 0.9.0.

For a reproducible build, name one:

```bash
COMODOR_VERSION=0.21.0 docker compose build
docker build --build-arg COMODOR_VERSION=0.21.0 .
```

The published image is rebuilt on every release, so `ghcr.io/ifekri/comodor:latest`
is the newest one and `ghcr.io/ifekri/comodor:0.21.0` is that release.

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
