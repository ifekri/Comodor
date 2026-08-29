# Changelog

Notable changes to Comodor. Versions follow [semantic versioning](https://semver.org).

## 0.19.1 — 2026-08-29

### WhatsApp setup, walked rather than documented

```bash
comodor whatsapp connect     # guided: links each page, checks each value
```

Eight things done in a browser and a terminal, in order, where getting one
wrong fails somewhere else entirely — a phone number pasted where the *number
id* goes fails at the first send with "Unsupported post request", and an app
secret that never got saved makes every webhook unverified, which looks exactly
like a bot nobody is talking to.

`connect` with no arguments now takes them one at a time and checks each as it
arrives: the token against Meta, the id for being an id rather than a phone
number, the secret for being a secret. A mistake is a sentence now instead of a
mystery next week. With arguments it is still the one-line form.

**The tunnel is started for you.** Meta will only deliver to HTTPS and will not
accept a self-signed certificate, so something has to sit in front of a process
listening on localhost — the genuinely hard step. `connect` runs `cloudflared`,
reads the address out of its banner and puts it where the dashboard needs it;
`comodor whatsapp start --tunnel` brings one up alongside the bot.

**And says which kind it is.** A quick tunnel gets a new hostname on every
start while Meta goes on delivering to the one it was given: a bot that works
until the first reboot and then silently receives nothing. That is said where
it is chosen rather than buried in a page, `start --tunnel` warns when the
address has moved, and the two commands that make a named tunnel are printed.

**The last step waits instead of assuming.** The endpoint is stood up and
Meta's verification callback is waited for, so the wizard finishes when Meta
has actually reached it.

### Honest about what it costs

About twenty minutes the first time against Telegram's one, and mostly in
Meta's dashboard — said in the wizard, the docs, the CLI reference and
`comodor help whatsapp`, along with the recommendation that Telegram is less
work for the same thing unless WhatsApp is specifically what you need.

And what is *not* needed, because everybody assumes otherwise: **no real phone
number, no payment method, no business verification.** Adding the WhatsApp
product creates a test number that messages five recipients for free, which is
four more than one person talking to their own agent requires.

### Fixed

`_wait_for_meta` took its timeout as a parameter default, which binds at import
— so nothing that changed it afterwards had any effect, and the wait was always
the full three minutes. It reads the constant at call time now.

## 0.19.0 — 2026-08-29

### WhatsApp

```bash
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook              # what to paste into Meta
comodor whatsapp pair                 # add your number
comodor whatsapp start --background
```

The same agent, reached from a WhatsApp business number. It runs the same
session the terminal, the browser and the Telegram bot run, so a task started
there learns the same lessons and lands in the same history.

**Meta's Cloud API**, which is the official one. The libraries most projects
reach for drive WhatsApp Web through a headless browser: they need Node, they
break whenever the web client changes, and they are against the terms the
account is held to. The failure mode is somebody's number being banned, which
is not a failure mode a coding tool gets to hand its users.

Two of Meta's decisions shape the whole of it.

**Messages are delivered, not fetched.** There is no long poll, so there is a
webhook — and a webhook can be reached by anybody who finds it, unlike a poll,
which only Telegram can answer. So every delivery is checked against an HMAC of
your app secret before it is parsed: in constant time, and against the raw
bytes rather than a re-serialised copy, because one different space fails a
genuine payload. Without a secret nothing verifies at all, and
`comodor whatsapp status` says so — a check that passes because nothing was
configured is worse than no check, because it looks like one.

The endpoint answers Meta *before* doing the work. Meta retries anything it
does not get a 200 for within seconds and an agent turn takes minutes, so a
webhook that waited would get the same message delivered five times. Message
ids are remembered, so a redelivery that arrives anyway does not become a
second turn.

**Buttons are rationed.** Three reply buttons of twenty characters, or one
button opening a list of ten rows. Those are hard API errors rather than
things Meta trims, and a rejected message arrives as a bot that answers nothing
with the reason only in a log. So the menu is a list and it is exactly ten
rows; paging takes eight because the two arrows count against the ten; and
every label is clipped where it is built rather than where it is used.

Two things follow from the medium and are said plainly rather than worked
around. WhatsApp cannot edit a message, so a turn cannot be watched growing —
it says one line when it starts, speaks occasionally while it works, and sends
the answer once. And Meta only permits free-form messages within a day of your
last one, so a task finishing after that cannot be reported until you write
again.

The allow-list matters more here than on Telegram, not less. A Telegram bot has
a username a stranger has to find; a WhatsApp business number is a phone number
and strangers message phone numbers. Everybody not paired gets silence.

### Nothing duplicated to get there

The background process and the systemd, launchd and Task Scheduler units were
already the same idea for both channels, so they moved into one place
parameterised by which channel they manage — and the tests that covered them
now run against both rather than asserting Telegram twice.

What is *not* shared is the part that genuinely differs. Sharing the
conversation code would have been a lie dressed as an abstraction: one channel
edits a message to stream a reply and the other cannot edit at all, one draws
eleven buttons in a grid and the other is allowed three.

### Everywhere it should be

The first-run wizard offers it beside Telegram and hands over to
`comodor whatsapp connect` rather than pretending a Meta app, a business
number, an app secret and a public HTTPS address can be produced at a terminal.
`comodor doctor` says whether it is running and whether webhooks can be
verified. The browser's Admin panel reports it, without the token, the app
secret or the numbers. There is `comodor help whatsapp`, a CLI reference, a
configuration section, and [the page](docs/whatsapp.md).

## 0.18.0 — 2026-08-29

### One wordmark

There were three. An eighty-two column block one and a forty-one column one in
the program, and a slanted face made of slashes and underscores in the shell
installer — so an install put one logo on screen, the program it had just
placed put a different one on the next, and neither was the one in the README.

There is one now: the README's, twenty-eight columns and three rows, drawn the
same in the installer, the setup wizard and the interface. Under `--ascii` it
becomes the one-line form instead of a transliteration — the letters are
half-blocks, and `^` and `_` in place of those produced a smear that read as
neither a word nor a logo.

**The installer draws it once per phase.** It used to print the banner a second
time before the last question without clearing between, so an install ended
with two of them on screen a page apart and the question scrolled away from the
logo belonging to it. Each phase now gets a screen: the mark at the top, and
under it only the step being worked on. Where the screen cannot be cleared — a
pipe, a log, a CI job — it prints once and the phases follow each other.

### Setup no longer drops you at a prompt

It ended by returning to the shell. Somebody answered six questions, watched it
say `Ready.`, and was put back at a prompt with nothing running — and
`comodor setup` is the command the installer calls, so that was the last thing
an install did.

```
 What now?
   1  Start Comodor          — the interface, here in this terminal
   2  Start the Telegram bot — in the background, answers while this is closed
   3  Both
   4  Nothing yet
```

On the same screen as `Ready.` rather than one that wipes it. The Telegram
lines appear only when there is a bot connected and paired, because an option
that cannot work is worse than an option that is not there.

### The bot runs without a terminal

It only ran in the foreground, holding a terminal open — which is the one
situation in which nobody needs a phone.

```bash
comodor telegram start --background   # detached
comodor telegram stop
comodor telegram status               # is it up, since when, as which pid
```

Detached means detached: closing the terminal, logging out and ending the
session all leave it answering. Output goes to a log beside your config, and
that log is appended to rather than replaced — the reason a bot stopped last
night is in the lines a restart would otherwise erase.

**Surviving a reboot is the operating system's job**, so there is a command
that asks it properly:

```bash
comodor telegram service show        # read the unit first
comodor telegram service install
```

A systemd **user** unit on Linux, a LaunchAgent on macOS, a Task Scheduler task
on Windows. A user service on all three and never a system one: this is an
agent that reads and writes your files with your credentials, and more
authority than the person who owns those files buys nothing and costs
everything if it is ever wrong. `service show` prints the unit before
`service install` writes it.

The bookkeeping around a background process is the part that goes wrong
quietly, so a pid file left behind by a crash is cleaned up rather than making
`start` refuse forever; a recycled process id is checked against the command
behind it before `stop` kills anything; and a child that dies in its first
second is reported as the failure it is instead of as a running bot.

`comodor doctor` now says whether the bot is actually up, not merely whether it
could be.

## 0.17.1 — 2026-08-29

Packaging metadata only: the project is published under the account that owns
it. No change to the program.

## 0.17.0 — 2026-08-28

### The first run fits one screen

Installing on an unfamiliar machine turned up a run of faults in the first five
minutes, all of them reachable before the first task. This is those.

**One option is one row again.** The note column was told to ellipsise but not
to stop wrapping, so a four-hundred-character skill description quietly became
eight lines. The window arithmetic counts options, not lines — so ten of them
claimed to fit and took sixty rows, the frame ran off the bottom of the screen,
and the cursor could be moved several times before the window noticed it had
left. One fault, two symptoms, and the second was the one people reported.

**Tab reads the rest.** A list that truncates with no way to see what was cut
is a list you cannot choose from, so tab opens the whole description under the
list — in the same frame, sized to what it needs rather than a fixed height,
and never taking so much that the list it is describing disappears.

**The arrow stayed visible.** At a hundred and forty-seven entries the note
column's demand for width squeezed the cursor marker and the checkbox to
nothing, so the one mark saying where you were vanished exactly when the list
was long enough to need it. The note yields now; the marks do not.

**Every step clears the one before it, on every kind of terminal.** Clearing
was tied to raw key reading. Over a connection where that does not work — and
that is a normal way to meet a new machine — the wizard fell back to typed
numbers and stopped clearing as well, so each question printed underneath the
last and the skills question printed all hundred and forty-seven entries in
full. Those are two capabilities and one failing no longer costs the other.

The typed path is a real path now, not a fallback: it pages, it searches with
`/word`, it reads one entry in full with `?7`, and its numbers are absolute so
a number you noted stays the number you type. The page size counts the recap,
which grows a line per answer — a fixed allowance fitted the first question and
overflowed the last.

**The wordmark is the same wordmark.** It ignored both the width it was given
and `--ascii`, so setup drew one logo and the interface behind it drew another.
And the unicode probe read the encoding before asking for UTF-8, which on
Windows meant a fresh console was told it could not draw the thing it was about
to draw.

### It offers you your phone

The Telegram bot shipped and nothing offered it — not the setup wizard, not
`comodor help`, not `comodor doctor`, not the browser's panel. A capability
nobody is told about is a capability nobody has.

It is now the last question of the first run. The token is checked against
Telegram there and then, rather than days later when a typo looks like a broken
feature, and the pairing finishes before the wizard does. Declining costs one
keypress, and abandoning it writes nothing.

**Three buttons in that bot had nothing behind them.** History, Model and
Skills were drawn on the keyboard and tapping them did nothing at all: no
message, no error, no note — the one control that is worse than a missing one,
because the natural response is to press it again. All three work, and a test
now walks every button and every screen those buttons open.

`/start` says what it is pointed at — model, folder, and what it is allowed to
do — and carries the settings themselves rather than hiding them behind
*Settings*. Lists longer than a screen page six at a time.

**And the status behind those buttons was blank.** It read four keys that have
never existed on a session, so Folder, Context and Spend reported nothing on
every status anybody asked for, and every learned rule printed as an empty
bullet. The tests were green throughout, because they invented the same keys
the code was reading.

### Everywhere else it should have been

`comodor help` has a Telegram topic. `comodor doctor` says when a bot is
connected that nobody is paired with — correct behaviour, indistinguishable
from broken, so it is said. The browser's Admin panel reports it, without the
token or the account ids. `docs/configuration.md` documents the settings,
`docs/cli.md` the commands, and `docs/getting-started.md` and `docs/skills.md`
the questions as they are now actually asked.

### Skills say what they are

Forty-four catalogue descriptions were cut at four hundred characters, thirty
of them mid-word — one ended "…semantic HTML, for" and nothing anywhere had the
rest. The catalogue carries the whole description now and the display decides
how much to show.

## 0.16.0 — 2026-08-28

### A model that runs on your own machine

```bash
comodor local list                       # what you can run, and what is here
comodor local get qwen2.5-coder-7b-q4    # download it, with a progress bar
comodor local use qwen2.5-coder-7b-q4
```

Pick one, watch it download, then use it with the network unplugged. No key and
no account. It appears among the providers as **Local LLM**, in the terminal and
under **Admin → Local LLM** in the browser, with the same list, the same
progress and the same buttons.

The list is a JSON file, so adding a model later is an edit rather than a
release — a name, a description, an https URL, the byte count and the checksum.
Anything left out is reported as unknown rather than guessed.
[How to add one](docs/local-models.md).

Downloads **resume**. One to nine gigabytes over a home line cannot mean
starting again because a laptop slept, so the bytes go to a `.part` file and
the next attempt continues from where it ended — the button reads
`Resume (37%)`.

Downloads are **verified**. Every entry carries an exact size and a SHA-256,
and the file is not accepted until it matches. This is not belt-and-braces: a
truncated model file is not obviously broken. It loads, and then produces
nonsense, and somebody spends an evening wondering why a well-regarded model is
useless. A file that fails is deleted rather than left to be half-trusted.

Inference runs in a **separate process** that keeps the model loaded between
requests, which is what Ollama, LM Studio and llama.cpp all do and for the same
reasons: generation is a long CPU-bound loop that would otherwise stall the
interface, loading four gigabytes must happen once rather than per turn, and an
out-of-memory kill then ends the model server instead of your session. The
server starts on your first message, not at startup — loading the weights on
every `comodor` invocation, including the ones that never ask the model
anything, would be a blank screen for no reason.

You need something to run a GGUF: `brew install llama.cpp`, `winget install
llama.cpp`, or a build from llama.cpp itself. Ollama and LM Studio work too.
`comodor local list` says plainly when nothing is available, so you find out
before spending an hour on a download rather than after.

Memory and disk are checked before the download starts, with a tenth of the
disk left spare — one that fills the last byte does not merely fail, it takes
the rest of the machine with it.

## 0.15.0 — 2026-08-24

### It asks before it guesses

When a request can be read more than one way, Comodor now settles what it can
by reading the project and puts the rest to you as one short multiple-choice
form — three or four questions, before it writes anything.

Given *"add rate limiting to the web server"* it read ten files and then asked
about client identity, the over-limit response and which routes to cover. One
of its options read "By IP address (recommended) — the server already reads
client_address for the loopback check", which is a line it had read a moment
earlier. Then it built.

Every question ends with a row you type your own answer into. Comodor adds that
row, not the model, and the model cannot remove it — the point of it is
covering what the model failed to think of.

Sending a form with questions left blank is fine and is not the same as
closing it. Comodor tells the agent which ones you skipped and that you have
therefore not constrained them, so it decides those itself and says which way
it went. Closing the form tells it to carry on with sensible defaults and not
to ask again.

In the terminal: tabs with a mark on each answered question, arrows to move,
space to pick, `enter` to advance or send, `ctrl+s` to send from anywhere,
`escape` to close. In the browser: the same form as a dialog.

At most four questions and four options each — plus the write-your-own row,
which does not use up one of the four. It never asks about something it could
find out by reading, never asks permission to proceed, and never asks you to
confirm its plan back to it. [Documentation](docs/questions.md).

### Also

- The editor page named only Zed. JetBrains and VS Code are where most people
  will meet ACP, and both are now written up with where the configuration
  actually goes — along with the error you will hit when a provider refuses
  your key, which arrives looking like a broken agent rather than a dead key.

## 0.14.0 — 2026-08-24

### Comodor runs inside your editor

```bash
comodor acp
```

Comodor speaks the [Agent Client Protocol](https://agentclientprotocol.com), so
Zed — or anything else that implements it — can drive it from its own panel.
You will not type that command: the editor launches it. `comodor acp
--print-config` prints the block your editor is asking for.

The editor gets streaming replies, tool calls named and marked read / edit /
execute so it can pick an icon, permission prompts asked and answered in the
editor, task lists drawn as plans, a stop button that actually interrupts, and
the same sessions the terminal resumes. The working folder is whichever project
you have open, and that is what confines every write.

It is the third interface and the smallest of the three, because the agent was
never the interface. The terminal draws the events, the browser sends them as
JSON, and this translates them into protocol notifications — all three watching
the same thing.

What it does not do is take a model provider from the editor. Comodor's
provider, model, rules, skills and permissions stay its own, set up with
`comodor setup` or in the browser. A Comodor that has never been configured
says so in the editor and names the command to run, rather than failing on the
first task.

See [In your editor](https://github.com/ifekri/Comodor/blob/main/docs/acp.md).

## 0.13.0 — 2026-08-24

### Sign in to OpenRouter instead of finding a key

Choose OpenRouter and you are asked how you want to connect: sign in, or paste
a key. Both stay — neither is better for everybody. Signing in is fewer steps
for somebody starting out; a key is what you want when Comodor is on a server,
when it comes from a team vault, or when you already have one.

Signing in opens OpenRouter in your browser and brings a key back on your own
account. Nothing is registered with anybody: it is OAuth PKCE, where the proof
is a random number Comodor invents and keeps rather than a credential a vendor
issues — which is also why there is no secret in the package to leak.

It works where there is no browser. Over SSH or in a container, OpenRouter
shows a code and you paste it back. Refused across a network, for the same
reason typing a key is: what comes back is a credential and there is no TLS
here.

### The model picker is a proper dropdown

Four hundred and sixteen models is too many for a plain list. It opens when you
ask, filters as you type, and moves with the arrow keys — the same picker in
the setup screen and in Admin, so a search that works in one works in the
other.

Sorted by vendor and then by model, so `bytedance/…` comes before
`bytedance-seed/…` rather than the other way round. Each row shows what
decides a choice:

```
anthropic/claude-sonnet-4.5
1M ctx · 64K out · $3.00/M in · $15.00/M out          VISION
```

A model that **cannot call tools** is marked in the warning colour. Seventy of
those four hundred cannot, and one of them does not give you a slower Comodor
— it gives you one that cannot read a file. A price the provider did not state
still reads "price not stated", never "free".

### Smaller

- The dropdown is positioned against the window, so it is no longer clipped by
  the panel it sits in — it opens upward where there is no room below.

## 0.12.0 — 2026-08-24

### The rule count was counting another folder's rules

The status strip said eight and the Rules panel beside it listed none. The
eight were real — learned in a different project — and the strip was counting
every confident rule in the brain while the panel, correctly, showed only the
ones that apply where you are. A number you cannot click through to is a
number to distrust.

They are the same number now. Rules learned in other folders are counted
separately and named as such.

### Model lists come from the provider

The list of models was six names written into a file by hand. OpenRouter
publishes four hundred and nineteen and will tell anybody who asks, without an
API key.

So it asks, caches the answer for six hours, and says which of those it is
doing — "from the provider, just now", or "checked two hours ago". When it
cannot ask it serves the built-in names and marks them as built-in. Each model
shows its context window and what it costs per million tokens in and out; a
price the provider did not state shows as *price not stated* rather than as
free, because those are different and the difference costs money.

### Admin manages things

It listed the model, the mode, the ceilings and the paths, all of it true and
none of it touchable — a status page with the wrong name on the tab. It now
changes:

- the **API key**, for the provider in use
- the **model**, from the live list, searchable
- the **provider**, the **mode**, and whether it keeps going on its own
- **skills** — install from the library, remove, or switch one off
- the **working folder**

Switching a skill off is a setting rather than a deletion, and Comodor will
not delete a skill it did not install.

### The working folder can be changed, and it means what it says

It is what confines every write, and until now it could only be set by
starting Comodor somewhere else. Changing it is a project change: a different
folder has its own learned rules, its own checkpoints and a conversation that
starts empty. The page says so before it does it.

Refused across a network, for the same reason a key is.

### The sidebar resizes, and long titles end properly

Drag the edge, or use the arrow keys, or double-click to reset; the width is
remembered. Below the tablet breakpoint the rail is a drawer with a width of
its own, so dragging is off there.

A long chat title stays on one line and dissolves into the space the delete
icon sits in, rather than wrapping to two lines or running underneath it. A
title that fits is not faded.

### Smaller

- The focus ring was four solid pixels of accent, the loudest thing in an
  interface built out of one-pixel borders. It is a hairline and a soft halo.
- An empty path in the folder field resolved to the current directory, so
  submitting a blank form moved the agent to wherever the process was started.
- The model picker pre-filled its search box with the current model, so
  opening it showed one row out of four hundred and nineteen.

## 0.11.0 — 2026-08-24

### Rules, in the browser

The terminal has had house rules since the beginning — `/rules`, `/rules
teach`, `/rules forget` — and the browser could not see them at all. That is
the wrong half to be missing: a rule is a standing instruction to the agent,
and somebody who cannot see what it has decided about them cannot correct it.

There is a tab for them now, driving the same engine, so a rule written in one
interface applies in the other. Two kinds sit in one list and the difference is
the point of the panel: what you wrote is obeyed from the first time, what the
agent noticed is obeyed once there is evidence and shows that evidence as a
count. Yours sort first.

A rule can now be switched off without being deleted, which is what people
want more often — a rule that is right in general and wrong for this project is
not a rule to throw away.

### Comodor can be set up from the browser

`comodor web` refused to start without a provider. That was right while the
page had nowhere to type a key into, and it made the browser interface
unreachable for exactly the person most likely to need it: somebody whose
Comodor is on a server or in a container, with no terminal in front of them.

It starts now and the page asks. Where a key may be typed is decided per
request rather than by the bind: from loopback it is the same as typing it in
the terminal on that machine; from inside a container it is allowed, because
the operator chose how to publish the port and was told what that means; from
anywhere else it is refused, because there is no TLS here and a key is a
credential with a bill attached.

Where it cannot be safe, the field is not drawn at all. A warning beside a box
is a warning next to a box somebody fills in anyway. What is drawn instead is
the two ways to do it safely, with the port already in the command.

### It offers what your machine already has

Setting an agent up means finding an API key: a billing page, a new secret, a
decision about who to pay. For a lot of people none of that is needed — a local
runtime is already running, or a key is already exported — and nothing asked.

Both setup paths now lead with what was found. Ollama with three models pulled
is offered as "running here — qwen2.5-coder:14b, llama3.3, deepseek-r1:14b",
first, with everything else underneath. A runtime that is up with nothing
pulled is reported and deliberately not offered: it would fail the first real
request.

Finding nothing takes about a third of a second, which matters because that is
what everybody without a local model pays. The first version took 3.7 seconds
— a refused connection was retried twice, and `localhost` resolves to two
addresses so each attempt was paid twice over.

## 0.10.3 — 2026-08-24

### The setup wizard has the wordmark at the top of every screen

Each question clears the terminal, so anything above it is gone by the first
one — and from then on every step arrived on a blank screen headed
`1/5 Which model provider?`, with nothing on it naming the program doing the
asking. Five screens in a row, including the last one, which is the one you
are left looking at.

It shrinks to a single line on a terminal that is narrow *or* short: five rows
of logo on a twenty-row screen is five rows the questions do not get.

The installer got it too, and asks the question it used to leave as homework:

```
── One thing left ─────────────────────────────────────────

  Comodor needs to know which provider and model to use.

    1  Set it up now  — choose a provider and a model
    2  Not right now  — I will run `comodor setup` later

  Choice [1]:
```

Enter takes the first. Where there is no terminal to ask on — a Dockerfile, a
CI step, a provisioning script — it is not asked at all and the commands are
printed instead, because defaulting to yes without a terminal hangs a build on
a wizard nobody can answer. `COMODOR_NO_SETUP=1` turns it off anywhere.

## 0.10.2 — 2026-08-24

### Terminals that cannot draw the glyphs were told they could

Adding the checkbox turned over a rock. Whether a terminal could handle the
interface was decided by encoding three box-drawing characters — and cp437 and
cp850 have those, which is still what a fresh `cmd.exe` gives a lot of people.
So the answer came back yes, and then fourteen glyphs those code pages do not
have went to the screen: the bullet, the tick, the warning triangle, and the
arrow that is the only thing marking which row the cursor is on. The ASCII
table had been there the whole time and was never reached for.

The check is built from the glyph table now, so a glyph added later widens it
by existing. And three hint lines that wrote `↑↓` as a literal go through the
theme, so a terminal whose borders have just been downgraded to `+-|` is not
still being sent arrows on the line underneath.

## 0.10.1 — 2026-08-24

### Setup takes as many skills as you want

The question offered a library and let you take exactly one thing out of it.
Somebody setting up for a Python project wants the review skill and the test
skill, and the list had no way to say so — they took one and either went
looking for `comodor skills` afterwards or never got the rest.

Move with the arrow keys, **space** to tick, **enter** to install everything
ticked. The hint line counts what is waiting, so enter is never a guess.

```
┌─ Skills ──────────────────────────────────────────────────┐
│    ☑ review        Review a change before it is committed │
│ ›  ☐ commit-style  Match the commit messages already here │
│    ☑ python-tests  Write tests the way this project does  │
└───────────────────────────────────── 2 selected ──────────┘
  ↑↓ move   space select   enter install 2   type filter   esc cancel
```

Nothing is ticked to begin with and enter with nothing ticked takes none, so
the wizard still never installs anything you did not ask for. The "None for
now" row is gone: an option meaning "no options", among real ones, is a thing
to explain rather than a thing to use.

Typing still filters, and ticks are held by value rather than by row — narrow
the list, tick something, clear the filter, and it is still ticked. Without a
terminal it can take over, the numbered form asks the same question and takes
`1,3` or `1 3`.

## 0.10.0 — 2026-08-24

### The browser interface, rebuilt

`comodor web` was one column and a list of events. It now has the shape the
terminal has had all along — chats on the left, the conversation in the middle,
what the agent is and may do in a panel you can open.

**Chats are kept.** They always were at the terminal, written to
`~/.comodor/sessions`; the browser wrote nothing, so a reload lost the lot and
the two interfaces could not see each other's work. Same folder now, so a chat
begun at the prompt opens in the browser and the other way round. They can be
listed, opened, deleted, and searched by what was said in them rather than by
their titles.

**Admin** is the answer to "what is this thing about to do to my machine":
which model is answering, how far it will go on its own, the four ceilings,
what it may touch without asking, what it has learned, every tool it can reach,
and where the files are. Four settings can be changed from there — the model,
the provider, the mode, and whether it keeps going without asking.

The list is short on purpose. Nothing that widens what the agent may do to the
machine is switchable from a page anyone holding the link can open. The
permission prompts already offer that choice per action, in front of the person
who will live with it.

**Write in any language.** Type Persian, Arabic or Hebrew and the message box
turns around as you type; answers arrive set the right way. There is no setting
and no language menu — each message is judged on its own, so a conversation
that moves between languages moves with it.

The judgement is by counting rather than by first letter, which is what makes
the two awkward cases come out right: a Persian sentence opening with a package
name is still Persian, and an English sentence quoting one Persian word is
still English. Code, paths and identifiers stay left-to-right inside a
right-to-left paragraph. Arabic-script text is set in Vazirmatn, which travels
inside the package rather than being fetched from a font host — this has to
work on a machine that cannot reach the internet — and is scoped so it applies
to Arabic script and to nothing else, leaving the Latin interface untouched in
the same line.

**It fits a phone.** Below 900 pixels the chat list becomes a drawer over the
conversation rather than a column beside it, because 292 pixels of sidebar on a
390-pixel screen leaves nothing wide enough to read code in.

Also: a light theme that follows the system until you say otherwise, an empty
state that suggests somewhere to start, a status strip that reports the
connection, the working folder, how full the context is and what the session
has cost, and keyboard shortcuts for search, the sidebar and the message box.

### Two chats in the same second were one chat

A session id was a timestamp to the second, which is safe at a terminal where
nobody starts two sessions inside one. In the browser "new chat" is a button:
two clicks in the same second produced the same id, and the second conversation
was appended to the first one's transcript. Neither could be read back
afterwards. Ids now carry a short suffix.

### Changing a setting said it three times

Pressing F3 three times filled the notice line with

    mode: chat (no tools)  mode: act (full tools)  mode: plan (read-only)

— a history of what the mode used to be, with the one true answer last and two
that were no longer true in front of it. The queue was missing a distinction
between an event and a state. "Copied 14 lines" happened once and is worth
seeing beside the next thing; "mode: plan" is the current value of a setting,
and there is only ever one of those. Notices that report a setting now replace
the last one about the same setting. Events still stack, which is right for
them.

### Smaller

- The dark theme had no definition of its own. There was a rule for light and a
  rule for the system preferring light, and dark was whatever was left when
  neither matched — true, and one mistyped selector from not being true.
- Contrast across the browser interface is measured against the surface each
  piece of text actually sits on. The rail, the footer and the composer are
  their own shades, and text that cleared the floor on the page did not clear
  it on the rail, which is where most of it appears.
- Every icon on the site is rendered from one vector, so changing the logo is
  replacing one file. Twenty-eight had been uploaded by hand.

## 0.9.0 — 2026-08-23

### It can use your computer

Comodor can drive the machine the way a person does — look at the screen, move
the mouse, click and type, in any application rather than only a browser.
Windows so far; the packages are shaped so a second platform is a second file.

**You watch it happen.** A halo marks where it is about to click *before* the
pointer moves, it travels there over about a third of a second rather than
teleporting, and a ripple marks where it landed. A panel at the top of the
screen says how much of the permission is left and how to end it. The pause
between the halo and the click is not decoration: it is the moment in which
stopping it is still possible.

When the agent is somewhere else — a server, the Docker image — the same thing
appears in the browser interface instead: the frame it looked at, with a marker
where it acted.

**Permission is a grant with a scope, a clock and a way out**, checked again
before every single action rather than once. Nothing is written to your config
file; closing Comodor ends it, and there is deliberately no "always allow".

    /computer 15m          fifteen minutes, anywhere
    /computer 1h this app  only while that window is in front
    /computer stop         end it now

**The way out is the mouse in a screen corner.** Every other stop needs a
keyboard the agent may be typing into, or a window it may be clicking on.
Pulling the mouse away is what a person actually does when their screen starts
moving on its own, and it cannot be intercepted. The agent may still click in a
corner itself — it remembers where it left the pointer.

Refused whatever you have allowed: a password manager, any window asking for a
password, a wallet, a locked screen, and Comodor's own window — an agent that
clicks into the terminal driving it types into its own prompt.

**Said plainly, because it is true:** a screenshot goes to the model and
everything on your screen goes with it. Redaction works on text and cannot read
pixels.

Verified end to end against `claude-sonnet-5` driving a real Notepad: four tool
calls for "type this sentence", seven for one needing `ctrl+a`, `Delete` and a
retype. Both landed the exact text, first attempt.

Four things found by building it against a real screen rather than reasoning
about one:

- **"Capture at 1280 wide" makes an ultrawide unreadable.** That advice assumes
  16:9. On a 3840x1080 display it is a three-times reduction, and the model is
  handed text it cannot read — so it guesses instead of asking. The size is
  fitted to the two limits that actually exist, which gives 2068x582 there and
  1480x833 on an ordinary laptop.
- **DPI awareness has to be set before anything reads a screen metric.** On a
  display at 125% — the default on most Windows laptops — an unaware process is
  told the screen is smaller than it is and every click lands short by the scale
  factor. The cause is invisible; it looks like bad aim.
- **The overlay stole the keyboard.** `WS_EX_NOACTIVATE` governs every
  activation after the window exists, and `tk.Tk()` has already shown and
  activated it before the next line of Python runs.
- **An application can rewrite what the agent types.** Notepad turned `ümlaut`
  into `umlaut`. Nothing was lost in transit — it was autocorrect. The tool now
  says so on every `type`.

A desktop run was also paying to look at screens it had already clicked past: a
screenshot costs its full price on every turn it stays, so a thirty-step task
carried close to fifty thousand tokens of stale pixels. Only the last two stay
now.

### Documentation that answers the question

The README was 795 lines and still did not let somebody work out what the tool
does or how to use one part of it. There is now a `docs/` folder — eighteen
pages, organised by what you are trying to do rather than by how the code is
laid out — and the README points at its index.

[docs/README.md](docs/README.md) · [getting started](docs/getting-started.md)
· [the interface](docs/interface.md) · [the terminal](docs/cli.md)
· [tools](docs/tools.md) · [safety](docs/safety.md)
· [learning](docs/learning.md) · [your screen](docs/computer.md)
· [configuration](docs/configuration.md) · [cost](docs/cost.md)
· [troubleshooting](docs/troubleshooting.md)

Every link is checked by the test suite, in both directions: nothing points at a
page that does not exist, and nothing exists that the index cannot reach.

### A help page written rather than generated

`comodor --help` printed argparse's list of flags. That answers "what arguments
does this accept" and never answers what somebody typing it is asking, which is
"what is this, and what do I do now".

It is written now, organised the way you meet the program — start it, use it,
drive it from a terminal, keep it working — with a command you can paste in
every section. `comodor help <topic>` goes deeper on one thing.

Tests check that every command and flag it names actually exists, that every
documentation page it promises is there, and that it fits eighty columns. A help
page naming a command that was renamed is worse than no help page.

### `browser` settings have never worked

`SECTIONS` is the list the loader walks, and `browser` was a field on `Config`
that was not in it. Every `browser` setting anybody has ever written was read,
ignored, and not complained about — including `headless: false`, whose whole
purpose is to let you watch the browser work.

Fixed, and `computer` registered the same way so it could not inherit the same
silence. Neither may be set by a project: a repository that can set
`browser.executable` names a binary for the agent to launch, and one that can
set `computer.enabled` asks the machine it was just cloned onto for your mouse.

### Smaller

- **A live check before a release.** `scripts/live_check.py` runs four
  end-to-end tasks against a real provider, reading credentials from a
  git-ignored `src/.env` and printing none of them. The suite is offline by
  design and cannot answer whether a release works against a real model.
- **A bus can say whether anyone is listening.** A consent request went to an
  empty room and waited out its timeout, then reported it as the user refusing.
- **`comodor web` in a detached container would have hung.** Compose sets
  `tty: true`, so a container has a terminal whether or not anybody is attached,
  and the setup questions would have been asked of nobody.

1100 tests on Linux, 1113 on Windows, ruff clean on both.

## 0.8.9 — 2026-08-22

Two consequences of 0.8.8, found by following its own changes into the places
they touch.

**A container has a tty and nobody reading it.** Refusing to serve a browser
interface with no provider asks the setup questions when there is a terminal
and prints an actionable message when there is not — and `isatty()` decided
which. The compose file sets `tty: true`, so a container has a terminal whether
or not anyone is attached: `docker compose up -d` would have reached the first
question and waited for an answer that was never coming. A hung container is a
worse failure than the one being fixed, and it lands on exactly the path the
image exists to serve. In a container the answer is always the message.

**Restoring borrowed values one at a time could keep half an object.** A
repository may name an MCP server, and it arrives switched off. Turn it on,
press save, and the restore did as it was told: `enabled` had changed so it was
kept, `command` had not so it went back to what the user's file said, which was
nothing. The saved entry was a server that was named, enabled and unrunnable.
For an object their own file never held — a server a repository named, a
provider that exists only because the environment supplied its key — either
they have adopted it and all of it is theirs, or they have not and none of it
belongs in their file. Half of it is the one answer that cannot be right.

## 0.8.8 — 2026-08-22

### Arriving from another agent

Somebody who already uses OpenClaw or Hermes has done the tedious part once:
found their API keys, pasted them somewhere, written a few skills. The first
run now offers to bring it across.

- **API keys**, which is the whole of the tedium. Both tools keep them in an
  `.env` beside their config, and OpenClaw also inlines them in its JSON.
- **The model** they had chosen, when this can host it.
- **Skills**, which both write in the same open format Comodor reads.

Three rules, because this reads other programs' files. Nothing is overwritten:
a key configured here wins, and the import fills gaps. Nothing is moved, so the
other tool keeps working. A malformed file is skipped rather than fatal, since
half the value is that it runs on machines whose other agent is in an odd
state.

**What does not come over is said, not skipped in silence.** Their memory is
prose; this agent's is lessons with confidence, evidence and decay, learned
from corrections. Importing one as the other would invent confidences nobody
measured and poison recall with entries that were never earned.

`comodor import` does the same outside the first run — `--dry-run` to see what
it would take, `--keys-only` to leave the rest.

### An audit of how settings are received and applied

Driving the whole first run, rather than testing its pieces, found the joins.
And auditing what reaches disk, rather than what the resolution order says,
found rather more.

**Saving wrote back four layers as though they were all yours.** The
configuration the agent runs on is merged from your file, the repository's
file, the environment and the command line. `save()` wrote that merged object
into your own file. One `/save` in a cloned repository made its model, its step
limit and its `max_cost_usd` — a spend ceiling — your permanent global
defaults. An API key you had deliberately kept in your environment was written
to disk in plain text. A `--model` typed once became permanent. Load now
remembers what your own file said and which values came from elsewhere; a value
you changed during the session is yours and is written, and one that still
holds whatever a borrowed layer supplied is not.

**The context gauge kept reading a million after a move to a 128k model.** The
window is set once by the wizard and read by the loop, which compacts at a
fraction of it. Nothing updated it on a switch, so the agent would never
compact and the run would fail at the provider's real ceiling — with the gauge
reading a million all the way there. It follows the model now, through one path
used by both ways of asking, which had also drifted: typing `/model x` left the
session record naming the old one.

**`comodor web` started a server nobody could use.** The interface asks the
setup questions when nothing is configured; `web` was dispatched before that
check, so a fresh machine got a URL, a browser window, and a failure on the
first task with nothing on screen to act on. The Docker image sends people
straight there. It now asks at a terminal, and elsewhere says what is missing
and what would fix it rather than starting.

**The spend limit was a decoration for every provider but one.**
`agent.max_cost_usd` defaults to $2 and the loop stops a task when the running
cost passes it — but that cost comes from a pricing table that deliberately
leaves rates unset for models it is not confident about. For an unpriced model
the cost is `None`, the meter never leaves zero, and the limit never fires. Of
seventeen providers only Anthropic's models are priced, so almost everybody who
set a ceiling and walked away did not have one. Nothing here invents a price;
it now says which ceilings are real, at the start of a session and in `doctor`.

**The setup catalogue and the pricing registry had drifted apart.** The
wizard's default for Anthropic was a model the registry had never heard of, so
the context gauge read a fallback 128k instead of a million, the spend limit
could not be enforced, and `doctor` warned that the model you were running "is
not in the known list".

**An API key was reaching two places it should not.** `to_public_dict` is
documented as safe to display, log or export, and masks the key it knows about
— but remembering the user's own document, so a borrowed value could be put
back, added a second copy nested where the mask never looked. And
`ProviderConfig.api_key` was an ordinary field, so the generated `repr` printed
it: every traceback naming a Config, and every pytest failure that shows one,
carried the key into whatever captured that output.

Smaller, from the same pass:

- **A skill folder was copied with `shutil.copytree`, which follows symlinks.**
  A skill is a file whose contents are read into a prompt, so a link in another
  program's directory pointing at `~/.ssh/id_rsa` would have been copied in and
  then sent to a model. The copy no longer reads outside the folder it was
  given, and the size limit is the whole tree rather than the entry file.
- **The wizard said "already configured" for three different things.** An
  imported key, one in your config file and one in your environment behave
  differently now, and the last is not copied to disk. It names the source.
- **The wizard offered a provider you had no key for**, immediately after
  announcing it had imported one for a different provider. A provider that has
  a key leads the list.
- **An import left `provider` empty and `configured` false**, which only
  appeared to work because the fallback picks whatever has a key — arbitrary
  as soon as there are two.
- **The config complaints added in 0.8.7 called a method that does not exist.**
  Any user with a refused project setting would have met an `AttributeError` on
  startup — exactly the user that change was written for. Found by writing the
  first test of that path.
- **`/theme nonsense` reported success**, while the palette table quietly fell
  back to Ember.
- **Three tests failed for anyone who sets `NO_COLOR`**, and the failure looked
  like a bug in the banner rather than a preference in the environment.
- The README said four setup questions. There are five.

## 0.8.7 — 2026-08-22

### A cloned repository could redirect your API key

`.comodor/config.json` is read from whatever directory the agent is started in,
which for a coding agent means: from a repository somebody else wrote,
immediately after cloning it. It was merged over the user's own settings with
no restriction. An audit of what that allowed found all of this:

| a repository could set | and then |
|---|---|
| `providers.*.base_url` | your API key is sent to their server on the first request |
| `safety.workspace_only` | the agent writes outside the project |
| `safety.auto_approve_shell` | it stops asking before running commands |
| `safety.deny_commands` | the list "no prompt can talk past" is emptied |
| `mcp.servers` with `enabled` | a command they named runs on your machine |
| `agent.system_prompt_extra` | instructions injected with your authority |

- **A project file is now restricted to an allow-list** of settings that cannot
  be turned against the person who cloned the repository: which model, what
  mode, the budgets, how it looks. An allow-list rather than a deny-list, so a
  setting added next year is untrusted by default — the right way round to be
  wrong.
- **A project may still say which MCP servers it uses**, which is the useful
  half of that feature, and they arrive **switched off** however the file asks.
  Declaring is a suggestion; enabling is a decision, and it belongs to the
  person whose machine it is.
- **Refusals are said out loud.** Silently ignoring somebody's file is how a
  config file gets a reputation for not working.

### A setting has to be the type it says it is

- **Fixed: `{"agent": {"max_steps": "lots"}}` was stored as the string**, and
  the first `steps >= max_steps` an hour later raised a TypeError in the middle
  of a task. Worse quietly, `{"loop": "false"}` was stored as the string
  `"false"` — which is true.
- Values are coerced where that is unambiguous, refused where it is not, and a
  refusal names the key and what was expected. `null` no longer replaces a
  string setting with `None`.

## 0.8.6 — 2026-08-22

### Nothing ships that has not passed the gate

Release triggered on a tag and CI triggered on a push. They were separate
workflows with no relationship, so tagging a commit whose tests were failing
published it — which is exactly what happened to 0.8.0 today, caught only by
looking at the runs afterwards.

- **Release now runs the gate itself**, as its own first job, and building,
  publishing and the GitHub release all depend on it. Making Release *wait* for
  CI is the obvious fix and the wrong one: workflows on different triggers
  cannot depend on each other, and polling the other one's status is a race.
- **The gate is the two commands a developer runs** — `ruff check` and the
  whole suite. Not a subset, not "fast tests": a gate that runs something other
  than what the developer runs is one nobody trusts and everybody eventually
  bypasses.

### A linter, chosen by counting

Ruff can be pointed at some eight hundred rules; most of them, on a codebase
with a settled voice, produce churn. Each family was run against the tree first
and picked on what it actually found:

| enabled | found | why |
|---|---|---|
| `F`, `E4`, `E7`, `E9` | 20 | unused imports, undefined names, a redefinition — every one real |
| `I` | 32 | import order, all mechanical, noise in every diff until settled |
| `B` | 6 | including four `zip()` calls that would silently truncate |
| `W`, `C4`, `PIE` | 9 | trailing whitespace, needless comprehensions |
| `E501` at 100 | 15 | past a hundred columns something has gone wrong, not just got untidy |

Deliberately **not** enabled: `BLE001` and `S110`, which between them flag 110
broad excepts — every one written on purpose, with a comment, around code that
must not be able to take the agent down. A rule needing 110 suppressions is not
finding a problem, it is disagreeing with a decision. `UP`, `SIM` and `RUF`
likewise: 271 findings about how things are spelled.

All 77 findings are fixed rather than suppressed, with two documented
exceptions: the model table in `providers/registry.py`, whose columns line up
across rows and which wrapping would make worse, and two frozen dataclasses
used as argument defaults, where sharing one instance is the point.

### A wordmark, and a line that earns its place

Starting the interface, a headless run or the browser server now opens with the
Comodor wordmark — and under it, the thing that makes it worth the space:

```
  412 lessons · 7 skills · 3 rules you set   from 128 finished tasks
```

Most banners are a logo and a version nobody reads twice. That line is about
*this* installation rather than about the program, and it goes up as the agent
is used, which is the whole idea of the thing.

- **It never reaches a pipe.** `comodor run … | jq` must see the answer and
  nothing else, so in a headless run the wordmark goes to the error stream with
  the progress, and nowhere at all when the destination is not a terminal —
  nor in `--json`, nor in CI.
- **It shrinks rather than wraps.** The art is 47 columns; below 51 it becomes
  a single styled line, because ASCII art reflowed by a terminal is not a
  smaller logo.
- **It fades with the palette.** The shades are interpolated from the theme's
  own accent and text colours rather than fixed, so it does not look wrong on
  the light themes.
- **A brain that will not open costs a line, not a session.** Every reading of
  it is best-effort.
- `COMODOR_BANNER=0` for one run, `"banner": false` in the config for good, and
  the environment wins either way — so a container can turn it on for a log
  without editing anything.

## 0.8.5 — 2026-08-22

### An answer nobody offered was accepted, and meant no

- **Fixed: `/api/answer` took any string and reported success.** It handed the
  word to the waiting worker; the permission engine compared it against the
  choices it knows — `allow`, `allow_always`, `deny` — did not recognise it,
  and treated the turn as refused. So a caller could send `"yes"`, be told
  `{"answered": true}`, and watch nothing happen.

  The page was never affected: it builds its buttons from the options in the
  event. Anything else driving the API had no such protection, and "accepted,
  and silently meant no" is the worst answer an interface can give. The choice
  must now be one the request offered, and a refusal says which they were.

## 0.8.4 — 2026-08-22

### The sandbox retry read only the first line

- **Fixed: the retry decided from a summary rather than from the output.** The
  error a person sees is trimmed to one line — forty lines of Chromium logging
  is a haystack, not a message — and the retry was matching that trimmed line.
  Chromium does not put the useful part first:

  ```
  The setuid sandbox is not running as root. Common causes:
    * An unprivileged process using ptrace on it, like a debugger.
    * A parent process set prctl(PR_SET_NO_NEW_PRIVS, ...)
  Failed to move to new namespace: ... errno = Operation not permitted
  ```

  Under a plain `docker run` the namespace line comes first and it worked;
  under compose, which sets `no-new-privileges`, a different line does and it
  did not — the same bug present or absent depending on how the container was
  started. What a person is shown and what the decision is made from are two
  things now, and only the second sees everything.

## 0.8.3 — 2026-08-22

### Running in a container

Both of these are what a container needs, and both were wrong in a way that
only showed up inside one.

- **A wide bind in a container is correct, and was warned about as if it were
  reckless.** A container has its own network namespace, so binding 127.0.0.1
  inside one hides the port from the machine running it — the interface becomes
  unreachable by the person who started it. Binding everything is the right
  thing to do there, and who may reach it is decided one layer out, by how the
  port was published. `comodor web` now recognises a container and explains
  that instead: `-p 127.0.0.1:8765:8765` is private, `-p 8765:8765` is a shell
  on the network. The warning is not removed anywhere it is true.
- **The browser could not start in a container at all.** Chromium isolates each
  renderer in a user namespace, which Docker's default seccomp profile does not
  allow, and it refuses to run rather than run unprotected. The usual answer is
  to pass `--no-sandbox` everywhere, which throws away a real protection on
  every machine where it works. The other answer is to relax the *container's*
  seccomp so the inner sandbox can work, which is worse: it weakens the strong
  outer boundary to enable the weaker inner one.

  So it starts properly, and if it is refused for that specific reason — not
  any other — it starts again without the inner sandbox and records that this
  is what happened. Laptops keep the protection, containers work with no flag
  from anyone, and the difference is reported rather than assumed.

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

- **Fixed: the loop's exit test allowed less time than shutting down is
  allowed to take.** Quitting waits up to two seconds for a turn still in
  flight, deliberately, so that stopping mid-task gives the agent a moment
  rather than abandoning it. The test asserted the loop exits within one. It
  could always fail, and only did when a turn happened to still be running as
  the budget expired — on a loaded machine. The budget has a name now and the
  test reads it, so the two cannot drift apart again.

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
