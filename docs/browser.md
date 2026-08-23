# The real browser

Not a page fetcher. A browser that is actually installed — it runs JavaScript,
keeps cookies, and can log in.

---

## What it uses

Chrome, Chromium, Edge or Brave, whichever is on the machine. **Nothing is
downloaded.** It starts one in a profile of its own that is signed into nothing,
and closes it when the session ends.

If none is installed, `browse` falls back to a text browser that still answers
most questions about a page. Both are called `browse`, because choosing between
two things named "browser" is a turn the model should not have to spend.

---

## What comes back

Not a screenshot. The title, the readable text, and a **numbered list of the
controls actually on screen**:

```
  Sign in — Example
  ─────────────────────────────────────────────
  Sign in to your account. New here? Create one.

  [1]  textbox   Email
  [2]  textbox   Password
  [3]  button    Sign in
  [4]  link      Forgot your password?
```

The model acts on one by its number. That list is filtered to what is visible,
named, on-screen and not a duplicate — which is a great deal smaller than the
accessibility tree, and, measured, smaller than a screenshot of the same page.

A screenshot only when the question is visual — layout, styling, a chart —
because a picture costs the same every time and cannot be trimmed.

---

## Verbs

| | |
|---|---|
| `open` | go to a URL |
| `click` | a control, by its number |
| `type` | into a field, by its number |
| `scroll` | up or down |
| `back` | the previous page |
| `read` | the page again, after something changed |
| `look` | a screenshot, when the question is about how it looks |
| `script` | run JavaScript and get its value back |

---

## Watching it work

```json
{ "browser": { "headless": false } }
```

A visible window, so you can see what it is doing.

> This setting used to be ignored — `browser` was not registered as a config
> section, so every `browser` setting silently did nothing. Fixed in 0.9.0.

---

## Using a session you are already logged into

Rather than handing over your profile, start your own browser with a DevTools
port and point Comodor at it:

```bash
chrome --remote-debugging-port=9222
```

```json
{ "browser": { "port": 9222 } }
```

It attaches to that browser and uses the tabs and cookies already there. Close
the port when you are done — anything on your machine can use it.

---

## Every setting

```json
{
  "browser": {
    "executable": "",
    "headless": true,
    "width": 1280,
    "height": 800,
    "port": 0
  }
}
```

| | |
|---|---|
| `executable` | a specific browser. Empty means look in the usual places |
| `headless` | invisible by default, so it does not steal focus |
| `width`, `height` | the window |
| `port` | attach to a browser you started, instead of launching one |

A repository cannot set any of these — `browser.executable` names a binary to
launch. [Safety](safety.md#what-a-repository-may-set).

---

## `browse` or `web_fetch`?

| | |
|---|---|
| `web_fetch` | the page is a document. Strips it to text. Cheap |
| `browse` | the page is an application. Needs JavaScript, a login, or a click |

The model is told to prefer `web_fetch` and reach for `browse` when it will not
do.

---

## In a container

The Docker image ships Chromium and the fonts to render with it. Chromium's own
sandbox cannot start inside a container whose seccomp profile blocks user
namespaces, so Comodor detects that and retries without the inner sandbox —
keeping the container's confinement, which is the real boundary. [Docker](docker.md).

---

## Under the hood

The Chrome DevTools Protocol over a hand-rolled WebSocket. No dependency: the
RFC 6455 framing is about a hundred lines and is part of the package, the same
way the HTTP client and the SSE reader are.

---

## See also

- [What the agent can do](tools.md) — the other tools
- [Using your screen](computer.md) — when the work is not a web page
- [Cost](cost.md) — why it returns text rather than pictures
