"""Model discovery: live first, cache next, and nothing invented.

The list of models a provider offers comes from the provider, not from a
hand-written tuple in `catalogue.py`. These pin the contract: live wins, a
fresh cache is used without a request, an old cache is stale evidence, a
failed endpoint is *unknown* availability (never a fabricated list), the cache
belongs to one endpoint, and a capability nobody described stays unknown.

No test here makes a network call; every response is a fake session.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from comodor import catalogue
from comodor.providers import models as discovery

# --------------------------------------------------------------------------- #
# a fake provider endpoint
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Answers `/models` from a script, and remembers what it was asked."""

    def __init__(self, handler):
        self._handler = handler
        self.calls: list[dict] = []
        self.closed = False

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self._handler(url, kwargs)

    def close(self):
        self.closed = True


@pytest.fixture
def endpoint(monkeypatch):
    """Install a fake transport; return a function to set the handler."""
    holder = {"handler": lambda url, kwargs: FakeResponse(200, {"data": []}),
              "sessions": []}

    def install(handler):
        holder["handler"] = handler

    def build(*args, **kwargs):
        session = FakeSession(holder["handler"])
        holder["sessions"].append(session)
        return session

    monkeypatch.setattr("comodor.net.http.Session", build)
    install.holder = holder
    return install


def _ok(payload):
    return lambda url, kwargs: FakeResponse(200, payload)


def _status(code):
    return lambda url, kwargs: FakeResponse(code, {})


# --------------------------------------------------------------------------- #
# live listing
# --------------------------------------------------------------------------- #


def test_an_openai_style_list_is_read_live(tmp_path, endpoint):
    endpoint(_ok({"data": [
        {"id": "gpt-x"},
        {"id": "gpt-y", "context_length": 128000},
    ]}))

    found = discovery.listing("openai", base_url="https://api.openai.com/v1",
                              cache_root=tmp_path)

    assert found.source == "live"
    assert {m.id for m in found.models} == {"gpt-x", "gpt-y"}
    assert found.models[0].context == 0          # the provider said nothing
    assert found.models[1].context == 128000


def test_an_anthropic_list_is_walked_a_page_at_a_time(tmp_path, endpoint):
    pages = {
        "": {"data": [{"id": "claude-a", "display_name": "Claude A",
                       "max_input_tokens": 200000, "max_tokens": 8000}],
             "has_more": True, "last_id": "claude-a"},
        "claude-a": {"data": [{"id": "claude-b"}], "has_more": False},
    }

    def handler(url, kwargs):
        after = (kwargs.get("params") or {}).get("after_id", "")
        return FakeResponse(200, pages[after])

    endpoint(handler)

    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)

    assert found.source == "live"
    assert [m.id for m in found.models] == ["claude-a", "claude-b"]
    assert found.models[0].context == 200000
    assert found.models[0].max_output == 8000
    assert found.models[0].name == "Claude A"
    # The second request asked for the page after the first.
    session = endpoint.holder["sessions"][-1]
    assert session.calls[1]["params"]["after_id"] == "claude-a"


def test_duplicate_model_ids_are_suppressed(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]}))
    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path)
    assert [m.id for m in found.models] == ["a", "b"]


def test_an_unknown_new_model_is_present_and_selectable(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "brand-new-model-2099"}]}))
    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path)
    assert [m.id for m in found.models] == ["brand-new-model-2099"]


# --------------------------------------------------------------------------- #
# unknown vs supplied capabilities
# --------------------------------------------------------------------------- #


def test_an_undescribed_capability_stays_unknown(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "m"}]}))
    model = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path).models[0]
    assert model.tools is None
    assert model.vision is None
    assert model.input_cost is None
    assert model.category == ""


