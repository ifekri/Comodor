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

## Cloudflare (where it lives)

Two Workers on one account, deployed from this repository.

| | |
|---|---|
| `comodor-site` | the page, as static assets. No Worker code. |
| `comodor-get` | `get.comodor.ai`, which needs code — see below |

```bash
NEXT_STATIC_EXPORT=1 npm run build
npx wrangler deploy                                   # the site
npx wrangler deploy --config workers/get/wrangler.jsonc   # the dispatcher
```

### Only `site` builds

Each Worker has exactly one build trigger, on the `site` branch. Cloudflare
adds a second by default — "non-production branch builds", matching `*` and
excluding the production branch — and on this repository that is actively
wrong: `main` is the Python agent and carries none of the site's files, so
every push to it started a build that could only fail. Both were removed. If
one reappears after somebody reconnects the repository in the dashboard, that
is where it came from.

### Deploying on push

Both Workers are connected to this repository through **Workers Builds**, so a
push to `site` builds and deploys them. Nothing local is needed and there is no
API token in a repository secret — Cloudflare holds the credential.

Connected in the dashboard, once each, at **Workers & Pages → the Worker →
Settings → Build → Connect**:

| | `comodor-site` | `comodor-get` |
|---|---|---|
| Root directory | `/` | `workers/get` |
| Build command | `npm run build:cloudflare` | *(none)* |
| Deploy command | `npx wrangler deploy` | `npx wrangler deploy` |
| Branch control | `site` | `site` |
| Build watch paths | `app/*`, `components/*`, `lib/*`, `public/*`, `wrangler.jsonc`, `package.json`, `next.config.mjs` | `workers/get/*` |

Both are connected and both have deployed from a push: `comodor-site` went
from `git push` to live on the real domain in twenty seconds.

Three things that make the difference between this working and failing:

**The Worker name has to match.** Cloudflare's rule is that the name in the
dashboard must equal the `name` in the Wrangler config *in the root directory
you specified*, or the build fails. That is the whole reason `comodor-get` has
its own `package.json` and its root directory is `workers/get`: pointed at `/`
it would find `wrangler.jsonc`, read `comodor-site`, and refuse.

**Branch control defaults to the repository's default branch**, which here is
`main` — the agent, not the site. It must be changed to `site` or nothing will
ever build.

**Watch paths keep them apart.** Without them, editing the dispatcher rebuilds
and redeploys the whole site and the other way round.

The build command is `npm run build:cloudflare`, not `NEXT_STATIC_EXPORT=1 npm
run build`. The second form works on Cloudflare's Linux builders and fails on
Windows, where `cmd` reads the assignment as a command — a difference between
CI and a developer's machine, which is the worst place to have one.
`tools/build-export.mjs` sets the variable in Node instead, so both agree.

### Watching a build

The builds API wants the Worker's **tag**, not its name — asking for
`comodor-site` returns an empty list rather than an error, which reads exactly
like "nothing has built yet" and is not.

```bash
npx wrangler deployments list --name comodor-site
```

Tags, for the API: `comodor-site` is `c07e856d31584cc78e579999b4bc91e2`,
`comodor-get` is `05eee70b3a7c4fbd899d2b2e5b13d67d`.

### The GitHub Pages workflow still runs, and is no longer a fallback

It was kept on the reasoning that the apex still carried A records aimed at
Pages, so removing the Worker would fall back to it. Those records are gone —
the apex is a Workers Custom Domain now — so nothing falls back anywhere. The
workflow builds a copy that no address points at.

Keeping it costs nothing and it is one command away from being a host again if
this account is ever unreachable, which is the only argument left for it. It is
not a safety net and should not be described as one.

### Custom Domains, and the outage that got us here

`comodor.ai` and `www.comodor.ai` are attached to `comodor-site` as **Workers
Custom Domains**. Each one owns its DNS record and its certificate, so there is
nothing else to keep in step.

It was routes first, and that took the site down. A route intercepts traffic
that has already reached Cloudflare — it does not make Cloudflare answer for a
hostname. The DNS records still pointed at GitHub Pages and were doing the only
job that mattered: getting the request to the edge at all. Deleting them,
because they looked like leftovers from the old host, removed the resolution
and everything below it stopped existing. The site returned `NXDOMAIN` while
the Worker sat there perfectly healthy with two routes attached to a hostname
nobody could look up.

