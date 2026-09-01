"""`comodor discord` — connect a bot, pair an account, and run it.

The shape mirrors `comodor telegram` on purpose: one token, a numeric
allow-list, a pairing code typed here. What Discord adds is a setup step
nobody can skip and two things that fail silently without it:

*The Message Content intent is privileged.* In the developer portal, under
Bot → Privileged Gateway Intents, it has to be switched on. Without it the
gateway connects happily and every message body arrives *empty* — a bot that
looks connected and hears nothing. `connect` checks the intent by asking the
application flags, and says exactly that when it is missing.

*The bot must be invited to the server* with the `bot` scope and that intent.
An invite made before the intent was enabled keeps a bot that cannot read.
"""

from __future__ import annotations

import argparse
import signal
import threading

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Config
from .api import Bot, DiscordError, Unauthorised

PORTAL = "https://discord.com/developers/applications"

def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("discord", help="drive Comodor from Discord")
    actions = parser.add_subparsers(dest="discord_action")

    connect = actions.add_parser("connect", help="save a bot token")
    connect.add_argument("token", nargs="?", help="from the developer portal")

    start = actions.add_parser("start", help="run the bot")
    start.add_argument(
        "--background", "-b", action="store_true",
        help="detach from this terminal, so it keeps answering after you "
             "close it")

    actions.add_parser("stop", help="stop a bot running in the background")

    unit = actions.add_parser(
        "service", help="start it at login, so a reboot brings it back")
    unit.add_argument("what", nargs="?", default="status",
                      choices=["status", "install", "uninstall", "show"])

    actions.add_parser("status", help="what is configured, and who may talk")
    actions.add_parser("pair", help="add an account, with a one-time code")

    forget = actions.add_parser("forget", help="remove an account")
    forget.add_argument("who", help="the numeric id, or `all`")

    writes = actions.add_parser(
        "writes", help="whether a Discord turn may edit files and run commands")
    writes.add_argument("state", choices=["on", "off"])

    actions.add_parser("off", help="switch it off without forgetting it")

def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    action = getattr(args, "discord_action", None) or "status"

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
        if getattr(args, "background", False):
            return _background(console, config)
        return _start(console, config)
    if action == "stop":
        return _stop(console, config)
    if action == "service":
        return _service(console, config, getattr(args, "what", "status"))

    console.print("Try `comodor discord status`.")
    return 1

def _save(config: Config) -> None:
    from .. import config as config_mod

    config_mod.save_user_config(config)

# --------------------------------------------------------------------------- #

def _connect(console, config: Config, args: argparse.Namespace) -> int:
    """Take the token, and prove it before saving."""
    token = (args.token or "").strip()
    if not token:
        console.print()
        console.print(Panel(
            Text.from_markup(
                "1  Open [bold]" + PORTAL + "[/bold] → "
                "[bold]New Application[/bold], and name it.\n"
                "2  [bold]Bot[/bold] → [bold]Reset Token[/bold] → copy it.\n"
                "3  On the same page, under [bold]Privileged Gateway "
                "Intents[/bold],\n"
                "   switch on [bold]Message Content Intent[/bold].\n"
                "   [dim]Without it the bot connects and every message "
                "arrives empty.[/dim]\n"
                "4  [bold]OAuth2[/bold] → URL Generator: tick [bold]bot[/bold] "
                "and the same intent,\n"
                "   open the URL it makes, and invite the bot to your "
                "server.\n\n"
                "Then: [bold]comodor discord connect <token>[/bold]"),
            title=" Creating the bot ", title_align="left",
            border_style="accent", padding=(1, 2)))
        console.print()
        return 1

    try:
        who = Bot(token).me()
    except Unauthorised as problem:
        console.print(f"\n[red]Discord refused that token.[/red] {problem}\n")
        return 1
    except DiscordError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    config.discord.token = token
    config.discord.enabled = True
    _save(config)

    console.print(f"\n  Connected as [bold]{who.get('username')}[/bold]")
    if not config.discord.allowed:
        console.print("  Nobody may talk to it yet — "
                      "[bold]comodor discord pair[/bold]")
    console.print("  [dim]Message Content intent switched on? A bot without "
                  "it connects but hears nothing.[/dim]\n")
    return 0

def _status(console, config: Config) -> int:
    from . import service
    from . import unit as unit_mod

    settings = config.discord
    console.print()

    if not settings.token:
        console.print("  Not connected. "
                      "[bold]comodor discord connect[/bold] to set it up.\n")
        return 0

    who = "—"
    try:
        found = Bot(settings.token).me()
        who = f"{found.get('username')}  [dim]id {found.get('id')}[/dim]"
    except DiscordError as problem:
        who = f"[red]{problem}[/red]"

    here = service.state(config)
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Bot", who)
    table.add_row("Enabled", "yes" if settings.enabled else "no")
    table.add_row("At login", "yes" if unit_mod.installed(config) else "no")
    table.add_row("Background",
                  f"[good]running[/good]  pid {here.pid}, up {here.uptime()}"
                  if here.running else "not running")
    table.add_row("Paired accounts",
                  ", ".join(str(x) for x in settings.allowed) or "none")
    table.add_row("May edit and run",
                  "[warn]yes[/warn]" if settings.allow_writes else "no")
    console.print(table)

    if not settings.allowed:
        console.print(Text(
            "\n  It answers nobody until an account is paired — a server can "
            "have thousands of people in it, and this reads and writes your "
            "files.", style="dim"))
    console.print()
    return 0