def test_provider_supplied_capabilities_are_preserved(tmp_path, endpoint):
    endpoint(_ok({"data": [{
        "id": "or/model",
        "supported_parameters": ["tools", "temperature"],
        "architecture": {"input_modalities": ["text", "image"],
                         "output_modalities": ["text"]},
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "context_length": 1000000,
    }]}))
    model = discovery.listing("openrouter", base_url="https://openrouter.ai/api/v1",
                              cache_root=tmp_path).models[0]
    assert model.tools is True
    assert model.vision is True
    assert model.category == "agent"
    assert model.context == 1000000
    assert model.input_cost == 3.0
    assert model.output_cost == 15.0


def test_a_structured_non_agent_type_is_filtered_from_the_agent_list(tmp_path, endpoint):
    endpoint(_ok({"data": [
        {"id": "image-only", "architecture": {"output_modalities": ["image"]}},
        {"id": "text-model", "architecture": {"output_modalities": ["text"]}},
        {"id": "unknown-type"},
    ]}))
    found = discovery.listing("openrouter", base_url="https://openrouter.ai/api/v1",
                              cache_root=tmp_path)
    assert {m.id for m in found.agent_models} == {"text-model", "unknown-type"}


# --------------------------------------------------------------------------- #
# failure is unknown, never invented
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("handler,reason", [
    (_ok({"data": []}), "the provider listed nothing"),
    (_status(401), "that key was refused"),
    (_status(403), "that key was refused"),
    (_status(500), "the provider answered 500"),
    (lambda url, kwargs: FakeResponse(200, ValueError("not json")), "ValueError"),
])
def test_a_failed_or_empty_list_is_unavailable_with_a_hint(
        tmp_path, endpoint, handler, reason):
    endpoint(handler)
    found = discovery.listing("openai", api_key="k", base_url="https://x/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert found.models == []
    assert reason in found.error
    # The hand-written hint is offered separately, never as availability.
    assert found.fallback == list(catalogue.get("openai").fallback_models)


def test_a_timeout_is_unavailable(tmp_path, endpoint):
    def handler(url, kwargs):
        raise TimeoutError("slow")
    endpoint(handler)
    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "TimeoutError" in found.error


def test_a_provider_with_no_endpoint_is_unavailable(tmp_path):
    found = discovery.listing("custom", cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "no endpoint" in found.error


# --------------------------------------------------------------------------- #
# the cache
# --------------------------------------------------------------------------- #


def _write(provider, endpoint_url, models, age=0.0, root=Path("."),
           api_key="", headers=None):
    discovery._write_cache(
        discovery.Listing(provider=provider, models=models,
                          fetched_at=time.time() - age, endpoint=endpoint_url),
        root, scope=discovery.scope_for(provider, api_key, headers))


def test_a_fresh_cache_is_used_without_a_request(tmp_path, endpoint):
    def explode(url, kwargs):
        raise AssertionError("the cache should have been used")
    endpoint(explode)
    _write("openai", "https://x/v1",
           [discovery.Model(id="cached-model", context=42)], root=tmp_path)

    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path)

    assert found.source == "cached"
    assert [m.id for m in found.models] == ["cached-model"]


def test_an_old_cache_is_stale_when_the_provider_cannot_be_reached(tmp_path, endpoint):
    endpoint(_status(500))
    _write("openai", "https://x/v1",
           [discovery.Model(id="old-model")], age=discovery.FRESH_FOR + 10,
           root=tmp_path)

    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path)

    assert found.source == "stale"
    assert [m.id for m in found.models] == ["old-model"]
    assert found.error


def test_a_successful_refresh_replaces_the_cache(tmp_path, endpoint):
    _write("openai", "https://x/v1", [discovery.Model(id="old")],
           age=discovery.FRESH_FOR + 10, root=tmp_path)
    endpoint(_ok({"data": [{"id": "new"}]}))

    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path, refresh=True)

    assert found.source == "live"
    assert [m.id for m in found.models] == ["new"]
    kept = discovery.cached("openai", "https://x/v1", tmp_path)
    assert [m.id for m in kept.models] == ["new"]