**A route is not an address.** A Custom Domain is. If these ever need to be
rebuilt, attach the domains first and let them create their own records —
never delete a record in the hope that something else is holding the name.

<details>
<summary>Routes, and why they were used at first — kept as a record</summary>

A Custom Domain is the tidier mechanism: it owns the DNS record and provisions
the certificate. It also **refuses to attach to a hostname that already has DNS
records**, and the apex still carries the four A records that pointed at GitHub
Pages:

```
100117: Hostname 'comodor.ai' already has externally managed DNS records
```

Deleting those needs a DNS-editing credential, and no Workers token is one —
`wrangler login --scopes-list` tops out at `zone:read`. So the site is attached
with routes instead. A route intercepts at the edge before the origin is
dialled, so those A records are never followed and Pages never serves a byte,
and switching over is atomic: there is no window with no site.

**This is the part that was wrong.** It reads as though the records were
merely untidy. They were load-bearing: they are what made Cloudflare answer for
the name at all, and the routes only worked because of them.

</details>

### The assets Worker

Serving 85 exported files needs nothing to run, and Cloudflare's own wording
for what that costs is *"requests to static assets are free and unlimited"*. A
script in front of every request would route each one through a function with
nothing to do and put the free plan's daily request ceiling in front of a
marketing page.

`wrangler.jsonc` now declares a `main`, and that sentence still holds. The
script is reached only through `assets.run_worker_first`, which names one
prefix — `/api/integrations/github/*`. Every other request goes to the asset
server without the script running at all. Nothing about serving the page
changed.

### The GitHub App

Six endpoints on `comodor.ai`, all behind that one prefix:

| | |
|---|---|
| `POST /api/integrations/github/install` | start a flow; takes the agent's public key, returns a signed state and the URL to open |
| `GET /api/integrations/github/setup` | where GitHub sends the browser after installing; starts the user check |
| `GET /api/integrations/github/callback` | where the user check returns; **the only place a grant is issued** |
| `POST /api/integrations/github/claim` | exchange the receipt for the verified installation **and a grant** |
| `POST /api/integrations/github/token` | an installation access token, one hour — **signed request** |
| `POST /api/integrations/github/verify` | what an installation is now — **signed request** |
| `POST /api/integrations/github/webhook` | what GitHub has to say |

They are here and could not be anywhere else. A GitHub App authenticates by
signing a JWT with a private key; that key cannot live in a static file or on
each user's machine, so it is a Cloudflare secret this Worker reads and nothing
else does. What crosses to an agent is an installation token that lasts an
hour.

#### Who may be *given* a grant

`setup` receives `installation_id` in a query string. Confirming with the app
JWT that such an installation exists is not the same question as whether it
belongs to the person at the browser — the app JWT can see every installation
of the app, so it answers yes about strangers. GitHub's documentation says this
directly: to trust the setup URL you must authenticate the user and check the
installation is one they can reach.

Without that, this worked:

```
attacker → /install with the attacker's own key    → a valid state
attacker → /setup?installation_id=VICTIM&state=THEIRS
Worker   → the app JWT confirms the installation exists
Worker   → issues the VICTIM's grant, naming the ATTACKER's key
attacker → /token, signed with the key they hold
```

So `setup` issues nothing. It redirects into a GitHub user authorisation for
the same App, and `callback` issues the grant only after all of:

1. the OAuth state opens under our secret and has not expired;
2. the browser presents the PKCE verifier for the challenge inside that state;
3. GitHub exchanges the `code`, server side, for a user access token;
4. `GET /user/installations` — asked **as the user**, not as the app — lists
   the installation the flow is for;
5. and that user is entitled to the **whole** of that installation.

Step 5 is separate from step 4 and the gap between them was a privilege
escalation. `/user/installations` answers "can this person see it", which an
ordinary organisation member with read on one repository can. A grant covers
the installation entire — `/token` mints with every repository and permission
the app holds — so answering step 4 alone would have handed that member write
on every other repository in it.