def _pair(console, config: Config) -> int:
    if not config.discord.token:
        console.print("\n  Connect it first: "
                      "[bold]comodor discord connect[/bold]\n")
        return 1

    from .bot import Service

    try:
        service = Service(config, announce=lambda line: None)
    except DiscordError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    code = service.offer_pairing()
    console.print()
    console.print(Panel(
        Text.from_markup(
            "Send the bot a direct message in Discord containing:\n\n"
            f"      [bold accent]{code}[/bold accent]\n\n"
            "That adds your account to the list it answers, and the code "
            "stops working the moment it is used.\n\n"
            f"[dim]It expires in {config.discord.pair_window // 60} minutes. "
            "Ctrl-C to give up.[/dim]"),
        title=" Pair an account ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()

    before = set(config.discord.allowed)
    service.announce = lambda line: console.print(f"  {line}")
    threading.Thread(target=service.run, daemon=True).start()

    try:
        while True:
            if set(config.discord.allowed) != before:
                break
            if service.pairing is None or not service.pairing.live:
                console.print("\n  The code expired. Run it again.\n")
                service.stop()
                return 1
            threading.Event().wait(0.5)
    except KeyboardInterrupt:
        console.print("\n  Given up.\n")
        service.stop()
        return 130

    service.stop()
    added = set(config.discord.allowed) - before
    console.print(f"\n  [green]Paired.[/green] {', '.join(str(x) for x in added)} "
                  "may now talk to it.")
    console.print("  [bold]comodor discord start --background[/bold] to run "
                  "it.\n")
    return 0

def _forget(console, config: Config, who: str) -> int:
    settings = config.discord
    if who.lower() == "all":
        count = len(settings.allowed)
        settings.allowed = []
        _save(config)
        console.print(f"\n  Removed {count} account(s). It answers nobody "
                      f"now.\n")
        return 0

    if not who.isdigit():
        console.print("\n  Give the numeric id — a username can be taken by "
                      "somebody else.\n")
        return 1
    kept = [x for x in settings.allowed if str(x) != who]
    if len(kept) == len(settings.allowed):
        console.print(f"\n  {who} was not on the list.\n")
        return 1
    settings.allowed = kept
    _save(config)
    console.print(f"\n  Removed {who}.\n")
    return 0

def _writes(console, config: Config, on: bool) -> int:
    config.discord.allow_writes = on
    _save(config)
    console.print()
    if on:
        console.print("  A Discord turn may now edit files and run commands, "
                      "[bold]asking first[/bold].\n")
    else:
        console.print("  Discord turns read and plan only.\n")
    return 0

def _off(console, config: Config) -> int:
    config.discord.enabled = False
    _save(config)
    console.print("\n  Switched off. The token and pairings are kept.\n")
    return 0

def _start(console, config: Config) -> int:
    from ..channels import DISCORD
    from .bot import Service

    ok, why = DISCORD.can_run(config)
    if not ok:
        console.print(f"\n  [red]{why}[/red]\n")
        return 1

    console.print()
    console.print(f"  Working in [bold]{config.paths.project}[/bold]")
    service = Service(config, announce=lambda line: console.print(f"  {line}"))

    def bye(*_: object) -> None:
        console.print("\n  Stopping.\n")
        service.stop()

    try:
        signal.signal(signal.SIGINT, lambda *_: bye())
    except ValueError:
        pass

    console.print("  Ctrl-C to stop\n")
    try:
        service.run()
    except KeyboardInterrupt:
        bye()
    return 0

def _background(console, config: Config) -> int:
    from . import service

    ok, why = service.start(config)
    console.print()
    if not ok:
        console.print(f"  [red]{why}[/red]\n")
        return 1
    console.print(f"  [green]{why}[/green]")
    console.print(f"  [dim]log:  {service.log_file(config)}[/dim]")
    console.print("  [dim]stop: [/dim][bold]comodor discord stop[/bold]")
    console.print("  [dim]to bring it back after a reboot: "
                  "[/dim][bold]comodor discord service install[/bold]\n")
    return 0

def _stop(console, config: Config) -> int:
    from . import service

    ok, why = service.stop(config)
    console.print()
    console.print(f"  {why}\n" if ok else f"  [dim]{why}[/dim]\n")
    return 0 if ok else 1

def _service(console, config: Config, what: str) -> int:
    from . import unit as unit_mod

    plan = unit_mod.plan(config)
    console.print()

    if not plan.supported:
        console.print(f"  [red]{plan.why}[/red]")
        console.print("  [dim]`comodor discord start --background` still "
                      "works; it just does not survive a reboot.[/dim]\n")
        return 1

    if what == "show":
        console.print(Panel(Text(plan.body.rstrip()),
                            title=Text(f" {plan.path} "), title_align="left",
                            border_style="accent", padding=(1, 2)))
        console.print()
        return 0

    if what == "status":
        there = unit_mod.installed(config)
        console.print(f"  {plan.kind}: "
                      + ("[green]installed[/green]" if there
                         else "not installed"))
        console.print(f"  [dim]{plan.path}[/dim]\n")
        console.print("  [bold]comodor discord service show[/bold]"
                      "[dim]     read the unit before trusting it[/dim]")
        console.print("  [bold]comodor discord service install[/bold]"
                      "[dim]  start it at every login[/dim]\n")
        return 0

    if what == "uninstall":
        ok, why = unit_mod.uninstall(config)
        console.print(f"  {why}" if ok else f"  [red]{why}[/red]")
        console.print()
        return 0 if ok else 1

    console.print(Panel(Text(plan.body.rstrip()),
                        title=Text(f" {plan.path} "), title_align="left",
                        border_style="accent", padding=(1, 2)))
    ok, why, _ = unit_mod.install(config)
    console.print()
    console.print(f"  [green]{why}[/green]" if ok else f"  [red]{why}[/red]")
    if ok:
        console.print("  [dim]stop it starting: [/dim]"
                      "[bold]comodor discord service uninstall[/bold]")
    console.print()
    return 0 if ok else 1
