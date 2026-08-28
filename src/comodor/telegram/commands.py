"""`comodor telegram` — connect a bot, pair an account, and run it.

The pairing step is the point of this command. A bot's username is public and
anybody who finds it can send it a message, so the list of accounts it answers
is filled here, at a terminal, by somebody who already has the machine — and
never from Telegram itself.
"""

from __future__ import annotations

import argparse
import signal
import threading
from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Config
from .api import Bot, TelegramError, Unauthorised


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "telegram", help="drive Comodor from a Telegram bot")
    actions = parser.add_subparsers(dest="telegram_action")

    connect = actions.add_parser("connect", help="save a bot token")
    connect.add_argument("token", nargs="?", help="from BotFather")

    actions.add_parser("start", help="run the bot until stopped")
    actions.add_parser("status", help="what is configured, and who may talk")
    actions.add_parser("pair", help="add an account, with a one-time code")

    forget = actions.add_parser("forget", help="remove an account")
    forget.add_argument("who", help="the numeric id, or `all`")

    writes = actions.add_parser(
        "writes", help="whether a Telegram turn may edit files and run commands")
    writes.add_argument("state", choices=["on", "off"])

    actions.add_parser("off", help="switch the bot off without forgetting it")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    # Through the project's theme, not a bare Console: the named styles this
    # module uses — `accent`, `warn` — are Comodor's, and a plain console
    # raises `MissingStyle` on the first panel rather than falling back.
    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)
    action = getattr(args, "telegram_action", None) or "status"

    if action == "connect":
        return _connect(console, config, args)
    if action == "status":
        return _status(console, config)
    if action == "pair":
        return _pair(console, config)
    if action == "forget":
        return _forget(console, config, args.who)
    if action == "writes":
        return _writes(console, config, args.state == "on")
    if action == "off":
        return _off(console, config)
    if action == "start":
        return _start(console, config)

    console.print("Try `comodor telegram status`.")
    return 1


def _save(config: Config) -> None:
    from .. import config as config_mod

    config_mod.save_user_config(config)


# --------------------------------------------------------------------------- #


def _connect(console, config: Config, args: argparse.Namespace) -> int:
    token = (args.token or "").strip()
    if not token:
        console.print()
        console.print(Panel(
            Text.from_markup(
                "Open Telegram and message [bold]@BotFather[/bold]:\n\n"
                "  [dim]/newbot[/dim]\n\n"
                "Give it a name, then a username ending in `bot`. It replies "
                "with a token that looks like\n"
                "[dim]1234567890:AA…[/dim]\n\n"
                "Then run:\n\n"
                "  [bold]comodor telegram connect <token>[/bold]"),
            title=" Getting a bot ", title_align="left",
            border_style="accent", padding=(1, 2)))
        console.print()
        return 0

    try:
        me = Bot(token).me()
    except Unauthorised:
        console.print("\n[red]Telegram refused that token.[/red] "
                      "BotFather can issue a new one with /token.\n")
        return 1
    except TelegramError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    config.telegram.token = token
    config.telegram.enabled = True
    _save(config)

    console.print(f"\n  Connected to [bold]@{me['username']}[/bold] "
                  f"([dim]{me['first_name']}[/dim])")
    if not config.telegram.allowed:
        console.print("  Nobody may talk to it yet — "
                      "[bold]comodor telegram pair[/bold]\n")
    else:
        console.print(f"  {len(config.telegram.allowed)} account(s) already "
                      f"paired\n")
    return 0


def _status(console, config: Config) -> int:
    telegram = config.telegram
    console.print()

    if not telegram.token:
        console.print("  No bot connected. "
                      "[bold]comodor telegram connect[/bold] to set one up.\n")
        return 0

    who = "—"
    try:
        me = Bot(telegram.token).me()
        who = f"@{me['username']}"
    except TelegramError as problem:
        who = f"[red]{problem}[/red]"

    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Bot", who)
    table.add_row("Enabled", "yes" if telegram.enabled else "no")
    table.add_row("Paired accounts",
                  ", ".join(str(x) for x in telegram.allowed) or "none")
    table.add_row("May edit and run",
                  "[warn]yes[/warn]" if telegram.allow_writes else "no")
    console.print(table)

    if not telegram.allowed:
        console.print(Text(
            "\n  It will answer nobody until an account is paired — which is "
            "the right thing for it to do, because a bot's username is public.",
            style="dim"))
    if telegram.allow_writes:
        console.print(Text(
            "\n  Turns started from Telegram may edit files and run commands.",
            style="yellow"))
    console.print()
    return 0


