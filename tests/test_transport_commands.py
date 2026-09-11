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


# --------------------------------------------------------------------------- #
# `comodor tui-v2` is setup-aware
#
# The renderer spawns a core over the protocol, and a core with no configured
# provider renders a conversation that cannot be answered. So the launcher runs
# the canonical setup first and starts only if it produced a usable
# configuration — in the same invocation. Bun and the process spawn are faked;
# no physical terminal, no real renderer, no network.
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402

from comodor.config import load  # noqa: E402

ENTRY = (Path(commands.__file__).resolve().parents[3]
         / "apps" / "tui" / "src" / "main.tsx")


@pytest.fixture
def checkout_with_tui(monkeypatch):
    """The launcher needs apps/tui present, Bun on the path, and a terminal.

    The terminal is faked the same way the renderer is: these tests are about
    the launcher's order of operations, and the non-TTY refusal is its own
    behavior with its own test below.
    """
    if not ENTRY.exists():
        pytest.skip("tui-v2 launcher tests run from a source checkout")
    monkeypatch.setattr("shutil.which", lambda name: "/fake/bun")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)


def a_fresh_config(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    return load(cwd=project, use_environment=False)


def test_tui_v2_runs_setup_before_spawning_a_core_on_a_fresh_machine(
        tmp_path, monkeypatch, checkout_with_tui):
    config = a_fresh_config(tmp_path, monkeypatch)
    assert config.needs_setup

    events: list[str] = []

    def fake_setup(cfg):
        events.append("setup")
        cfg.use("ollama", model="qwen2.5-coder:14b")
        cfg.save()
        return cfg

    def fake_call(argv, cwd=None, env=None):
        events.append("spawn")
        # At the moment of the spawn the configuration must already be usable:
        # this is the "no unconfigured core" guarantee, checked at the seam.
        assert not load(cwd=cwd, use_environment=False).needs_setup
        return 0

    monkeypatch.setattr("comodor.setup.run_setup", fake_setup)
    monkeypatch.setattr("subprocess.call", fake_call)

    rc = commands.run_tui(config, argparse.Namespace())

    assert rc == 0
    assert events == ["setup", "spawn"], \
        "setup must complete before the core is spawned, in one invocation"


def test_a_pipeline_is_refused_before_any_renderer(tmp_path, monkeypatch):
    """A bare launch with no terminal is a refusal, not escape codes in a pipe.

    The demo path is the deliberate exception — it is the scripted smoke —
    and everything else gets a sentence and an exit code.
    """
    config = a_fresh_config(tmp_path, monkeypatch)
    config.use("ollama", model="qwen2.5-coder:14b")
    config.save()
    config = load(cwd=config.paths.project, use_environment=False)
    monkeypatch.setattr("shutil.which", lambda name: "/fake/bun")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    forbidden: list[str] = []
    monkeypatch.setattr("subprocess.call",
                        lambda *a, **k: forbidden.append("spawned"))

    rc = commands.run_tui(config, argparse.Namespace())

    assert rc == 2
    assert forbidden == []


def test_tui_v2_launches_directly_when_already_configured(
        tmp_path, monkeypatch, checkout_with_tui):
    config = a_fresh_config(tmp_path, monkeypatch)
    config.use("ollama", model="qwen2.5-coder:14b")
    config.save()
    config = load(cwd=config.paths.project, use_environment=False)
    assert not config.needs_setup

    def forbidden(cfg):
        raise AssertionError("setup ran on an already-configured machine")

    events: list[str] = []
    monkeypatch.setattr("comodor.setup.run_setup", forbidden)
    monkeypatch.setattr("subprocess.call",
                        lambda *a, **k: events.append("spawn") or 0)

    rc = commands.run_tui(config, argparse.Namespace())

    assert rc == 0
    assert events == ["spawn"]


def test_tui_v2_does_not_spawn_when_setup_is_cancelled(
        tmp_path, monkeypatch, checkout_with_tui):
    config = a_fresh_config(tmp_path, monkeypatch)

    def cancelling(cfg):
        raise KeyboardInterrupt

    spawned: list[int] = []
    monkeypatch.setattr("comodor.setup.run_setup", cancelling)
    monkeypatch.setattr("subprocess.call",
                        lambda *a, **k: spawned.append(1) or 0)

    rc = commands.run_tui(config, argparse.Namespace())

    assert rc == 130
    assert spawned == [], "a cancelled setup must not spawn an unusable core"
    assert not config.paths.config_file.exists(), \
        "a cancelled setup wrote a configuration"


def test_tui_v2_does_not_spawn_when_setup_stops_short(
        tmp_path, monkeypatch, checkout_with_tui):
    """run_setup returning an still-unusable configuration (it stopped on a
    refusal and said why) must not reach the spawn either."""
    config = a_fresh_config(tmp_path, monkeypatch)

    stalled = lambda cfg: cfg                    # noqa: E731 - unchanged
    spawned: list[int] = []
    monkeypatch.setattr("comodor.setup.run_setup", stalled)
    monkeypatch.setattr("subprocess.call",
                        lambda *a, **k: spawned.append(1) or 0)

    rc = commands.run_tui(config, argparse.Namespace())

    assert rc == 1
    assert spawned == [], "an unfinished setup must not spawn a core"


def test_tui_v2_still_refuses_without_bun(tmp_path, monkeypatch):
    """The launcher's own requirements are checked before setup is offered, so
    nobody answers the questions only to be told the renderer cannot start."""
    if not ENTRY.exists():
        pytest.skip("tui-v2 launcher tests run from a source checkout")
    config = a_fresh_config(tmp_path, monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)

    def forbidden(cfg):
        raise AssertionError("setup was offered though Bun is missing")

    monkeypatch.setattr("comodor.setup.run_setup", forbidden)

    assert commands.run_tui(config, argparse.Namespace()) == 2
