"""`comodor slack` — connect a workspace, pair an account, and run it.

The shape mirrors `comodor telegram` on purpose. What is different is
`manifest`: Slack lets an app be created from a YAML document, so instead of
walking somebody through eleven checkboxes across four settings pages, the
whole app — its name, its scopes, its events, Socket Mode already switched on —
is printed and pasted once.

That is the difference between Slack and WhatsApp here. Both need an app made
in somebody's dashboard; only one of them lets the app be described in a file.
"""

from __future__ import annotations

import argparse
import signal
import threading

from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..config import Config
from .api import Slack, SlackError, Unauthorised

NEW_APP = "https://api.slack.com/apps?new_app=1"

#: Everything the app needs, so nobody has to find eleven checkboxes.
#:
#: `connections:write` is on the app-level token rather than the bot one and is
#: the single most missed setting — without it Socket Mode cannot open, and the
#: error says `not_allowed_token_type`, which does not mention scopes.
MANIFEST = """\
display_information:
  name: Comodor
  description: A coding agent that learns the way you correct it
  background_color: "#0d0d0f"
features:
  bot_user:
    display_name: Comodor
    always_online: true
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - im:history
      - im:read
      - im:write
      - channels:history
      - groups:history
      - users:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
  interactivity:
    is_enabled: true
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
"""


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("slack", help="drive Comodor from Slack")
    actions = parser.add_subparsers(dest="slack_action")

    connect = actions.add_parser("connect", help="save the two Slack tokens")
    connect.add_argument("--bot-token", dest="bot_token",
                         help="xoxb-… from OAuth & Permissions")
    connect.add_argument("--app-token", dest="app_token",
                         help="xapp-… from Basic Information")

    actions.add_parser("manifest",
                       help="the app definition to paste into Slack")

    start = actions.add_parser("start", help="run the bot")
    start.add_argument("--background", "-b", action="store_true",
                       help="detach from this terminal, so it keeps answering "
                            "after you close it")

    actions.add_parser("stop", help="stop a bot running in the background")

    unit = actions.add_parser(
        "service", help="start it at login, so a reboot brings it back")
    unit.add_argument("what", nargs="?", default="status",
                      choices=["status", "install", "uninstall", "show"])

    actions.add_parser("status", help="what is configured, and who may talk")
    actions.add_parser("pair", help="add an account, with a one-time code")

    forget = actions.add_parser("forget", help="remove an account")
    forget.add_argument("who", help="the Slack user id, or `all`")

    writes = actions.add_parser(
        "writes", help="whether a Slack turn may edit files and run commands")
    writes.add_argument("state", choices=["on", "off"])

    actions.add_parser("off", help="switch it off without forgetting it")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    action = getattr(args, "slack_action", None) or "status"

    if action == "connect":
        return _connect(console, config, args)
    if action == "manifest":
        return _manifest(console)
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

    console.print("Try `comodor slack status`.")
    return 1


def _save(config: Config) -> None:
    from .. import config as config_mod

    config_mod.save_user_config(config)


# --------------------------------------------------------------------------- #


