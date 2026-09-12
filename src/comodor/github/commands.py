"""`comodor github` — connect an installation, see it, and take it away.

The connection is made here rather than from a chat or the web panel, and that
is the same rule the channels follow: granting something access to
repositories is a decision made at the machine, by whoever has it, not by
whoever reached the bot.
"""

from __future__ import annotations

import argparse

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "github", help="connect repositories on GitHub")
    actions = parser.add_subparsers(dest="github_action")

    actions.add_parser("connect", help="install the app on an account")
    actions.add_parser("status", help="what is connected, and what it may do")
    actions.add_parser("refresh", help="re-read permissions from GitHub")

    repos = actions.add_parser("repos", help="repositories the app can see")
    repos.add_argument("--account", default="",
                       help="only this account's installation")

    disconnect = actions.add_parser(
        "disconnect", help="forget an installation")
    disconnect.add_argument("account", nargs="?",
                            help="the account to forget; omit to be asked")

    writes = actions.add_parser(
        "writes", help="whether a turn may change a repository")
    writes.add_argument("state", choices=["on", "off"])


def run(config: Config, args: argparse.Namespace) -> int:
    from ..terminal import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)

    action = getattr(args, "github_action", "") or "status"
    if action == "connect":
        return _connect(console, config)
    if action == "status":
        return _status(console, config)
    if action == "refresh":
        return _refresh(console, config)
    if action == "repos":
        return _repos(console, config, getattr(args, "account", ""))
    if action == "disconnect":
        return _disconnect(console, config, getattr(args, "account", "") or "")
    if action == "writes":
        return _writes(console, config, args.state == "on")

    console.print("Nothing to do. Try `comodor github status`.")
    return 1


# --------------------------------------------------------------------------- #


def _link(url: str, label: str) -> Text:
    """A word that is the URL, rather than the URL printed as a word.

    An installation link is about two hundred and seventy characters of signed
    state. Printed, it wraps across four lines of an eighty-column terminal,
    pushes everything around it out of shape, and cannot be clicked anyway.
    OSC 8 — which Rich emits for a `link` style — makes the terminal treat a
    short label as the link, so it stays one line at every width and is still
    one click.

    Terminals that do not understand OSC 8 show the label and ignore the
    escape. That is why the URL is also copied to the clipboard, and why the
    fallback prints it in full when neither works: nobody may be left with a
    link they cannot reach.
    """
    return Text(label, style=f"bold link {url}")


def _offer_the_link(console, url: str, opened: bool) -> None:
    """Show the way to the page without printing the page's address at it.

    Three routes, best first, and the full URL appears at most once — never
    twice, which is what a "here it is, and here it is again in case" layout
    becomes on a narrow terminal.
    """
    from ..terminal import clipboard

    lines: list[Text] = [
        Text("Browser opened." if opened else "No browser could be opened."),
        Text(""),
        _link(url, "Open GitHub installation page"),
    ]

    copied = ""
    if not opened or clipboard.available():
        try:
            copied = clipboard.copy(url)
        except Exception:
            # `copy` raises with advice about installing a tool, and that
            # advice is beside the point here: the link is already open, or
            # about to be printed in full below. A clipboard that cannot be
            # reached must not be the thing that ends a connection.
            copied = ""

    if copied:
        lines += [Text(""),
                  Text("Installation link copied to clipboard.", style="dim")]
    elif not opened:
        # Nothing opened it and nothing can copy it, so the only way left is
        # to read it. Once, in its own block, where wrapping pushes nothing
        # else out of shape.
        lines += [Text(""),
                  Text("Copy this into a browser:", style="dim"),
                  Text(url, style="dim", overflow="fold")]

    lines += [Text(""),
              Text("Choose the account, then the repositories it may see. "
                   "GitHub then asks you to sign in once more — that step is "
                   "what proves the installation is yours.", style="dim")]

    # A Group rather than one joined Text. Joining flattens each piece into a
    # single Text with a single overflow policy, and the URL's `fold` is lost
    # with it — so the one line that must be readable in full gets cropped
    # instead, which is the opposite of what the fallback is for.
    console.print(Panel(Group(*lines), title=" Connect GitHub ",
                        title_align="left", border_style="accent"))


def _wait(console, connector, pending):
    """Wait for the browser to finish, and collect the result.

    The normal path. Nothing is pasted, nothing is read from the terminal, and
    the person does not run a second command — the browser finishes and this
    notices.
    """
    with console.status("Waiting for GitHub authorization…", spinner="dots"):
        return connector.wait_for(pending)


