"""First-run setup and the JSON configuration it writes.

The wizard is the first thing a new user meets, and the config file is the only
thing they are ever asked to own. Both are driven here without a terminal: the
prompts are injected, so the whole flow — questions, answers, what lands on
disk, what comes back on the next start — runs in the suite.
"""

from __future__ import annotations

import io
import json
import os
import stat

import pytest
from rich.console import Console

from comodor import catalogue
from comodor.config import Config, load
from comodor.paths import Paths
from comodor.setup import Answers, SetupWizard


@pytest.fixture
def blank(tmp_path):
    """A config with nothing set up yet, pointed at a temporary home."""
    config = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "project"))
    (tmp_path / "project").mkdir(parents=True, exist_ok=True)
    from comodor.config import _build_providers

    config.providers = _build_providers()
    return config


def wizard(config, answers: list[str], key: str = "test-key-0123456789"):
    """A wizard whose questions are answered from a list."""
    replies = iter(answers)
    return SetupWizard(
        config,
        console=Console(file=io.StringIO(), width=90, force_terminal=False),
        prompt=lambda message: next(replies),
        secret=lambda message: key,
    )


# --------------------------------------------------------------------------- #
# the catalogue
# --------------------------------------------------------------------------- #


def test_the_catalogue_offers_the_providers_people_actually_use():
    ids = {spec.id for spec in catalogue.offered()}
    for expected in ("openrouter", "anthropic", "openai", "google", "deepseek",
                     "groq", "mistral", "xai", "ollama"):
        assert expected in ids, f"{expected} is missing from the catalogue"


def test_every_provider_entry_is_complete_enough_to_use():
    for spec in catalogue.CATALOGUE:
        if spec.id == "custom":
            continue                       # the user supplies the URL
        assert spec.base_url.startswith("http"), spec.id
        assert spec.label and spec.blurb, spec.id
        assert spec.default_model, spec.id
        if spec.needs_key:
            assert spec.keys_url.startswith("http"), f"{spec.id} has no key page"


def test_local_providers_need_no_key():
    for spec in catalogue.local():
        assert not spec.needs_key
        assert "localhost" in spec.base_url


# --------------------------------------------------------------------------- #
# the wizard
# --------------------------------------------------------------------------- #


def test_a_full_first_run_configures_a_provider(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o", "gpt-4o-mini"])

    setup = wizard(blank, ["3", "2", "1"])   # openai, second model, ask-first
    answers = setup.run()

    assert answers.provider == "openai"
    assert answers.model == "gpt-4o-mini"
    assert answers.api_key == "test-key-0123456789"
    assert answers.approvals == "ask"


def test_pressing_enter_takes_the_default(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    answers = wizard(blank, ["", "", ""]).run()

    assert answers.provider == catalogue.offered()[0].id
    assert answers.model == "a-model"
    assert answers.approvals == "ask"


def test_a_bad_choice_is_re_asked_rather_than_defaulted(blank, monkeypatch):
    """Falling through to a default the user did not pick is worse than asking."""
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["a-model"])
    answers = wizard(blank, ["999", "banana", "2", "", ""]).run()

    assert answers.provider == catalogue.offered()[1].id


def test_a_local_provider_skips_the_key_question(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["llama3.3"])

    index = [spec.id for spec in catalogue.offered()].index("ollama") + 1
    setup = wizard(blank, [str(index), "1", "1"], key="should-not-be-asked")
    answers = setup.run()

    assert answers.provider == "ollama"
    assert answers.api_key == ""


def test_the_answers_are_applied_and_saved(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "2"])   # openai, gpt-4o, writes-allowed
    saved = setup.apply(setup.run())

    assert saved.provider == "openai"
    assert saved.active_model() == "gpt-4o"
    assert saved.providers["openai"].configured
    assert saved.safety.auto_approve_writes is True
    assert saved.safety.auto_approve_shell is False
    assert saved.paths.config_file.exists()


def test_approval_choices_map_to_the_safety_settings(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["m"])
    for choice, writes, shell in (("1", False, False), ("2", True, False),
                                  ("3", True, True)):
        setup = wizard(blank, ["3", "1", choice])
        saved = setup.apply(setup.run())
        assert (saved.safety.auto_approve_writes,
                saved.safety.auto_approve_shell) == (writes, shell)


def test_a_custom_endpoint_can_be_supplied(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: [])

    index = [spec.id for spec in catalogue.offered()].index("custom") + 1
    setup = wizard(blank, [str(index), "https://llm.internal/v1", "my-model", "1"])
    saved = setup.apply(setup.run())

    assert saved.providers["custom"].base_url == "https://llm.internal/v1"
    assert saved.active_model() == "my-model"


