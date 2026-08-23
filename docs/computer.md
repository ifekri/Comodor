# Using your screen

Comodor can drive the machine the way a person does — look at the screen, move
the mouse, click and type — in any application, not only a browser.

This is the most powerful thing it can do and the most dangerous. Read the
[permission model](#permission) before you switch it on.

> **Windows only so far.** The macOS and Linux backends are not written. On
> those platforms the tool is not offered at all, rather than offered and
> failing — see [Why it is not there](#why-it-is-not-there).

---

## What it looks like

You watch it happen. Before the pointer moves, a halo appears where it is about
to click:

```
   ┌─────────────────────────────────────────┐
   │   Comodor · 14m 32s left, anywhere      │   ← the panel, top centre
   │   move the mouse to a corner to stop    │
   └─────────────────────────────────────────┘


              ╭──────────╮
              │   Save   │      ◎  ← the halo, drawn before it moves
              ╰──────────╯
                              clicking (842, 517)
```

The pointer then travels there over about a third of a second rather than
teleporting, and a ripple marks where the click landed.

**The pause is not decoration.** It is the moment in which you can still stop
it. A cursor that jumps and clicks in the same instant gives you nothing.

If the agent is running somewhere else — a server, a container — the same thing
appears in the [web interface](web.md) instead: the frame it looked at, with a
marker where it acted.

---

## Switching it on

Two steps, deliberately. Neither happens by itself.

**1. Allow the tool to exist**, in `~/.comodor/config.json`:

```json
{
  "computer": {
    "enabled": true
  }
}
```

Until this is set, the model is not offered the tool at all. It is not in the
tool list, so it cannot ask for it and cannot be talked into it.

**2. Allow it to act**, at the moment it matters:

```
/computer 15m              fifteen minutes, anywhere on screen
/computer 1h this app      one hour, only while the current window is in front
/computer                  how things stand
/computer stop             end it now
```

Or let the model ask. The first time it needs the screen you get this:

```
  Let Comodor use your screen, mouse and keyboard?

  It will be able to see everything on your screen and to click and type
  anywhere, in any application.

  Screenshots go to the model. Whatever is on screen goes with them - open
  messages, tokens, anything visible. Redaction works on text and cannot
  read pixels.

  It will never touch a password manager, a window asking for a password,
  a locked screen, or Comodor's own window.

  To stop it at any moment: move your mouse into a corner of the screen.

  [15 minutes]  [15 minutes, this app only]  [1 hour]  [no]
```

---

## Stopping it

**Move the mouse into a corner of the screen.** That is the whole thing.

It works while the agent is holding the pointer, which no keyboard shortcut can
promise — the agent may be typing into a window at that moment. It is also what
people actually do when their screen starts moving on its own.

Touching a corner ends the run and takes the permission away. Asking again is a
new grant.

The agent can still click in a corner itself — the Start button, a close box.
It remembers where it left the pointer, so only a pointer that moved somewhere
nobody put it counts as you.

Other ways to stop it, when your hands are on the keyboard:

```
/computer stop       ends the permission
Esc                  stops the current task
```

---

## Permission

A grant is three things at once, and none of them is a checkbox.

| | |
|---|---|
| **A scope** | everywhere, or one application by its window title |
| **A clock** | it expires, and the time left is on screen the whole time |
| **A way out** | the corner, which works while the pointer is being driven |

It is checked **before every single action**, not once at the start. A window
that appears halfway through a granted run is caught.

### Refused whatever you have allowed

- A password manager — 1Password, Bitwarden, KeePass, LastPass, Dashlane,
  NordPass, and the system credential stores.
- Any window whose title mentions a password, passphrase, 2FA or a one-time
  code.
- A wallet or hardware-wallet application — MetaMask, Ledger Live, Trezor.
- Anything that looks like online banking.
- A locked screen.
- **Comodor's own window.** An agent that clicks into the terminal driving it
  types into its own prompt.

Add your own:

```json
{
  "computer": {
    "never": ["Internal HR", "Payroll"]
  }
}
```

Matched anywhere in the window title, case-insensitively.

### What a grant is not

It is **never written to your config file**. Closing Comodor ends it. There is
no "always allow" for the screen and that omission is deliberate.

A repository cannot enable this. `computer` is not in the list of things a
project's `.comodor/config.json` may set, and a repository that tries is
refused out loud. See [Safety](safety.md#what-a-repository-may-set).

---

## What goes to the model

**Screenshots, and everything visible in them.** This is worth stopping on.

If a password manager is open behind your editor, if a chat window has a message
in it, if an API key is printed in a terminal — that is in the picture, and the
picture goes to whichever provider you configured.

Comodor's redaction works on text and cannot read pixels. There is no way around
this: the feature is "let the model see your screen".

Practical advice:

- Close what you would not paste into a chat window.
- Use `/computer 1h this app` so it only acts while one window is in front —
  though it still *sees* whatever is in the screenshot.
- Prefer the [browser tool](browser.md) when the work is a web page. It returns
  text, not pixels, and costs a fraction as much.

---

## What it can do

Seventeen actions, behind one tool. The names are Anthropic's, because models
are trained on that vocabulary.

### Looking

| Action | What it does |
|---|---|
| `screenshot` | The active monitor. `whole_desktop: true` for every monitor. |
| `zoom` | A region, at full resolution — how it reads small text |
| `cursor_position` | Where the pointer is |

### Pointing

| Action | |
|---|---|
| `mouse_move` | Travel somewhere without clicking |
| `left_click` `right_click` `middle_click` | With optional modifier keys |
| `double_click` `triple_click` | Triple selects a line in most editors |
| `left_click_drag` | From one point to another |
| `left_mouse_down` `left_mouse_up` | For anything a drag cannot express |
| `scroll` | Up, down, left, right, by wheel clicks |

### Typing

| Action | |
|---|---|
| `type` | Text, by character — correct on every keyboard layout |
| `key` | `Return`, `ctrl+s`, `alt+Tab`, `F5`, `Page_Down`, … |
| `hold_key` | Hold a key or combination for a duration |
| `wait` | Let something on screen finish |

Text is typed **by character, not by key position**. Pressing the key where `@`
sits on a US keyboard produces something else on a French one; naming the
character produces `@` everywhere, including on layouts with no key for it.

---

## Typed is not the same as arrived

Applications rewrite what is typed into them.

Windows 11's Notepad has autocorrect on by default. Typing `ümlaut` into it
produces `umlaut`. Nothing was lost in transit — every one of thirty accented
and non-Latin characters arrives intact when sent alone, and `üxqzv` in the same
position is untouched. The application changed it.

Comodor says so on every `type`:

```
Typed 29 characters. Applications can autocorrect or reformat what is
typed into them - take a screenshot if what arrived matters.
```

If the exact text matters — a password field, a config value, a commit message
— have it look again.

---

## Screenshots and what they cost

A screenshot is the most expensive thing this tool sends.

The size is fitted to what the model will accept: a long edge of 2,576 pixels
and a token budget. The default budget is 1,600 visual tokens, which gives a
readable picture on every screen tried.

| Your screen | At the default budget | Cost |
|---|---|---|
| 1920 × 1080 | 1480 × 833 | ~1,590 tokens |
| 3840 × 1080 | 2068 × 582 | ~1,554 tokens |
| 3840 × 2160 | 1064 × 599 | ~836 tokens |

**Do not set this too low.** The common advice of "capture at 1280 wide" assumes
a 16:9 screen. On a 3840 × 1080 display it means a three-times reduction, and at
that size the model is handed text it cannot read — so it guesses instead of
asking. Measured on that screen: menu labels illegible at 1280 wide, perfectly
clear at 2068.

```json
{
  "computer": {
    "screenshot_tokens": 1600
  }
}
```

700 is cheap and still readable on a laptop. 4784 is the most the model accepts.

**Old screenshots are dropped automatically.** Only the last two stay in the
conversation; the rest become a line saying one was there. Without this a
thirty-step task would carry close to fifty thousand tokens of pixels, nearly
all of them describing a screen that has since been clicked. Change it with
`agent.keep_screenshots` if you have a reason.

---

## Every setting

```json
{
  "computer": {
    "enabled": false,
    "screenshot_tokens": 1600,
    "grant_seconds": 900,
    "travel_seconds": 0.32,
    "overlay": true,
    "never": []
  }
}
```

| Setting | Default | |
|---|---|---|
| `enabled` | `false` | Whether the model is offered the tool at all |
| `screenshot_tokens` | `1600` | Legibility against price. Max 4784 |
| `grant_seconds` | `900` | How long a plain grant lasts |
| `travel_seconds` | `0.32` | How long the pointer takes to travel. `0` would work and be unwatchable |
| `overlay` | `true` | Draw the halo and the panel. Off for a machine nobody is sitting at |
| `never` | `[]` | Extra window titles never to touch |

---

## Why it is not there

If `computer` is not among the tools, one of these is true:

**The platform has no backend.** Windows only so far. The tool is not offered
rather than offered and failing every time — a tool the model can see and never
use invites a wasted call on every turn.

**It is switched off.** `computer.enabled` defaults to `false`.

Ask it directly:

```
/computer
```

```
no screen control: it is switched off. Set computer.enabled in your config.
```

---

## Under the hood

For the curious, and for anyone porting it to another platform.

**No dependencies.** Screen capture is GDI through `ctypes`; the downscale is
`StretchBlt` in `HALFTONE` mode, which averages rather than dropping pixels —
the difference between readable small text and speckle. PNG encoding is `zlib`
and `struct`, about forty lines. Input is `SendInput`.

**DPI awareness is set before anything reads a screen metric.** On a display
scaled to 125% — the default on most Windows laptops — a process that has not
declared itself DPI-aware is told the screen is smaller than it is, and every
click lands short by exactly the scale factor. The cause is invisible; it looks
like the model cannot aim.

**Coordinates are converted in one place.** The model answers in the pixels of
the picture it was shown, which is a shrunken crop of a screen starting at an
origin it was never told about. `Shot.to_screen` is the only code that knows
this, because a second copy is a second chance to get it wrong.

**The overlay is a click-through, never-focused window.** `WS_EX_LAYERED |
WS_EX_TRANSPARENT | WS_EX_NOACTIVATE`, so the pointer reaches what is underneath
and the keyboard stays where it was. It runs in its own thread with its own
event loop, and a failure to draw is a missing picture, not a missing feature —
the agent works with no display at all.

Porting to macOS or Linux means writing one file beside `win32.py` with the same
dozen functions. Nothing above that layer imports `ctypes`.

---

## See also

- [Safety and permissions](safety.md) — the rest of the permission model
- [The real browser](browser.md) — cheaper, when the work is a web page
- [From a browser](web.md) — watching it work from somewhere else
- [Cost](cost.md) — what a long desktop session actually costs