def test_a_failed_refresh_keeps_the_stale_cache(tmp_path, endpoint):
    _write("openai", "https://x/v1", [discovery.Model(id="old")],
           age=discovery.FRESH_FOR + 10, root=tmp_path)
    endpoint(_status(500))

    found = discovery.listing("openai", base_url="https://x/v1",
                              cache_root=tmp_path, refresh=True)

    assert found.source == "stale"
    assert [m.id for m in found.models] == ["old"]


def test_a_cache_belongs_to_one_endpoint(tmp_path, endpoint):
    endpoint(_status(500))
    _write("openai", "https://endpoint-a/v1", [discovery.Model(id="a-model")],
           root=tmp_path)

    # The same provider on a different endpoint must not reuse endpoint A's list.
    other = discovery.listing("openai", base_url="https://endpoint-b/v1",
                              cache_root=tmp_path)
    assert other.source == "unavailable"
    assert other.models == []

    assert discovery.cached("openai", "https://endpoint-a/v1", tmp_path) is not None
    assert discovery.cached("openai", "https://endpoint-b/v1", tmp_path) is None


def test_the_cache_never_stores_a_key(tmp_path):
    _write("openai", "https://x/v1", [discovery.Model(id="m")], root=tmp_path)
    text = next((tmp_path / "cache").glob("models-openai-*.json")).read_text(
        encoding="utf-8")
    assert "api_key" not in text
    assert "Authorization" not in text


def test_a_corrupt_cache_is_ignored_not_fatal(tmp_path):
    path = discovery._cache_file("openai", tmp_path, "https://x/v1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert discovery.cached("openai", "https://x/v1", tmp_path) is None


# --------------------------------------------------------------------------- #
# local runtimes
# --------------------------------------------------------------------------- #


def test_a_local_runtime_is_listed_live(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "qwen2.5-coder:14b"}]}))
    found = discovery.listing("ollama", base_url="http://localhost:11434/v1",
                              cache_root=tmp_path)
    assert found.source == "live"
    assert [m.id for m in found.models] == ["qwen2.5-coder:14b"]


# --------------------------------------------------------------------------- #
# the request carries the provider's headers
# --------------------------------------------------------------------------- #


def test_a_configured_custom_header_reaches_model_discovery(tmp_path, endpoint):
    seen: dict = {}

    def handler(url, kwargs):
        seen.update(kwargs.get("headers") or {})
        return FakeResponse(200, {"data": [{"id": "m"}]})

    endpoint(handler)
    discovery.listing("openai", api_key="k", base_url="https://x/v1",
                      cache_root=tmp_path,
                      headers={"X-Tenant": "acme", "X-Route": "eu"})

    assert seen.get("X-Tenant") == "acme"
    assert seen.get("X-Route") == "eu"
    # ... and the API-key authentication is still there.
    assert seen.get("Authorization") == "Bearer k"


def test_openrouter_application_headers_travel_with_discovery(tmp_path, endpoint):
    seen: dict = {}
    endpoint(lambda url, kwargs: (seen.update(kwargs.get("headers") or {}),
                                  FakeResponse(200, {"data": [{"id": "m"}]}))[1])
    discovery.listing("openrouter", base_url="https://openrouter.ai/api/v1",
                      cache_root=tmp_path)
    assert seen.get("HTTP-Referer") and seen.get("X-Title")


def test_a_custom_header_does_not_override_authentication(tmp_path, endpoint):
    seen: dict = {}
    endpoint(lambda url, kwargs: (seen.update(kwargs.get("headers") or {}),
                                  FakeResponse(200, {"data": [{"id": "m"}]}))[1])
    discovery.listing("openai", api_key="k", base_url="https://x/v1",
                      cache_root=tmp_path, headers={"X-Tenant": "acme"})
    assert seen.get("Authorization") == "Bearer k"
    assert seen.get("X-Tenant") == "acme"


def test_header_values_are_not_written_to_the_cache(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "m"}]}))
    discovery.listing("openai", api_key="sk-secret-key", base_url="https://x/v1",
                      cache_root=tmp_path, headers={"X-Tenant": "secret-tenant"})

    for path in (tmp_path / "cache").glob("*"):
        assert "sk-secret-key" not in path.name
        assert "secret-tenant" not in path.name
        text = path.read_text(encoding="utf-8")
        assert "sk-secret-key" not in text
        assert "secret-tenant" not in text
        assert "Authorization" not in text


