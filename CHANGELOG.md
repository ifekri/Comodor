# Changelog

Notable changes to Comodor. Versions follow [semantic versioning](https://semver.org).

## 0.3.1 — 2026-08-21

### `comodor update`

- Moves to the newest published version using whatever put this copy here — uv,
  pipx, pip, or the environment the installer built. Guessing wrong is worse
  than not offering the command: `pip install --upgrade` inside a uv tool
  environment appears to work and leaves uv's record pointing at a version that
  is gone.
- It runs the new one afterwards and asks what version it is, and that answer is
  what gets printed. That check earned its place immediately: `uv tool upgrade`
  on a tool installed as `comodor==0.2.3` exits zero having done nothing, because
  the recorded requirement pins it. When the version does not move, it
  reinstalls from the index and says that is what happened.
- `--check` reports what is available and changes nothing.
- A source checkout is refused, with the directory named: `git pull` is the
  upgrade there, and overwriting a working tree with a release throws away work
  that was never committed.
- On Windows the upgrade is handed to a detached process that waits for this one
  to exit, because a running program cannot replace its own executable — and is
  reported as started rather than finished, because nothing here can see how it
  ends.
- `comodor doctor` now mentions a newer release, on a short timeout and silently
  when there is no network. It is never a `--fix`: a diagnostic must not change
  what is installed under somebody unasked.

## 0.3.0 — 2026-08-20

### A browser, not a fetcher

- `browser` opens a page, lists its links numbered and resolved, follows one,
  goes back, pages through a long document and finds text inside it. `web_fetch`
  strips the markup and the links go with it, so the only way onward was
  guessing a URL.
- Links inside the content rank above the navigation bar every page of a
  documentation site repeats.
- One session for the visit — one cookie jar, one connection pool — so
  redirects and consent pages survive the hop to the next page.
- Long pages are handed over a screenful at a time rather than cut off at
  40,000 characters, with `find` to jump to the part that matters.
- Moving around a page already fetched touches no network and asks no
  permission. A new host does.
- No JavaScript engine, and no plans for one: that means a real browser, which
  means a real dependency. A page that draws itself in the client says so and
  names the Puppeteer server in the MCP catalogue instead of pretending.

### It asks which directory this is about

- The project root is found by walking upwards from where you started, and the
  answer is occasionally a surprise. It is shown once per folder, with what is
  in it, and confirmed before the agent exists.
- Once. A prompt that appears every time is one people learn to dismiss without
  reading. Approved folders are remembered in `safety.trusted_folders` — the
  exact directory, never a prefix, so approving `~/work/api` does not quietly
  approve `~/work`.
- `--cwd` is you naming it yourself, so it does not ask.

### Also

- The `/progress` section is out of the README.

## 0.2.3 — 2026-08-20

### Uninstall left the environment behind when uv was not on PATH

- **Fixed:** the installer fetches `uv` into `~/.local/bin` when the machine has
  none, and a shell that ran `curl | sh` never read a profile — so `uv` is
  frequently installed and not on PATH at the same time. `uv tool uninstall`
  could not be run, and a real uninstall reported "No such file or directory:
  'uv'" and left seventy megabytes on disk. The tool is now looked for where an
  installer would have put it, and if it genuinely is not there the environment
  is removed directly.
- The PATH line the installer added is still kept when other programs live in
  the same directory, but the note now names them — `uv, uvx` says more than "2
  other programs" about whether the line is worth keeping.

## 0.2.2 — 2026-08-20

### Setup is a keyboard, not a numbered list

- Each question gets a screen of its own. What has already been answered stays
  as three quiet lines at the top; everything else goes. The questions used to
  stack, so by the fourth one the terminal was a transcript of decisions
  already made.
- One framed list at a time, moved through with the arrow keys. The frame never
  grows past the terminal: however many options there are, the list is windowed
  to what fits and travels with the cursor, with a count of what is above and
  below.
- Typing filters. With sixty models on offer, `son` beats sixty presses of the
  down arrow.
- The numbered prompt is still there for anywhere without a terminal — a pipe,
  a test, an editor's console — and is what the caller falls back to if raw
  mode cannot be had.

### Code in an answer looks like code

- Fenced blocks are framed in the interface's own border colour with the
  language on the top edge, rather than being an unlabelled darker rectangle in
  a panel that is also carrying prose, tool output and diffs.
- Inline `code` was bright cyan on black, which is a hole punched in a
  paragraph. It is the accent colour.
- **Fixed:** `balance`, which closes a fence the stream has not finished,
  closed it and then stripped a backtick off the fence it had just written.
  Every streaming answer containing code reached the parser with a
  two-backtick fence, which closes nothing, so the code was laid out as prose
  until the model happened to finish the block.

### The footer

- **Fixed:** the Settings control was drawn with three sides. The status block
  handed Rich more rows than the panel had and Rich cropped the last one, which
  was the bottom edge of the box.
- **Fixed:** a two-row button put its label on the lower row and left the upper
  one blank, so SEND was a coloured bar with a word under it. The rows now
  carry the label and the keystroke that does the same thing — a shortcut the
  interface has always known and had nowhere to print.

### Releasing

- The tag is the version. Nothing in the tree carries a number any more:
  `hatch-vcs` derives it from the tag and writes a generated, git-ignored
  `_version.py`. There is no file to bump, so there is no file to forget.
- The release workflow builds first and reads the version back off the wheel
  filename — the answer actually going to PyPI — and checks it against the tag.

## 0.2.1 — 2026-08-20

### The interface drew every other row on POSIX

- **Fixed:** `tty.setraw` clears `OPOST`, and a line discipline belongs to the
  terminal device rather than to one descriptor, so switching it off in order
  to read keystrokes also stopped a newline becoming carriage-return-newline on
  the way *out*. Every frame is exactly as wide as the terminal, which leaves
  the cursor in the deferred-wrap state at the end of each row, and terminals
  do not agree on what a bare line feed does from there — several perform the
  pending wrap as well as the feed. The result was a blank row between every
  drawn row, a picture twice the height of the screen, and the top half of it
  scrolled away before anyone saw it. Never visible on Windows, which does not
  use that code path.

### `comodor uninstall`

- Removes the data directory, the `.comodor` folder in every project it was
  used in, the environment the installer built, the `comodor` command, and the
  line the installer wrote into a shell profile.
- Shows the list before it touches anything; `--dry-run` stops there. The
  prompt asks for the word, not a letter.
- It knows which projects to clean because every session records where it ran,
  rather than by searching the disk. It will not take a directory off PATH that
  other programs are still using, will not touch a source checkout, and does
  not claim to have deleted a file the operating system would not let go of.

## 0.2.0 — 2026-08-19

### `comodor doctor` repairs what it finds

- Nine checks covering the config, the selected provider and model, the brain,
  the search index, skills, leftover files and MCP servers.
- `--fix` applies every repair on offer and re-checks, so what it prints is the
  state afterwards. Repairs are safe to run twice.
- It repairs only what it can rebuild. A corrupt search index is deleted — it
  is a cache. A corrupt config is reported and left alone, because it holds the
  API key; likewise the brain, and skill files the user wrote.
- Plain `doctor` never changes anything. A diagnostic command that silently
  rewrites files is one nobody can predict.

### MCP: tools from other programs

- A Model Context Protocol client written directly against the wire format —
  JSON-RPC over a subprocess — so support costs no new dependency.
- Twelve servers in a catalogue with their commands, what they need and what
  each can reach: Filesystem, Git, GitHub, Fetch, Memory, Sequential thinking,
  SQLite, PostgreSQL, Puppeteer, Brave Search, Slack and Time.
- `comodor mcp add <id>` for those; `comodor mcp custom <name> <command> …` for
  anything else in the ecosystem. Both start the server and list its tools
  before saving it as enabled — an entry that has never worked is not a
  feature.
- Servers connect lazily, on first use. One that fails is dropped once, with
  its own stderr as the explanation, and the session continues.
- MCP tools are namespaced by server and pass through the same permission gate
  as the built-in ones; risk is inferred from the tool's description, rounding
  up when unsure.
- `/mcp` in the interface, and a doctor check that starts each enabled server
  to confirm it answers.

### Setup, and an installer that finishes

- Configuration is one JSON file written by a first-run wizard. The `.env` file
  is gone, and with it the `python-dotenv` dependency: **`rich` is now the only
  one**.
- The installer no longer stops on a Python that refuses `pip install`
  ([PEP 668](https://peps.python.org/pep-0668/)). It builds a virtual
  environment instead, or downloads `uv` when the machine has nothing usable,
  and never passes `--break-system-packages`.
- It also finds tools that are installed but not on PATH. A `curl | sh` shell
  never reads your profile, so a perfectly good `uv` in `~/.local/bin` was
  invisible; that was the reported failure.
- PATH is set up for you rather than described to you.

### The agent

- A reason/act loop with parallel execution of read-only tools, cancellation at
  any point, and context compaction that only ever cuts at a safe seam — never
  between a tool call and its result.
- Three modes. **Act** has the full tool set; **Plan** is read-only, and hides
  the write tools from the model rather than merely refusing them, so the answer
  is a plan instead of a thwarted attempt to edit; **Chat** has no tools at all.
- A model gateway, off by default. Enabled, it ranks healthy providers by cost,
  speed or quality and fails over when a call breaks — but never retries a
  stream that has already produced output, because half an answer twice is worse
  than a reported failure.
- Tools for files, search, shell, Python, the web and a task list.

### Reflex — learning from corrections

- Five signals, read deterministically and without a model call: a file you
  rewrite after the agent wrote it, an `/undo`, a denied permission, the same
  request asked twice, and a tool that fails the same way twice.
- Rules carry their evidence (`31 of 34 literals`), and how much evidence a rule
  needs depends on where it came from — four agreeing observations to trust the
  codebase, two for an edit you made, one for something you said outright.
- Detection runs at the *start* of a turn, so a correction lands on the next
  answer rather than the one after it.
- LLM reflection still runs in the background, and is optional. Turn it off and
  Reflex keeps learning, because it never needed a model.
- `/progress` reports the trend with sparklines, and is built to under-claim:
  it refuses to headline a drop from a near-zero base, reports rates in
  percentage points, and says so when there is too little history to judge.

### Skills

- Markdown files with front matter in `~/.comodor/skills/` and
  `.comodor/skills/`, describing how a kind of work should be done. A project
  file shadows a personal one of the same name.
- Both layouts of the [Agent Skills](https://agentskills.io) open format are
  read: a single `.md` file, or a folder holding `SKILL.md` with `references/`,
  `scripts/` and `assets/` beside it. A skill written for another agent runs
  here unchanged.
- Bundled files are named in the prompt but never inlined. `read_skill_file`
  fetches one on demand, and can reach nothing outside a loaded skill's own
  folder — the reachable set is what discovery found, not what a path can
  express.
- `/skills draft` offers a procedure Comodor has repeated at least three times
  as a finished `SKILL.md`, evidence attached; `/skills adopt <name>` writes it.
  Nothing is written without approval.
- Matched against the request and only then injected, so a collection costs no
  more per turn than a single file. `always: true` opts a file into every turn.
- Applied identically in the interface and in headless runs, so a team
  convention holds in CI too.
- Three worked examples are written on first run.

### Setup and configuration

- First run asks four questions in the terminal and saves the answers. There is
  no dotfile to create and no environment variable to export.
- 18 providers in the catalogue, each carrying its own endpoint, model list and
  key page: OpenRouter, Anthropic, OpenAI, Google Gemini, DeepSeek, xAI,
  Mistral, Groq, Cerebras, Moonshot, Z.AI, Qwen, Together, Fireworks, Xiaomi
  MiMo, Ollama, LM Studio, and any other OpenAI-compatible endpoint.
- One JSON file, written atomically and `0600` on Unix. A project's
  `.comodor/config.json` merges over the personal one so a repository can pin
  settings without carrying secrets; provider environment variables still take
  precedence, which keeps CI working with no file at all.

### Searching past sessions

- `/search <words>` finds anything said in an earlier conversation, ranked with
  FTS5 in under a millisecond, with a pure-Python fallback for SQLite builds
  without it.
- `search_history` gives the agent the same index, so it can look up how a
  problem was solved before instead of solving it again. History enters the
  context only when it asks.
- The index is a cache derived from the transcripts. Deleting it costs nothing
  but a rebuild; deleting a session removes it from search.

### Interface

- A Rich interface recomputed every frame from the terminal size, with four
  breakpoints from a 40-column SSH window to an ultrawide monitor. Below the
  floor it says so plainly rather than drawing a corrupted screen.
- Raw keyboard and mouse input written directly against the terminal: SGR mouse
  reporting, bracketed paste, and a Windows console path alongside the POSIX
  one.
- `--ascii` for terminals without box-drawing glyphs; a monochrome terminal gets
  a monochrome theme automatically.
- `comodor --demo` runs the whole interface against a scripted offline provider,
  with no account and no key.

### Safety

- Risk tiers, checkpoints with `/undo`, a deny list no prompt can talk past,
  workspace confinement, and redaction of keys and tokens from logs, transcripts
  and exports.
- `--yes` exists for CI; headless runs refuse to change anything without it.

### Performance

- Recall is flat at 0.38 ms from 3,000 to 20,000 lessons: a RAM mirror with an
  inverted index and a capped candidate set, a background writer that batches
  commits so nothing user-facing waits on disk, and speculative recall that runs
  the ranking while you are still typing.
- `tests/test_performance.py` enforces these as ceilings, so a change that makes
  memory slow fails the suite.

## 0.1.0 — 2026-08-19

First public release: the agent loop, Reflex, `/progress`, the responsive Rich
interface, the safety model and the performance work described above.
Configuration was a `.env` file at this point, and skills, session search and
the provider catalogue did not exist yet.