def _pair(console, config: Config) -> int:
    if not config.telegram.token:
        console.print("\n  Connect a bot first: "
                      "[bold]comodor telegram connect[/bold]\n")
        return 1

    from .bot import Service

    try:
        service = Service(config, announce=lambda line: None)
        username = f"@{service.bot.me()['username']}"
    except TelegramError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    code = service.offer_pairing()
    console.print()
    console.print(Panel(
        Text.from_markup(
            f"Message [bold]{username}[/bold] on Telegram and send:\n\n"
            f"      [bold accent]{code}[/bold accent]\n\n"
            f"That adds your account to the list this bot answers, and the "
            f"code stops working the moment it is used.\n\n"
            f"[dim]It expires in {config.telegram.pair_window // 60} minutes. "
            f"Ctrl-C to give up.[/dim]"),
        title=" Pair an account ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()

    before = set(config.telegram.allowed)
    stop = threading.Event()

    def watch(line: str) -> None:
        console.print(f"  {line}")

    service.announce = watch
    worker = threading.Thread(target=service.run, daemon=True)
    worker.start()

    try:
        while not stop.wait(0.5):
            if set(config.telegram.allowed) != before:
                break
            if service.pairing is None or not service.pairing.live:
                if set(config.telegram.allowed) == before:
                    console.print("\n  The code expired. Run it again.\n")
                    service.stop()
                    return 1
                break
    except KeyboardInterrupt:
        console.print("\n  Given up.\n")
        service.stop()
        return 130

    service.stop()
    added = set(config.telegram.allowed) - before
    console.print(f"\n  [green]Paired.[/green] "
                  f"{', '.join(str(x) for x in added)} may now talk to it.")
    console.print("  [bold]comodor telegram start[/bold] to run it.\n")
    return 0


def _forget(console, config: Config, who: str) -> int:
    if who.lower() == "all":
        count = len(config.telegram.allowed)
        config.telegram.allowed.clear()
        _save(config)
        console.print(f"\n  Forgot {count} account(s). "
                      f"The bot now answers nobody.\n")
        return 0
    try:
        wanted = int(who)
    except ValueError:
        console.print(f"\n  [red]{who!r} is not a numeric id.[/red]\n")
        return 1
    if wanted not in config.telegram.allowed:
        console.print(f"\n  {wanted} was not on the list.\n")
        return 1
    config.telegram.allowed.remove(wanted)
    _save(config)
    console.print(f"\n  {wanted} can no longer talk to it.\n")
    return 0


def _writes(console, config: Config, on: bool) -> int:
    config.telegram.allow_writes = on
    _save(config)
    console.print()
    if on:
        console.print(Panel(
            Text(
                "Turns started from Telegram may now edit files and run "
                "commands.\n\n"
                "Each one still asks first, and the approval is a button in "
                "the chat. Worth knowing that a tap made on a phone, in a "
                "queue, is a decision made with less attention than the same "
                "one at a keyboard — which is why this is off by default."),
            title=" Writes are on ", title_align="left",
            border_style="yellow", padding=(1, 2)))
    else:
        console.print("  Telegram turns are read-only again.")
    console.print()
    return 0


def _off(console, config: Config) -> int:
    config.telegram.enabled = False
    _save(config)
    console.print("\n  Switched off. The token and the paired accounts are "
                  "kept — `comodor telegram start` turns it back on.\n")
    return 0


def _start(console, config: Config) -> int:
    telegram = config.telegram
    if not telegram.token:
        console.print("\n  No bot connected. "
                      "[bold]comodor telegram connect[/bold]\n")
        return 1
    if not telegram.allowed:
        console.print("\n  [yellow]Nobody is paired[/yellow], so it would "
                      "answer nobody. [bold]comodor telegram pair[/bold] "
                      "first.\n")
        return 1

    from .bot import Service

    if not telegram.enabled:
        telegram.enabled = True
        _save(config)

    service = Service(config, announce=lambda line: console.print(f"  {line}"))

    def bye(*_: object) -> None:
        console.print("\n  Stopping…")
        service.stop()

    signal.signal(signal.SIGINT, bye)

    console.print()
    console.print(f"  Working in [dim]{Path(config.paths.project)}[/dim]")
    console.print(f"  {len(telegram.allowed)} paired account(s) · "
                  f"{'may edit and run' if telegram.allow_writes else 'read-only'}")
    console.print("  [dim]Ctrl-C to stop[/dim]\n")

    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()
    console.print("  Stopped.\n")
    return 0
