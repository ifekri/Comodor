# Models on your own machine

Comodor can download a model, keep it on your disk, and run it there — no key,
no account, and it keeps working with the network unplugged.

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4    # make it the one the agent talks to
```

The same list is in the browser under **Admin → Local LLM**, with the same
download, the same progress and the same buttons.

## How this is put together, and why it is not slow

Everything credible does the same thing — Ollama, LM Studio, llama.cpp, vLLM —
and Comodor does it too: **inference runs in a separate process that speaks an
OpenAI-compatible API, and the model stays loaded in it between requests.**

Three reasons, all about the agent staying responsive:

**The GIL.** Generation is a long CPU-bound loop. Run it in Comodor's own
process and every other thread — the interface repainting, a tool finishing,
the event bus — waits behind it. In another process it is another core's
problem.

**Loading is expensive and must happen once.** Reading four gigabytes off disk
and laying it out takes seconds to tens of seconds. Loading per request pays
that every turn; a resident server pays it once and answers in milliseconds
after.

**A crash stays over there.** An out-of-memory kill on a 14B model ends the
model server, not your session. The agent reports a connection error and the
transcript survives.

The happy consequence is that there is almost no new code: a local server on
`http://127.0.0.1:PORT/v1` *is* an OpenAI-compatible endpoint, so the existing
provider drives it unchanged. The port is chosen when the server starts, which
is why the `local` provider carries no URL in the configuration — one written
there would be wrong the next time.

The server starts on your **first message**, not at startup. Loading four
gigabytes every time you ran `comodor` — including the times you never asked
the model anything — would be a blank screen for no reason.

## What you need

The model file, which Comodor downloads, and something to run it. Comodor uses
whichever it finds:

```bash
brew install llama.cpp          # macOS
winget install llama.cpp        # Windows
                                # Linux: github.com/ggml-org/llama.cpp
```

Ollama or LM Studio, if either is already running, work too. `comodor local
list` says plainly when nothing is available, so you find out before spending
an hour on a download rather than after.

## The download

A model is one to nine gigabytes over your home line, and everything about the
download is shaped by that.

**It resumes.** Bytes go to a `.part` file. Stop it, close the laptop, lose the
connection — the next `comodor local get` asks the server to continue from
where that file ends. The browser shows `Resume (37%)` instead of `Download`.

**It is verified.** Every catalogue entry carries an exact byte count and a
SHA-256, and the file is not accepted until it matches. This is not
belt-and-braces: a truncated GGUF is *not* obviously broken — it loads, and
then the model produces nonsense, and you spend an evening wondering why a
well-regarded model is useless. A file that fails is deleted rather than left
to be found later and half-trusted.

**It is watchable.** In the terminal, a bar with the four numbers that answer
the question being asked:

```
qwen2.5-coder-7b-q4 ━━━━━━━━━━━━━━╸────────  38.2%  1.7/4.4 GB  8.9 MB/s  0:05:12
```

In the browser, the same numbers under a bar on the model's card, updating from
the event stream rather than by polling.

## Where the files go

One directory, shared by every project on the machine — the same model in three
checkouts would otherwise be three copies of the same bytes.

```bash
comodor local where
```

`comodor local remove <id>` deletes one, and says how much came back.

## Adding a model to the list

The list is a JSON file, so a new model is an edit rather than a release. Both
the terminal and the browser pick it up.

```json
{
  "id": "my-model-q4",
  "name": "My Model 7B",
  "description": "One sentence on what it is good at, and what it is not.",
  "url": "https://huggingface.co/OWNER/REPO/resolve/main/file.gguf",
  "size": 4683074336,
  "sha256": "1664fccab734674a...",
  "context": 32768,
  "parameters": "7B",
  "quantization": "Q4_K_M",
  "needs_ram_gb": 8,
  "license": "apache-2.0",
  "good_at": ["code"],
  "tools": true,
  "vision": false
}
```

`id`, `name`, `url` and `size` are required — everything else is optional, and
anything you leave out is reported as unknown rather than guessed. A wrong
number here costs somebody a download and a crash.

Get the size and checksum from the API rather than typing them:

```bash
curl -s 'https://huggingface.co/api/models/OWNER/REPO?blobs=true' | python -c \
  "import json,sys;[print(f['rfilename'], f['size'], f.get('lfs',{}).get('sha256')) \
   for f in json.load(sys.stdin)['siblings'] if f['rfilename'].endswith('.gguf')]"
```

Two rules the loader enforces:

- **`https` only.** A model file is an executable artefact in every way that
  matters, and one fetched over a channel somebody can rewrite in flight is not
  something to allow because a catalogue asked for it.
- **One bad entry does not cost the list.** A malformed model is skipped and
  the rest load, because the alternative is an empty picker.

Comodor ships a copy of the list and looks for a fresher one once a day, caching
what it finds. With no network it uses the cache, and failing that the copy that
shipped — which is the whole point of shipping one.

## What it will not do

`needs_ram_gb` is checked against your machine before the download starts, and a
model that will not fit says so rather than letting you spend an hour finding
out. `comodor local get --yes` overrides it if you disagree.

Disk is checked the same way, with a tenth left spare: a download that fills the
last byte of a disk does not just fail, it takes the rest of the machine with
it.