def _manifest(console) -> int:
    console.print()
    console.print(Panel(
        Text.from_markup(
            f"Open [bold]{NEW_APP}[/bold] and choose "
            "[bold]From a manifest[/bold],\npick your workspace, then paste "
            "what is below.\n\n"
            "[dim]It defines the app completely — name, scopes, events, and "
            "Socket Mode\nalready switched on — so there are no checkboxes to "
            "find.[/dim]"),
        title=" Creating the app ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()
    console.print(Syntax(MANIFEST, "yaml", theme="ansi_dark",
                         background_color="default"))
    console.print()
    console.print("  Then [bold]Install to Workspace[/bold], and:")
    console.print("  [bold]comodor slack connect[/bold]\n")
    return 0


def _connect(console, config: Config, args: argparse.Namespace) -> int:
    """Take the two tokens, and prove them before saving."""
    bot = (args.bot_token or "").strip()
    app = (args.app_token or "").strip()

    if not (bot or app):
        return _walk(console, config)

    if not bot:
        console.print("\n  [red]The bot token is the one that does the "
                      "work.[/red] `--bot-token xoxb-…`\n")
        return 1

    try:
        who = Slack(bot, app).me()
    except Unauthorised as problem:
        console.print(f"\n[red]Slack refused that token.[/red] {problem}\n")
        return 1
    except SlackError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    config.slack.bot_token = bot
    if app:
        config.slack.app_token = app
    config.slack.team = str(who.get("team") or "")
    config.slack.enabled = True
    _save(config)

    console.print(f"\n  Connected to [bold]{who.get('team')}[/bold] as "
                  f"[dim]{who.get('user')}[/dim]")
    if not config.slack.app_token:
        console.print("  [warn]No app-level token yet[/warn] — Socket Mode "
                      "cannot open without one.")
        console.print("  [dim]comodor slack connect --app-token xapp-…[/dim]")
    if not config.slack.allowed:
        console.print("  Nobody may talk to it yet — "
                      "[bold]comodor slack pair[/bold]")
    console.print()
    return 0


def _walk(console, config: Config) -> int:
    """Both tokens, one at a time, each checked as it arrives."""
    _manifest(console)

    def ask(message: str) -> str:
        console.print(f"  [bold]{message}[/bold][dim]:[/dim] ", end="")
        try:
            return input().strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    console.print(Panel(
        Text.from_markup(
            "With the app installed, two tokens:\n\n"
            "  [bold]1[/bold]  [bold]OAuth & Permissions[/bold] → "
            "[bold]Bot User OAuth Token[/bold]  [dim]xoxb-…[/dim]\n"
            "  [bold]2[/bold]  [bold]Basic Information[/bold] → "
            "[bold]App-Level Tokens[/bold] → Generate,\n     [dim]scope "
            "connections:write  →  xapp-…[/dim]\n\n"
            "[dim]The second is what lets it connect without a public "
            "address.[/dim]"),
        title=" The two tokens ", title_align="left",
        border_style="accent", padding=(1, 2)))

    bot = ""
    while True:
        bot = ask("bot token (xoxb-…)")
        if not bot:
            console.print("  [dim]Stopping here.[/dim]\n")
            return 1
        try:
            who = Slack(bot).me()
        except SlackError as problem:
            console.print(f"  [red]{problem}[/red]")
            continue
        console.print(f"  [green]Works.[/green] {who.get('team')} "
                      f"[dim]as {who.get('user')}[/dim]")
        config.slack.team = str(who.get("team") or "")
        break

    app = ""
    while True:
        app = ask("app-level token (xapp-…)")
        if not app:
            console.print("  [red]Socket Mode cannot open without it.[/red] "
                          "[dim]Stopping here.[/dim]\n")
            return 1
        try:
            probe = Slack(bot, app)
            probe.open_socket()
        except SlackError as problem:
            console.print(f"  [red]{problem}[/red]")
            continue
        console.print("  [green]Socket Mode opens.[/green]")
        break

    config.slack.bot_token = bot
    config.slack.app_token = app
    config.slack.enabled = True
    _save(config)

    console.print("\n  One thing left — say who may talk to it:")
    console.print("    [bold]comodor slack pair[/bold]")
    console.print("  then [bold]comodor slack start --background[/bold]\n")
    return 0


def _status(console, config: Config) -> int:
    from . import service
    from . import unit as unit_mod

    settings = config.slack
    console.print()

    if not settings.bot_token:
        console.print("  Not connected. "
                      "[bold]comodor slack connect[/bold] to set it up.\n")
        return 0

    who = settings.team or "—"
    try:
        found = Slack(settings.bot_token, settings.app_token).me()
        who = f"{found.get('team')}  [dim]as {found.get('user')}[/dim]"
    except SlackError as problem:
        who = f"[red]{problem}[/red]"

    here = service.state(config)
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Workspace", who)
    table.add_row("Enabled", "yes" if settings.enabled else "no")
    table.add_row("Socket Mode",
                  "ready" if settings.app_token
                  else "[warn]no app-level token[/warn]")
    table.add_row("At login", "yes" if unit_mod.installed(config) else "no")
    table.add_row("Background",
                  f"[good]running[/good]  pid {here.pid}, up {here.uptime()}"
                  if here.running else "not running")
    table.add_row("Paired accounts", ", ".join(settings.allowed) or "none")
    table.add_row("May edit and run",
                  "[warn]yes[/warn]" if settings.allow_writes else "no")
    console.print(table)

    if not settings.allowed:
        console.print(Text(
            "\n  It answers nobody until an account is paired — a workspace "
            "can have hundreds of people in it, and this reads and writes your "
            "files.", style="dim"))
    console.print()
    return 0


def _pair(console, config: Config) -> int:
    if not (config.slack.bot_token and config.slack.app_token):
        console.print("\n  Connect it first: "
                      "[bold]comodor slack connect[/bold]\n")
        return 1

    from .bot import Service

    try:
        service = Service(config, announce=lambda line: None)
    except SlackError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    code = service.offer_pairing()
    console.print()
    console.print(Panel(
        Text.from_markup(
            "Send [bold]Comodor[/bold] a direct message in Slack containing:\n\n"
            f"      [bold accent]{code}[/bold accent]\n\n"
            "That adds your account to the list it answers, and the code stops "
            "working the moment it is used.\n\n"
            f"[dim]It expires in {config.slack.pair_window // 60} minutes. "
            f"Ctrl-C to give up.[/dim]"),
        title=" Pair an account ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()

    before = set(config.slack.allowed)
    service.announce = lambda line: console.print(f"  {line}")
    threading.Thread(target=service.run, daemon=True).start()

    try:
        while True:
            if set(config.slack.allowed) != before:
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
    added = set(config.slack.allowed) - before
    console.print(f"\n  [green]Paired.[/green] {', '.join(added)} may now "
                  f"talk to it.")
    console.print("  [bold]comodor slack start --background[/bold] to run "
                  "it.\n")
    return 0


def _forget(console, config: Config, who: str) -> int:
    settings = config.slack
    if who.lower() == "all":
        count = len(settings.allowed)
        settings.allowed = []
        _save(config)
        console.print(f"\n  Removed {count} account(s). It answers nobody "
                      f"now.\n")
        return 0

    kept = [x for x in settings.allowed if x != who]
    if len(kept) == len(settings.allowed):
        console.print(f"\n  {who} was not on the list.\n")
        return 1
    settings.allowed = kept
    _save(config)
    console.print(f"\n  Removed {who}.\n")
    return 0


def _writes(console, config: Config, on: bool) -> int:
    config.slack.allow_writes = on
    _save(config)
    console.print()
    if on:
        console.print("  A Slack turn may now edit files and run commands, "
                      "[bold]asking first[/bold].\n")
    else:
        console.print("  Slack turns read and plan only.\n")
    return 0


def _off(console, config: Config) -> int:
    config.slack.enabled = False
    _save(config)
    console.print("\n  Switched off. The tokens and pairings are kept.\n")
    return 0


def _start(console, config: Config) -> int:
    from ..channels import SLACK
    from .bot import Service

    ok, why = SLACK.can_run(config)
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
    console.print("  [dim]stop: [/dim][bold]comodor slack stop[/bold]")
    console.print("  [dim]to bring it back after a reboot: "
                  "[/dim][bold]comodor slack service install[/bold]\n")
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
        console.print("  [dim]`comodor slack start --background` still works; "
                      "it just does not survive a reboot.[/dim]\n")
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
        console.print("  [bold]comodor slack service show[/bold]"
                      "[dim]     read the unit before trusting it[/dim]")
        console.print("  [bold]comodor slack service install[/bold]"
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
                      "[bold]comodor slack service uninstall[/bold]")
    console.print()
    return 0 if ok else 1