def _paste(console, connector, pending):
    """The older flow, for a Worker that cannot hold a result.

    Kept because a deployment can be behind this client, and being handed a
    receipt with nowhere to put it is worse than being asked for one.
    """
    console.print()
    console.print("That page will show one line. Paste it here — it says "
                  "which installation was confirmed, signed so it cannot be "
                  "altered.", style="dim")
    console.print()
    try:
        receipt = input("Paste the line from that page: ").strip()
    except EOFError:
        raise KeyboardInterrupt from None
    return connector.collect(pending, receipt)


def _connect(console, config: Config) -> int:
    from .connect import ConnectError, Connector

    connector = Connector(config)
    console.print()
    console.print("Starting a GitHub connection…")

    try:
        pending = connector.begin()
    except ConnectError as problem:
        console.print(Panel(Text(str(problem)), title=" Could not start ",
                            title_align="left", border_style="yellow"))
        return 1

    opened = connector.open(pending)
    console.print()
    _offer_the_link(console, pending.url, opened)

    try:
        installation = (_wait(console, connector, pending) if pending.automatic
                        else _paste(console, connector, pending))
    except KeyboardInterrupt:
        # Nothing was written, because nothing is written until a result has
        # been checked. The browser may still finish; the result expires
        # unclaimed, and a result nobody claimed grants nobody anything.
        console.print()
        console.print("Nothing was connected.")
        return 1
    except ConnectError as problem:
        console.print()
        console.print(Panel(Text(str(problem)), title=" Not connected ",
                            title_align="left", border_style="yellow"))
        return 1

    config.github.remember(installation)
    config.github.enabled = True
    _save(config)

    console.print()
    console.print(Panel(
        Text.from_markup(
            f"Connected to [bold]{installation.account_login}[/bold] "
            f"({installation.account_type.lower()}).\n\n"
            + ("Every repository on that account, including new ones."
               if installation.repository_selection == "all"
               else "The repositories you selected.")
            + "\n\nTurns read repositories now. "
              "[bold]comodor github writes on[/bold] lets them open pull "
              "requests as well."),
        title=" Connected ", title_align="left", border_style="green"))
    return 0


def _status(console, config: Config) -> int:
    settings = config.github
    console.print()

    if not settings.installations:
        console.print(Panel(
            Text.from_markup(
                "No GitHub account is connected.\n\n"
                "[bold]comodor github connect[/bold] installs the app on an "
                "account and asks which repositories it may see.\n\n"
                "Nothing else needs it: a repository checked out here works "
                "with no connection at all."),
            title=" GitHub ", title_align="left", border_style="accent"))
        return 0

    table = Table(box=None, pad_edge=False)
    table.add_column("Account")
    table.add_column("Kind")
    table.add_column("Repositories")
    table.add_column("May")

    unusable = []
    organisations = []
    for one in settings.installations:
        may = ", ".join(sorted(
            f"{name}:{level}" for name, level in one.permissions.items()))
        table.add_row(one.account_login, one.account_type.lower(),
                      "all" if one.repository_selection == "all" else "selected",
                      may or "—")
        # A record whose grant or key is missing reads as connected and fails
        # at the first request. Said here, rather than discovered in the
        # middle of a turn.
        if not one.usable or not _has_key(config, one.installation_id):
            unusable.append(one.account_login or str(one.installation_id))
        elif one.account_type == "Organization":
            organisations.append(one.account_login)

    console.print(table)
    console.print()

    if unusable:
        console.print(Panel(
            Text.from_markup(
                f"[bold]{', '.join(unusable)}[/bold] cannot be used.\n\n"
                f"Either this machine no longer holds the key that proves the "
                f"connection is its own, or the connection predates a security "
                f"fix and cannot be checked against your current access. "
                f"Nothing is wrong on GitHub.\n\n"
                f"[bold]comodor github connect[/bold] establishes a new one."),
            title=" Needs reconnecting ", title_align="left",
            border_style="yellow"))
        console.print()

    if organisations:
        # Said here rather than discovered at the first refusal. Losing owner
        # rights is not a failure of anything on this machine, and somebody
        # whose connection stops working should already know why it might.
        console.print(
            f"An organisation connection ({', '.join(organisations)}) keeps "
            f"working only while the account that made it is still an owner "
            f"there. That is checked with GitHub every time, not remembered "
            f"from when you connected.")
        console.print()
    console.print(
        f"Turns may {'change' if settings.allow_writes else 'read'} "
        f"repositories. Changes open a pull request from a "
        f"{settings.branch_prefix}… branch; nothing is pushed to a default "
        f"branch.")
    return 0


