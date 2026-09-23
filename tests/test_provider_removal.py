"""B.AI was removed as an official provider. Its old config must be safe.

The removal is a catalogue removal, not an adapter one, and it must not turn a
saved choice into a silent redirect: a user who had B.AI selected must not have
their prompt — or their stored key — sent to a different paid provider. They
are told the provider is gone and asked to choose a replacement.
"""

from __future__ import annotations

import json

from comodor import catalogue
from comodor.config import load


def _write_config(tmp_path, document: dict) -> None:
    home = tmp_path / "comodor-home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(document), encoding="utf-8")


def test_bai_is_absent_from_the_catalogue():
    assert catalogue.get("bai") is None
    assert "bai" not in {spec.id for spec in catalogue.CATALOGUE}
    assert "bai" not in {spec.env_key.lower() for spec in catalogue.CATALOGUE
                         if spec.env_key}


def test_bai_is_absent_from_the_setup_provider_list():
    assert "bai" not in {spec.id for spec in catalogue.offered()}


def test_bai_is_recorded_as_retired():
    assert "bai" in catalogue.RETIRED
    assert catalogue.RETIRED["bai"] == "B.AI"


def test_bai_environment_variables_no_longer_create_a_provider(monkeypatch):
    monkeypatch.setenv("BAI_API_KEY", "sk-bai-secret")
    monkeypatch.setenv("BAI_ENDPOINT", "https://api.b.ai/v1")
    monkeypatch.setenv("BAI_MODEL", "glm-5.3-flash")

    config = load()

    assert "bai" not in config.providers
    assert config.provider != "bai"
    assert all(entry.api_key != "sk-bai-secret"
               for entry in config.providers.values())


def test_an_old_saved_bai_config_does_not_crash_and_needs_setup(tmp_path):
    _write_config(tmp_path, {
        "provider": "bai",
        "model": "glm-5.3-flash",
        "providers": {"bai": {"api_key": "sk-bai-secret",
                              "base_url": "https://api.b.ai/v1",
                              "model": "glm-5.3-flash"}},
    })

    config = load()                                     # must not raise

    assert config.provider == "bai", "the saved name must be kept, not cleared"
    assert config.active() is None
    assert config.needs_setup is True
    assert any("bai" in complaint for complaint in config.complaints)


def test_an_old_saved_bai_config_is_not_silently_routed_elsewhere(tmp_path):
    _write_config(tmp_path, {
        "provider": "bai",
        "providers": {
            "bai": {"api_key": "sk-bai-secret"},
            # Another usable provider is configured, so a naive fallback would
            # pick it and send the prompt there. It must not.
            "openai": {"api_key": "sk-openai", "model": "gpt-4o"},
        },
    })

    config = load()

    assert config.provider == "bai", \
        "a removed provider must not be swapped for another without asking"
    assert config.active() is None


def test_an_old_bai_key_is_not_forwarded_to_another_provider(tmp_path):
    _write_config(tmp_path, {
        "provider": "bai",
        "providers": {
            "bai": {"api_key": "sk-bai-secret"},
            "openai": {"api_key": "sk-openai"},
        },
    })

    config = load()

    assert "bai" not in config.providers
    for entry in config.providers.values():
        assert "sk-bai-secret" not in (entry.api_key or "")
        assert "sk-bai-secret" not in " ".join(entry.api_keys or [])


# --------------------------------------------------------------------------- #
# a project pin must not re-trap the user
# --------------------------------------------------------------------------- #


def _write_project(tmp_path, document: dict):
    project = tmp_path / "project"
    (project / ".comodor").mkdir(parents=True, exist_ok=True)
    (project / ".comodor" / "config.json").write_text(
        json.dumps(document), encoding="utf-8")
    return project


def test_a_project_pin_to_a_retired_provider_does_not_override_the_user(tmp_path):
    """A tracked project file pinning B.AI must not override the replacement
    the user explicitly selected."""
    _write_config(tmp_path, {"provider": "openrouter",
                             "providers": {"openrouter": {"api_key": "sk-or"}}})
    project = _write_project(tmp_path, {"provider": "bai"})

    config = load(cwd=project)

    assert config.provider == "openrouter", \
        "a stale project pin must not override the user's explicit choice"
    assert config.active() is not None
    assert any("bai" in reason for reason in config.project_refused)


def test_a_project_pin_to_a_retired_provider_is_reported(tmp_path):
    _write_config(tmp_path, {"providers": {"openrouter": {"api_key": "sk-or"}}})
    project = _write_project(tmp_path, {"provider": "bai"})

    config = load(cwd=project)

    assert any("no longer supported" in reason for reason in config.project_refused)


def test_a_project_pin_to_a_retired_provider_loads_no_key(tmp_path):
    _write_config(tmp_path, {"providers": {"openrouter": {"api_key": "sk-or"}}})
    project = _write_project(tmp_path, {
        "provider": "bai",
        "providers": {"bai": {"api_key": "sk-bai"}},
    })

    config = load(cwd=project)

    assert "bai" not in config.providers
    assert all("sk-bai" not in (entry.api_key or "")
               for entry in config.providers.values())


def test_a_project_pin_alone_still_requires_setup(tmp_path):
    """Nothing but a retired project pin: no supported provider is auto-picked."""
    project = _write_project(tmp_path, {"provider": "bai"})

    config = load(cwd=project)

    assert config.needs_setup is True
    assert config.active() is None
    assert any("bai" in reason for reason in config.project_refused)
