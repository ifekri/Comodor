"""`comodor import`, for people who are past the first run.

The wizard offers this once. Somebody who installs OpenClaw a week later, or
who answered "start fresh" and changed their mind, needs a way back to it that
is not "delete your config and start over".
"""

from __future__ import annotations

import json

import pytest

from comodor.cli import run_import


class Args:
    def __init__(self, dry_run: bool = False, keys_only: bool = False) -> None:
        self.dry_run = dry_run
        self.keys_only = keys_only


@pytest.fixture(autouse=True)
def look_here_not_at_the_real_home(monkeypatch, tmp_path):
    """The command reads `Path.home()`. Point that at a temporary directory,
    or running this suite on the machine it was written on would read a real
    OpenClaw installation and copy a real API key."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)


@pytest.fixture(autouse=True)
def every_provider_has_a_slot(config):
    from comodor import catalogue
    from comodor.config import provider_from_spec

    for spec in catalogue.offered():
        config.providers.setdefault(spec.id, provider_from_spec(spec))
    config.model = ""
    config.provider = ""
    return config


def openclaw(home, key="sk-ant-brought-over"):
    root = home / ".openclaw"
    (root / "skills" / "review").mkdir(parents=True)
    (root / "skills" / "review" / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review\n---\n\nTwice.\n", encoding="utf-8")
    (root / "openclaw.json").write_text(json.dumps({
        "models": {"providers": {"anthropic": {
            "apiKey": key, "baseUrl": "https://api.anthropic.com/v1"}}},
        "agents": {"defaults": {"model": "claude-sonnet-5"}},
    }), encoding="utf-8")
    return root


def test_nothing_to_import_is_not_a_failure(config, capsys):
    assert run_import(config, Args()) == 0
    assert "Nothing to import" in capsys.readouterr().out


def test_it_brings_everything_over(config, tmp_path, capsys):
    openclaw(tmp_path)

    assert run_import(config, Args()) == 0

    assert config.providers["anthropic"].api_key == "sk-ant-brought-over"
    assert config.model == "claude-sonnet-5"
    assert (config.paths.skills / "openclaw-review" / "SKILL.md").is_file()


def test_a_dry_run_changes_nothing(config, tmp_path, capsys):
    """This reads another program's files and writes to yours. The reasonable
    first question is what it would do."""
    openclaw(tmp_path)

    assert run_import(config, Args(dry_run=True)) == 0

    assert not config.providers["anthropic"].api_key
    assert not config.paths.config_file.exists()
    assert "nothing was changed" in capsys.readouterr().out


def test_keys_only_leaves_the_rest(config, tmp_path):
    openclaw(tmp_path)

    run_import(config, Args(keys_only=True))

    assert config.providers["anthropic"].api_key == "sk-ant-brought-over"
    assert not config.model
    assert not (config.paths.skills / "openclaw-review").exists()


def test_running_it_twice_says_so_rather_than_doing_it_twice(config, tmp_path, capsys):
    openclaw(tmp_path)
    run_import(config, Args())
    capsys.readouterr()

    assert run_import(config, Args()) == 0

    assert "Nothing new" in capsys.readouterr().out


def test_it_leaves_a_configuration_that_runs(config, tmp_path):
    """A key, a model, and no provider chosen is a config that only appears to
    work — `active()` falls back to whatever has a key, which is arbitrary the
    moment there are two."""
    openclaw(tmp_path)

    run_import(config, Args())

    assert config.provider == "anthropic"
    assert config.providers["anthropic"].configured
    assert config.active() is not None


def test_no_key_reaches_the_screen(config, tmp_path, capsys):
    openclaw(tmp_path)

    run_import(config, Args())

    assert "sk-ant-brought-over" not in capsys.readouterr().out


def test_a_skill_the_copy_refused_is_named(config, tmp_path, capsys):
    """The reason is worked out while copying, which is after the listing was
    printed. Getting it on screen anyway is the whole point of saying it."""
    root = openclaw(tmp_path)
    folder = root / "skills" / "heavy"
    folder.mkdir()
    (folder / "SKILL.md").write_text("---\nname: heavy\ndescription: x\n---\n",
                                     encoding="utf-8")
    (folder / "dump.md").write_text("x" * 3_000_000, encoding="utf-8")

    run_import(config, Args())

    out = capsys.readouterr().out
    assert "heavy" in out and "not imported" in out
