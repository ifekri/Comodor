"""Agreeing on which directory this is about, before anything reads it.

Comodor works out its own project root: it walks up from where you started it
until it finds a `.git`, a `pyproject.toml`, a `package.json` — whichever marker
comes first. That is almost always the right answer and occasionally a
surprising one. Start it from a subdirectory of a monorepo and the root is the
monorepo; start it in your home directory by accident and the root is your home
directory, which is where it will then read files, take checkpoints and write.

None of that is dangerous by itself — writes still ask, and the workspace guard
refuses to touch anything outside the root — but "outside the root" is only a
useful boundary if you know where the root is. So it is shown, once per folder,
and confirmed before the agent exists.

Once. A prompt that appears every single time is a prompt people learn to
dismiss without reading, which is worse than not asking: it trains the reflex
that gets used on the one occasion it mattered. The answer is remembered in
`safety.trusted_folders`, and only the exact directory is remembered — approving
`~/work/api` does not quietly approve `~/work`.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.text import Text

from .config import Config
from .ui import chooser
from .ui.theme import Theme


def is_trusted(config: Config, root: Path) -> bool:
    """Has this exact directory been approved before?"""
    resolved = str(Path(root).resolve())
    return any(_same(entry, resolved) for entry in config.safety.trusted_folders)


def trust(config: Config, root: Path) -> None:
    """Remember it, and write it down."""
    resolved = str(Path(root).resolve())
    if not is_trusted(config, root):
        config.safety.trusted_folders.append(resolved)
        try:
            config.save()
        except Exception:
            # An unwritable config costs a second prompt next time, which is a
            # long way from a reason to refuse to start.
            pass


def _same(a: str, b: str) -> bool:
    # Windows paths differ in case and nowhere else; POSIX ones do not.
    import sys

    return a.lower() == b.lower() if sys.platform == "win32" else a == b


def describe(root: Path) -> str:
    """What is in there, in one line, so the path is not the only evidence."""
    parts: list[str] = []
    if (root / ".git").exists():
        parts.append("a git repository")
    try:
        entries = list(root.iterdir())
        visible = [entry for entry in entries if not entry.name.startswith(".")]
        files = sum(1 for entry in visible if entry.is_file())
        folders = sum(1 for entry in visible if entry.is_dir())
        parts.append(f"{files} file{'s' if files != 1 else ''}, "
                     f"{folders} folder{'s' if folders != 1 else ''}")
    except OSError as error:
        parts.append(f"unreadable: {error.strerror or error}")

    if root == Path.home():
        # Worth saying plainly. It is the one root that is almost never meant.
        parts.append("this is your home directory")
    return " · ".join(parts)


def confirm(config: Config, console: Console, theme: Theme,
            cwd: Path | None = None) -> Path | None:
    """Settle the workspace. Returns it, or None if the user would rather not.

    Returns immediately for a directory that has been approved before, and for
    anywhere there is no terminal to ask in — a piped or scripted run has
    already said what it wants by being scripted, and a question nobody can
    answer is a hang.
    """
    root = Path(config.paths.project)
    here = Path(cwd or Path.cwd()).resolve()

    if is_trusted(config, root):
        return root
    if not chooser.interactive(console):
        return root

    console.print()
    console.print(Text.assemble(
        ("  Comodor will work in", theme.style("dim")),
    ))
    console.print(Text.assemble(
        ("  ", ""),
        (str(root), theme.style("accent", bold=True)),
    ))
    console.print(Text(f"  {describe(root)}", style=theme.style("dim")))
    console.print()

    options = [chooser.Option("here", "Yes, work here",
                              "remembered, so this is the only time it asks")]
    if here != root:
        # The root came from walking upwards, so it can be a long way above
        # where you actually are. Offering the alternative is cheaper than
        # making somebody quit and start again with --cwd.
        options.append(chooser.Option(
            "cwd", f"Work in {here.name} instead", str(here)))
    options.append(chooser.Option("quit", "No, quit", "nothing has been read yet"))

    picked = chooser.choose(console, theme, options, title="Workspace")

    if picked == "cwd":
        trust(config, here)
        return here
    if picked == "here":
        trust(config, root)
        return root
    return None