def test_header_values_are_not_in_serialized_listing_output(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "m"}]}))
    found = discovery.listing("openai", api_key="sk-secret-key",
                              base_url="https://x/v1", cache_root=tmp_path,
                              headers={"X-Tenant": "secret-tenant"})
    blob = json.dumps(found.as_dict())
    assert "sk-secret-key" not in blob
    assert "secret-tenant" not in blob


# --------------------------------------------------------------------------- #
# an incomplete paginated walk is never authoritative
# --------------------------------------------------------------------------- #


def _anthropic_pages(pages):
    def handler(url, kwargs):
        after = (kwargs.get("params") or {}).get("after_id", "")
        return pages[after]
    return handler


def test_an_anthropic_page_failure_is_not_a_live_listing(tmp_path, endpoint):
    endpoint(_anthropic_pages({
        "": FakeResponse(200, {"data": [{"id": "claude-a"}],
                               "has_more": True, "last_id": "claude-a"}),
        "claude-a": FakeResponse(500, {}),
    }))
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert found.models == []
    assert "500" in found.error
    assert not list((tmp_path / "cache").glob("models-anthropic-*.json"))


def test_an_anthropic_page_timeout_is_not_a_live_listing(tmp_path, endpoint):
    def handler(url, kwargs):
        if not (kwargs.get("params") or {}).get("after_id"):
            return FakeResponse(200, {"data": [{"id": "claude-a"}],
                                      "has_more": True, "last_id": "claude-a"})
        raise TimeoutError("slow")
    endpoint(handler)
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "TimeoutError" in found.error


def test_an_anthropic_malformed_page_is_not_a_live_listing(tmp_path, endpoint):
    endpoint(_anthropic_pages({
        "": FakeResponse(200, {"data": [{"id": "claude-a"}],
                               "has_more": True, "last_id": "claude-a"}),
        "claude-a": FakeResponse(200, ValueError("not json")),
    }))
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "ValueError" in found.error


def test_has_more_without_a_cursor_is_incomplete(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "claude-a"}], "has_more": True}))
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "cursor" in found.error


def test_a_repeated_cursor_is_incomplete(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "claude-a"}],
                  "has_more": True, "last_id": "same"}))
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "repeated" in found.error


def test_the_page_limit_is_not_treated_as_complete(tmp_path, endpoint):
    def handler(url, kwargs):
        after = (kwargs.get("params") or {}).get("after_id", "") or "start"
        return FakeResponse(200, {"data": [{"id": f"m-{after}"}],
                                  "has_more": True, "last_id": f"c-{after}"})
    endpoint(handler)
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path)
    assert found.source == "unavailable"
    assert "page limit" in found.error


def test_an_incomplete_refresh_preserves_the_complete_cache(tmp_path, endpoint):
    _write("anthropic", "https://api.anthropic.com/v1",
           [discovery.Model(id="claude-old")],
           age=discovery.FRESH_FOR + 10, root=tmp_path, api_key="k")
    endpoint(_anthropic_pages({
        "": FakeResponse(200, {"data": [{"id": "claude-a"}],
                               "has_more": True, "last_id": "claude-a"}),
        "claude-a": FakeResponse(500, {}),
    }))
    found = discovery.listing("anthropic", api_key="k",
                              base_url="https://api.anthropic.com/v1",
                              cache_root=tmp_path, refresh=True)
    assert found.source == "stale"
    assert [m.id for m in found.models] == ["claude-old"]


def test_an_incomplete_walk_never_writes_a_cache(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "claude-a"}], "has_more": True}))
    discovery.listing("anthropic", api_key="k",
                      base_url="https://api.anthropic.com/v1", cache_root=tmp_path)
    assert not list((tmp_path / "cache").glob("models-anthropic-*.json"))


