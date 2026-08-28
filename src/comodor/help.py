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
        ("comodor telegram start", "drive it from your phone, all buttons"),
        ("comodor skills browse", "procedures it follows when the work calls for them"),
        ("comodor mcp list", "tools from Model Context Protocol servers"),
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
  /skills                   the same, in the interface

Write your own in  ~/.comodor/skills/<name>/SKILL.md.
Full guide: docs/skills.md"""),

    "cost": ("Paying less for the same work", """\
  /cost                     tokens, spend, and what the cache saved
  agent.max_cost_usd        stop a task at a price
  agent.max_steps           stop it at a number of steps

Prompt caching is on by default. The parts of a request that do not change -
the system prompt, the tool schemas - are re-served by the provider at a tenth
of the price, which is most of a long session.

A spend limit only works for a model with a published rate. `comodor doctor`
says plainly when it cannot be enforced.  Full guide: docs/cost.md"""),

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

    "telegram": ("From your phone", """\
  comodor telegram connect TOKEN   a bot from @BotFather
  comodor telegram pair            a one-time code that adds your account
  comodor telegram start           run it until stopped
  comodor telegram status          what is set, and who may talk to it

The first-run setup asks about this as its last question, so a fresh install
has already offered it.

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