| the installation sits on | who may connect it |
|---|---|
| a personal account | that account, and only it. Not a collaborator on one of its repositories |
| an organisation | an active member with `role: admin` — what GitHub calls an owner |
| anything else | nobody. An account type this does not recognise is refused rather than guessed at |

Organisation owners are the people who could install, uninstall or re-scope the
app anyway, so this grants nothing they could not already take.

Membership is read as the user through `GET /user/memberships/orgs/{org}`. If
that call fails for any reason — including a missing permission — the
connection is refused: a check that cannot run has not passed.

The user access token exists between 3 and 4. It is never persisted, never
logged, never in a response, and never reaches the agent. Ordinary work is
still installation access tokens alone; OAuth bootstraps a connection and
appears nowhere in a turn.

**PKCE, and what each half of it does.** GitHub supports `code_challenge` and
`code_verifier` with S256, so the authorisation code is bound at GitHub to the
verifier this Worker sends when redeeming it — a code intercepted on its way
back cannot be exchanged by anybody who does not also hold the verifier.

The same verifier is checked here too, against the challenge inside the signed
state, and that is not redundant: it says the callback arrived at the browser
that started the flow, which is a statement about this Worker's own state
rather than about the code. A genuine state handed to somebody else's browser
fails it before any code is redeemed.

The verifier lives in a `HttpOnly; Secure; SameSite=Lax` cookie scoped to this
path. `Lax` rather than `Strict` is forced rather than chosen: the callback
arrives as a top-level navigation from github.com, and `Strict` would withhold
the cookie on exactly that hop.

#### Who may ask for a token

`/token` and `/verify` do **not** accept an `installation_id`. An installation
id is a small integer that appears in URLs, so granting on one would let anyone
who learned another person's id obtain a working token for their repositories.

Instead, each connection has a key pair the agent generates at
`comodor github connect`. The public half travels in the signed state; the
Worker returns a **grant** — `{version, installation_id, account id, account
type, actor id, actor login, public key, fingerprint, issued_at}`, HMAC-signed
under `GITHUB_APP_WEBHOOK_SECRET`. Every later request carries the grant, a
timestamp, a nonce and an ECDSA P-256 signature over all four.
`workers/site/github/grant.js` checks the grant first, then the signature
against the key the grant names, then reads the installation id **out of the
grant**.

#### And whether they still may

A grant has no expiry, so an entitlement checked once at issue time would be
permanent: an organisation owner who connects on Monday and is demoted on
Tuesday would still mint full installation tokens on Wednesday.

So the grant names the person it was issued to, and `entitlement.js` asks
GitHub again at **every** mint. For an organisation, in this order:

1. resolve the installation as the app — and refuse if its account id or type
   is no longer what the grant says;
2. mint a token carrying **`members: read` and nothing else**;
3. `GET /orgs/{org}/memberships/{actor_login}` with that token;
4. require `state: active`, `role: admin`, and the membership's own `user.id`
   to equal the grant's actor id — the id, because a login can be changed and
   a freed one claimed by somebody else;
5. only now, mint the full installation token.

Step 2 is the part worth not skipping. Using the full token to decide whether
the full token is allowed means the credential exists before the decision does.

A personal installation needs no call: the grant's actor id must equal the
account id GitHub reports for the installation.

**Everything fails closed** — a missing permission, a 404, a rename, an id
mismatch, a network error, an unrecognised account type. There is no path back
to what the grant said when it was issued.

`/verify` runs the same check. An endpoint that refused to *act* but still
described the installation would report a private organisation's account,
repository selection and permission set to somebody who had left it.

**The grant format is `g2`.** A `g1` grant does not name an actor and cannot be
upgraded in place — the missing field is not something either side can look
up — so it is refused with a message telling the person to run
`comodor github connect` again. Anyone who connected before this deploys will
need to.

**What this cannot undo.** An installation token already minted stays valid for
up to an hour, and GitHub offers no revocation for one. That window is not
closable here. What is closed is the refresh: a grant cannot obtain another
token once the person behind it loses access.

Nothing is stored for any of this. The grant carries its own contents and its
own signature, which is what makes it possible without a KV namespace or a D1
database — neither of which exists for this integration.

