# get.comodor.ai

One address that gives each system the installer it needs.

```bash
curl -fsSL get.comodor.ai | sh      # macOS, Linux, BSD
```

```powershell
irm get.comodor.ai | iex            # Windows
```

---

## Why it is not on GitHub Pages with the rest of the site

`comodor.ai` is a static export. A static host serves the same bytes to every
caller by definition, so it cannot answer `curl` and PowerShell differently —
and answering them differently is the entire feature.

A single script that both shells can run was the other candidate and does not
survive contact: PowerShell parses the whole file before running any of it,
while `sh` only reads as far as its `exit`. Three constructions were tried and
each one failed in one shell or the other. That asymmetry is why essentially no
project ships a sh/PowerShell polyglot.

So this is one small thing on hosting that can read a request. Everything else
stays exactly where it is.

## What it does

Reads the `User-Agent` and sends a **302** to the right script on `comodor.ai`.

| who is asking | where they go |
|---|---|
| `curl`, `wget`, httpie, or no agent at all | `/install.sh` |
| `WindowsPowerShell/5.1`, `PowerShell/7.x`, `pwsh` | `/install.ps1` |
| a browser | the page, at `#install` |

PowerShell is checked before the browser test on purpose: both of its agent
strings begin `Mozilla/5.0`, so a naive browser check hands a Windows user a
shell script.

`?ps1` and `?sh` override the guess, for a client that misreports itself and
for a link that has to be unambiguous.

A redirect rather than a proxy, so there is one copy of each script — at the
address the site already serves it from — and this file never needs
redeploying when an installer changes.

Verified that both clients follow a cross-host 302 and receive the body intact:
`curl -fsSL` because `-L` is in there, `Invoke-RestMethod` because it follows
by default.

## Deploying it

In the Hostinger panel:

1. **Websites → Subdomains**, create `get` under `comodor.ai`. Note the
   document root it gives you, usually `public_html/get`.
2. Upload `index.php` into that folder. Nothing else is needed — `index.php`
   is already a default index, so no `.htaccess` and no rewrite rules.
3. Issue the SSL certificate for the subdomain if the panel does not do it by
   itself. `curl` will refuse an untrusted certificate, and the error it prints
   is not one most people will diagnose.

DNS needs no change: the subdomain record is created by the panel, and
`comodor.ai` keeps pointing at GitHub Pages exactly as it does now.

## Checking it afterwards

```bash
curl -sI get.comodor.ai                            | grep -i location   # install.sh
curl -sI -A "PowerShell/7.4.0" get.comodor.ai      | grep -i location   # install.ps1
curl -sI -A "Mozilla/5.0 Chrome/120" get.comodor.ai | grep -i location  # the page
curl -fsSL get.comodor.ai | head -2                                     # the real script
```

The response must carry `Vary: User-Agent`. Without it a shared cache can hand
the PowerShell script to the next person running `sh`.

## If it is ever removed

Nothing breaks. Every install command that names a script directly —
`comodor.ai/install.sh`, `comodor.ai/install.ps1` — keeps working, because
those are what this redirects to.
