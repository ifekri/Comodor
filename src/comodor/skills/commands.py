"""`comodor skills` — browse the library, fetch what you want, keep it current.

The list is a list, and the interesting column is the one saying what is
already on this machine. Somebody running this has one of three questions —
what is there, is this one installed, has it moved since I installed it — and
all three are answered by the same table.

Nothing downloads without being named. `add` takes ids; there is no `add all`,
because a library is a place to take one thing from.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import Config
from . import catalogue as library


def register(sub: argparse._SubParsersAction) -> None:
    parent = sub.add_parser("skills", help="browse and install skills")
    actions = parent.add_subparsers(dest="action")

    browse = actions.add_parser("browse", help="what is available, and what you have")
    browse.add_argument("search", nargs="?", default="",
                        help="only entries matching this")
    browse.add_argument("--refresh", action="store_true",
                        help="ignore the cache and ask the server")

    add = actions.add_parser("add", help="download one or more skills")
    add.add_argument("ids", nargs="+", metavar="id")
    add.add_argument("--force", action="store_true",
                     help="replace a skill of the same name that you wrote")

    drop = actions.add_parser("remove", help="delete an installed skill")
    drop.add_argument("ids", nargs="+", metavar="id")

    actions.add_parser("update", help="refetch anything whose version has moved")
    actions.add_parser("list", help="what is installed on this machine")


def run(config: Config, args: argparse.Namespace) -> int:
    from ..ui import console as console_module

    theme = console_module.prepare_theme(config.ui.theme, config.ui.ascii_borders,
                                         no_color=False)
    console = console_module.build(theme)
    root = config.paths.skills
    action = getattr(args, "action", None) or "browse"

    if action == "list":
        return _list(console, theme, root)

    try:
        catalogue = library.fetch(
            config.skills.catalogue_url,
            cache_root=config.paths.user,
            force=getattr(args, "refresh", False),
        )
    except library.CatalogueError as error:
        console.print(f"\n  [bad]{error}[/bad]\n")
        return 1

    if catalogue.stale:
        console.print(f"\n  [warn]offline — showing a copy from "
                      f"{_ago(catalogue.age)}[/warn]")

    if action == "browse":
        return _browse(console, theme, catalogue, root, getattr(args, "search", ""))
    if action == "add":
        return _add(console, theme, catalogue, root, args.ids,
                    force=getattr(args, "force", False))
    if action == "remove":
        return _remove(console, theme, root, args.ids)
    if action == "update":
        return _update(console, theme, catalogue, root)
    return _browse(console, theme, catalogue, root, "")


# --------------------------------------------------------------------------- #


def _browse(console, theme, catalogue: library.Catalogue, root: Path,
            search: str) -> int:
    from rich.table import Table

    entries = catalogue.search(search)
    if not entries:
        console.print(f"\n  nothing matches [accent]{search}[/accent]\n")
        return 1

    # The description is what somebody is reading; everything else is
    # navigation. So the widths come from the terminal rather than from the
    # data, and the description takes what is left.
    #
    # Sized from the data, this collapsed the moment the catalogue grew: the id
    # column claimed the longest id there was, the tags column would not wrap,
    # and the description got the remainder — which at a hundred and forty-seven
    # skills was two characters, printing every word down the screen one letter
    # at a time.
    room = max(40, console.width - 4)
    longest = max(len(entry.id) for entry in entries)
    names = min(longest, max(14, room // 4))
    tags = 0 if room < 70 else min(22, room // 5)
    words = max(20, room - names - tags - 5)

    table = Table.grid(padding=(0, 1))
    table.add_column(width=1)
    table.add_column(width=names, no_wrap=True, overflow="ellipsis")
    table.add_column(width=words, no_wrap=True, overflow="ellipsis")
    if tags:
        table.add_column(width=tags, justify="right", no_wrap=True,
                         overflow="ellipsis")

    for entry in entries:
        state = library.installed(root, entry.id)
        if not state.present:
            mark, style = "", "dim"
        elif not state.managed:
            # Same name, not from here. Saying "update available" about
            # somebody's own file is how they end up losing it.
            mark, style = theme.glyphs.dot, "dim"
        elif state.version != entry.version:
            mark, style = theme.glyphs.rise, "warn"
        else:
            mark, style = theme.glyphs.check, "good"

        # One line each. A catalogue is scanned rather than read, and four
        # hundred characters of description per row for a hundred and
        # forty-seven of them is a wall nobody reaches the bottom of — the
        # whole text is one `comodor skills add` away.
        row = [
            f"[{style}]{mark}[/{style}]",
            f"[value]{entry.id}[/value]",
            " ".join(entry.description.split()),
        ]
        if tags:
            row.append(f"[dim]{' '.join(entry.tags)}[/dim]")
        table.add_row(*row)

    console.print(f"\n[title]Skills[/title]  [dim]{len(entries)} of "
                  f"{len(catalogue.skills)} · {catalogue.updated}[/dim]\n")
    console.print(table)
    console.print(f"\n  [dim]{theme.glyphs.check} installed   "
                  f"{theme.glyphs.rise} an update is available[/dim]")
    console.print("  [dim]comodor skills add <id>[/dim]\n")
    return 0


def _add(console, theme, catalogue: library.Catalogue, root: Path,
         ids: list[str], force: bool = False) -> int:
    root.mkdir(parents=True, exist_ok=True)
    failures = 0
    console.print("")

    for skill_id in ids:
        entry = catalogue.get(skill_id)
        if entry is None:
            console.print(f"  [bad]no skill called {skill_id}[/bad]")
            failures += 1
            continue
        try:
            library.install(entry, catalogue, root, force=force)
        except library.CatalogueError as error:
            console.print(f"  [bad]{skill_id}[/bad]  [dim]{error}[/dim]")
            failures += 1
            continue
        console.print(f"  [good]{theme.glyphs.check}[/good] {skill_id} "
                      f"[dim]{entry.version} → {root / skill_id}[/dim]")

    console.print("")
    return 1 if failures else 0


def _remove(console, theme, root: Path, ids: list[str]) -> int:
    console.print("")
    missing = 0
    for skill_id in ids:
        if library.remove(root, skill_id):
            console.print(f"  [good]removed[/good] [dim]{root / skill_id}[/dim]")
        else:
            console.print(f"  [dim]{skill_id} is not installed[/dim]")
            missing += 1
    console.print("")
    return 1 if missing else 0


def _update(console, theme, catalogue: library.Catalogue, root: Path) -> int:
    """Refetch the ones that have moved, and say so when none have."""
    behind = []
    for entry in catalogue.skills:
        state = library.installed(root, entry.id)
        # Only what this program installed. A folder without a stamp is the
        # user's, whatever it happens to be called.
        if state.managed and state.version != entry.version:
            behind.append(entry)

    if not behind:
        console.print("\n  [good]every installed skill is current.[/good]\n")
        return 0
    return _add(console, theme, catalogue, root, [entry.id for entry in behind])


def _list(console, theme, root: Path) -> int:
    """What is on the machine — including anything written by hand.

    Read off the disk rather than out of the catalogue, because a skill written
    locally is as real as a downloaded one and would otherwise be invisible.
    """
    from rich.padding import Padding

    from .registry import SkillRegistry

    registry = SkillRegistry()
    # The project folder is deliberately excluded: this command is about what
    # is on the machine, and a project skill belongs to the repository it is
    # committed in rather than to the user.
    registry.discover(root, root)
    found = registry.all()
    if not found:
        console.print(f"\n  nothing in [dim]{root}[/dim]\n"
                      "  [dim]comodor skills browse[/dim]\n")
        return 0

    console.print(f"\n[title]Installed[/title]  [dim]{root}[/dim]\n")
    for skill in found:
        # By the folder it was downloaded into, not by the name it calls
        # itself. The two are often different — a skill in `brutalist/` may
        # announce itself as `industrial-brutalist-ui` — and looking the stamp
        # up by the declared name simply misses, so a skill this program
        # installed shows no version and reads as one the user wrote by hand.
        state = library.installed(root, _folder_of(skill, root))
        version = f"  [dim]{state.version}[/dim]" if state.version else ""
        console.print(f"  [value]{skill.name}[/value]{version}")
        # Padding rather than a leading "    ", so the second line of a long
        # description lands under the first instead of back at the margin.
        console.print(Padding(f"[dim]{_trim(skill.description)}[/dim]",
                              (0, 0, 0, 4)))
    console.print("")
    return 0


#: How much of a skill's own description belongs in a list of skills. Some run
#: to a full paragraph, and a paragraph an entry is not a list.
DESCRIPTION_CHARS = 150


def _folder_of(skill, root: Path) -> str:
    """The directory a skill lives in, which is what an id names."""
    if skill.root is not None:
        return skill.root.name
    if skill.path is not None and skill.path.parent != root:
        return skill.path.parent.name
    return skill.name


def _trim(text: str) -> str:
    """One paragraph of prose, cut to a line or two, on a word."""
    text = " ".join((text or "").split())
    if len(text) <= DESCRIPTION_CHARS:
        return text
    return text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _ago(seconds: float) -> str:
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"
