"""The help page, written to be read rather than generated.

`argparse` produces a list of flags. That answers "what arguments does this
accept" and almost never answers the question somebody typing `--help` is
actually asking, which is "what is this, and what do I do now". A first-time
reader got a wall of options with no shape, no examples, and no mention of the
things Comodor is actually for - the corrections it learns from, the browser,
the screen.

So the page is written. It is organised the way somebody meets the program:
start it, use it, drive it from a terminal, configure it, get out of trouble.
Every section carries a command you can paste.

`comodor help <topic>` goes deeper on one thing, which keeps the front page
short. The topics are the same names as the documentation pages, so learning
one teaches the other.
"""

from __future__ import annotations

from typing import Iterable

from rich.console import Console, Group
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from . import __version__
from .ui import console as console_module
from .ui.theme import Theme

DOCS = "https://github.com/ifekri/Comodor/tree/main/docs"


# --------------------------------------------------------------------------- #
# the front page
# --------------------------------------------------------------------------- #

#: (heading, [(what you type, what it does)]). The order is the order somebody
#: meets the program in, not alphabetical: alphabetical is a reference, and a
#: reference is not what a first-time reader needs.
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Start here", [
        ("comodor", "the interface — this is the usual way in"),
        ("comodor setup", "choose a provider and model; asked once"),
        ("comodor --demo", "try the whole interface offline, no key needed"),
        ("comodor import", "bring keys and skills over from OpenClaw or Hermes"),
    ]),
    ("Do one thing and stop", [
        ("comodor run \"fix the failing test\"", "one task, no interface"),
        ("comodor run \"...\" --yes", "do not ask before writing or running"),
        ("comodor run \"...\" --json", "machine-readable result, for scripts"),
        ("comodor --resume", "reopen the last session and carry on"),
    ]),
    ("Reach further", [
        ("comodor web", "use it from a browser, here or on a server"),
        ("comodor serve", "speak the OpenAI protocol, for other frontends"),
        ("comodor telegram start", "drive it from your phone, all buttons"),
        ("comodor slack start", "the same, in a Slack workspace"),
        ("comodor discord start", "the same, on a Discord server"),
        ("comodor whatsapp start", "the same, from a WhatsApp number"),
        ("comodor skills browse", "procedures it follows when the work calls for them"),
        ("comodor mcp list", "tools from Model Context Protocol servers"),
    ]),
    ("Mind and memory", [
        ("comodor curator run", "a maintenance pass over the brain, now"),
        ("comodor memory-provider status", "an optional external memory service"),
    ]),
    ("Keep it working", [
        ("comodor doctor", "check everything; `--fix` repairs what it can"),
        ("comodor update", "move to the newest release; `--check` just looks"),
        ("comodor uninstall", "remove it and everything it wrote; `--dry-run` lists"),
    ]),
]

OPTIONS: list[tuple[str, str]] = [
    ("--provider NAME", "openrouter, anthropic, openai, ollama, …"),
    ("--model ID", "override the model for this run"),
    ("--mode act|plan|chat", "plan is read-only; chat has no tools at all"),
    ("--no-loop", "answer once instead of working until it is done"),
    ("--cwd PATH", "the folder it may touch (default: the project root)"),
    ("--theme NAME", "ember, midnight, matrix, mono"),
    ("--ascii", "for terminals without box-drawing characters"),
    ("--no-mouse", "leave the mouse to the terminal"),
    ("--resume [ID]", "reopen the most recent session, or one by id"),
    ("--profile NAME", "use a separate brain, sessions and config"),
    ("--demo", "the interface, offline, against a scripted provider"),
    ("--version", "which version this is"),
]

IN_THE_INTERFACE: list[tuple[str, str]] = [
    ("type and press Enter", "ask for something"),
    ("/help", "every command, in the interface"),
    ("/mode", "act, plan or chat  ·  F3 cycles"),
    ("/undo", "put back the last file it changed"),
    ("/memory  /rules", "what it has learned, and the rules it follows"),
    ("/progress", "evidence that it is getting better, not a claim"),
    ("/computer 15m", "let it use your screen, for fifteen minutes"),
    ("/cost", "tokens, spend, and what the cache saved"),
    ("Esc", "stop what it is doing"),
    ("F2", "the task list  ·  F1 help  ·  Ctrl-C twice to leave"),
]

