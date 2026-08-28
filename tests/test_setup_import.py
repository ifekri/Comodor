"""The first run, when another agent is already installed.

Both halves of this are tested elsewhere — the wizard in `test_setup.py`, the
reading of other tools' files in `test_migrate.py`. What is checked here is the
join, which is where the value and the bugs both are: an import that announces
itself and then lets the next screen ask for the key it just brought over is
worse than no import at all.

The wizard is driven with a scripted prompt, so `_choose` falls back to typing a
number and the whole run is deterministic.
"""

from __future__ import annotations

import json
import re

import pytest

from comodor.setup import SetupWizard


@pytest.fixture(autouse=True)
def every_provider_has_a_slot(config):
    """A real `load` builds an entry for every provider in the catalogue.

    The shared fixture carries one fake provider, which is enough for tests
    that never look further; these ones ask what happened to Anthropic.
    """
    from comodor import catalogue
    from comodor.config import provider_from_spec

    for spec in catalogue.offered():
        config.providers.setdefault(spec.id, provider_from_spec(spec))

    # And a first run has not chosen a model yet. The shared fixture names one,
    # which the import then correctly declines to replace — so leaving it in
    # would test the wrong thing, and hide whether the model ever arrives.
    config.model = ""
    return config


@pytest.fixture(autouse=True)
def allow_the_import(monkeypatch):
    """The suite refuses imports by default; these tests are about them.

    They still never reach a real home — every one passes its own directory.
    """
    monkeypatch.delenv("COMODOR_NO_IMPORT", raising=False)


def openclaw(home, key="sk-ant-brought-over", model="claude-sonnet-5"):
    root = home / ".openclaw"
    (root / "skills" / "review").mkdir(parents=True)
    (root / "skills" / "review" / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review a change\n---\n\nTwice.\n",
        encoding="utf-8")
    (root / "openclaw.json").write_text(json.dumps({
        "models": {"providers": {"anthropic": {
            "apiKey": key, "baseUrl": "https://api.anthropic.com/v1"}}},
        "agents": {"defaults": {"model": model}},
    }), encoding="utf-8")
    return root


class Script:
    """A scripted person at the keyboard, who also records what they saw."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.asked: list[str] = []
        self.secrets: list[str] = []

    def prompt(self, message: str) -> str:
        self.asked.append(message)
        return self.replies.pop(0) if self.replies else ""

    def secret(self, message: str) -> str:
        self.secrets.append(message)
        return "sk-typed-by-hand"


def drive(config, home, *replies: str) -> tuple[SetupWizard, Script, object]:
    script = Script(*replies)
    wizard = SetupWizard(config, prompt=script.prompt, secret=script.secret,
                         home=home)
    answers = wizard.run()
    return wizard, script, answers


# --------------------------------------------------------------------------- #
# the offer
# --------------------------------------------------------------------------- #


def test_no_other_agent_means_no_extra_question(config, tmp_path, capsys):
    """Five questions, as before. Offering to import nothing is a question
    that wastes somebody's time on the screen where their patience is thinnest."""
    drive(config, tmp_path, "1", "1", "1", "1", "1")

    out = capsys.readouterr().out
    assert "1/5" in out

    # Stripped of colour first. This used to read the raw stream, so it was
    # really asserting that no escape sequence on that line contained the
    # digit — which held until a palette changed and `38;5;236m` appeared in
    # a border. The step number is the thing being checked, not the ink.
    plain = re.sub(r"\x1b\[[0-9;:?]*[a-zA-Z]", "", out)
    before = plain.split("Which model provider?")[0].splitlines()
    assert not any("6/" in line for line in before[-3:]), \
        "a sixth step was offered"


def test_an_installation_is_offered_as_the_first_step(config, tmp_path, capsys):
    openclaw(tmp_path)

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    out = capsys.readouterr().out
    assert "You already use OpenClaw" in out
    assert "1/6" in out, "the import is the first of six, not an aside"


def test_the_key_arrives(config, tmp_path):
    openclaw(tmp_path)

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert config.providers["anthropic"].api_key == "sk-ant-brought-over"


def test_starting_fresh_takes_nothing(config, tmp_path):
    openclaw(tmp_path)

    drive(config, tmp_path, "3", "2", "1", "1", "1", "1")

    assert not config.providers["anthropic"].api_key
    assert not list(config.paths.skills.glob("openclaw-*")) \
        if config.paths.skills.is_dir() else True


def test_keys_only_leaves_the_skills_behind(config, tmp_path):
    openclaw(tmp_path)

    drive(config, tmp_path, "2", "1", "1", "1", "1", "1")

    assert config.providers["anthropic"].api_key == "sk-ant-brought-over"
    assert not (config.paths.skills / "openclaw-review").exists()


# --------------------------------------------------------------------------- #
# what the import means for the questions after it
# --------------------------------------------------------------------------- #


def test_the_provider_whose_key_arrived_leads_the_list(config, tmp_path, capsys):
    """Otherwise the wizard announces an Anthropic key and then defaults to a
    provider the person has no key for, which is it contradicting itself."""
    openclaw(tmp_path)

    _, _, answers = drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert answers.provider == "anthropic"
    assert "key imported" in capsys.readouterr().out