# --------------------------------------------------------------------------- #
# agent-facing filtering
# --------------------------------------------------------------------------- #


def test_as_dict_exposes_the_agent_set_and_the_raw_set(tmp_path, endpoint):
    endpoint(_ok({"data": [
        {"id": "image", "architecture": {"output_modalities": ["image"]}},
        {"id": "text", "architecture": {"output_modalities": ["text"]}},
        {"id": "unknown"},
    ]}))
    found = discovery.listing("openrouter",
                              base_url="https://openrouter.ai/api/v1",
                              cache_root=tmp_path)
    payload = found.as_dict()
    assert {m["id"] for m in payload["models"]} == {"text", "unknown"}
    assert {m["id"] for m in payload["all_models"]} == {"image", "text", "unknown"}


def test_the_adapter_lists_only_agent_models(tmp_path, endpoint):
    from comodor.config import ProviderConfig
    from comodor.providers.gateway import build_provider

    endpoint(_ok({"data": [
        {"id": "image", "architecture": {"output_modalities": ["image"]}},
        {"id": "text", "architecture": {"output_modalities": ["text"]}},
    ]}))
    provider = build_provider(ProviderConfig(
        name="openai", kind="openai", base_url="https://x/v1", api_key="k"))
    try:
        assert provider.list_models() == ["text"]
    finally:
        provider.close()


def test_a_custom_provider_unknown_model_is_still_selectable(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "whatever-1"}]}))
    found = discovery.listing("custom", base_url="https://my-endpoint/v1",
                              cache_root=tmp_path)
    assert [m.id for m in found.agent_models] == ["whatever-1"]


# --------------------------------------------------------------------------- #
# the cache is scoped to the credential/header set
# --------------------------------------------------------------------------- #


def test_the_same_credential_reuses_the_cache(tmp_path, endpoint):
    def explode(url, kwargs):
        raise AssertionError("the cache should have been used")
    endpoint(explode)
    _write("openai", "https://x/v1", [discovery.Model(id="m")],
           root=tmp_path, api_key="key-A")
    found = discovery.listing("openai", api_key="key-A",
                              base_url="https://x/v1", cache_root=tmp_path)
    assert found.source == "cached"


def test_a_changed_credential_does_not_reuse_the_cache(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "b-model"}]}))
    _write("openai", "https://x/v1", [discovery.Model(id="a-model")],
           root=tmp_path, api_key="key-A")
    found = discovery.listing("openai", api_key="key-B",
                              base_url="https://x/v1", cache_root=tmp_path)
    assert found.source == "live"
    assert [m.id for m in found.models] == ["b-model"]


def test_a_changed_tenant_header_does_not_reuse_the_cache(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "b-model"}]}))
    _write("openai", "https://x/v1", [discovery.Model(id="a-model")],
           root=tmp_path, api_key="k", headers={"X-Tenant": "A"})
    found = discovery.listing("openai", api_key="k", base_url="https://x/v1",
                              cache_root=tmp_path, headers={"X-Tenant": "B"})
    assert found.source == "live"


def test_reordered_headers_are_the_same_scope():
    assert discovery.scope_for("openai", "k", {"A": "1", "B": "2"}) == \
        discovery.scope_for("openai", "k", {"B": "2", "A": "1"})


def test_no_secret_appears_in_the_cache_path_or_content(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "m"}]}))
    discovery.listing("openai", api_key="sk-secret", base_url="https://x/v1",
                      cache_root=tmp_path, headers={"X-Tenant": "tenant-secret"})
    for path in (tmp_path / "cache").glob("*"):
        assert "sk-secret" not in path.name
        assert "tenant-secret" not in path.name
        text = path.read_text(encoding="utf-8")
        assert "sk-secret" not in text
        assert "tenant-secret" not in text


def test_a_public_listing_still_caches(tmp_path, endpoint):
    endpoint(_ok({"data": [{"id": "m"}]}))
    discovery.listing("openai", base_url="https://x/v1", cache_root=tmp_path)
    assert discovery.cached("openai", "https://x/v1", tmp_path) is not None
