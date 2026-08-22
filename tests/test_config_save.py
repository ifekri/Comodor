"""What `/save` writes, and what it must not.

The configuration the agent runs on is merged from four places: the user's own
file, the repository's `.comodor/config.json`, the environment and the command
line. Saving that merged object into the user's file is what these tests exist
to prevent: one `/save` in a cloned repository would otherwise make that
repository's spend ceiling the person's permanent default, and would copy an
API key they had deliberately kept in their environment onto disk.

The other half matters just as much. A setting they change during the session
is theirs, and pressing save has to keep it.
"""

from __future__ import annotations

import json

import pytest

from comodor.config import load


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / ".comodor"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "COMODOR_MODEL",
                 "COMODOR_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "project").mkdir()
    return tmp_path


def mine(home, **document):
    path = home / ".comodor" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def theirs(home, **document):
    path = home / "project" / ".comodor" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def written(home):
    return json.loads((home / ".comodor" / "config.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# what must not be written
# --------------------------------------------------------------------------- #


def test_a_repositorys_setting_does_not_become_your_default(home):
    """Clone a repository, press save once, and its choices would otherwise
    follow you into every other project you ever open."""
    mine(home, model="the-model-i-chose", agent={"max_steps": 10})
    theirs(home, model="a-model-this-repository-prefers",
           agent={"max_steps": 999})

    config = load(cwd=home / "project")
    assert config.agent.max_steps == 999, "it should apply while running"
    config.save()

    assert written(home)["model"] == "the-model-i-chose"
    assert written(home)["agent"]["max_steps"] == 10


def test_a_repositorys_spend_ceiling_does_not_become_yours(home):
    mine(home)
    theirs(home, agent={"max_cost_usd": 500.0})

    config = load(cwd=home / "project")
    config.save()

    assert written(home)["agent"]["max_cost_usd"] == 2.0


def test_a_key_you_keep_in_your_environment_stays_there(home, monkeypatch):
    """Somebody who exports a key rather than saving one has made a decision.
    Writing it to disk quietly reverses it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-only-in-my-environment")
    mine(home)

    config = load(cwd=home / "project")
    assert config.providers["anthropic"].api_key == "sk-only-in-my-environment"
    config.save()

    body = (home / ".comodor" / "config.json").read_text(encoding="utf-8")
    assert "sk-only-in-my-environment" not in body


def test_a_flag_typed_once_is_not_permanent(home):
    mine(home, agent={"mode": "act"})

    config = load(cwd=home / "project", overrides={"agent": {"mode": "plan"}})
    assert config.agent.mode == "plan"
    config.save()

    assert written(home)["agent"]["mode"] == "act"


# --------------------------------------------------------------------------- #
# what must be written
# --------------------------------------------------------------------------- #


def test_something_you_change_while_running_is_kept(home):
    """`/model x` then `/save` has to mean what it says."""
    mine(home, model="the-old-one")

    config = load(cwd=home / "project")
    config.model = "the-one-i-just-picked"
    config.save()

    assert written(home)["model"] == "the-one-i-just-picked"


def test_changing_a_setting_a_repository_also_set_still_works(home):
    """The repository's value is refused; the user's own choice of the same
    setting is not."""
    mine(home, agent={"max_steps": 10})
    theirs(home, agent={"max_steps": 999})

    config = load(cwd=home / "project")
    config.agent.max_steps = 50
    config.save()

    assert written(home)["agent"]["max_steps"] == 50


def test_a_key_you_type_is_saved(home):
    """Which is what the setup wizard does, and it promises as much on screen."""
    mine(home)

    config = load(cwd=home / "project")
    config.use("anthropic", api_key="sk-typed-by-hand", model="claude-sonnet-5")
    config.save()

    again = load(cwd=home / "project")
    assert again.providers["anthropic"].api_key == "sk-typed-by-hand"
    assert again.model == "claude-sonnet-5"
    assert again.provider == "anthropic"


def test_a_key_that_replaces_one_from_the_environment_is_saved(home, monkeypatch):
    """Typing a different key over an environment one is an explicit choice."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-environment")
    mine(home)

    config = load(cwd=home / "project")
    config.use("anthropic", api_key="sk-i-typed-this-instead")
    config.save()

    body = (home / ".comodor" / "config.json").read_text(encoding="utf-8")
    assert "sk-i-typed-this-instead" in body
    assert "sk-from-the-environment" not in body


def test_an_imported_key_is_saved(home):
    """The import writes into the configuration after it is loaded, so it is
    the user's own doing and not a borrowed layer."""
    mine(home)
    claw = home / ".openclaw"
    claw.mkdir()
    (claw / "openclaw.json").write_text(json.dumps({
        "models": {"providers": {"anthropic": {
            "apiKey": "sk-from-openclaw",
            "baseUrl": "https://api.anthropic.com/v1"}}}}), encoding="utf-8")

    from comodor import migrate

    config = load(cwd=home / "project")
    migrate.apply(migrate.discover(home)[0], config)
    config.save()

    assert written(home)["providers"]["anthropic"]["api_key"] == "sk-from-openclaw"


def test_saving_twice_is_stable(home):
    """A round trip that drifts turns every save into a slow rewrite of the
    file into something nobody chose."""
    mine(home, model="mine", agent={"max_steps": 7})
    theirs(home, agent={"max_steps": 999})

    load(cwd=home / "project").save()
    once = written(home)
    load(cwd=home / "project").save()

    assert written(home) == once
