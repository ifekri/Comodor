# Changelog

Notable changes to Comodor. Versions follow [semantic versioning](https://semver.org).

## 0.8.2 — 2026-08-22

### A refused request broke the connection it arrived on

- **Fixed: the web server decided before it read the body.** A POST rejected
  for a missing token or a missing header was answered without its body ever
  being read, which leaves those bytes in the socket. This server speaks
  HTTP/1.1, so every connection is kept alive and the *next* request reads that
  leftover as its own request line; and a socket closed with unread data sends
  a reset rather than a close, which the caller sees as an aborted connection
  instead of the 401 that was actually sent.

  The body is read first now and the verdict comes after — including a body
  over the size cap, which is drained and discarded rather than left unread,
  because it is what goes unread that breaks the connection.

## 0.8.1 — 2026-08-22

### A delegate's changes never applied on Windows

- **Fixed: the patch was mangled before git saw it.**
  `subprocess.run(..., text=True)` wraps stdin in a stream with the platform's
  newline handling, and on Windows every `\n` written becomes `\r\n`. For a
  command's *output* that is harmless. For a patch it is fatal: every line of
  the diff gains a carriage return, the context stops matching the file, and
  git refuses the whole thing.

  The failure was silent and one-platform in the worst way. On Linux and macOS
  nothing is translated, so a delegate that edited a file worked — and on
  Windows the same delegate reported that its changes would not apply cleanly,
  kept the worktree, and looked exactly like a merge conflict that was never
  there. Git is spoken to in bytes now, and only its output is decoded.

## 0.8.0 — 2026-08-22

Three things a much larger agent had and this one did not. A fourth — loading
tool schemas on demand — was measured and rejected: the schemas sit in the
cached prefix, so their real cost is 156 tokens a request, and varying them
would forfeit the whole cache to save that.

### One result no longer pays for the rest of the task

A tool result is written into the conversation once and resent with every
request that follows it, so its price is its size times the steps still to
come. Reading one ordinary module in this repository cost **23,082 tokens**.

- **What does not fit is moved, not cut.** Truncating bounds the cost and loses
  the content: the middle of a failing test run is gone, and the agent answers
  from the half it kept. Now the whole of it is written to a file and the
  result carries the head, the tail, and the path — read a slice with
  `read_file`, or search it with `grep`. Output that was *already* a file on
  disk is not copied at all; the pointer names the original.
- Six ordinary calls measured **29,633 → 10,553 tokens**.
- **Fixed: the shell cut its output before anything could save it**, so the
  saved copy was an already-cut one. It caps for memory now, not for the model.
- **Fixed: `read_file` could not do what its own error message advised.** Over
  the byte cap it said "read a slice with offset/limit instead" and then
  refused the slice too — the whole file was loaded before one was taken, so a
  large log was unreadable by the tool suggesting how to read it. Windows are
  streamed now; a slice of a large file costs what the slice costs.

### Work that costs its own context

- **`delegate`** hands one self-contained piece of work to a second agent with
  its own conversation, and returns only its answer. Surveying a subsystem may
  mean opening nine files to produce one sentence; done in the main
  conversation those nine files are permanent. Now the reading stays with the
  delegate.
- It cannot write unless told to, it cannot delegate, and it does not reflect —
  its episode is half a task seen out of context, and learning from it would
  teach the brain about a fragment. It stops when the parent does.
- **With `write=true`, and a git project, it works in a worktree of its own.**
  A real checkout at the same commit; what comes back is a patch, applied here
  if it applies cleanly and kept aside with its path if something moved
  underneath it.

### A real browser, and the reason it is not screenshots

Comodor drives Chrome, Chromium, Edge or Brave — whichever is already on the
machine — over the DevTools protocol. Nothing is downloaded and there is no new
dependency: CDP is JSON-RPC over a WebSocket, and a WebSocket client is a
handshake and a frame format.

The obvious design is a screenshot every step and a coordinate to click. It is
wrong on precision, because a model judging pixels on a resized image misses
and cannot say what it meant. And it is wrong on cost, which was measured:

|  | whole tree | only what is on screen | a screenshot |
|---|---|---|---|
| Hacker News | 8,760 | 933 | 1,365 |
| a GitHub repository | 18,681 | 778 | 1,365 |
| a Wikipedia article | 32,342 | 414 | 1,365 |

The page's own accessibility tree, sent whole, is *more* expensive than a
picture — which was the surprise, and the reason the design is what it is. The
advantage is filtering, available to text and not to pixels: half a screenshot
answers nothing, but a list of controls can be cut to the ones a person could
see and click. Numbered, so the model answers with a number.

- **`browse`**, one tool with verbs — open, click, type, scroll, back, read,
  look, script — rather than eight tools, because every schema is sent on every
  request and eight descriptions of one browser is eight times the description.
- **`look` is the screenshot**, for questions that are actually about
  appearance, and it arrives as an image: inside the tool result on Anthropic,
  in a following user turn on the OpenAI dialect, which is the only place that
  one allows it.
- A profile of its own, signed into nothing. `browser.port` attaches to a
  Chrome you started yourself, for a session you are already logged into.
- Where no browser is installed, the existing text browser is offered instead,
  so the model always sees exactly one thing called a browser.
- **Fixed on the way:** headless runs and the web session never closed their
  tools, which cost nothing when the heaviest thing a tool held was a
  connection pool and would now have left a Chrome behind on every invocation.

### And a browser, for when a terminal is not where you are

```bash
comodor web
```

The terminal interface was never the agent — it is one subscriber to an event
bus. A browser is a second one, so this is a small amount of code: the standard
library's HTTP server, one page that loads nothing from the internet, and
long-polling rather than a websocket protocol to maintain. Streaming answers,
tool calls as they run, permission prompts, the mode switch, the running cost.

It is also a remote code execution endpoint, because that is what an agent is,
so: loopback by default; a token per run, never written to disk, moved out of
the URL into an `HttpOnly`, `SameSite=Strict` cookie; constant-time comparison;
a header on writing requests that no cross-origin form can set; and a plain
statement of what you have done, plus the SSH tunnel you should have used
instead, if you bind it to a public address.

- **Fixed while building it:** a `Request` carries a `kind` of its own —
  `"permission"` — and spreading it into the event frame overwrote the event's
  own kind. Every permission prompt arrived under a name the page was not
  listening for, so none of them would ever have been shown.

### An MCP server can be a URL

- **Streamable HTTP transport**, alongside the existing subprocess one. The
  interesting servers are increasingly hosted, shared by a team, and holding
  credentials nobody wants on a laptop.
- Both reply shapes are read — a JSON body, or an event stream carrying the
  reply among the server's own progress and requests.
- The `Mcp-Session-Id` a server issues is carried on every later request.
  Without it a stateful server treats each call as a stranger's first: tools
  listed, then unavailable a second later.
- **`comodor mcp remote <name> <url>`**, with `--token` and `--header`. Probed
  before it is enabled, and a plain `http://` endpoint that is not on this
  machine is refused — the token and everything the tools return would cross in
  the clear.

## 0.7.1 — 2026-08-21

### A skill that matched, and then never arrived

The published library grew to thirteen authored skills. Eleven of them could
not be used, and nothing said so — they downloaded, appeared as installed,
matched the right question, were selected, and were then discarded before the
request was built.

- **Fixed: the turn's skill budget was 1,200 tokens**, which is the size of the
  sample skill and nothing else. Real authored skills — a design system, an
  image-direction brief — run from two to ten thousand. It is 12,000 now, which
  admits any single skill in the library; a second large one in the same turn
  is still refused, and now says which.
- **Fixed: an oversized skill ended the list instead of being skipped.**
  Ranking puts the best match first, not the smallest, so one large skill at
  the top discarded every skill behind it — including ones that would have fit.
- **Fixed: the drop was silent.** A skill the user wrote, that matched, that
  never travelled, and an answer that came back as though they had never
  written it. It now says what was too large and names the setting.
- **Fixed: the interface announced skills that had already been thrown away.**
  The "using this skill" event was emitted from the matched list rather than
  from what was actually sent.
- **Fixed: `comodor skills list` showed no version for most skills.** It looked
  the install record up by the name a skill calls itself, which for most is not
  the folder it lives in — `brutalist/` announces itself as
  `industrial-brutalist-ui` — so a managed skill read as one written by hand.
  Long descriptions are trimmed and hang under their entry rather than wrapping
  back to the margin.

### And five of them could not be found either

Reachability was measured across the whole library — one natural request per
skill, the kind somebody would actually type. Eight of thirteen matched.

- **Fixed: a skill could only be found by its whole name.** The tokenizer keeps
  `industrial-brutalist-ui` in one piece, which is right — `src/app.py` and
  `snake_case` are single terms and splitting them ruins recall — but it meant
  "build a brutalist dashboard" matched nothing at all. The parts of a compound
  term are now indexed alongside the whole of it, for skills only: the same
  tokenizer serves the learned brain, where the identifiers are file paths.
- **Fixed: the match floor excluded the case it was written to admit.** It was
  0.34 and the comment said "a share of the request's terms" — a third. A third
  is 0.3333, so a request covering exactly one term in three was rejected by
  seven thousandths while ranking first. It is the fraction now.

Thirteen of thirteen, measured the same way.

## 0.7.0 — 2026-08-21

### The same tokens, paid for once

A model has no memory between requests, so an agent resends its whole
conversation at every step: a file read at step two is billed again at step
three, and four, and at every step until the task ends. Providers sell those
resends at a tenth of the price, on one condition — the request must *begin*
with bytes they have already seen, the same ones, from the first character.

- **Requests are now built so that condition holds.** Recalled lessons and
  matched skills used to be appended to the system prompt, and recall runs
  against each new request — so the first paragraph differed every turn and
  nothing behind it could ever match. They travel with the turn that asked for
  them instead, behind everything already cached, and the head of a request is
  now identical from the first message of a session to the last. Measured on a
  real session against a live endpoint — three turns, tools running, files
  read: **86% of everything the model read was served from cache**, and by the
  third turn the prompt had doubled while what it cost had not moved.
- **Cache breakpoints are placed rather than sprinkled.** One on the head,
  which covers the tool schemas too, and two that roll along the tail — never
  on a block below the size the provider will actually keep, since a mark there
  is silently ignored and the write premium is paid for nothing.
- **Nothing the model reads has changed.** Every lesson, skill and tool result
  arrives in the same words; only the order is different. A test asserts the
  property literally — each request in a session must be a byte-exact extension
  of the one before it — so anything that quietly breaks it fails the suite
  rather than costing ten times the money.
- **An endpoint that refuses the marks loses the discount, not the answer.**
  Proxies and self-hosted gateways speak this protocol too; a refusal that
  names the field is retried once as a plain request.

### Money, counted properly

- **Fixed: the spend meter would have understated every cached session.** Cache
  reads and writes are billed at a tenth and a quarter more than plain input,
  and Anthropic reports all three separately — `input_tokens` excludes the
  other two. Counting only that field made a long session look nearly free, and
  the spend guard is built on that number.
- **Fixed: the context gauge measured the bill instead of the prompt.** With
  caching working the two differ by an order of magnitude. It reads what the
  model read.
- `/cost` shows the share served from cache and what it saved, taken from what
  the provider reports rather than from what was requested — the two differ
  whenever a prefix has expired.
- `"prompt_cache": false` switches the whole thing off; `"prompt_cache_ttl":
  "1h"` holds prefixes for an hour instead of five minutes, and sends the
  opt-in header that requires.

## 0.6.1 — 2026-08-21

### Two things the benchmark found

- **Fixed: starting up loaded the whole brain.** The RAM mirror read every
  lesson in the table, so start-up grew linearly with it — 1.15 seconds at
  fifty thousand lessons, paid before the first prompt appeared. The mirror is
  a cache of what can plausibly be recalled, not the record: recall multiplies
  relevance by confidence and discards what scores near zero, so the decayed
  tail cannot win however well it matches. The strongest six thousand are held
  in memory and the tail stays reachable through FTS. **1154 ms → 195 ms.**
- **Fixed: one common word made the full-text query enormous.** Twelve terms
  were unioned across the table and it measured at 20 ms. Ordering them by
  rarity changed nothing — a single term matching most of the table dominates
  whatever is ranked ahead of it — so the common ones are dropped rather than
  demoted, which is what an IDF floor says from the other direction. **20.3 ms
  → 0.12 ms**, and recall quality is unchanged: twelve planted lessons, twelve
  found, among twenty thousand.
- Both are budgets in the suite now, along with a test that two processes can
  write to one brain — which is the normal way to work, and the thing a plain
  file cannot do.

## 0.6.0 — 2026-08-21

### Memory reads every script

- **Fixed, and it was total:** the tokenizer behind every part of memory
  matched `[A-Za-z0-9_]` and nothing else. For anyone working in Persian,
  Arabic, Hebrew, Russian, Greek or Devanagari it returned an empty list —
  nothing indexed, nothing recalled, no duplicate detection, and no error
  anywhere to say the whole feature was a no-op. It reads words in any script
  now, and keeps a Persian word whole across its zero-width non-joiner instead
  of splitting it into two fragments.
- Stopwords for Persian, Arabic and Hebrew, so the index does not fill with
  their equivalents of "the".

### It learns your vocabulary, by counting

- Recall used to fail whenever the request and the lesson said the same thing
  in different words. Every finished task is now read as a bag of words that
  belonged to one piece of work, and terms that keep arriving together are
  related — so `spec` reaches `pytest`, `auth` reaches `session` and
  `src/auth.py`, and a Persian `تست` reaches `pytest`, with no synonym list, no
  embedding model and no translation.
- Normalised mutual information rather than raw counts, so a term that appears
  in everything associates with nothing.
- An inferred term is worth a third of one the user typed and never displaces a
  real match; a pair seen once is coincidence and is ignored until it happens
  twice.
- Measured: expanding a query is 0.009 ms against a recall budget of 0.4 ms,
  learning from a finished task is 0.019 ms, and the whole vocabulary is 169 KB
  after four thousand tasks. All three are enforced as tests.
- `comodor doctor` shows how many terms have been related, and from how many
  tasks. `learning.associative` turns it off.

## 0.5.0 — 2026-08-21

### A library of skills, on a branch rather than in the package

- `comodor skills browse` lists what is available and marks what is on this
  machine; `add`, `remove` and `update` do the rest. Skills are Markdown, and
  shipping a folder of them inside the wheel would put files nobody asked for
  on every machine and mean a release every time somebody fixed a typo — so
  they live on the `skills` branch and are fetched on request.
- `catalogue.json` on that branch is the authority: it lists what exists, what
  to show for it, and the exact files that make it up. `files` is an explicit
  list rather than a wildcard, so a file added there by accident cannot reach
  somebody's machine.
- Cached, and revalidated rather than refetched. A copy younger than five
  minutes is used without asking the server at all; past that the request
  carries the `ETag` and the usual answer is `304` with no body. Three skill
  commands in a row cost one request.
- Offline shows the cached copy with its age rather than an error, up to a
  month, because a list of skills from this morning is worth more than a stack
  trace.
- **It will not overwrite a skill you wrote.** A folder this program installed
  carries a stamp; one written by hand does not, and `review` is a name a
  person is likely to have used first. Same name and no stamp: refused, with
  `--force` for when it is meant. `update` only touches what it installed.
- A filename in the catalogue that climbs out of the skill folder is refused.
  It is a file on the internet, and `../../.ssh/authorized_keys` is a perfectly
  valid JSON string.
- A download that fails halfway leaves nothing: files land in a staging folder
  and are moved into place at the end. A skill directory with three of its four
  files loads, and misbehaves.
- The first-run wizard offers the library once, with nothing selected. A
  network that is not there skips the question rather than failing the run.
- `skills.catalogue_url` and `skills.catalogue_ttl` are settings, so a team can
  point at its own without forking the program.

## 0.4.0 — 2026-08-21

### The interface is a page, not four boxes

- The bordered panels are gone. A rule under the name, a rule above the
  composer, and space between them. Four borders was four things competing to
  be looked at first, and the transcript was framed exactly as loudly as the
  context gauge.
- The status block — six labelled pairs where half the characters were the
  labels — is one line at the bottom, and it sheds from the right as the
  terminal narrows.
- The three coloured buttons are three quiet words, still clickable: the hit
  rectangles sit on the words.
- Indentation carries the speaker. Tool calls are aligned as the table they
  already were: verb, target, and the time against the right margin.
- The newest line is at the bottom, against the composer.
- Two new palettes, `paper` and `ink`. Light palettes paint their own
  background, because dark ink on somebody's dark terminal is not a light
  theme, and no program can ask a terminal to change colour. They ask for a
  light syntax theme too — the first render of `paper` came out with half the
  code block missing, monokai putting its identifiers in near-white on a page
  that was now near-white.
- **Fixed:** the footer line could run one cell past the measure and wrap,
  taking the whole layout down a row. There is no border clipping it now.
- **Fixed:** the composer has to hold its own height, or a one-line draft pulls
  the footer up the screen and every newline puts it back.

### Right-to-left languages

- Persian, Arabic and Hebrew are set to the right of their column, where the
  line begins for that reader. Left-to-right text is untouched, and a code
  block inside a right-to-left answer stays on the left.
- Every field where the interface's own words meet the user's is fenced in a
  Unicode isolate, so the bidirectional algorithm cannot resolve the neutral
  characters between them against the wrong side — which is how a task titled
  `افزودن مسیر /health` ends up with the path in the wrong place. The marks are
  zero-width, so the layout still measures correctly.
- Titles are trimmed before they are fenced. An isolate whose closing mark was
  truncated away leaks into the rest of the line, which is worse than not
  fencing at all.
- `comodor doctor` mentions the terminal font when it sees right-to-left
  writing in the history. It cannot be repaired from there: a program writes
  characters and the terminal picks the glyphs, so the setting to change is the
  terminal's own.
- The SVG snapshot `preview --svg` writes now asks for Tahoma first.

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
