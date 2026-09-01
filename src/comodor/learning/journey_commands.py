"""`comodor journey` — what the brain has learned, in the order it happened.

Read-only by default; the one verb that changes anything (`remove`) follows
the curator's rules: disable or forget rather than destroy evidence.
"""

from __future__ import annotations

import argparse

from rich.panel import Panel
from rich.text import Text

from ..config import Config


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "journey", help="everything the brain has learned, oldest first")
    actions = parser.add_subparsers(dest="journey_action")

    actions.add_parser("show", help="the timeline (the default)")

    remove = actions.add_parser(
        "remove", help="retire one node, e.g. `remove rule:3`")
    remove.add_argument("node", help="a node id from the timeline, "
                                     "like lesson:12 or fact:4")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme,
                                         config.ui.ascii_borders, no_color=False)
    console = console_module.build(theme)
    verb = getattr(args, "journey_action", None) or "show"

    from . import journey
    from .store import BrainStore

    store = BrainStore(config.paths.brain_db)
    try:
        if verb == "remove":
            return _remove(console, journey, store, args.node)
        return _show(config, console, theme, journey, store)
    finally:
        store.close()


def _show(config, console, theme, journey, store) -> int:
    console.print(journey.render(journey.build(store), theme))
    return 0


def _remove(console, journey, store, node: str) -> int:
    done, said = journey.remove(store, node)
    style = "good" if done else "bad"
    console.print(Panel(Text(said, style=style), title="journey remove"))
    return 0 if done else 1
