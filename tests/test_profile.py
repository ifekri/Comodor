"""What the model in front of us can do, and what follows from it.

`ModelInfo.supports_tools` and `supports_vision` have been in the registry
since it was written and nothing read either of them. The one that costs
something is the window: `agent.context_limit` defaults to a million, and the
agent loop fell back to 128k when it was unset — neither number describes any
particular model. Against a 32k model that means compaction never fires, the
conversation grows past what the model can read, and the first sign of it is
the provider refusing the request.
"""

from __future__ import annotations

import json

import pytest

from comodor.config import Config, ProviderConfig
from comodor.paths import Paths
from comodor.providers import profile


@pytest.fixture
def settings(tmp_path):
    made = Config(paths=Paths(user=tmp_path / "home", project=tmp_path / "work"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    (tmp_path / "work").mkdir(parents=True, exist_ok=True)
    return made


def a_cached_catalogue(root, provider: str, entries: list[dict]):
    """What the model picker leaves on disk after listing a provider."""
    where = root / "cache"
    where.mkdir(parents=True, exist_ok=True)
    (where / f"models-{provider}.json").write_text(
        json.dumps({"provider": provider, "fetched_at": 1.0, "models": entries}),
        encoding="utf-8")


# --------------------------------------------------------------------------- #
# the window
# --------------------------------------------------------------------------- #


def test_a_known_model_uses_its_real_window(settings):
    settings.model = "claude-haiku-4-5"
    settings.agent.context_limit = 1_000_000

    found = profile.of(settings)

    assert found.context == 200_000, "the registry knows this one"
    assert found.source == "registry"


def test_a_local_model_takes_the_window_its_provider_published(settings):
    """The bug this exists for. Nothing in the registry knows a local model, so
    the configured million stood and compaction never fired."""
    settings.provider = "ollama"
    settings.model = "qwen2.5-coder:7b"
    settings.agent.context_limit = 1_000_000
    a_cached_catalogue(settings.paths.user, "ollama",
                       [{"id": "qwen2.5-coder:7b", "context": 32_768}])

    found = profile.of(settings)

    assert found.context == 32_768
    assert found.source == "provider"
    assert found.cramped


def test_where_two_sources_disagree_the_smaller_wins(settings):
    """Compacting sooner than needed costs a summary. Compacting later than the
    model can bear costs the turn, and the error does not say why."""
    settings.provider = "openrouter"
    settings.model = "some-model"
    settings.agent.context_limit = 500_000
    a_cached_catalogue(settings.paths.user, "openrouter",
                       [{"id": "some-model", "context": 8_192}])

    assert profile.of(settings).context == 8_192


def test_a_configured_window_is_honoured_when_nobody_else_knows(settings):
    settings.provider = "custom"
    settings.model = "something-nobody-has-heard-of"
    settings.agent.context_limit = 64_000

    found = profile.of(settings)

    assert found.context == 64_000
    assert found.source == "configured"


def test_an_absurd_configured_window_is_ignored(settings):
    """A limit of 100 tokens cannot hold the system prompt. It is far likelier
    to be a typo or a mis-parsed entry than a real window."""
    settings.provider = "custom"
    settings.model = "unknown-thing"
    settings.agent.context_limit = 100

    assert profile.of(settings).context > profile.IMPLAUSIBLE


def test_no_information_at_all_still_gives_a_usable_number(settings):
    settings.provider = ""
    settings.model = ""
    settings.agent.context_limit = 0

    found = profile.of(settings)

    assert found.context > 0, "the loop divides by this"


def test_a_corrupt_catalogue_cache_is_ignored_not_fatal(settings):
    settings.provider = "ollama"
    settings.model = "whatever"
    settings.agent.context_limit = 128_000
    where = settings.paths.user / "cache"
    where.mkdir(parents=True, exist_ok=True)
    (where / "models-ollama.json").write_text("{not json", encoding="utf-8")

    assert profile.of(settings).context == 128_000


# --------------------------------------------------------------------------- #
# the rest of what the registry already knew and nobody read
# --------------------------------------------------------------------------- #


def test_an_unknown_model_is_not_assumed_to_do_several_calls_at_once(settings):
    """A local runtime handed six parallel calls tends to return one malformed
    blob, and the turn is spent on it."""
    settings.provider = "ollama"
    settings.model = "some-small-thing"

    assert profile.of(settings).parallel_tools is False


def test_a_known_model_may_be_asked_for_several_at_once(settings):
    settings.model = "claude-sonnet-5"

    assert profile.of(settings).parallel_tools is True


def test_vision_is_only_claimed_where_it_is_known(settings):
    settings.model = "claude-sonnet-5"
    assert profile.of(settings).vision is True

    settings.model = "a-model-nobody-catalogued"
    assert profile.of(settings).vision is False


# --------------------------------------------------------------------------- #
# what the loop does with it
# --------------------------------------------------------------------------- #


def test_the_loop_compacts_against_the_model_not_the_config(settings, bus):
    """The whole point: a small model must trigger compaction that a config
    saying "one million" would have suppressed forever."""
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    settings.providers["fake"] = ProviderConfig(
        name="fake", kind="fake", base_url="offline", api_key="k",
        model="scripted", configured=True)
    settings.provider = "ollama"
    settings.model = "tiny-local-model"
    settings.agent.context_limit = 1_000_000
    a_cached_catalogue(settings.paths.user, "ollama",
                       [{"id": "tiny-local-model", "context": 8_192}])

    agent = AgentLoop(settings, Gateway(settings), ToolRegistry(), bus,
                      PermissionEngine(settings, bus), Conversation())

    assert agent._window() == 8_192, \
        "the loop is still working to a number nothing measured"


def test_a_broken_profile_does_not_stop_a_turn(settings, bus, monkeypatch):
    from comodor.agent import AgentLoop, Conversation
    from comodor.providers.gateway import Gateway
    from comodor.safety import PermissionEngine
    from comodor.tools import ToolRegistry

    monkeypatch.setattr(profile, "of",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    settings.agent.context_limit = 250_000

    agent = AgentLoop(settings, Gateway(settings), ToolRegistry(), bus,
                      PermissionEngine(settings, bus), Conversation())

    assert agent._window() == 250_000
