"""`comodor whatsapp` — connect a number, pair an account, and run it.

The shape mirrors `comodor telegram` deliberately: somebody who has set one up
should not have to learn a second vocabulary for the same idea. What differs is
`connect`, because WhatsApp needs four things where Telegram needs one, and
`webhook`, because Meta delivers rather than being asked.
"""

from __future__ import annotations

import argparse
import signal
import threading

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Config
from .api import Cloud, Unauthorised, WhatsAppError


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "whatsapp", help="drive Comodor from WhatsApp")
    actions = parser.add_subparsers(dest="whatsapp_action")

    connect = actions.add_parser(
        "connect", help="save the number, the token and the app secret")
    connect.add_argument("--token", help="a permanent access token")
    connect.add_argument("--number-id", dest="number_id",
                         help="the phone number id, not the number")
    connect.add_argument("--app-secret", dest="app_secret",
                         help="from the app's Basic Settings")
    connect.add_argument("--url", dest="public_url",
                         help="the public HTTPS address of the webhook")
    connect.add_argument("--tunnel", action="store_true",
                         help="start a Cloudflare tunnel and use its address")

    start = actions.add_parser("start", help="run the bot")
    start.add_argument("--background", "-b", action="store_true",
                       help="detach from this terminal, so it keeps answering "
                            "after you close it")
    start.add_argument("--tunnel", action="store_true",
                       help="bring up a Cloudflare tunnel alongside it")

    actions.add_parser("stop", help="stop a bot running in the background")

    unit = actions.add_parser(
        "service", help="start it at login, so a reboot brings it back")
    unit.add_argument("what", nargs="?", default="status",
                      choices=["status", "install", "uninstall", "show"])

    actions.add_parser("webhook", help="what to paste into Meta's dashboard")
    actions.add_parser("status", help="what is configured, and who may talk")
    actions.add_parser("pair", help="add an account, with a one-time code")

    forget = actions.add_parser("forget", help="remove an account")
    forget.add_argument("who", help="the number, or `all`")

    writes = actions.add_parser(
        "writes", help="whether a WhatsApp turn may edit files and run commands")
    writes.add_argument("state", choices=["on", "off"])

    actions.add_parser("off", help="switch it off without forgetting it")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    action = getattr(args, "whatsapp_action", None) or "status"

    if action == "connect":
        return _connect(console, config, args)
    if action == "status":
        return _status(console, config)
    if action == "webhook":
        return _webhook(console, config)
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
        return _start(console, config, args)
    if action == "stop":
        return _stop(console, config)
    if action == "service":
        return _service(console, config, getattr(args, "what", "status"))

    console.print("Try `comodor whatsapp status`.")
    return 1


def _ask(console, message: str) -> str:
    """One line from the person at the terminal, or empty if there is nobody.

    Empty rather than an exception on end-of-file: the wizard treats "nothing
    entered" as "stop here and keep what we have", which is the right answer
    for a pipe as well as for somebody pressing enter.
    """
    console.print(f"  [bold]{message}[/bold][dim]:[/dim] ", end="")
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        return ""


def _save(config: Config) -> None:
    from .. import config as config_mod

    config_mod.save_user_config(config)


# --------------------------------------------------------------------------- #


def _connect(console, config: Config, args: argparse.Namespace) -> int:
    """Take the four things Meta needs, and prove the first two work."""
    from .webhook import make_verify_token

    token = (args.token or "").strip()
    number_id = (args.number_id or "").strip()
    secret = (args.app_secret or "").strip()

    if not (token or number_id or secret):
        # Nothing given at all: walk it, rather than printing instructions and
        # leaving somebody to run the command again with three flags they have
        # to go and find first.
        from ..ui import console as console_module
        from .guide import walk

        theme = console_module.prepare_theme(
            config.ui.theme, config.ui.ascii_borders, no_color=False)
        return walk(console, theme, config,
                    ask=lambda message: _ask(console, message),
                    save=_save)

    if not (token and number_id):
        console.print()
        console.print(Panel(
            Text.from_markup(
                "WhatsApp needs four things, all from "
                "[bold]developers.facebook.com[/bold]:\n\n"
                "  [bold]1[/bold]  A [bold]Meta app[/bold] with the WhatsApp "
                "product added.\n"
                "  [bold]2[/bold]  Its [bold]phone number id[/bold] — the "
                "number Meta shows\n     [dim]beside the number, not the "
                "number itself.[/dim]\n"
                "  [bold]3[/bold]  An [bold]access token[/bold]. The one on "
                "the dashboard lasts a day;\n     [dim]a System User token "
                "under Business Settings does not expire.[/dim]\n"
                "  [bold]4[/bold]  The [bold]app secret[/bold], from Settings "
                "→ Basic.\n     [dim]Every webhook is signed with it. Without "
                "it, anything that\n     reaches the endpoint can pretend to "
                "be Meta.[/dim]\n\n"
                "Then:\n\n"
                "  [bold]comodor whatsapp connect \\\n"
                "      --number-id 123456789 \\\n"
                "      --token EAAG… \\\n"
                "      --app-secret 0a1b…[/bold]"),
            title=" Connecting WhatsApp ", title_align="left",
            border_style="accent", padding=(1, 2)))
        console.print()
        return 0

    try:
        me = Cloud(token, number_id,
                   version=config.whatsapp.api_version).me()
    except Unauthorised as problem:
        console.print(f"\n[red]Meta refused that token.[/red] {problem}\n")
        return 1
    except WhatsAppError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    config.whatsapp.token = token
    config.whatsapp.phone_number_id = number_id
    if secret:
        config.whatsapp.app_secret = secret
    if args.public_url:
        config.whatsapp.public_url = args.public_url.strip()
    if not config.whatsapp.verify_token:
        config.whatsapp.verify_token = make_verify_token()
    config.whatsapp.enabled = True
    _save(config)

    shown = me.get("display_phone_number") or number_id
    named = me.get("verified_name") or ""
    console.print(f"\n  Connected to [bold]{shown}[/bold]"
                  + (f" ([dim]{named}[/dim])" if named else ""))

    if not config.whatsapp.app_secret:
        console.print("  [warn]No app secret yet[/warn] — webhooks cannot be "
                      "verified until there is one.")
        console.print("  [dim]comodor whatsapp connect --app-secret <secret>"
                      "[/dim]")
    if not config.whatsapp.allowed:
        console.print("  Nobody may talk to it yet — "
                      "[bold]comodor whatsapp pair[/bold]")
    console.print("  Then [bold]comodor whatsapp webhook[/bold] for what to "
                  "paste into Meta.\n")
    return 0


