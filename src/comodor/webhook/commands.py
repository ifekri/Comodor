"""`comodor webhook` — subscribe external systems to the agent.

One command per verb, mirroring the other channels' CLIs. `add` generates
the shared secret and prints the curl line that proves it works; nobody
should have to guess what a valid delivery looks like before wiring one up.
"""

from __future__ import annotations

import argparse

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "webhook", help="let external systems hand the agent work")
    actions = parser.add_subparsers(dest="webhook_action")

    add = actions.add_parser("add", help="subscribe one system")
    add.add_argument("name", help="a name for it, e.g. ci")
    add.add_argument("--path", required=True,
                     help="the path it posts to, e.g. /ci")
    add.add_argument("--template", required=True,
                     help="the prompt; {payload} is the body, {.field.path} "
                          "picks one value")
    add.add_argument("--reply-url", help="where the finished answer is POSTed")
    add.add_argument("--allow-writes", action="store_true",
                     help="let this subscription's turns edit files and run "
                          "commands (default: plan only)")

    actions.add_parser("list", help="the subscriptions, and recent events")
    remove = actions.add_parser("remove", help="forget one subscription")
    remove.add_argument("name")

    actions.add_parser("serve", help="run it here, in this terminal")
    start = actions.add_parser("start", help="run it detached from this terminal")
    # The daemon relaunches with exactly this spelling, so the child runs in
    # the foreground and the parent returns as soon as it is up.
    start.add_argument("--foreground", action="store_true",
                       help="run here, not detached (used by --background)")
    start.add_argument("--background", "-b", action="store_true",
                       dest="background", default=True)
    actions.add_parser("stop", help="stop a detached one")

    test = actions.add_parser("test", help="send one signed event to a running "
                                           "server")
    test.add_argument("path", help="which subscription to hit, e.g. /ci")
    test.add_argument("--data", default='{"hello": "world"}', help="JSON to send")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    action = getattr(args, "webhook_action", None) or "list"

    if action == "add":
        return _add(console, config, args)
    if action == "remove":
        return _remove(console, config, args)
    if action == "test":
        return _test(console, config, args)
    if action == "serve":
        from .server import run as run_server

        return run_server(config, args)
    if action == "start":
        if getattr(args, "foreground", False):
            from .server import run as run_server

            return run_server(config, args)
        return _background(console, config)
    if action == "stop":
        return _stop(console, config)

    return _list(console, config)


def _channel():
    from ..channels import Channel

    return Channel(name="webhook", label="Webhook", section="webhook",
                   ready=lambda cfg: (True, ""))


def _background(console, config: Config) -> int:
    from ..channels import daemon

    config.webhook.enabled = True
    ok, why = daemon.start(config, _channel())
    console.print()
    if not ok:
        console.print(f"  [red]{why}[/red]\n")
        return 1
    console.print(f"  [green]{why}[/green]")
    console.print(f"  [dim]log:  {daemon.log_file(config, _channel())}[/dim]")
    console.print("  [dim]stop: [/dim][bold]comodor webhook stop[/bold]\n")
    return 0


def _stop(console, config: Config) -> int:
    from ..channels import daemon

    ok, why = daemon.stop(config, _channel())
    console.print()
    console.print(f"  {why}\n" if ok else f"  [dim]{why}[/dim]\n")
    return 0 if ok else 1


def _add(console, config: Config, args: argparse.Namespace) -> int:
    from .subs import Sub, a_secret, load

    path = args.path if args.path.startswith("/") else f"/{args.path}"
    subs = load(config)
    if subs.by_path(path) is not None:
        console.print(f"\n  [red]{path} is already subscribed.[/red] "
                      "Remove it first, or pick another path.\n")
        return 1

    secret = a_secret()
    subs.add(Sub(name=args.name, path=path, secret=secret,
                 template=args.template, reply_url=args.reply_url or "",
                 allow_writes=bool(args.allow_writes)))

    console.print()
    console.print(Panel(Text.from_markup(
        f"[bold]{args.name}[/bold] listens on [bold]{path}[/bold]\n\n"
        f"Shared secret (shown once; it is in the subscriptions file too):\n"
        f"  [bold accent]{secret}[/bold accent]\n\n"
        "The sender signs the raw body with HMAC-SHA256 and puts the\n"
        "hex digest in X-Comodor-Signature-256, like so:\n\n"
        f'  hex=$(printf \'%s\' \'<body>\' | openssl dgst -sha256 \\\n'
        f'        -hmac \'{secret}\' | awk \'{{print $2}}\')\n'
        f'  curl -X POST http://127.0.0.1:{config.webhook.port}{path} \\\n'
        f'    -H "X-Comodor-Signature-256: sha256=$hex" \\\n'
        f"    -d '<body>'"),
        title=" Subscribed ", title_align="left",
        border_style="accent", padding=(1, 2)))
    if not args.allow_writes:
        console.print("  [dim]Plan mode only — pass --allow-writes to let "
                      "these turns edit files.[/dim]")
    console.print()
    return 0


def _remove(console, config: Config, args: argparse.Namespace) -> int:
    from .subs import load

    if load(config).remove(args.name):
        console.print(f"\n  Removed {args.name}.\n")
        return 0
    console.print(f"\n  No subscription called {args.name}.\n")
    return 1


def _list(console, config: Config) -> int:
    from .subs import load

    subs = load(config).load()
    console.print()
    if not subs:
        console.print("  Nothing subscribed yet. "
                      "[bold]comodor webhook add[/bold] to add one.\n")
        return 0

    table = Table(box=None, pad_edge=False, show_header=True)
    table.add_column("Name", style="bold")
    table.add_column("Path")
    table.add_column("Writes")
    table.add_column("Replies to")
    for sub in subs:
        table.add_row(sub.name, sub.path,
                      "yes" if sub.allow_writes else "no",
                      sub.reply_url or "—")
    console.print(table)
    console.print()
    return 0


def _test(console, config: Config, args: argparse.Namespace) -> int:
    from ..net.http import post
    from .subs import load

    subs = load(config)
    sub = subs.by_path(args.path if args.path.startswith("/")
                       else f"/{args.path}")
    if sub is None:
        console.print(f"\n  Nothing listens on {args.path}.\n")
        return 1

    import hashlib
    import hmac as hmac_mod

    body = args.data.encode("utf-8")
    digest = hmac_mod.new(sub.secret.encode("utf-8"), body,
                          hashlib.sha256).hexdigest()
    try:
        answer = post(f"http://127.0.0.1:{config.webhook.port}{sub.path}",
                      data=body, timeout=10.0,
                      headers={"X-Comodor-Signature-256": f"sha256={digest}",
                               "Content-Type": "application/json"})
        console.print(f"\n  {answer.status_code}: {answer.text.strip()}\n")
        return 0 if answer.ok else 1
    except Exception as problem:
        console.print(f"\n  [red]{problem}[/red] — is the server running? "
                      "[bold]comodor webhook start -b[/bold]\n")
        return 1
