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
