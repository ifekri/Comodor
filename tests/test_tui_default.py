"""Which interface answers, for which command.

The default switched once — bare `comodor` went from the previous interface
to the production one — and the proof here is dispatch, not rendering: a
test that draws a screen to learn which screen it drew is a test that fails
on the screen's bugs rather than on the routing's. `run_tui` and the legacy
interface are swapped for spies, and `main()` is driven with the arguments a
person types.
"""

from __future__ import annotations

from typing import Any

import pytest

from comodor import cli


@pytest.fixture
def spy(monkeypatch, config):
    """Capture which launcher `main()` reaches, with which config."""
    seen: dict[str, Any] = {"tui": None, "legacy": None, "others": []}

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: config)
    import comodor.transport.commands as transport

    monkeypatch.setattr(transport, "run_tui",
                        lambda cfg, args: seen.__setitem__("tui", cfg) or 0)
    # `run_tui` is imported lazily inside `main` from the same module the
    # dispatch imports it from, so patching the module attribute is enough.
    monkeypatch.setattr(cli, "start_interface",
                        lambda cfg, args: seen.__setitem__("legacy", cfg) or 0)
    return seen


def test_bare_command_reaches_the_production_interface(spy, config):
    """`comodor` with nothing after it is the production interface.

    The whole cutover is this line being true. The workspace-confirm path is
    the production launcher's own; the test drives it with `--cwd` so no
    question is asked.
    """
    code = cli.main(["--cwd", str(config.paths.project)])

    assert code == 0
    assert spy["tui"] is config
    assert spy["legacy"] is None


def test_the_v2_alias_reaches_the_same_launcher(spy, config):
    """`comodor tui-v2` is a compatibility path, not a second interface."""
    code = cli.main(["--cwd", str(config.paths.project), "tui-v2"])

    assert code == 0
    assert spy["tui"] is config
    assert spy["legacy"] is None


def test_the_legacy_command_reaches_the_previous_interface(spy, config):
    """`comodor legacy` is the explicit compatibility route, one command deep."""
    code = cli.main(["--cwd", str(config.paths.project), "legacy"])

    assert code == 0
    assert spy["legacy"] is config
    assert spy["tui"] is None


def test_a_subcommand_never_reaches_an_interface(spy, config):
    """`comodor run` and friends bypass both interfaces entirely."""
    called: list[str] = []

    import comodor.cli as module

    module.run_headless = lambda cfg, args: called.append("run") or 0
    code = cli.main(["--cwd", str(config.paths.project), "run", "do a thing"])

    assert code == 0
    assert called == ["run"]
    assert spy["tui"] is None and spy["legacy"] is None


def test_provider_and_model_reach_the_production_launcher(spy, config):
    """Flags the person set must be the config the launcher gets."""
    cli.main(["--cwd", str(config.paths.project),
              "--provider", "fake", "--model", "fake-1"])

    received = spy["tui"]
    assert received is not None
    assert received.provider == "fake"
    assert received.model == "fake-1"


def test_mode_and_no_loop_reach_the_production_launcher(spy, config):
    cli.main(["--cwd", str(config.paths.project),
              "--mode", "plan", "--no-loop"])

    received = spy["tui"]
    assert received is not None
    assert str(received.agent.mode) == "plan"
    assert received.agent.loop is False


def test_cwd_is_the_launchers_workspace(spy, config, tmp_path):
    """The artifact's directory is never the workspace; the user's project is.

    `--cwd` names the folder, and the config loader resolves it to the
    project root by walking up — inside the fixture's workspace, that is the
    fixture root. What matters is the launcher receives *that* answer, not
    the artifact's directory and not the directory the command was typed in.
    """
    inside = config.paths.project / "nested"
    inside.mkdir()
    cli.main(["--cwd", str(inside)])

    received = spy["tui"]
    assert received is not None
    assert received.paths.project == config.paths.project


def test_the_spawned_core_is_this_interpreter_and_gets_the_flags(
        monkeypatch, tmp_path):
    """The core the interface spawns must be this install's own.

    `COMODOR_BIN`/`COMODOR_ARGS` are the seam: a pipx environment's renderer
    must not reach whichever `comodor` a PATH happens to name first, and the
    flags the person set must reach the process that actually answers.
    """
    import argparse
    import sys

    from comodor.config import load
    from comodor.transport.commands import run_tui
    from comodor.tui import runtime

    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    (tmp_path / "project").mkdir()
    config = load(cwd=tmp_path / "project", use_environment=False)
    config.use("ollama", model="qwen2.5-coder:14b")
    config.save()
    config = load(cwd=config.paths.project, use_environment=False)
    assert not config.needs_setup

    monkeypatch.setattr(runtime, "bun", lambda: "/fake/bun")
    monkeypatch.setattr(runtime, "checkout_entry",
                        lambda: config.paths.project / "main.tsx")
    monkeypatch.setattr(runtime, "packaged_dist", lambda: None)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    seen: dict[str, Any] = {}

    def fake_call(argv, cwd=None, env=None):
        seen["argv"] = argv
        seen["cwd"] = cwd
        seen["env"] = env
        return 0

    monkeypatch.setattr("subprocess.call", fake_call)

    code = run_tui(config, argparse.Namespace(
        provider="fake", model="fake-1", mode="plan", no_loop=True,
        demo=False, resume=""))

    assert code == 0
    env = seen["env"]
    assert env["COMODOR_BIN"] == sys.executable
    args = env["COMODOR_ARGS"]
    assert args.startswith("-m comodor")
    assert "--provider fake" in args
    assert "--model fake-1" in args
    assert "--mode plan" in args
    assert "--no-loop" in args
    # The workspace is the project, never the artifact's own directory.
    assert seen["cwd"] == str(config.paths.project)