The freshness window is 120 seconds and there is no nonce ledger, so a captured
request can be replayed inside it. That is stated rather than glossed: it
requires breaking TLS first, and the grant fixes the installation, so a replay
mints exactly what the original would have.

Three test files cover this, and all run in `npm test`:

```bash
npm test          # 114 tests, including:
                  #   authorisation.test.mjs        — 27, forgery and replay
                  #   setup-authorisation.test.mjs  — 31, who may be given one
                  #   entitlement.test.mjs          — 18, whether they still may
                  #   agent-vector.test.mjs         —  8, real agent output
```

`agent-vector.test.mjs` is the one worth knowing about: the agent signs in
pure Python (the project ships one dependency, so the curve arithmetic is
written out) and this Worker verifies with Web Crypto. Two independent
implementations, so the fixtures in that file were produced by the agent and
are checked against `authorise()` here. A drift on either side fails there
rather than in production.

Set the secrets once:

```bash
npx wrangler secret put GITHUB_APP_ID
npx wrangler secret put GITHUB_APP_PRIVATE_KEY     # PKCS#8 — see below
npx wrangler secret put GITHUB_APP_WEBHOOK_SECRET
npx wrangler secret put GITHUB_APP_SLUG            # the app's URL name
npx wrangler secret put GITHUB_APP_CLIENT_ID       # user verification
npx wrangler secret put GITHUB_APP_CLIENT_SECRET   # user verification
```

All six are Cloudflare secrets. None is in this repository, in
`wrangler.jsonc`, in a build output, or in anything a browser receives.

### Settings on the GitHub App itself

In the app's settings under the `comodor-ai` organisation:

| Field | Value |
|---|---|
| **Setup URL** | `https://comodor.ai/api/integrations/github/setup` |
| **Redirect on update** | on — so changing a selection reconnects cleanly |
| **Callback URL** | `https://comodor.ai/api/integrations/github/callback` |
| **Request user authorization (OAuth) during installation** | **off** |
| **Webhook URL** | `https://comodor.ai/api/integrations/github/webhook` |
| **Webhook secret** | the same value as `GITHUB_APP_WEBHOOK_SECRET` |

**Organisation permissions:** `Members: Read`.

That one is not for doing anything with members. It is what
`GET /user/memberships/orgs/{org}` needs while connecting, and what
`GET /orgs/{org}/memberships/{user}` needs at every mint afterwards. Those two
calls are the only way to tell an organisation owner from an ordinary member.
Without the permission, GitHub answers 403 (or refuses the narrowed token with
422) and every organisation connection and every organisation mint is refused
with a message naming this permission — the integration fails closed rather
than falling back to trusting what it was told earlier.

It is read-only, it is used for nothing else, and no membership information is
stored or shown.

The callback URL must match exactly; GitHub refuses a `redirect_uri` that
differs by so much as a trailing slash.

"Request user authorization during installation" stays **off** on purpose. It
would send the browser to the callback immediately after installing, before the
setup URL has established which flow this is — the state would not be there and
the connection would fail. The user check is started by `setup`, which is the
one place that knows.

`GITHUB_APP_CLIENT_ID` and `GITHUB_APP_CLIENT_SECRET` are on the same settings
page. The client secret is shown once; if it is lost, generate a new one and
put it back with `wrangler secret put` — nothing else has a copy.

GitHub hands out a **PKCS#1** key (`BEGIN RSA PRIVATE KEY`); Web Crypto reads
only **PKCS#8**. Convert it first, or the Worker refuses with this same line:

```bash
openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt \
  -in comodor.private-key.pem -out comodor-pkcs8.pem
```

`GITHUB_APP_CLIENT_ID` and `GITHUB_APP_CLIENT_SECRET` were once deliberately
unset, on the reasoning that installation is not OAuth and nothing here needs a
GitHub *user* identity. That was right about ordinary work and wrong about one
moment: confirming an installation belongs to the person claiming it is exactly
a user-identity question, and nothing but a user token can answer it.

So they are required, and the rest of that reasoning still holds. No OAuth
token is stored, none is refreshed, none reaches an agent, and none is used for
anything after the connection is made. Every turn afterwards acts as the app
against an installation.