CLOSING = [
    ("It learns from corrections.", "Edit what it wrote, or tell it plainly, and "
                                    "the next answer follows. `/progress` shows "
                                    "whether that is working."),
    ("It asks before it acts.", "Writing a file or running a command is a "
                                "prompt, once, and you can say always. Every "
                                "write is checkpointed - `/undo` puts it back."),
    ("Your keys stay yours.", "In your own config file or your environment, "
                              "never in a repository, never sent anywhere but "
                              "the provider you chose."),
]


# --------------------------------------------------------------------------- #
# topics, for `comodor help <topic>`
# --------------------------------------------------------------------------- #

TOPICS: dict[str, tuple[str, str]] = {
    "computer": ("Letting it use your screen", """\
Comodor can drive the machine the way a person does - look at the screen, move
the mouse, click and type, in any application.

  Switch it on          set  computer.enabled: true  in your config
  Allow it              /computer 15m       fifteen minutes, anywhere
                        /computer 1h this app   only the window in front
  Stop it               move the mouse into a corner of the screen
                        or  /computer stop

While it works you can watch: a halo marks where it is about to click before
the pointer moves, a ripple marks where it landed, and a panel at the top of
the screen shows how long the permission has left.

It will never touch a password manager, a window asking for a password, a
locked screen, or Comodor's own window - whatever you have allowed.

Screenshots go to the model, and whatever is on your screen goes with them.

Windows only so far.  Full guide: docs/computer.md"""),

    "browser": ("The real browser", """\
`browse` drives a browser that is actually installed - it runs JavaScript,
keeps cookies, and can log in. Nothing is downloaded; it uses Chrome, Chromium,
Edge or Brave in a profile of its own.

What comes back is the title, the readable text, and a numbered list of the
controls on screen; the model acts on one by its number. A screenshot only when
the question is visual, because a picture costs the same every time and cannot
be trimmed.

  browser.headless: false   in your config, to watch it work

Full guide: docs/browser.md"""),

    "learning": ("What it learns, and how to see it", """\
Corrections first. Edit a file it wrote, or say "no, do it this way", and that
becomes a lesson with a confidence that rises when it holds and decays when it
does not.

  /memory      what it has learned
  /rules       the house rules it drew from your code and your edits
  /teach       tell it something directly
  /good  /bad  say whether an answer was right
  /progress    the evidence: recall, corrections, and whether they are falling

Nothing leaves your machine. The brain is a SQLite file under your config
directory.  Full guide: docs/learning.md"""),

    "skills": ("Procedures it follows", """\
A skill is a written procedure - a markdown file with a name and a description
- that Comodor loads when the work matches it.

  comodor skills browse     what is available
  comodor skills add NAME   install one
  comodor skills list       what you have
  comodor skills rollback --list
                            every change the agent made, and how to undo it
  /skills                   the same, in the interface
  /skills draft             procedures Comodor worked out and wants to save
  /skills adopt NAME        save one of those drafts as your own skill

Write your own in  ~/.comodor/skills/<name>/SKILL.md. The agent can write
and patch them too (skill_manage); every change is recorded, and the
injection scan flags anything suspicious at write time.
Full guide: docs/skills.md"""),

    "curator": ("Keeping the brain tidy", """\
Every few days a maintenance pass runs over what has been learned: lessons
whose confidence has decayed below the floor stop being recalled, duplicate
facts merge, and skills unused for a month are hidden and, after three,
moved to the archive. Nothing is deleted; `curator restore` brings a skill
back from `skills/.archive/`.

  comodor curator run       do a pass now
  comodor curator report    what the last pass did, and why
  comodor curator restore NAME    bring an archived skill back
  comodor curator pin NAME  exempt a skill from the curator
  comodor curator pause     stop the automatic passes

curator.interval_days sets how often it runs; the pass itself costs no
tokens and never runs in the middle of a session."""),

    "cost": ("Paying less for the same work", """\
  /cost                     tokens, spend, and what the cache saved
  /insights [days]          spend and progress across every session
  comodor insights --json   the same numbers, for scripts
  agent.max_cost_usd        stop a task at a price
  agent.max_steps           stop it at a number of steps

Prompt caching is on by default. The parts of a request that do not change -
the system prompt, the tool schemas - are re-served by the provider at a tenth
of the price, which is most of a long session.

A spend limit only works for a model with a published rate. `comodor doctor`
says plainly when it cannot be enforced.  Full guide: docs/cost.md"""),

    "voice": ("Speaking, and being spoken to", """\
Voice notes sent to a channel can be transcribed, and answers in Telegram can
also arrive as a voice message. Both are off until you turn them on, because
a recording is a copy of a person, not a summary of what they asked.

  Turn voice on          set  voice.enabled: true  in your config
  Transcribe notes       set  voice.stt_provider: groq   (or openai)
                         and put the key in the named environment variable
                         (voice.stt_key_env, GROQ_API_KEY by default)
  Spoken answers         set  voice.tts_enabled: true
                         or send /voice on in Telegram
  What is set            /voice          (Telegram) or comodor doctor

Transcription sends the recording to the provider you named, and needs a key;
with no key it refuses and says which variable is missing, rather than sending
anything unnamed. Speech uses the Edge service, which needs no key; the voice
is voice.tts_voice, a Persian one by default. A voice note that cannot be
transcribed is kept on disk, and its path is offered, never discarded."""),

    "safety": ("What it can do, and what it cannot", """\
Every tool has a tier. Reading is silent; writing asks; running a command,
reaching the network or driving the screen asks louder.

  /approve writes           stop asking before file writes
  /undo                     restore the last file it changed
  safety.workspace_only     it may not touch anything outside the project
  safety.deny_commands      commands no prompt can talk it into

A repository's own `.comodor/config.json` may set the model and the budgets and
nothing that could be turned against you - not the provider endpoint, not the
approvals, not the screen.  Full guide: docs/safety.md"""),

    "config": ("Where things live, and what wins", """\
  ~/.comodor/config.json        yours; the wizard writes it
  ./.comodor/config.json        the project's; safe to commit, limited
  environment                   ANTHROPIC_API_KEY, OPENAI_API_KEY, …
  the command line              --model, --mode, …  for one run

Later beats earlier. `/save` writes back only what *you* chose - never the
repository's settings, and never a key you keep in your environment.

  comodor doctor                what is set, and what is wrong with it

Full guide: docs/configuration.md"""),

    "web": ("From a browser", """\
  comodor web                   here, on 127.0.0.1
  comodor web --host 0.0.0.0    reachable from elsewhere - read the warning
  comodor web --port 9000

The URL it prints contains a token; a new one each run unless you set
COMODOR_WEB_TOKEN. The interface has no way to enter an API key, so a provider
must be configured before it will start.

In Docker:  docker compose up   and open the address it prints.
Full guide: docs/web.md"""),

    "slack": ("From Slack", """\
  comodor slack manifest           the app definition to paste into Slack
  comodor slack connect            the two tokens, checked as you paste them
  comodor slack pair               a one-time code that adds your account
  comodor slack start -b           run it detached from this terminal
  comodor slack status             what is set, who may talk, is it running

About five minutes. Slack takes an app *manifest*, so the app is one paste
rather than a page of checkboxes - name, scopes, events and Socket Mode all
switched on already.

Socket Mode is why this needs no public address: the app opens a websocket
outward rather than being posted to. That is the whole difference between this
and WhatsApp, which needs a certificate and a tunnel.

Two tokens, and they are not interchangeable:

  xoxb-...   the bot token, from OAuth & Permissions. Does the work.
  xapp-...   the app-level token, from Basic Information, scope
             connections:write. Opens the socket, and nothing else.

In a channel it answers when mentioned; in a direct message, always. It answers
a fixed list of accounts and nobody else - a workspace can have hundreds of
people in it, and this reads and writes your files.

Full guide: docs/slack.md"""),

    "discord": ("From Discord", """\
  comodor discord connect          guided: the token, and the one intent to
                                   switch on before anything works
  comodor discord pair             a one-time code that adds your account
  comodor discord start -b         run it detached from this terminal
  comodor discord status           what is set, who may talk, is it running

About three minutes. One token, from the developer portal; the bot opens a
websocket outward, so nothing here needs a public address.

The one setting people miss: under Bot → Privileged Gateway Intents, switch on
Message Content Intent. Without it the bot connects and shows online, and
every message arrives empty - a bot that looks fine and hears nothing.

In a server it answers when mentioned; in a direct message, always. It answers
a fixed list of numeric ids and nobody else - a server can have thousands of
people in it, and this reads and writes your files."""),

    "serve": ("Speaking OpenAI", """\
  comodor serve                    here, on 127.0.0.1, port 8787
  comodor serve --port 9000
  comodor serve --token MYTOKEN    a fixed token instead of a printed one

The same agent, answering `POST /v1/chat/completions` - the protocol every
chat frontend already speaks (Open WebUI, LobeChat, IDE chat panels). Point
one at the address it prints, paste the token as the API key, done.

  GET  /v1/models                  the one model, named `comodor`
  POST /v1/chat/completions        streaming and not; standard shapes

One request is one whole agent turn - tools run, files change, and the final
answer arrives as one message. `X-Comodor-Session: <id>` continues a
conversation (echo the id the response carries); without it every request
stands alone.

What is ours, in a `comodor` block on the response, and never in the way:

  comodor: {"session": "...", "steps": 3, "stopped": "done"}

  comodor: {"mode": "plan"}     in the request body - set the mode for
                                that one request, act / plan / ask / chat

One turn may edit files and run commands. The token IS the permission to do
that, so it is worth what a password is worth: loopback by default, and a
reverse proxy with its own auth before anything wider."""),

    "webhook": ("Letting other systems hand it work", """\
  comodor webhook add ci --path /ci --template "A CI run just reported: {payload}"
  comodor webhook list               what is subscribed, and what it may do
  comodor webhook start -b           run it detached from this terminal
  comodor webhook test /ci           send one signed event to prove the wire

CI, monitoring, Git hosts - anything that POSTs JSON when something happens
can hand the agent the event, and the agent turns it into a task. Each
subscription has its own path, its own shared secret, and its own prompt
template ({payload} is the body; {.pull_request.title} picks a field).

The sender signs the raw body with HMAC-SHA256 and sends the digest in
X-Comodor-Signature-256. A wrong signature gets the same 404 an unknown path
gets - nothing here tells a prober what exists.

By default these turns read and plan only. --allow-writes widens one
subscription, not the agent, and it is the one flag worth thinking twice
about: a machine talking to a machine is exactly the caller whose
instructions nobody has read."""),

    "memory-provider": ("An external memory service (optional)", """\
  comodor memory-provider setup --base-url http://127.0.0.1:9310
  comodor memory-provider status     what is set, and whether it answers
  comodor memory-provider off        forget the external service

The brain here is local and complete; this is one optional service alongside
it, never instead of it. New facts are mirrored out to the service, and with
--augment recall may also ask it for lines - which are capped, and marked as
coming from outside, because they were not earned here.

The key lives in an environment variable (default $MEM0_API_KEY) and is never
written to the config file. With the service down, nothing changes except a
warning: the local write already happened."""),

    "whatsapp": ("From WhatsApp", """\
  comodor whatsapp connect         guided: links each page, checks each value
  comodor whatsapp webhook         what to paste into Meta's dashboard
  comodor whatsapp pair            a one-time code that adds your number
  comodor whatsapp start -b        run it detached from this terminal
  comodor whatsapp status          what is set, who may talk, is it running

Telegram does the same thing in about a minute. This takes about twenty and is
technical, and most of it is in Meta's dashboard - so unless it has to be
WhatsApp, `comodor help telegram` is the shorter road.

What is NOT needed, because everybody assumes otherwise: no real phone number,
no payment method, no business verification. The test number Meta creates
messages five people for free, which is four more than one person talking to
their own agent needs.

Meta's Cloud API, which is the official one. The libraries that drive WhatsApp
Web instead need Node, break whenever the web client changes, and are against
the terms the account is held to - the failure mode there is somebody's phone
number being banned.

Two things work differently from Telegram, and both are Meta's design:

*Messages are delivered, not fetched.* There is no long poll. Meta posts each
message to a URL, so something of yours has to be reachable over HTTPS. The
bot listens on localhost; `connect` starts a Cloudflare tunnel in front of it
if cloudflared is installed, and `start --tunnel` brings one up alongside.

A quick tunnel gets a new address every start, and Meta keeps delivering to
the old one - so for a bot meant to keep running, make a named tunnel once:

  cloudflared tunnel login && cloudflared tunnel create comodor

*Every webhook is signed* with your app secret, and the signature is checked.
Without one, anything that reaches that URL can hand the agent instructions
with somebody else's number on them.

There is also a day-long window: WhatsApp only lets the bot message you within
twenty-four hours of your last message. A task that finishes after that cannot
be reported until you write again.

Full guide: docs/whatsapp.md"""),

    "telegram": ("From your phone", """\
  comodor telegram connect TOKEN   a bot from @BotFather
  comodor telegram pair            a one-time code that adds your account
  comodor telegram start           here, holding this terminal
  comodor telegram start -b        detached - keeps answering after you close it
  comodor telegram stop            end a background one
  comodor telegram service install start it at login, so a reboot brings it back
  comodor telegram status          what is set, who may talk, and is it running

The first-run setup asks about this, and offers to start it when the questions
are over, so a fresh install has already been through all of it.

Started with -b it is detached from the terminal: closing the terminal, logging
out and ending the session all leave it answering. A reboot does not - that is
the operating system's job, and `service install` is how to ask for it.

A bot's username is public, so it answers a fixed list of numeric account ids
and nobody else - and everyone else gets silence rather than a refusal. The
list is filled by pairing, at this terminal, and never from Telegram.

It reads and plans only until:

  comodor telegram writes on

Approving a shell command with a thumb, in a queue, is a decision made with
less attention than the same approval at a keyboard. The consequences are the
same, so this one is opt-in and cannot be turned on from the phone.

Full guide: docs/telegram.md"""),
}


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #


