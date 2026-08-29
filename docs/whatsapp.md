# From WhatsApp

The same agent, reached from a WhatsApp business number: send it a task, watch
it work, answer its questions — without opening a terminal.

```bash
comodor whatsapp connect --number-id … --token … --app-secret …
comodor whatsapp webhook              # what to paste into Meta
comodor whatsapp pair                 # add your number
comodor whatsapp start --background   # run it
```

It runs the same agent session the terminal, the browser and the Telegram bot
run. A task started here learns the same lessons and appears in the same
history.

## Why this takes more setting up than Telegram

Telegram gives you a token and lets you poll for messages. WhatsApp is Meta's
**Cloud API**, and two of its design decisions shape everything here.

**Messages are delivered, not fetched.** There is no long poll. Meta posts each
inbound message to a URL, which means something of yours has to be reachable
from the internet over HTTPS. That is the extra work, and there is no way
around it.

**Meta wants an app.** A business account, a number, an access token and an app
secret — four things that live in a browser, which is why the first-run wizard
points at this page rather than trying to collect them.

The alternative most projects reach for is a library that drives WhatsApp Web
through a headless browser. Those need Node, they break whenever WhatsApp
changes its web client, and they are against the terms the account is held to:
the failure mode is the number being banned. Not something a coding tool gets
to hand its users.

## Setting it up

### 1. A Meta app with WhatsApp on it

At [developers.facebook.com](https://developers.facebook.com), create an app
and add the **WhatsApp** product. Meta gives you a test number to start with;
a real one is added later under the business account.

You need four things from there:

| | |
|---|---|
| **Phone number id** | The numeric id beside the number — *not* the number |
| **Access token** | The dashboard's own lasts 24 hours. A **System User** token under Business Settings does not expire, and is the one to use |
| **App secret** | Settings → Basic. Every webhook is signed with it |
| **A public HTTPS address** | Where Meta delivers. See below |

```bash
comodor whatsapp connect \
    --number-id 123456789012345 \
    --token EAAG… \
    --app-secret 0a1b2c…
```

That checks the token against Meta before saving anything, so a typo is a
message now rather than a mystery next week.

### 2. Somewhere for Meta to deliver to

The bot listens on `127.0.0.1:8770`. Meta will only deliver to **HTTPS** and
will not accept a self-signed certificate, so something has to put a real one
in front of it. A tunnel is the usual answer and needs no open port and no DNS:

```bash
cloudflared tunnel --url http://127.0.0.1:8770
```

That prints a `https://…trycloudflare.com` address. Give it to Comodor so it
can show you what to paste:

```bash
comodor whatsapp connect --url https://something.trycloudflare.com/whatsapp
comodor whatsapp webhook
```

```
  Callback URL   https://something.trycloudflare.com/whatsapp
  Verify token   Kq3nP…
```

Paste both into **WhatsApp → Configuration** in the dashboard, then subscribe
the app to the **messages** field. Meta immediately calls the URL once to check
it; the bot answers that handshake itself.

A reverse proxy you already run works the same way — anything that terminates
TLS and forwards to `127.0.0.1:8770`.

### 3. Pair your number

```bash
comodor whatsapp pair
```

That prints a six-digit code. Send it to the business number from WhatsApp and
your number is added. The code works once and expires in five minutes.

**A business number is a phone number**, and strangers message phone numbers as
a matter of course. So it answers a fixed list and everybody else gets
**silence** — not a refusal. A number that says "you are not allowed" has told
a stranger that it is worth trying again.

```bash
comodor whatsapp status         # who may talk to it
comodor whatsapp forget 15551234567
comodor whatsapp forget all
```

The list is compared as digits, so `+1 555…`, `001 555…` and `1555…` are one
person rather than three.

## What it can do, and what it cannot

**By default it reads and plans, and changes nothing.** A WhatsApp session is
held in plan mode whatever the terminal is set to, for the same reason as
Telegram: approving a shell command with a thumb, in a queue, is a decision
made with less attention than the same approval at a keyboard.

```bash
comodor whatsapp writes on
comodor whatsapp writes off
```

That is a terminal command on purpose. A bot that could widen its own
permissions would only need somebody's phone.

## The buttons

WhatsApp allows **three** reply buttons of twenty characters, or one button
that opens a list of **ten** rows. Those are hard limits — Meta rejects the
whole message rather than trimming it — so the menu is a list, and it is
exactly ten rows:

| | |
|---|---|
| **New chat** | Forget the conversation so far |
| **History** | Re-open an earlier conversation |
| **Mode** | Act, plan or chat |
| **Status** | Model, folder, context, spend |
| **Model** | Switch to another one |
| **Folder** | Which project it works in |
| **Skills** | Install or remove one |
| **Rules** | What it learned from your corrections |
| **What it may do** | Whether it can edit and run |
| **Help** | What everything does |

While a task is running the only thing offered is **Stop**: there is no room on
a screen this narrow to keep a control around greyed out.

Longer lists — models, skills, history — are paged eight at a time, because the
two navigation rows count against the ten.

## Two things that will surprise you

**It cannot edit a message.** Telegram streams a reply by rewriting one message
as the answer arrives. WhatsApp has no edit, and a message per token would be a
hundred notifications for one question. So a turn says one line when it starts,
speaks occasionally while it works, and sends the answer when there is one.

**There is a day-long window.** Meta only permits free-form messages within
twenty-four hours of *your* last message. If a long task finishes after that,
the bot cannot tell you — it says so in its log, and writing to it again
reopens the window.

## Running it

Exactly as Telegram:

```bash
comodor whatsapp start                # here, holding this terminal
comodor whatsapp start --background   # detached; survives closing it
comodor whatsapp stop
comodor whatsapp service install      # starts at login, survives a reboot
comodor whatsapp service show         # read the unit before trusting it
```

The log is `whatsapp.log` beside your config, appended to rather than replaced.

A **user** service on every platform — systemd, launchd, Task Scheduler — never
a system one. This is an agent that reads and writes your files with your
credentials, and more authority than the person who owns those files buys
nothing.

## How it is built

No new dependency. The Cloud API is `POST /messages` over the HTTP client this
project already has, and the webhook is `http.server` from the standard
library.

The endpoint answers Meta **before** doing the work. Meta retries anything it
does not get a 200 for within seconds, and an agent turn takes minutes — a
webhook that waits gets the same message delivered five times.

Message ids are remembered, so a redelivery that arrives anyway does not become
a second turn.

## What it will not do

- Answer anybody who is not paired, or say why.
- Accept a webhook it cannot verify. Without an app secret nothing is
  verified, and `comodor whatsapp status` says so in yellow.
- Take a token, a number or an allowed account from a project's
  `.comodor/config.json`. A repository that could add its author to that list
  would be a backdoor.
- Edit anything until `whatsapp writes on`.
- Print the token. It is redacted out of every error raised.
