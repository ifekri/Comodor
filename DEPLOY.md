# Deploying comodor.ai

This repository is the site and nothing else. It is deliberately separate from
the agent's repository: visitors clone `ifekri/comodor` to read the agent, and
the marketing site has no business being in there.

```
npm install
npm run build     # next build
npm start         # next start, listening on $PORT (default 3000)
```

Node 20 or newer. The server reads `PORT` from the environment — no port is
hardcoded and no `-p` flag is passed, because `next start` already honours it.

## Hostinger (Web App)

Their Web App platform lists Next.js as a supported framework and offers Node
18-24 with npm, which is exactly this shape.

| Setting | Value |
|---|---|
| Branch | `main` |
| Framework | Next.js |
| Node version | 20.x or newer |
| Package manager | npm |
| Install command | `npm install` |
| Build command | `npm run build` |
| Start command | `npm start` |
| Root directory | repository root |
| Output | server (not static export) |

Then point the `comodor.ai` A/CNAME record at the app and enable TLS. Nothing
here needs an environment variable: no database, no API, no secret.

## The two URLs that must keep working

They are what the front page tells people to run, so they are checked after
every deploy:

```
https://comodor.ai/install.sh     text/plain, 200
https://comodor.ai/install.ps1    text/plain, 200
```

```bash
curl -sI https://comodor.ai/install.sh | grep -i content-type   # must be text/plain
curl -fsSL https://comodor.ai/install.sh | sh -n /dev/stdin     # parses without running
```

A stale or misconfigured install script is the one failure on this site that
costs a visitor something rather than merely looking wrong.

**They are route handlers, not static files** - `app/install.sh/route.ts` and
`app/install.ps1/route.ts`, reading from `lib/scripts/`. They started in
`public/`, which looked simpler and was wrong: the host serves static files
through its own front web server, so Next's `headers()` rules never ran and the
scripts arrived as `application/x-sh` - a type a browser downloads rather than
displays, contradicting the page's invitation to read them before running them.
Going through Node means the headers are ours. Move them back to `public/` and
that regression comes back.

## Editing the install scripts

`lib/scripts/install.sh` and `lib/scripts/install.ps1` are the real installers.
Check the syntax of whichever you touched:

```bash
sh -n lib/scripts/install.sh
pwsh -NoProfile -File tools/parse-check.ps1        # or Parser::ParseFile inline
```

Then run it for real against a throwaway environment rather than trusting the
syntax check - the failures that matter here are behavioural, not syntactic:

```bash
python -m venv /tmp/probe
VIRTUAL_ENV=/tmp/probe PATH=/tmp/probe/bin:$PATH   COMODOR_INSTALL_REF=/path/to/comodor COMODOR_FORCE_TOOL=pip   sh lib/scripts/install.sh
```

The script ends by running `comodor --version`, so a run that prints a version
is the assertion.

**Test it on a real machine, not by reading it.** Every behaviour below was
found by running the thing and none of them by inspection:

- `curl | sh` runs a non-interactive shell that never reads the user's profile,
  so `command -v uv` misses a uv that is installed in `~/.local/bin`. The
  script searches known install directories as well as PATH. This was the
  reported failure: the right tool was on the disk the whole time.
- **PEP 668.** A distribution or tool-managed Python refuses `pip install
  --user` outright. The script detects the marker and builds a virtual
  environment instead, which the rule does not cover. It never passes
  `--break-system-packages`.
- `python3 -m venv` on Debian without `python3-venv` prints an error, leaves a
  half-built directory, and has been seen exiting 0. What gets checked is
  whether the environment it produced can actually install a package.
- The newest Python is not always the one that works: Ubuntu's
  `/usr/bin/python3.12` cannot build an environment while a `python3.12` in
  `~/.local/bin` can. Every candidate is tried, not the first match.
- When nothing on the machine can install anything, uv is downloaded — it needs
  no Python and can fetch one. `COMODOR_NO_BOOTSTRAP=1` turns that off.

The scenario matrix lives in this repository's history rather than in CI,
because it needs a real distribution to be meaningful. To re-run it, use a
Debian or Ubuntu 24.04 box (WSL is fine — it has PEP 668 and no `python3-venv`)
and exercise, at minimum: uv present but off PATH; no package manager at all;
`COMODOR_FORCE_TOOL=venv`; a second run; and `COMODOR_NO_BOOTSTRAP=1` with
nothing usable, checking that the failure message names a command that would
actually fix it.

Line endings matter: `install.sh` must stay LF (a CRLF shebang is reported as
`bad interpreter`) and `install.ps1` stays CRLF.

## GitHub Pages

The site also builds as a static export and publishes to Pages from the `site`
branch of `ifekri/Comodor`. `main` — the branch somebody lands on to read the
agent — never contains any of this.

```
https://ifekri.github.io/Comodor/
```

`.github/workflows/pages.yml` does the whole thing on push. Two settings decide
whether the result works at all:

| | |
|---|---|
| `base_path` | `/Comodor` for the github.io URL, **empty** for a custom domain |
| `custom_domain` | writes a `CNAME`; Pages drops the domain without that file |

A push defaults to the github.io preview. To switch to the real domain, run the
workflow by hand with `base_path` empty and `custom_domain` set to `comodor.ai`,
then point the DNS at Pages.

**The base path is the one that fails silently.** At
`user.github.io/Repo/`, every absolute asset URL resolves a level too high; the
page arrives with no stylesheet and looks broken rather than misconfigured. The
workflow asserts that `out/index.html` actually references the prefix before it
deploys.

### Three things that bite

