"""The help page: what somebody typing `--help` actually gets.

argparse produces a list of flags, which answers "what arguments does this
accept" and not "what is this, and what do I do now". The page is written
instead, so these check the things a written page can get wrong: a command that
no longer exists, a topic promised and missing, a documentation link pointing
nowhere.

The last one matters most. Documentation that promises a page and does not have
it is worse than documentation that stops short — the reader goes looking, finds
nothing, and stops believing the rest.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from rich.console import Console

from comodor import help as help_page
from comodor.cli import build_parser, main

DOCS = Path(__file__).resolve().parents[1] / "docs"


def rendered(topic: str = "") -> str:
    buffer = io.StringIO()
    console = Console(file=buffer, width=100, no_color=True, force_terminal=False)
    help_page.render(console=console, topic=topic)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# it appears at all
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"]])
def test_every_way_of_asking_reaches_the_written_page(argv, capsys):
    assert main(argv) == 0

    out = capsys.readouterr().out
    assert "Start here" in out
    assert "usage: comodor [-h]" not in out, "that is argparse's page, not ours"


def test_a_subcommand_still_gets_its_own_flag_list(capsys):
    """For one subcommand, the list of its flags really is the answer."""
    with pytest.raises(SystemExit):
        main(["run", "--help"])

    out = capsys.readouterr().out
    assert "usage: comodor run" in out
    assert "--max-steps" in out


def test_it_works_before_the_configuration_is_loaded(monkeypatch, capsys):
    """Somebody who cannot get the program to start is exactly the person who
    needs this page, so it must not depend on a config that loads."""
    def broken(*args, **kwargs):
        raise RuntimeError("the config is unreadable")

    monkeypatch.setattr("comodor.cli.load_config", broken)

    assert main(["--help"]) == 0
    assert "Start here" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# what it says is true
# --------------------------------------------------------------------------- #


def test_every_command_it_mentions_exists():
    """A help page naming a command that was renamed is worse than no page."""
    page = rendered()
    parser = build_parser()
    real = set()
    for action in parser._actions:
        if action.choices and hasattr(action.choices, "keys"):
            real.update(action.choices.keys())

    named = set(re.findall(r"^\s+comodor ([\w][\w-]*)", page, re.M))
    unknown = named - real
    assert not unknown, f"the page names commands that do not exist: {unknown}"


def test_every_flag_it_mentions_exists():
    page = rendered()
    parser = build_parser()
    real = {option for action in parser._actions for option in action.option_strings}

    named = set(re.findall(r"^\s+(--[a-z-]+)", page, re.M))
    unknown = named - real
    assert not unknown, f"the page names flags that do not exist: {unknown}"


def test_the_topics_it_offers_all_answer():
    page = rendered()
    for topic in help_page.topics():
        assert topic in page, f"{topic} is a topic but is not listed"
        assert help_page.render(
            console=Console(file=io.StringIO(), width=100, no_color=True),
            topic=topic) == 0


def test_an_unknown_topic_says_what_would_have_worked():
    out = rendered(topic="nonsense")

    assert "No help topic" in out
    assert "computer" in out


# --------------------------------------------------------------------------- #
# the documentation it points at
# --------------------------------------------------------------------------- #


def test_every_documentation_page_it_names_is_there():
    """The topics end with `Full guide: docs/<name>.md`. A promise that does not
    resolve teaches the reader to stop following them."""
    missing = []
    for name, (_, body) in help_page.TOPICS.items():
        for reference in re.findall(r"docs/([\w-]+\.md)", body):
            if not (DOCS / reference).exists():
                missing.append(f"{name} -> docs/{reference}")
    assert not missing, f"help points at pages that do not exist: {missing}"


def test_the_documentation_index_exists_and_reaches_every_page():
    index = DOCS / "README.md"
    assert index.is_file(), "docs/README.md is the front door"

    body = index.read_text(encoding="utf-8")
    linked = {target.partition("#")[0]
              for _, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", body)}
    orphans = [page.name for page in sorted(DOCS.glob("*.md"))
               if page.name != "README.md" and page.name not in linked]
    assert not orphans, f"pages the index does not reach: {orphans}"


def link_path(target: str) -> str:
    """The file a Markdown link points at, out of everything in the brackets.

    `[text](path "title")` is an ordinary link and the title is not part of the
    path — reading it as one turns a working link into a broken one and reports
    the wrong thing as the bug. `<path>` is legal too.
    """
    target = target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1:target.index(">")]
    else:
        target = target.split(maxsplit=1)[0] if target.split() else ""
    return target.partition("#")[0]


def test_no_documentation_link_is_broken():
    broken = []
    for page in sorted(DOCS.glob("*.md")):
        for label, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)",
                                        page.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = link_path(target)
            if path and not (page.parent / path).exists():
                broken.append(f"{page.name}: [{label}]({target})")
    assert not broken, f"broken links: {broken}"


def reachable(root: Path, path: str) -> str:
    """Empty if the link resolves, otherwise why it does not.

    An empty directory counts as missing. Git does not track one, so a link to
    it works on the machine where the folder happens to exist and is broken in
    every fresh clone — which is the worst kind of broken link, because the
    person who wrote it cannot reproduce the report.
    """
    where = root / path
    if not where.exists():
        return "does not exist"
    if where.is_dir() and not any(where.iterdir()):
        return "is an empty directory, which git does not track"
    return ""


def test_the_readme_points_at_the_index():
    readme = (DOCS.parent / "README.md").read_text(encoding="utf-8")

    assert "docs/README.md" in readme
    broken = []
    for _, target in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", readme):
        if target.startswith(("http", "mailto", "#")):
            continue
        path = link_path(target)
        if not path:
            continue
        why = reachable(DOCS.parent, path)
        if why:
            broken.append(f"{target} — {why}")
    assert not broken, f"the README points at nothing: {broken}"


def test_a_link_to_an_empty_directory_is_broken(tmp_path):
    """It resolves for whoever wrote it and for nobody else."""
    (tmp_path / "hollow").mkdir()
    (tmp_path / "solid").mkdir()
    (tmp_path / "solid" / "thing.md").write_text("x", encoding="utf-8")

    assert reachable(tmp_path, "hollow")
    assert not reachable(tmp_path, "solid")
    assert reachable(tmp_path, "absent")


@pytest.mark.parametrize("target,expected", [
    ("docs/README.md", "docs/README.md"),
    ("docs/README.md 'Comodor Documentation English'", "docs/README.md"),
    ('docs/tools.md "The tools"', "docs/tools.md"),
    ("<docs/web.md>", "docs/web.md"),
    ("docs/safety.md#permissions", "docs/safety.md"),
])
def test_a_link_title_is_not_part_of_the_path(target, expected):
    """A titled link is ordinary Markdown, and reading the title as part of the
    filename reports a working link as broken — which sends somebody looking
    for a missing file that is not missing."""
    assert link_path(target) == expected


# --------------------------------------------------------------------------- #
# it is readable
# --------------------------------------------------------------------------- #


def test_it_fits_a_narrow_terminal():
    """80 columns is still the default in a great many places."""
    buffer = io.StringIO()
    console = Console(file=buffer, width=80, no_color=True, force_terminal=False)
    help_page.render(console=console)

    overlong = [line for line in buffer.getvalue().splitlines() if len(line) > 80]
    assert not overlong, f"{len(overlong)} lines run past 80 columns"


def test_it_says_what_the_program_is_before_listing_flags():
    page = rendered()

    assert page.index("learns the way you correct it") < page.index("Options")