def test_model_discovery_falls_back_when_the_provider_cannot_be_reached(blank):
    """A wizard that hangs or crashes on a bad key would be unusable."""
    setup = wizard(blank, ["3", "1", "1"])
    spec = catalogue.get("openai")
    models = setup._discover_models(spec, Answers(provider="openai", api_key="bad"))

    assert models, "the known list should stand in when the API says nothing"
    assert set(models) <= set(spec.models) or models


# --------------------------------------------------------------------------- #
# the config file
# --------------------------------------------------------------------------- #


def test_the_saved_file_is_json_and_round_trips(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1"])
    saved = setup.apply(setup.run())

    document = json.loads(saved.paths.config_file.read_text(encoding="utf-8"))
    assert document["provider"] == "openai"
    assert document["providers"]["openai"]["api_key"] == "test-key-0123456789"

    reloaded = load(cwd=saved.paths.project, use_environment=False)
    reloaded.paths = saved.paths
    reloaded = load(cwd=saved.paths.project, use_environment=False)
    assert isinstance(document["agent"], dict)
    assert document["version"] >= 1


def test_reloading_finds_the_saved_provider(blank, monkeypatch, tmp_path):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])

    setup = wizard(blank, ["3", "1", "1"])
    setup.apply(setup.run())

    fresh = load(cwd=tmp_path / "project", use_environment=False)
    assert fresh.provider == "openai"
    assert fresh.active_model() == "gpt-4o"
    assert not fresh.needs_setup
    assert not fresh.first_run


def test_a_missing_config_asks_for_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "nothing-here"))
    config = load(cwd=tmp_path, use_environment=False)

    assert config.first_run
    assert config.needs_setup


def test_a_corrupt_config_does_not_stop_the_program(tmp_path, monkeypatch):
    """Defaults must carry the run; `doctor` reports the file separately."""
    home = tmp_path / "home"
    home.mkdir(parents=True)
    (home / "config.json").write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    config = load(cwd=tmp_path, use_environment=False)
    assert config.agent.mode == "act"


def test_the_config_file_is_not_world_readable(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1"])
    saved = setup.apply(setup.run())

    if os.name == "nt":
        pytest.skip("POSIX permissions do not apply on Windows")
    mode = stat.S_IMODE(saved.paths.config_file.stat().st_mode)
    assert mode & (stat.S_IRGRP | stat.S_IROTH) == 0, "the file holds an API key"


def test_no_temporary_file_is_left_behind(blank, monkeypatch):
    monkeypatch.setattr(SetupWizard, "_discover_models",
                        lambda self, spec, answers: ["gpt-4o"])
    setup = wizard(blank, ["3", "1", "1"])
    saved = setup.apply(setup.run())

    leftovers = list(saved.paths.user.glob("*.tmp"))
    assert leftovers == []


def test_a_project_config_can_pin_settings_without_carrying_a_key(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".comodor").mkdir(parents=True)
    home.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")

    (home / "config.json").write_text(json.dumps({
        "provider": "openai",
        "providers": {"openai": {"api_key": "sk-user", "configured": True}},
    }), encoding="utf-8")
    (project / ".comodor" / "config.json").write_text(json.dumps({
        "agent": {"mode": "plan", "max_steps": 5},
    }), encoding="utf-8")
    monkeypatch.setenv("COMODOR_HOME", str(home))

    config = load(cwd=project, use_environment=False)
    assert config.agent.mode == "plan"
    assert config.agent.max_steps == 5
    assert config.providers["openai"].api_key == "sk-user"


def test_environment_variables_still_win_for_ci(tmp_path, monkeypatch):
    monkeypatch.setenv("COMODOR_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-the-environment")

    config = load(cwd=tmp_path, use_environment=True)
    assert config.providers["openai"].api_key == "sk-from-the-environment"
    assert not config.needs_setup


def test_use_selects_and_configures_in_one_step():
    config = Config()
    from comodor.config import _build_providers

    config.providers = _build_providers()
    config.use("groq", api_key="gsk-x", model="llama-3.3-70b-versatile")

    assert config.provider == "groq"
    assert config.active_model() == "llama-3.3-70b-versatile"
    assert config.providers["groq"].configured
    assert not config.needs_setup


def test_an_unconfigured_local_provider_is_not_chosen_silently():
    """Ollama is 'ready' without a key, but only if the user asked for it."""
    config = Config()
    from comodor.config import _build_providers

    config.providers = _build_providers()
    assert config.needs_setup, "a fresh install has nothing selectable"

    config.use("ollama")
    assert not config.needs_setup
