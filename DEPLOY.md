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
