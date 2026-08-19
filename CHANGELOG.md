# Changelog

Notable changes to Comodor. Versions follow [semantic versioning](https://semver.org).

## 0.1.0 — unreleased

First public release.

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
