"""The parser and the manual describe the same command line.

Two directions, both found wanting in the post-migration audit: three
registered commands (`approvals`, `cron`, `plugins`) appeared in no document
and had no help topic, and a removed command can outlive itself in a page
that nobody re-read. Neither is caught by any test of the commands themselves.
"""

from __future__ import annotations

import re
from pathlib import Path

from comodor import cli

ROOT = Path(__file__).resolve().parents[1]
CLI_GUIDE = ROOT / "docs" / "cli.md"


def registered() -> dict[str, str]:
    """Every subcommand the parser accepts, with its one-line help."""
    parser = cli.build_parser()
    subparsers = next(action for action in parser._actions
                      if hasattr(action, "choices") and isinstance(action.choices, dict))
    return {action.dest: action.help or ""
            for action in subparsers._choices_actions}


def mentioned_in_guide() -> set[str]:
    """Every `comodor <word>` the CLI guide shows, as a command name."""
    text = CLI_GUIDE.read_text(encoding="utf-8")
    return set(re.findall(r"\bcomodor ([a-z][a-z0-9-]*)\b", text))


def test_every_registered_command_is_in_the_cli_guide():
    missing = sorted(name for name in registered() if name not in mentioned_in_guide())
    assert not missing, f"docs/cli.md does not mention: {missing}"


def test_every_command_the_guide_shows_is_registered():
    """The reverse: a page that still shows `comodor legacy` is advertising a
    command the parser rejects. Words after `comodor` that are flags, quoted
    tasks or prose are not commands and are not counted."""
    known = set(registered())
    not_commands = {"help"}  # `comodor help <topic>` is registered too, kept explicit
    shown = mentioned_in_guide() - not_commands
    unknown = sorted(name for name in shown if name not in known)
    assert not unknown, f"docs/cli.md shows commands the parser does not have: {unknown}"


def test_every_registered_command_has_a_help_line():
    """`comodor --help` prints the one-liner; an empty one is a blank row."""
    blank = sorted(name for name, line in registered().items() if not line.strip())
    assert not blank, blank
