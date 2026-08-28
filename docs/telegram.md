# From your phone

Comodor can be driven from a Telegram bot: send it a task, watch it work,
answer its questions and stop it — without opening a terminal.

**The first-run setup asks about this.** The last of the six questions offers
to connect a bot, checks the token with Telegram there and then, and pairs your
account before the wizard finishes. If you said *Not now*, or you are setting up
a machine that is already configured:

```bash
comodor telegram connect <token>   # a bot from @BotFather
comodor telegram pair              # add your account
comodor telegram start             # run it
```

It runs the same agent session the browser interface does. Everything is a
button; typing is for the task itself.

## Getting a bot

Message [@BotFather](https://t.me/botfather) on Telegram, send `/newbot`, give
it a name and a username ending in `bot`. It replies with a token:

```
1234567890:AAF…
```

```bash
comodor telegram connect 1234567890:AAF…
```

## Pairing

**A bot's username is public.** Anyone who finds it can send it a message, and
this one can read your files. So it answers a fixed list of numeric Telegram
user ids and nobody else.

```bash
comodor telegram pair
```

That prints a six-digit code. Send it to your bot on Telegram and your account
is added. The code works once and expires in five minutes.

Everyone else gets **silence** — not a refusal. A bot that says "you are not
allowed" has told a stranger that it exists, that it is a Comodor, and that
there is a list worth getting onto.

```bash
comodor telegram status         # who may talk to it
comodor telegram forget 12345   # revoke one account
comodor telegram forget all     # revoke everybody
```

## What it can do, and what it cannot

**By default it reads and plans, and changes nothing.** A Telegram session is
held in plan mode whatever the terminal is set to.

That is deliberate. Approving a shell command with a thumb, on a phone, in a
queue, is a decision made with less attention than the same approval at a
keyboard — and the consequences are identical.

```bash
comodor telegram writes on      # let it edit files and run commands
comodor telegram writes off
```

With writes on it still asks first, and the approval is a button in the chat:

```
Comodor wants to run
  npm test

  ✓  Yes, once
  ✓✓ Yes, and stop asking this session
  ✗  No
```

The widest commitment is never the first button under your thumb — on a phone
they are close together and "always" cannot be undone.

## The buttons

`/start` answers with the model, the folder and what it is allowed to do, and
the settings underneath. They are on the first screen rather than behind a
*Settings* button, because what a bot is pointed at is the first thing anybody
wants to know and the first thing they want to change.

| | |
|---|---|
| **New chat** | Forget the conversation so far |
| **History** | Re-open any earlier conversation, whole |
| **Stop** | Interrupt what is running — replaces *New chat* while it is |
| **Mode** | Act, plan or chat, each spelled out |
| **Status** | Model, folder, context, spend |
| **Model** | Every model the provider offers; tap to switch |
| **Folder** | Which project it is confined to |
| **Skills** | Install or remove one from the library |
| **Rules** | What it has learned from your corrections, and how many |
| **Settings** | The rest — cost, and what it may do |
| **Help** | What everything does, without leaving the chat |

When the agent needs a decision it asks with buttons too — the same questions
it would ask in the terminal, one per screen, with **Write my own** for
anything it did not think of.

Lists longer than a screen — models, skills, history — are paged six at a time,
with **Previous** and **Next**. Telegram will render eighty buttons happily and
nobody will scroll them.

## Running it

`comodor telegram start` holds the terminal. To keep it up:

**systemd** — `~/.config/systemd/user/comodor-telegram.service`

```ini
[Unit]
Description=Comodor on Telegram
After=network-online.target

[Service]
ExecStart=%h/.local/bin/comodor telegram start
WorkingDirectory=%h/projects/the-one-you-want
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now comodor-telegram
```

**Windows** — Task Scheduler, *at log on*, running
`comodor telegram start` with **Start in** set to the project folder.

The folder matters: the agent only reads and writes inside the directory it was
started in, and that is the one the bot will work in.

## How it is built

No new dependency. The Bot API is `getUpdates` in a loop and `sendMessage`,
over the HTTP client this project already has —
`python-telegram-bot` would have been the largest thing in the wheel, for that.

The reply is edited on a timer rather than per token. Telegram charges a round
trip per edit and rate-limits them, so per-token editing produces a message
that is throttled into arriving all at once at the end.

The bot holds an update offset and advances it as it goes. Without one, a
restart replays every message the bot has ever received — which, for an agent
that runs commands, is not merely noisy.

## What it will not do

- Answer anybody who is not paired, or say why.
- Take a token or an allowed account from a project's `.comodor/config.json`.
  A repository that could add its author to that list would be a backdoor, and
  unlike the browser or the screen there would be nothing on screen to see it
  happening.
- Edit anything until `telegram writes on`.
- Print the token. It is in every Bot API URL, so every error raised has it
  stripped out.