def _has_key(config: Config, installation_id: int) -> bool:
    """Whether the private key for this connection is still on this machine.

    The grant alone is not an identity - it is a public statement that would
    survive being copied out of a config file. The key is the half that
    matters, and it lives outside the config, so it can go missing on its own.
    """
    from . import identity
    try:
        identity.load(config.paths.user, installation_id)
    except identity.IdentityError:
        return False
    return True


def _refresh(console, config: Config) -> int:
    """Ask GitHub what each installation is now.

    Permissions change: somebody narrows an installation, or accepts a new
    one the app asked for. A stale record refuses operations that would work,
    or attempts ones that will not.
    """
    from .connect import ConnectError, Connector

    if not config.github.installations:
        console.print("Nothing is connected.")
        return 1

    connector = Connector(config)
    changed = 0
    for one in list(config.github.installations):
        try:
            fresh = connector.verify(one.installation_id)
        except ConnectError as problem:
            console.print(f"{one.account_login}: {problem}")
            continue

        if fresh is None:
            config.github.forget(one.installation_id)
            console.print(f"{one.account_login}: the installation is gone; "
                          f"forgotten here too.")
            changed += 1
            continue

        config.github.remember(fresh)
        changed += 1

    if changed:
        _save(config)
    console.print(f"{changed} updated.")
    return 0


def _repos(console, config: Config, account: str) -> int:
    from .api import GitHub, GitHubError
    from .connect import Connector
    from .repos import Repositories

    if not config.github.installations:
        console.print("Nothing is connected.")
        return 1

    repositories = Repositories(config, Connector(config).mint)
    wanted = (account or "").strip().lower()
    shown = 0

    for one in config.github.installations:
        if wanted and one.account_login.lower() != wanted:
            continue
        ident = one.installation_id

        def token(ident=ident):
            return repositories.tokens.for_installation(ident)

        try:
            found = GitHub(token).repositories()
        except GitHubError as problem:
            console.print(f"{one.account_login}: {problem}")
            continue

        console.print()
        console.print(f"[bold]{one.account_login}[/bold] — {len(found)}")
        for repo in found:
            private = " (private)" if repo.get("private") else ""
            console.print(f"  {repo.get('full_name')}{private}")
        shown += 1

    if not shown:
        console.print(f"No installation for {account!r}.")
        return 1
    return 0


def _disconnect(console, config: Config, account: str) -> int:
    from .connect import Connector

    settings = config.github
    if not settings.installations:
        console.print("Nothing is connected.")
        return 1

    wanted = (account or "").strip().lower()
    if not wanted:
        console.print("Which account? One of: " + ", ".join(
            one.account_login for one in settings.installations))
        return 1

    found = settings.find(wanted)
    if found is None:
        console.print(f"No installation for {account!r}.")
        return 1

    Connector(config).disconnect(found.installation_id)
    settings.forget(found.installation_id)
    if not settings.installations:
        settings.enabled = False
    _save(config)

    console.print()
    console.print(Panel(
        Text.from_markup(
            f"{found.account_login} is disconnected here.\n\n"
            "The app may still be installed on GitHub. Remove it at "
            "[bold]github.com/settings/installations[/bold] to revoke its "
            "access as well — this only forgets it on this machine."),
        title=" Disconnected ", title_align="left", border_style="green"))
    return 0


def _writes(console, config: Config, on: bool) -> int:
    config.github.allow_writes = on
    _save(config)
    console.print()
    if on:
        console.print(Panel(
            Text(
                "Turns may now change repositories on GitHub.\n\n"
                "Every change goes to a branch and a pull request — nothing "
                "is committed to a default branch, and nothing is merged. A "
                "pull request opened by mistake is public, which is why this "
                "is off by default."),
            title=" Writes are on ", title_align="left", border_style="yellow"))
    else:
        console.print(Panel(
            Text("Turns read repositories and change nothing."),
            title=" Writes are off ", title_align="left", border_style="green"))
    return 0


def _save(config: Config) -> None:
    from .. import config as config_mod

    config_mod.save_user_config(config)