def render(console: Console | None = None, theme: Theme | None = None,
           topic: str = "") -> int:
    """Print the help page, or one topic of it."""
    theme = theme or console_module.prepare_theme("ember", False, no_color=False)
    console = console or console_module.build(theme)

    if topic:
        return _topic(console, theme, topic.strip().lower())

    console.print()
    console.print(_headline(theme))
    console.print()
    console.print(Padding(Text("comodor [options] [command]",
                               style=theme.style("value")), (0, 0, 1, 2)))

    for heading, rows in SECTIONS:
        console.print(_block(theme, heading, rows))

    console.print(_block(theme, "Options", OPTIONS))
    console.print(_block(theme, "Inside the interface", IN_THE_INTERFACE))

    console.print(Padding(Text("Worth knowing", style=theme.style("label", bold=True)),
                          (0, 0, 0, 2)))
    for title, body in CLOSING:
        console.print(Padding(Text.assemble(
            (title + "  ", theme.style("accent")),
            (body, theme.style("dim")),
        ), (0, 4, 0, 4)))

    console.print()
    console.print(Padding(Text.assemble(
        ("comodor help <topic>", theme.style("accent")),
        ("   ", ""),
        (", ".join(sorted(TOPICS)), theme.style("dim")),
    ), (0, 0, 0, 2)))
    console.print(Padding(Text.assemble(
        ("Everything, in full   ", theme.style("dim")),
        (DOCS, theme.style("value")),
    ), (0, 0, 1, 2)))
    return 0