def _webhook(console, config: Config) -> int:
    """The two strings Meta's dashboard asks for, and where they go."""
    settings = config.whatsapp
    console.print()

    if not settings.verify_token:
        console.print("  Nothing to show yet — "
                      "[bold]comodor whatsapp connect[/bold] first.\n")
        return 1

    where = settings.public_url or (
        f"https://<your-address>{settings.path}")
    console.print(Panel(
        Text.from_markup(
            "In the Meta app dashboard, under [bold]WhatsApp → "
            "Configuration[/bold]:\n\n"
            f"  [dim]Callback URL[/dim]\n  [bold]{where}[/bold]\n\n"
            f"  [dim]Verify token[/dim]\n  [bold]{settings.verify_token}"
            "[/bold]\n\n"
            "Then subscribe the app to the [bold]messages[/bold] field.\n\n"
            "[dim]Meta only delivers to HTTPS, and will not accept a "
            "self-signed\ncertificate. The bot listens on "
            f"{settings.host}:{settings.port}{settings.path}; something has to "
            "put a\nreal certificate in front of it — a tunnel is the usual "
            "answer:[/dim]\n\n"
            f"  [bold]cloudflared tunnel --url "
            f"http://{settings.host}:{settings.port}[/bold]"),
        title=" The webhook ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()
    return 0


def _status(console, config: Config) -> int:
    from . import service
    from . import unit as unit_mod

    settings = config.whatsapp
    console.print()

    if not settings.token:
        console.print("  Not connected. "
                      "[bold]comodor whatsapp connect[/bold] to set it up.\n")
        return 0

    who = "—"
    try:
        me = Cloud(settings.token, settings.phone_number_id,
                   version=settings.api_version).me()
        who = str(me.get("display_phone_number") or settings.phone_number_id)
    except WhatsAppError as problem:
        who = f"[red]{problem}[/red]"

    here = service.state(config)
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Number", who)
    table.add_row("Enabled", "yes" if settings.enabled else "no")
    table.add_row("Signature checking",
                  "on" if settings.app_secret else "[warn]off — no app secret[/warn]")
    table.add_row("Webhook", settings.public_url or "[warn]not set[/warn]")
    table.add_row("At login", "yes" if unit_mod.installed(config) else "no")
    table.add_row("Background",
                  f"[good]running[/good]  pid {here.pid}, up {here.uptime()}"
                  if here.running else "not running")
    table.add_row("Paired numbers",
                  ", ".join(settings.allowed) or "none")
    table.add_row("May edit and run",
                  "[warn]yes[/warn]" if settings.allow_writes else "no")
    console.print(table)

    if not settings.allowed:
        console.print(Text(
            "\n  It answers nobody until a number is paired — which is right, "
            "because a business number is a phone number and strangers message "
            "phone numbers.", style="dim"))
    if not settings.app_secret:
        console.print(Text(
            "\n  Without an app secret every webhook is unverified: anything "
            "that can reach the endpoint can pretend to be Meta.",
            style="yellow"))
    console.print()
    return 0


def _pair(console, config: Config) -> int:
    settings = config.whatsapp
    if not settings.token:
        console.print("\n  Connect it first: "
                      "[bold]comodor whatsapp connect[/bold]\n")
        return 1

    from .bot import Service

    try:
        service = Service(config, announce=lambda line: None)
        number = "this number"
        try:
            me = service.cloud.me()
            number = str(me.get("display_phone_number") or number)
        except WhatsAppError:
            pass
    except WhatsAppError as problem:
        console.print(f"\n[red]{problem}[/red]\n")
        return 1

    code = service.offer_pairing()
    console.print()
    console.print(Panel(
        Text.from_markup(
            f"Message [bold]{number}[/bold] on WhatsApp and send:\n\n"
            f"      [bold accent]{code}[/bold accent]\n\n"
            f"That adds your number to the list this bot answers, and the code "
            f"stops working the moment it is used.\n\n"
            f"[dim]It expires in {settings.pair_window // 60} minutes. "
            f"Ctrl-C to give up.[/dim]"),
        title=" Pair a number ", title_align="left",
        border_style="accent", padding=(1, 2)))
    console.print()

    before = set(settings.allowed)
    service.announce = lambda line: console.print(f"  {line}")
    worker = threading.Thread(target=service.run, daemon=True)
    worker.start()

    try:
        while True:
            if set(config.whatsapp.allowed) != before:
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
    added = set(config.whatsapp.allowed) - before
    console.print(f"\n  [green]Paired.[/green] {', '.join(added)} may now "
                  f"talk to it.")
    console.print("  [bold]comodor whatsapp start --background[/bold] to run "
                  "it.\n")
    return 0


def _forget(console, config: Config, who: str) -> int:
    settings = config.whatsapp
    if who.lower() == "all":
        count = len(settings.allowed)
        settings.allowed = []
        _save(config)
        console.print(f"\n  Removed {count} number(s). It answers nobody now.\n")
        return 0

    from ..config import _digits

    wanted = _digits(who)
    kept = [x for x in settings.allowed if _digits(x) != wanted]
    if len(kept) == len(settings.allowed):
        console.print(f"\n  {who} was not on the list.\n")
        return 1
    settings.allowed = kept
    _save(config)
    console.print(f"\n  Removed {who}.\n")
    return 0


def _writes(console, config: Config, on: bool) -> int:
    config.whatsapp.allow_writes = on
    _save(config)
    console.print()
    if on:
        console.print("  A WhatsApp turn may now edit files and run commands, "
                      "[bold]asking first[/bold].")
        console.print("  [dim]Approving with a thumb is a decision made with "
                      "less attention than the same one at a keyboard.[/dim]\n")
    else:
        console.print("  WhatsApp turns read and plan only.\n")
    return 0


def _off(console, config: Config) -> int:
    config.whatsapp.enabled = False
    _save(config)
    console.print("\n  Switched off. The number and the pairings are kept.\n")
    return 0


def _start(console, config: Config, args: argparse.Namespace) -> int:
    from ..channels import WHATSAPP
    from .bot import Service

    ok, why = WHATSAPP.can_run(config)
    if not ok:
        console.print(f"\n  [red]{why}[/red]\n")
        return 1
    if not config.whatsapp.app_secret:
        console.print("\n  [red]No app secret, so no webhook can be "
                      "verified.[/red]")
        console.print("  [dim]comodor whatsapp connect --app-secret <secret>"
                      "[/dim]\n")
        return 1

    console.print()
    console.print(f"  Working in [bold]{config.paths.project}[/bold]")

    opened = None
    if getattr(args, "tunnel", False):
        from . import tunnel as tunnel_mod

        opened, why = tunnel_mod.start_quick(config.whatsapp.port,
                                             config.whatsapp.host)
        if opened is None:
            console.print(f"  [red]{why}[/red]\n")
            return 1
        where = opened.webhook(config.whatsapp.path)
        console.print(f"  Tunnel [bold]{where}[/bold]")
        if where != config.whatsapp.public_url:
            # A quick tunnel gets a new hostname every run and Meta keeps
            # delivering to the old one. Saying nothing here produces a bot
            # that starts cleanly and never receives anything.
            console.print("  [warn]This is not the address Meta has.[/warn] "
                          "Update the Callback URL in")
            console.print("  [dim]the dashboard, or make a named tunnel for "
                          "an address that does not move.[/dim]")
            config.whatsapp.public_url = where
            _save(config)

    service = Service(config, announce=lambda line: console.print(f"  {line}"))

    def bye(*_: object) -> None:
        console.print("\n  Stopping.\n")
        service.stop()
        if opened is not None:
            opened.stop()

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
    console.print("  [dim]stop: [/dim][bold]comodor whatsapp stop[/bold]")
    console.print("  [dim]to bring it back after a reboot: "
                  "[/dim][bold]comodor whatsapp service install[/bold]\n")
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
        console.print("  [dim]`comodor whatsapp start --background` still "
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
        console.print("  [bold]comodor whatsapp service show[/bold]"
                      "[dim]     read the unit before trusting it[/dim]")
        console.print("  [bold]comodor whatsapp service install[/bold]"
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
                      "[bold]comodor whatsapp service uninstall[/bold]")
    console.print()
    return 0 if ok else 1
