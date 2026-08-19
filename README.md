# comodor.ai

The official site for [Comodor](https://github.com/ifekri/comodor), a terminal
coding agent that learns from the edits you make to its output.

The page has one job: hand the visitor the right install command for the machine
they are sitting at. Everything else on it exists to answer "why would I run
that".

## Shape

```
app/          layout, page, sitemap, robots
components/   the interface reconstruction, the install command, the demos
lib/          site.config.ts (every name and URL) and detect-os.ts
public/       install.sh, install.ps1 — served as plain text
styles/       tokens copied from the agent's Ember theme
```

The hero is not a screenshot. It is the Comodor interface rebuilt in HTML and
CSS, with the install command sitting where the prompt would be — so it stays
sharp at any zoom, the command is selectable text, and the design cannot drift
from the product without someone noticing.

OS detection only decides which tab opens first. Every platform's command is in
the markup from the first byte, and a `<noscript>` list repeats them, so a
visitor with scripting off or an unrecognised user agent still gets something
they can copy.

## Running it

```bash
npm install      # from the repository root; website/ is a workspace
npm run dev
```

Deployment, including the Hostinger settings, is in [DEPLOY.md](DEPLOY.md).
