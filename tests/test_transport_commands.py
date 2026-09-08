"""What a person is told about the protocol, and whether it is still true.

The core's own greeting and its `--stdio` help both advertised version 1 for
the whole time the core was speaking version 2. Nothing failed, because a
sentence is not a contract — but it is the first thing somebody reads when a
client and a core refuse each other, and it pointed at the wrong version.

So the wording is derived from the number, and these tests fail if anybody
writes a version out by hand again.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from comodor.protocol import PROTOCOL_LABEL, PROTOCOL_VERSION
from comodor.transport import commands

ROOT = Path(__file__).resolve().parents[1]


def test_the_label_is_derived_from_the_version():
    assert PROTOCOL_LABEL == f"protocol v{PROTOCOL_VERSION}"


def test_the_stdio_help_names_the_protocol_the_core_speaks():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    commands.register(sub)

    core = sub.choices["core"]
    help_text = next(action.help for action in core._actions
                     if action.dest == "stdio")

    assert PROTOCOL_LABEL in help_text
    # And no other version is named anywhere in it.
    assert not re.search(r"protocol v\d+", help_text.replace(PROTOCOL_LABEL, ""))


def test_a_bare_core_command_says_which_protocol_it_speaks(tmp_path, capsys):
    """The message printed when no transport was chosen."""
    from comodor.config import Config
    from comodor.paths import Paths

    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path))
    args = argparse.Namespace(stdio=False)

    assert commands.run(config, args) == 2

    printed = capsys.readouterr().err
    assert PROTOCOL_LABEL in printed
    assert "protocol v1" not in printed


def test_no_source_file_advertises_a_protocol_version_by_hand():
    """The drift guard.

    Scans the package for a version written into a sentence rather than
    derived, which is the shape the stale greeting had. The one place allowed
    to spell it out is the definition of the label itself.
    """
    offenders: list[str] = []
    for path in sorted((ROOT / "src" / "comodor").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), start=1):
            if not re.search(r"protocol v\d+", line):
                continue
            if "PROTOCOL_LABEL = " in line:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

    assert not offenders, "a protocol version is written out by hand:\n" + "\n".join(offenders)


def test_the_greeting_a_spawned_core_prints_names_the_protocol(tmp_path):
    """End to end, because the greeting is built at run time."""
    import json
    import os
    import subprocess
    import sys

    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps({
        "provider": "fake",
        "model": "fake-1",
        "providers": {"fake": {"name": "fake", "kind": "fake",
                               "base_url": "offline", "api_key": "test",
                               "model": "fake-1", "label": "Fake"}},
        "learning": {"enabled": False}, "mcp": {"enabled": False},
        "cron": {"enabled": False}, "skills": {"enabled": False},
    }), encoding="utf-8")

    environment = dict(os.environ, COMODOR_HOME=str(home),
                       PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8",
                       COMODOR_OFFLINE="1")
    process = subprocess.run(
        [sys.executable, "-m", "comodor", "core"],
        cwd=str(tmp_path), env=environment, capture_output=True, text=True,
        timeout=60)

    assert PROTOCOL_LABEL in process.stderr
    assert "protocol v1" not in process.stderr