def _headline(theme: Theme) -> Padding:
    return Padding(Text.assemble(
        ("Comodor", theme.style("accent", bold=True)),
        (f"  {__version__}\n", theme.style("dim")),
        ("A terminal coding agent that learns the way you correct it.",
         theme.style("text")),
    ), (0, 0, 0, 2))


def _block(theme: Theme, heading: str, rows: Iterable[tuple[str, str]]) -> Group:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=theme.style("accent"), no_wrap=True)
    table.add_column(style=theme.style("dim"), overflow="fold")
    for left, right in rows:
        table.add_row(left, right)
    return Group(
        Padding(Text(heading, style=theme.style("label", bold=True)), (0, 0, 0, 2)),
        Padding(table, (0, 2, 1, 4)),
    )


def _topic(console: Console, theme: Theme, name: str) -> int:
    entry = TOPICS.get(name)
    if entry is None:
        console.print()
        console.print(Padding(Text.assemble(
            (f"No help topic called {name!r}.\n", theme.style("bad")),
            ("Try: ", theme.style("dim")),
            (", ".join(sorted(TOPICS)), theme.style("accent")),
        ), (0, 0, 1, 2)))
        return 1

    title, body = entry
    console.print()
    console.print(Padding(Text(title, style=theme.style("accent", bold=True)),
                          (0, 0, 1, 2)))
    for block in _paragraphs(body):
        # Wrapped, never clipped, even for the command tables. On a terminal
        # too narrow for one of those rows, a wrapped line is untidy and a
        # truncated one is wrong - "set computer.enabled: true in your con"
        # is not an instruction anybody can follow.
        console.print(Padding(Text(block, style=theme.style("text"),
                                   overflow="fold"),
                              (0, 2, 1, 2)))
    return 0


def _paragraphs(body: str) -> list[str]:
    """Prose reflowed to the terminal; indented blocks left exactly as written.

    The body is hard-wrapped in the source so it is readable there. Handing
    that to a renderer that wraps again produces a second break inside every
    line - "look at the / screen, move / the mouse" on a narrow terminal. So
    prose is joined back into one line and wrapped once, here, at the width
    that actually exists.

    An indented block is a small table of commands, where the line breaks and
    the alignment are the content. Those are left alone.
    """
    blocks: list[str] = []
    for chunk in body.split("\n\n"):
        lines = chunk.split("\n")
        if any(line.startswith("  ") for line in lines):
            blocks.append(chunk)
        else:
            blocks.append(" ".join(line.strip() for line in lines if line.strip()))
    return [block for block in blocks if block]


def topics() -> list[str]:
    return sorted(TOPICS)