def test_an_imported_key_is_never_asked_for_again(config, tmp_path):
    openclaw(tmp_path)

    _, script, _ = drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert script.secrets == [], "the wizard asked for a key it already had"


def test_a_key_can_still_be_replaced_by_hand(config, tmp_path):
    """Offering to keep it is not the same as refusing to change it."""
    openclaw(tmp_path)

    # …, provider, key: "enter a different one", …
    _, script, answers = drive(config, tmp_path, "1", "1", "2", "1", "1", "1")

    assert script.secrets, "the second option must actually ask"
    assert answers.api_key == "sk-typed-by-hand"


def test_the_imported_model_leads_the_model_list(config, tmp_path, capsys):
    openclaw(tmp_path, model="claude-opus-5")

    _, _, answers = drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert answers.model == "claude-opus-5"
    assert "brought over" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# restraint
# --------------------------------------------------------------------------- #


def test_the_other_tool_keeps_working(config, tmp_path):
    """Copy, never move."""
    root = openclaw(tmp_path)

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert (root / "openclaw.json").is_file()
    assert (root / "skills" / "review" / "SKILL.md").is_file()


def test_a_key_you_already_have_is_not_replaced(config, tmp_path):
    openclaw(tmp_path)
    config.providers["anthropic"].api_key = "sk-mine"

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert config.providers["anthropic"].api_key == "sk-mine"


def test_the_key_is_saved_before_the_wizard_finishes(config, tmp_path):
    """Somebody who closes the terminal at the model question should not have
    to go and find their API key a second time."""
    openclaw(tmp_path)
    script = Script("1", "1", "1", "1", "1", "1")
    wizard = SetupWizard(config, prompt=script.prompt, secret=script.secret,
                         home=tmp_path)
    wizard._offer_import(wizard._look_for_another_agent(), 1, 6)

    written = json.loads(config.paths.config_file.read_text(encoding="utf-8"))
    assert written["providers"]["anthropic"]["api_key"] == "sk-ant-brought-over"


def test_no_key_ever_reaches_the_screen(config, tmp_path, capsys):
    """A key on screen is a key in a scrollback buffer, and in whatever
    recording was running."""
    openclaw(tmp_path)

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert "sk-ant-brought-over" not in capsys.readouterr().out


def test_what_was_left_behind_is_said(config, tmp_path, capsys):
    """Somebody with a MEMORY.md in the other tool will look for it here. Not
    finding it, with no explanation, reads as broken rather than decided."""
    root = openclaw(tmp_path)
    (root / "MEMORY.md").write_text("- prefers tabs\n", encoding="utf-8")

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    out = capsys.readouterr().out
    assert "MEMORY.md" in out
    assert out.count("poison recall") == 1, "said once, not once per heading"


def test_another_agent_in_a_broken_state_is_not_fatal(config, tmp_path):
    """The first run is not the place to fail because a different program left
    a file this could not read."""
    root = tmp_path / ".openclaw"
    (root / "skills").mkdir(parents=True)
    (root / "openclaw.json").write_text("{ not json", encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-survived\n", encoding="utf-8")

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert config.providers["anthropic"].api_key == "sk-survived"


# --------------------------------------------------------------------------- #
# where a key already is, said accurately
# --------------------------------------------------------------------------- #


def test_a_key_in_your_environment_is_named_as_such(config, tmp_path, capsys,
                                                    monkeypatch):
    """An environment key is deliberately not copied to disk. Somebody told
    only "already configured" would unset the variable one day and find an
    agent that stopped working and a config file that never held a key."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-in-the-environment")
    config.providers["anthropic"].api_key = "sk-in-the-environment"

    drive(config, tmp_path, "1", "1", "1", "1", "1")

    out = capsys.readouterr().out
    assert "set in your environment ($ANTHROPIC_API_KEY)" in out
    assert "stays there rather than being copied" in out


def test_a_key_in_your_config_file_is_named_as_such(config, tmp_path, capsys):
    config.providers["anthropic"].api_key = "sk-already-saved"

    drive(config, tmp_path, "1", "1", "1", "1", "1")

    out = capsys.readouterr().out
    assert "already in your config file" in out


def test_an_imported_key_is_named_as_imported(config, tmp_path, capsys):
    openclaw(tmp_path)

    drive(config, tmp_path, "1", "1", "1", "1", "1", "1")

    assert "A key for this provider is imported." in capsys.readouterr().out


def test_the_promise_about_the_config_file_is_not_made_falsely(
        config, tmp_path, capsys, monkeypatch):
    """"It is stored in your config file" is true of a key you type and false
    of one in your environment. It is only said where it holds."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-in-the-environment")
    config.providers["anthropic"].api_key = "sk-in-the-environment"

    drive(config, tmp_path, "1", "1", "1", "1", "1")

    assert "It is stored in your config file" not in capsys.readouterr().out
