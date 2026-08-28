"""`comodor local` — pick a model, fetch it, run without a network.

The download is the part that needs care in a terminal. It is four gigabytes
over somebody's home line, which is long enough that a still cursor reads as a
hang, so it draws a real bar with the four numbers that answer the question
being asked: how far, how fast, how much left, how long.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table
from rich.text import Text

from ..config import Config
from . import (
    BadCatalogue,
    DownloadFailed,
    Model,
    fetch,
    find_binary,
    human_bytes,
    load,
    memory_gb,
    store_for,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "local", help="run a model on this machine, with no network")
    actions = parser.add_subparsers(dest="local_action")

    listing = actions.add_parser("list", help="models you can run, and what is here")
    listing.add_argument("--all", action="store_true",
                         help="include ones this machine cannot run")

    get = actions.add_parser("get", help="download a model")
    get.add_argument("model", nargs="?", help="a model id, or omit to choose")
    get.add_argument("--yes", action="store_true", help="do not ask first")

    remove = actions.add_parser("remove", help="delete a downloaded model")
    remove.add_argument("model", nargs="?", help="a model id, or omit to choose")

    use = actions.add_parser("use", help="make a downloaded model the active one")
    use.add_argument("model", nargs="?", help="a model id, or omit to choose")

    actions.add_parser("where", help="where the files are kept")


def run(config: Config, args: argparse.Namespace) -> int:
    console = Console()
    action = getattr(args, "local_action", None) or "list"

    try:
        catalogue = load(Path(config.paths.user), allow_network=True)
    except (BadCatalogue, OSError) as problem:
        console.print(f"[red]The model list could not be read:[/red] {problem}")
        return 1

    store = store_for(Path(config.paths.user))

    if action == "list":
        return _list(console, catalogue, store, show_all=getattr(args, "all", False))
    if action == "where":
        from .catalogue import bundled_path, yours_path

        mine = yours_path(Path(config.paths.user))
        console.print()
        console.print(f"  Models      {store.root}")
        used = store.bytes_used()
        console.print(f"              {human_bytes(used)} used" if used
                      else "              nothing downloaded yet")
        console.print()
        console.print(f"  Your list   {mine}")
        console.print(Text(
            "              " + ("edit this to add or change models"
                                 if mine.is_file() else
                                 "does not exist yet — create it to add your own"),
            style="dim"))
        console.print(f"  Shipped     {bundled_path()}")
        console.print(Text("              replaced on every upgrade; edit yours "
                           "instead", style="dim"))
        console.print()
        return 0
    if action == "get":
        return _get(console, config, catalogue, store, args)
    if action == "remove":
        return _remove(console, catalogue, store, args)
    if action == "use":
        return _use(console, config, catalogue, store, args)

    console.print("Try `comodor local list`.")
    return 1


# --------------------------------------------------------------------------- #
# listing
# --------------------------------------------------------------------------- #


def _list(console: Console, catalogue, store, *, show_all: bool) -> int:
    ram = memory_gb()

    table = Table(box=None, pad_edge=False, header_style="bold")
    table.add_column("")
    table.add_column("Model")
    table.add_column("Size", justify="right")
    table.add_column("Context", justify="right")
    table.add_column("Needs", justify="right")
    table.add_column("")

    shown = 0
    for model in catalogue:
        fits = model.fits(ram)
        if fits is False and not show_all:
            continue
        shown += 1
        held = store.have(model)
        partial = store.partial_bytes(model)

        if held and held.complete:
            mark, style = "●", "green"
        elif partial:
            mark, style = "◐", "yellow"
        else:
            mark, style = "○", "dim"

        note = ""
        if held and held.complete:
            note = "downloaded"
        elif partial:
            note = f"{partial / model.size * 100:.0f}% downloaded"
        elif fits is False:
            note = "too big for this machine"

        table.add_row(
            Text(mark, style=style),
            Text(model.id, style="bold" if held else ""),
            f"{model.gigabytes:.1f} GB",
            f"{model.context:,}" if model.context else "—",
            f"{model.needs_ram_gb:g} GB" if model.needs_ram_gb else "—",
            Text(note, style="green" if note == "downloaded" else "dim"),
        )

    console.print()
    console.print(table)
    console.print()

    hidden = len(catalogue) - shown
    bits = []
    if ram:
        bits.append(f"this machine has {ram:.0f} GB")
    if hidden and not show_all:
        bits.append(f"{hidden} hidden as too large — `--all` to see them")
    bits.append(f"list from {catalogue.source}")
    console.print(Text("  " + " · ".join(bits), style="dim"))

    if find_binary() is None:
        console.print()
        console.print(Panel(
            Text.from_markup(
                "No llama.cpp server was found, so a downloaded model cannot be "
                "run yet.\n\n"
                "  [bold]macOS[/bold]    brew install llama.cpp\n"
                "  [bold]Linux[/bold]    from github.com/ggml-org/llama.cpp\n"
                "  [bold]Windows[/bold]  winget install llama.cpp\n\n"
                "Comodor will also use Ollama or LM Studio if either is running."),
            title=" One thing missing ", title_align="left",
            border_style="yellow", padding=(1, 2)))
    console.print()
    return 0


# --------------------------------------------------------------------------- #
# downloading
# --------------------------------------------------------------------------- #


def _choose(console: Console, catalogue, store, *, only_downloaded: bool = False):
    """Ask which model, when the command did not name one."""
    from ..ui.chooser import choose

    options = []
    for model in catalogue:
        held = store.have(model)
        if only_downloaded and not (held and held.complete):
            continue
        state = "downloaded" if held and held.complete else f"{model.gigabytes:.1f} GB"
        options.append((model.id, f"{model.name} — {state}"))

    if not options:
        console.print("Nothing to choose from.")
        return None
    picked = choose("Which model?", options)
    return catalogue.get(picked) if picked else None


def _get(console: Console, config: Config, catalogue, store,
         args: argparse.Namespace) -> int:
    model = catalogue.get(args.model) if args.model else _choose(console, catalogue, store)
    if model is None:
        if args.model:
            console.print(f"[red]No model called[/red] {args.model!r}. "
                          f"Try `comodor local list`.")
            return 1
        return 0

    held = store.have(model)
    if held and held.complete:
        console.print(f"  {model.name} is already here: {held.path}")
        return 0

    ram = memory_gb()
    if model.fits(ram) is False:
        console.print(Panel(
            Text(f"{model.name} wants about {model.needs_ram_gb:g} GB and this "
                 f"machine has {ram:.0f} GB.\n\nIt will download and then fail "
                 f"to load. A smaller model is on the list."),
            title=" Too large for this machine ", title_align="left",
            border_style="red", padding=(1, 2)))
        if not args.yes:
            return 1

    if store.room_for(model) is False:
        free = store.free_bytes() or 0
        console.print(f"[red]Not enough disk.[/red] {model.name} needs "
                      f"{model.gigabytes:.1f} GB and {human_bytes(free)} is free.")
        return 1

    resuming = store.partial_bytes(model)
    console.print()
    console.print(f"  [bold]{model.name}[/bold]  {model.gigabytes:.1f} GB"
                  + (f"  (resuming from {resuming / model.size * 100:.0f}%)"
                     if resuming else ""))
    if model.description:
        console.print(Text(f"  {model.description}", style="dim"))
    console.print(Text(f"  {model.url}", style="dim"))
    console.print()

    columns = (
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=None),
        TextColumn("{task.percentage:>5.1f}%"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(compact=True),
    )

    stopped = False
    with Progress(*columns, console=console, transient=False) as bar:
        task = bar.add_task(model.id, total=model.size)

        def watch(progress) -> None:
            bar.update(task, completed=progress.done, total=progress.total)

        try:
            path = fetch(model.url, store.path_for(model),
                         expect_size=model.size, expect_sha256=model.sha256,
                         watch=watch)
        except KeyboardInterrupt:
            stopped = True
            path = None
        except DownloadFailed as problem:
            console.print(f"\n[red]{problem}[/red]")
            return 1

    if stopped:
        kept = store.partial_bytes(model)
        console.print(f"\n  Stopped. {human_bytes(kept)} kept — "
                      f"`comodor local get {model.id}` continues from there.")
        return 130

    console.print(f"\n  [green]Verified[/green] against its checksum: {path}")

    if find_binary() is None:
        console.print(Text(
            "\n  A llama.cpp server is still needed to run it — "
            "`comodor local list` says how.", style="yellow"))
        return 0

    _activate(console, config, model)
    return 0


# --------------------------------------------------------------------------- #
# the rest
# --------------------------------------------------------------------------- #


def _remove(console: Console, catalogue, store, args: argparse.Namespace) -> int:
    model = (catalogue.get(args.model) if args.model
             else _choose(console, catalogue, store, only_downloaded=True))
    if model is None:
        return 0 if not args.model else 1
    if store.remove(model):
        console.print(f"  Deleted {model.name}.")
    else:
        console.print(f"  {model.name} was not here.")
    return 0


def _use(console: Console, config: Config, catalogue, store,
         args: argparse.Namespace) -> int:
    model = (catalogue.get(args.model) if args.model
             else _choose(console, catalogue, store, only_downloaded=True))
    if model is None:
        return 0 if not args.model else 1

    held = store.have(model)
    if not (held and held.complete):
        console.print(f"  {model.name} is not downloaded. "
                      f"`comodor local get {model.id}` first.")
        return 1
    _activate(console, config, model)
    return 0


def _activate(console: Console, config: Config, model: Model) -> None:
    """Make this the model the agent uses.

    The base URL is left empty on purpose. The port a local server listens on
    is decided when it starts, so writing one into the config would record a
    number that is wrong the next time.
    """
    from .. import config as config_mod

    entry = config.use("local", model=model.id)
    entry.label = "Local"
    entry.configured = True
    config_mod.save_user_config(config)
    console.print(f"  [green]Now using[/green] {model.name}, on this machine.")
    _ = time  # kept for the timing hooks the web side reuses
