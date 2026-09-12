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
    seen: dict[str, Any] = {"tui": None, "others": []}

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: config)
    import comodor.transport.commands as transport

    monkeypatch.setattr(transport, "run_tui",
                        lambda cfg, args: seen.__setitem__("tui", cfg) or 0)
    # `run_tui` is imported lazily inside `main` from the same module the
    # dispatch imports it from, so patching the module attribute is enough.
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


def test_the_v2_alias_reaches_the_same_launcher(spy, config):
    """`comodor tui-v2` is a compatibility path, not a second interface."""
    code = cli.main(["--cwd", str(config.paths.project), "tui-v2"])

    assert code == 0
    assert spy["tui"] is config


def test_the_legacy_command_is_gone(spy, config, capsys):
    """`comodor legacy` was the rollback route while the default changed.

    The interface it started is removed, and so is the command: argparse's
    ordinary refusal, not a hidden alias and not a custom apology. What it
    must not do is start anything.
    """
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--cwd", str(config.paths.project), "legacy"])

    assert stopped.value.code == 2
    assert spy["tui"] is None, "an unknown command must not reach the launcher"
    said = capsys.readouterr().err
    assert "invalid choice" in said and "legacy" in said


def test_help_does_not_advertise_the_retired_commands(capsys):
    # `--help` is Comodor's own page (it returns rather than exiting), and
    # argparse's usage line is what `legacy` shows up in when it is a command.
    assert cli.main(["--help"]) == 0
    said = capsys.readouterr().out
    for retired in ("legacy", "preview", "--no-mouse", "/undo", "/computer"):
        assert retired not in said, f"help still advertises {retired!r}"
    with pytest.raises(SystemExit):
        cli.main(["not-a-command"])
    usage = capsys.readouterr().err
    assert "legacy" not in usage and "preview" not in usage


def test_preview_is_gone_with_the_interface_it_rendered(spy, config):
    """`comodor preview` drew one frame of the previous interface to an SVG.

    There is no static frame of the current one to draw — it is a live
    renderer — and `comodor --demo` is the way to look at it.
    """
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--cwd", str(config.paths.project), "preview", "120x34"])

    assert stopped.value.code == 2
    assert spy["tui"] is None


def test_a_subcommand_never_reaches_an_interface(spy, config, monkeypatch):
    """`comodor run` and friends bypass both interfaces entirely."""
    called: list[str] = []

    # Through `monkeypatch`, so it is undone. A bare assignment here leaked
    # into every test that ran after it on the same xdist worker, and
    # `test_headless.py` — which reads `run_headless`'s source and drives the
    # real one — then failed on whichever platform's scheduling put it
    # second. That is what a "flaky on macOS and 3.12" failure was.
    monkeypatch.setattr(cli, "run_headless",
                        lambda cfg, args: called.append("run") or 0)
    code = cli.main(["--cwd", str(config.paths.project), "run", "do a thing"])

    assert code == 0
    assert called == ["run"]
    assert spy["tui"] is None


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
    monkeypatch.setattr(runtime, "bun_version", lambda executable: (1, 4))
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


def test_bare_command_does_not_run_setup_before_the_launcher(spy, config,
                                                             monkeypatch):
    """Runtime checks first, then setup — and the launcher owns both.

    `main()` used to run the setup questions for the bare command before the
    launcher was reached, so a fresh machine without Bun answered everything
    and was refused afterwards. Now a configuration that still needs setup
    goes to the launcher as it is, and the launcher decides the order.
    """
    monkeypatch.setattr(type(config), "needs_setup",
                        property(lambda self: True))

    def forbidden(cfg):
        raise AssertionError("main() ran setup before the launcher")

    monkeypatch.setattr("comodor.setup.run_setup", forbidden)

    code = cli.main(["--cwd", str(config.paths.project)])

    assert code == 0
    assert spy["tui"] is config, "the launcher received the unconfigured config"
