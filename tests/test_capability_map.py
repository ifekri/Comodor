"""The capability map, and the one bug it found the day it was written.

`tools/capability-map.py` asks the code what it can do and writes the answer
down. It exists because "I thought that part worked" is expensive to find out
in the middle of something else.

The first run reported **13 of 20 subsystems broken**. None of them were: the
package was installed non-editable, so `python -m comodor` was running a copy
in `site-packages` from some earlier day, and that copy predated telegram,
slack, whatsapp, discord, cron, curator, plugins, webhook and serve. Every
manual check anybody had run against the CLI had been checking the wrong code.

That is exactly the class of thing the map is for, and it is also a trap the
map can fall into itself — so the first test here is that it never reports on
a stale install again.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "capability-map.py"


@pytest.fixture(scope="module")
def mapper():
    """The generator, imported as a module rather than run as a script."""
    spec = importlib.util.spec_from_file_location("capability_map", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# the trap it fell into
# --------------------------------------------------------------------------- #


def test_the_cli_being_measured_is_the_one_in_this_tree():
    """A non-editable install runs a copy in `site-packages`, and a map built
    against that is a map of whatever was installed months ago.

    It reported thirteen working subsystems as broken. The failure mode is
    worse than a wrong number: everything it says would be about code nobody
    is looking at.
    """
    found = subprocess.run(
        [sys.executable, "-c",
         "import comodor, sys; sys.stdout.write(comodor.__file__)"],
        cwd=ROOT, capture_output=True, text=True, timeout=120)

    where = Path(found.stdout.strip())
    assert "site-packages" not in where.parts, (
        f"`comodor` imports from {where}, not from this tree. Reinstall with "
        f"`pip install -e .[dev]` — the CLI in use is not the code here.")
    assert (ROOT / "src") in where.parents


def test_every_command_the_map_runs_actually_exists():
    """Two of the twenty were names I guessed rather than read: `memory
    status` and `web status`, neither of which exists. A guessed name reports
    a working subsystem as broken, which is the same lie the other way round.
    """
    spec = importlib.util.spec_from_file_location("capability_map", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sys.path.insert(0, str(ROOT / "src"))
    from comodor.cli import build_parser

    top: dict = {}
    for action in build_parser()._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            top = choices
            break

    for label, args in module.SAFE_COMMANDS:
        if args[0].startswith("--"):
            continue
        command, *rest = args
        assert command in top, f"{label}: there is no `{command}` command"
        if rest and not rest[0].startswith("--"):
            nested: dict = {}
            for inner in top[command]._actions:
                inner_choices = getattr(inner, "choices", None)
                if isinstance(inner_choices, dict):
                    nested = inner_choices
                    break
            assert rest[0] in nested, \
                f"{label}: `{command}` has no `{rest[0]}` sub-command"


# --------------------------------------------------------------------------- #
# what it produces
# --------------------------------------------------------------------------- #


def test_it_reads_the_commands_from_the_parser(mapper):
    found = dict(mapper.commands())

    assert "run" in found and "doctor" in found
    assert "telegram writes" in found, "sub-commands are not being reached"
    assert found["doctor"], "the help text is empty — the table would be blank"


def test_it_reads_the_tools_from_the_registry(mapper):
    modes = mapper.tools_by_mode()

    assert "write_file" in modes["act"]
    assert "write_file" not in modes["plan"], \
        "plan mode is being reported as able to write"
    assert modes["chat"] == [], "chat mode is being given tools"


def test_it_names_the_tools_that_are_only_sometimes_offered(mapper):
    """A tool missing from the map because a registry did not have it, with no
    note of why, reads as a tool that does not exist."""
    optional = dict(mapper.optional_tools())

    assert "computer" in optional
    assert "memory" in optional
    for name, why in optional.items():
        assert why, f"{name} is listed as conditional with no condition"


def test_it_notices_a_channel_the_panel_cannot_connect(mapper):
    """Discord was registered as a channel with no form in the web panel for
    two weeks. The map is where that becomes visible."""
    for entry in mapper.channels():
        assert entry["form"], \
            f"{entry['name']} is a channel the panel lists and cannot connect"
        assert entry["bot"], f"{entry['name']} has no bot module"
        assert entry["cli"], f"{entry['name']} has no CLI"


def test_the_page_says_what_broke_rather_than_burying_it(mapper):
    """A page that reports failures in a table cell somewhere is a page whose
    failures nobody reads."""
    import inspect

    source = inspect.getsource(mapper.render)

    assert "are broken right now" in source
    assert "BROKEN" in source


def test_it_can_check_itself_without_writing(mapper, tmp_path, monkeypatch):
    """`--check` is what a hook would run. It must not have side effects."""
    import inspect

    source = inspect.getsource(mapper.main)
    check_half = source.split("if args.check:")[1].split("OUT.write_text")[0]

    assert "write_text" not in check_half, "--check writes the file"


def test_the_child_is_given_the_source_tree_explicitly(mapper):
    """`sys.path.insert` at the top of the script changes *this* interpreter.

    The child gets nothing from it, and `cwd` does not make a src-layout
    package importable — so without an explicit PYTHONPATH the child imports
    whatever is in site-packages, which is the exact stale copy this file
    exists to catch. An uninstalled checkout could not import it at all.
    """
    import inspect

    source = inspect.getsource(mapper.smoke)

    assert "PYTHONPATH" in source, \
        "the child is left to find comodor however it can"
    assert "env=environment" in source, "the environment is built and not used"


def test_a_child_that_cannot_import_comodor_is_not_reported_as_working(mapper):
    """`python -m comodor` with the package missing exits 1, prints "No module
    named comodor", and produces no traceback. An "exit 0 or 1 is fine" rule
    called that a working command — for all twenty of them at once."""
    import os

    broken = dict(os.environ)
    broken["PYTHONPATH"] = "nowhere-at-all"

    finished = subprocess.run(
        [sys.executable, "-S", "-m", "comodor", "--version"],
        cwd=ROOT, capture_output=True, text=True, env=broken,
        encoding="utf-8", errors="replace", timeout=180)
    output = (finished.stdout or "") + (finished.stderr or "")

    assert finished.returncode == 1
    assert "Traceback (most recent call last)" not in output
    assert "No module named" in output

    # The rule the map applies to that answer.
    allowed = {0, 1} if "comodor --version" in mapper.MAY_EXIT_ONE else {0}
    assert finished.returncode not in allowed, \
        "a missing package would be reported as a working command"


def test_only_doctor_is_allowed_to_exit_one(mapper):
    """It is documented as meaning "I found something to report". Extending
    that to every command is what hid the failure above."""
    assert mapper.MAY_EXIT_ONE == {"comodor doctor"}


def test_nothing_in_the_safe_list_reaches_the_network(mapper):
    """`comodor local list` calls the catalogue with `allow_network=True`: it
    contacts a remote server and writes `local-models.json` into the user's
    cache. Generating a supposedly read-only map must not do either, and must
    not stall when the network is gone."""
    reaching = {"local"}       # the ones known to fetch
    for label, args in mapper.SAFE_COMMANDS:
        assert args[0] not in reaching, \
            f"{label} performs network I/O and writes to the user's cache"


def test_check_does_not_need_a_baseline_file(mapper, tmp_path, monkeypatch):
    """The map is git-ignored, so a clean checkout has none. Diffing against a
    missing file failed every time on the exact machine `--check` is for."""
    import inspect

    source = inspect.getsource(mapper.check)

    assert "OUT.read_text" not in source, \
        "--check still compares against a file that will not be there"
    assert "smoke()" in source, "--check no longer runs anything"


def test_check_reports_what_is_wrong_rather_than_that_something_is(mapper):
    """"Out of date" sent somebody to regenerate a file. A list of what failed
    sends them to the thing that failed."""
    import inspect

    source = inspect.getsource(mapper.check)

    assert "problems" in source
    assert "has no form" in source, "a broken channel is not named"


def test_the_map_is_not_committed():
    """It records what answered on one machine at one moment. A committed copy
    would be stale the next day and believed anyway."""
    finished = subprocess.run(
        ["git", "check-ignore", "CAPABILITIES.md"],
        cwd=ROOT, capture_output=True, text=True, timeout=60)

    assert finished.returncode == 0, \
        "CAPABILITIES.md is committable — it is a photograph, not a document"


def test_the_generator_is_committed():
    """The opposite: without it, nobody else can rebuild the map."""
    finished = subprocess.run(
        ["git", "check-ignore", "tools/capability-map.py"],
        cwd=ROOT, capture_output=True, text=True, timeout=60)

    assert finished.returncode != 0, "the generator is ignored by git"