**Jekyll eats `_next`.** Pages runs static output through Jekyll unless
`.nojekyll` is present, and Jekyll ignores every directory starting with an
underscore — which is the entire stylesheet and every script. The workflow
creates the file; do not remove it.

**The environment only allows `main` by default.** Enabling Pages creates a
`github-pages` environment whose deployment branch policy lists the default
branch and nothing else. Deploying from `site` fails with a job that has *no
steps at all* and no error message, because it never starts. Fixed once with:

```bash
gh api -X POST repos/ifekri/Comodor/environments/github-pages/deployment-branch-policies   -f name=site -f type=branch
```

**No headers, ever.** A static host assigns content types from the extension.
`/install.sh` arrives as `application/x-sh`, which browsers download — hence the
`.txt` copies described above. `curl` is unaffected either way.

### Checking a Pages build without deploying one

```bash
NEXT_STATIC_EXPORT=1 NEXT_BASE_PATH=/Comodor npm run build
node tools/serve-export.mjs 4300 /Comodor
node tools/a11y.mjs   http://localhost:4300/Comodor/
node tools/themes.mjs http://localhost:4300/Comodor/
```

`serve-export.mjs` imitates Pages rather than Next: the subpath, the
directory-index resolution, and the MIME map. Testing an export against
`next start` proves nothing about the host it is going to.

## The design, and what the motion is for

Warm paper, ink, hairlines — and the terminal set into it as a dark figure, the
way a plate sits in a printed manual. That is the whole system. It exists
because the previous version dressed the site as the product (black page, amber
text, monospace throughout) and read as costume: everything in this category
looks like that, and a page of one uniform texture has nowhere left to put
emphasis.

Consequences worth keeping:

- **The ember is loud in exactly two places** — the italic word in the headline
  and inside the terminal figures. Spending it anywhere else is what turns a
  restrained page into a busy one.
- **No shadows and no rounded cards on the paper side.** Depth comes from the
  figures being a different material. Hairlines and space do the rest.
- **Instrument Serif is display only.** It is the decision that stops this
  looking like a template; it is also unreadable as body text.

GSAP appears four times, and each one does something the static page cannot:

| Where | Why |
|---|---|
| Hero entrance | Establishes reading order. About a second, and the install command arrives early rather than last. |
| Reflex section | Pinned and scroll-scrubbed. The reader operates the correction loop instead of reading about it. |
| Figures | They count up because the number *is* the claim — two readings landing on the same value says "flat" faster than the sentence does. |
| Section rules | A line drawing itself is the quietest entrance available. |

Everything else is still, and that is the point. Adding a fifth is how a page
starts to feel automated.

## Light and dark

Dark is a second design, not an inversion, and the reason is the central device:
the terminal is a dark figure on pale paper. Flipping the page dissolves exactly
that — a near-black panel on a near-black page is one smudge, not a figure and a
ground.

So the relationship is rebuilt. The page becomes a **warm charcoal** (`#282420`),
the terminal goes **deeper than it** (`#080705`), and a warmer border carries the
edge that tone alone no longer can. The accent moves too: `#bf3d0b` is picked for
contrast against paper and turns muddy on charcoal, so dark uses `#ff7d3c`.

The first attempt had the page at `#13110d` and the terminal at `#0a0906` — two
tones that are both "very dark". They measured **1.06:1** apart. `tools/themes.mjs`
asserts at least 1.25:1, which is what forced the page to lift.

Three things the switch has to get right:

- **No flash.** An inline blocking script in `<head>` applies the stored choice
  before the first paint. React cannot do this job: by the time a component
  mounts, the wrong theme has already been on screen for a frame, and on a page
  this pale or this dark, one frame is very visible.
- **A default that is not a guess.** Until somebody chooses, the system
  preference wins and nothing is stored — so a reader who changes their OS
  setting later is not stuck with what they had in January.
- **Contrast in both.** `themes.mjs` measures real WCAG ratios on five text
  roles per theme. It caught `--ink-3` at **3.73:1** in light — a bug that had
  already shipped, affecting every label, eyebrow and note on the page.

## Checking it

```bash
npm start &
node tools/a11y.mjs http://localhost:3300    # the checks that matter
node tools/themes.mjs                         # both themes: contrast, no flash
node tools/shots.mjs                          # screenshots at four widths
sh tools/check-scripts.sh                     # the installers
```

`a11y.mjs` earns its place: it caught the one defect that reading the source
would not have. Under `prefers-reduced-motion` two of the three Reflex beats
stayed dimmed to 25% forever, because the dim state was an inline style in the
markup and only the timeline lifted it. Anyone with that preference saw a
permanently greyed-out page. **A scroll-scrubbed animation must never be the
only thing that makes content legible** — that check now asserts it.

`shots.mjs` is not decoration either. The first pass of this design had a
four-second entrance, unreadable quote glyphs, a pinned panel that was mostly
empty and a flag wrapping mid-token. All four were invisible in the source and
obvious in a screenshot.

## Changing the install commands or the links

Everything the page says about names, commands and URLs comes from
`lib/site.config.ts` — the repository URL, the PyPI package name, the domain,
the per-OS commands and the alternatives list. Change it there and the hero, the
install section, the footer and the metadata all follow.

The install scripts carry their own copies of the package name and repository
URL, at the top of each file, because they have to run standalone.

## Local development

```bash
npm install
npm run dev          # http://localhost:3000
```

Worth checking before shipping a change:

- the page with JavaScript disabled — every OS command must still be readable
  (there is a `<noscript>` list for exactly this);
- 360 px, 768 px and 1440 px widths;
- `prefers-reduced-motion`, which holds the Reflex demo on its first frame and
  lets the visitor step through it.
