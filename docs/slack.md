# From Slack

The same agent, in your workspace: send it a task, watch it work, answer its
questions — without opening a terminal.

```bash
comodor slack manifest              # the app definition to paste into Slack
comodor slack connect               # the two tokens, checked as you paste them
comodor slack pair                  # add your account
comodor slack start --background    # run it
```

About five minutes, and there is **no public address to arrange** — which is
what separates this from [WhatsApp](whatsapp.md).

It runs the same agent session the terminal, the browser and the Telegram bot
run. A task started here learns the same lessons and lands in the same history.

## Why this is easy

Slack has two ways of delivering events. The Events API posts to a URL, which
means a public HTTPS address, a certificate and a tunnel — all the work that
makes WhatsApp hard.

**Socket Mode** inverts it: the app asks Slack for a websocket address and
connects *outward*. Nothing has to be reachable from the internet, and there is
no address to keep up to date. That is the whole trick, and it is why Slack
sits beside Telegram rather than beside WhatsApp.

The second thing that helps is the **app manifest**. Slack lets an app be
described in a YAML document, so instead of finding eleven checkboxes across
four settings pages, the whole app — name, scopes, events, Socket Mode already
switched on — is one paste.

## Setting it up

### 1. Create the app

```bash
comodor slack manifest
```

That prints the manifest and the link. At
[api.slack.com/apps](https://api.slack.com/apps?new_app=1), choose **From a
manifest**, pick your workspace, paste it, create — then **Install to
Workspace**.

### 2. The two tokens

They are not interchangeable, and mixing them up is the single most common way
this fails. Comodor refuses each in the other's place by name rather than
letting Slack answer `invalid_auth` an hour later.

| | | |
|---|---|---|
| `xoxb-…` | **Bot token** | OAuth & Permissions. Does everything the bot does |
| `xapp-…` | **App-level token** | Basic Information → App-Level Tokens, scope `connections:write`. Opens the socket, and nothing else |

```bash
comodor slack connect
```

With no arguments it walks you through both and checks each as it arrives — the
bot token against `auth.test`, the app token by actually opening a socket with
it. A wrong one is a sentence now rather than a mystery next week.

### 3. Pair your account

```bash
comodor slack pair
```

That prints a six-digit code. Send it to Comodor as a direct message and your
account is added. The code works once and expires in five minutes.

**A workspace can have hundreds of people in it**, and this is an agent that
reads and writes your files. So it answers a fixed list of Slack user ids and
ignores everybody else.

```bash
comodor slack status
comodor slack forget U01234567
comodor slack forget all
```

## Where it answers

**In a direct message**, always.

**In a channel, only when mentioned.** A bot that replies to every message in a
shared channel is a bot somebody removes that afternoon.

**In the thread it was spoken to in.** A question asked in a thread is answered
in that thread, not in the channel in front of everybody.

Its own messages are never answered — a bot that replies to itself is a loop
with a rate limit on it.

## What it can do, and what it cannot

**By default it reads and plans, and changes nothing.** A Slack session is held
in plan mode whatever the terminal is set to, for the same reason as the other
channels: approving a shell command from a phone, in a queue, is a decision
made with less attention than the same approval at a keyboard.

```bash
comodor slack writes on
comodor slack writes off
```

A terminal command on purpose. A bot that could widen its own permissions would
only need somebody's Slack account.

## The buttons

Slack is the roomiest of the three channels — messages can be edited and
buttons are plentiful — so a reply is one message that grows as the answer
arrives, and the whole menu fits one screen.

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

While a task is running the only thing offered is **Stop**.

## Running it

```bash
comodor slack start                # here, holding this terminal
comodor slack start --background   # detached; survives closing it
comodor slack stop
comodor slack service install      # starts at login, survives a reboot
comodor slack service show         # read the unit before trusting it
```

The log is `slack.log` beside your config, appended to rather than replaced.

A **user** service on every platform — systemd, launchd, Task Scheduler — never
a system one. This is an agent that reads and writes your files with your
credentials, and more authority than the person who owns those files buys
nothing.

## From the browser panel

`comodor web` → **Admin** → **From your phone** connects, pairs, starts and
stops all of this without a terminal. Those controls only answer requests from
the machine Comodor is running on: a bot token hands remote control of it to
whoever holds the token.

## How it is built

No new dependency. The Web API is `POST /api/chat.postMessage` over the HTTP
client this project already has, and Socket Mode runs over the websocket client
written for driving Chrome — which is why adding Slack added no packages.

Three things the socket loop is careful about, each of them a way a bot goes
quiet without anybody noticing:

- **Every envelope is acknowledged.** Slack redelivers what it does not hear
  about, and for an agent that runs commands one message becoming three turns
  is not merely noisy.
- **`disconnect` is routine.** Slack rotates connections on a schedule.
  Treating that as a failure produces a bot that dies every few hours.
- **A quiet workspace still gets pings.** The case that matters most — nobody
  has messaged it for an hour — is exactly the one a dropped socket ruins.

## What it will not do

- Answer anybody who is not paired.
- Answer everything in a channel it was added to.
- Take a token or an allowed account from a project's `.comodor/config.json`.
  A repository that could add its author to that list would be a backdoor.
- Edit anything until `slack writes on`.
- Print either token. Both are redacted out of every error raised.