Tests, none of which need a key or a network:

```bash
npm run test:github
```

### `get.comodor.ai`

The one address here that genuinely needs code at request time. Every install
line on the page points at it:

```
curl -fsSL get.comodor.ai | sh
irm get.comodor.ai | iex
```

So it has to read who is asking and answer differently, which a static export
cannot do by definition. It fetches the scripts from the site rather than
carrying copies, so editing `lib/scripts/install.sh` and deploying the site is
enough — a copy would drift the first time somebody fixed the installer and
forgot this Worker existed.

**The order of its checks is the whole trick.** PowerShell's `Invoke-RestMethod`
introduces itself as:

```
Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.26100; en-US) PowerShell/7.4.6
```

It opens with `Mozilla/5.0`, exactly as a browser does. Check for a browser
first and every Windows install is handed an HTML page to run. PowerShell is
therefore tested first and the browser check is last. `workers/get/dispatch.test.mjs`
holds the real agent strings:

```bash
node --test workers/get/dispatch.test.mjs
```

### After a DNS change, check this subdomain

Moving `comodor.ai` on to Cloudflare's nameservers did not carry
`get.comodor.ai` with it, and the record simply was not there afterwards — so
every install line on the front page failed to resolve, while the site itself
looked perfectly healthy. Nothing on the page can tell you this has happened.

```bash
curl -sS -m 20 https://get.comodor.ai | head -2                    # #!/bin/sh
curl -sS -m 20 -A "Mozilla/5.0 (Windows NT 10.0) PowerShell/7.4.6"      https://get.comodor.ai | head -2                              # Windows installer
curl -sS -o /dev/null -w '%{http_code} %{redirect_url}
'      -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0"      -H "sec-fetch-mode: navigate" https://get.comodor.ai          # 302 to the page
```

The Worker is attached with a **Custom Domain**, not a route: a custom domain
creates its own DNS record and provisions the certificate, so the hostname is
declared in `workers/get/wrangler.jsonc` rather than living only in a dashboard
nobody thinks to check.

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

## GitHub Pages (previous host)

Kept because the constraints below are real and the export still has to satisfy
most of them. The site moved off Pages for two reasons: its HTML is served
`Cache-Control: max-age=600` and that number cannot be changed, and its terms
exclude a site "primarily directed at ... providing commercial software as a
service", which a product page drifts towards the moment anything is sold.

The site also builds as a static export and publishes to Pages from the `site`
branch of `ifekri/Comodor`. `main` — the branch somebody lands on to read the
agent — never contains any of this.

```
https://ifekri.github.io/Comodor/
```

`.github/workflows/pages.yml` does the whole thing on push. Two settings decide
whether the result works at all:

A push builds for `comodor.ai` — assets at the root, plus a `CNAME`, without
which Pages drops the domain on the next deploy. That is the default because
the alternative would mean every ordinary commit shipping a build that is
broken on the real domain.

To build the github.io preview instead, run the workflow by hand with
**preview: true**.

### DNS

Pages needs these on the apex, replacing whatever the domain points at now:

```
A     @   185.199.108.153
A     @   185.199.109.153
A     @   185.199.110.153
A     @   185.199.111.153
AAAA  @   2606:50c0:8000::153
AAAA  @   2606:50c0:8001::153
AAAA  @   2606:50c0:8002::153
AAAA  @   2606:50c0:8003::153
CNAME www ifekri.github.io.
```

Until they are in place the Pages site cannot be reached at all: with a custom
domain configured, Pages redirects its own `github.io` URL to that domain, so
the preview address stops working the moment the domain is set.

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
node tools/a11y.mjs        http://localhost:4300/Comodor/
node tools/themes.mjs      http://localhost:4300/Comodor/
node tools/install-fit.mjs http://localhost:4300/Comodor/
```

`install-fit.mjs` checks the one string this page exists to deliver at fourteen
widths on all three tabs. It exists because the command used to grow a
horizontal scrollbar — only on the long macOS and Linux commands, and only in
the narrow band of widths where the hero has just gone two-column. Nine pixels
of overflow, hiding the end of the command with nothing on screen to say so.
The Windows tab is short and always looked fine, which is how it survived.

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
