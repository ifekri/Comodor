"""The key pool: rotation across one provider's keys, honest masking, and
the rule that a rate limit cools a key instead of stalling the session."""

from __future__ import annotations

from comodor.config import ProviderConfig
from comodor.providers.pool import DEFAULT_COOLDOWN_SECONDS, KeyPool, pool_keys

# -- the key list --------------------------------------------------------------- #

def test_api_key_leads_and_duplicates_are_dropped():
    entry = ProviderConfig(name="x", api_key="a", api_keys=["a", "b", "c"])
    assert pool_keys(entry) == ["a", "b", "c"]


def test_a_single_key_user_has_a_pool_of_one():
    assert pool_keys(ProviderConfig(name="x", api_key="a")) == ["a"]


def test_a_keyless_provider_has_no_pool():
    assert pool_keys(ProviderConfig(name="x")) == []


# -- rotation --------------------------------------------------------------------- #

def test_keys_rotate_round_robin():
    pool = KeyPool(provider="p", keys=["a", "b", "c"])
    drawn = [pool.next_key()[0] for _ in range(6)]
    assert drawn == ["a", "b", "c", "a", "b", "c"]


def test_a_rate_limited_key_is_skipped():
    pool = KeyPool(provider="p", keys=["a", "b"])
    pool.report_rate_limited("a")
    drawn = [pool.next_key()[0] for _ in range(4)]
    assert drawn == ["b", "b", "b", "b"]


def test_retry_after_from_the_provider_is_honoured():
    pool = KeyPool(provider="p", keys=["a"])
    pool.report_rate_limited("a", retry_after=300.0)
    assert pool.status()[0]["cooldown_left"] > 60.0


def test_a_cooldown_uses_the_default_without_retry_after():
    pool = KeyPool(provider="p", keys=["a"])
    pool.report_rate_limited("a")
    left = pool.status()[0]["cooldown_left"]
    assert DEFAULT_COOLDOWN_SECONDS - 1 <= left <= DEFAULT_COOLDOWN_SECONDS


def test_a_success_clears_the_cooldown():
    pool = KeyPool(provider="p", keys=["a"])
    pool.report_rate_limited("a")
    pool.report_ok("a")
    assert pool.status()[0]["healthy"]


def test_when_every_key_cools_the_soonest_unlocking_is_used():
    pool = KeyPool(provider="p", keys=["a", "b"])
    pool.report_rate_limited("a", retry_after=300.0)
    pool.report_rate_limited("b", retry_after=30.0)
    key, _ = pool.next_key()
    assert key == "b"                      # b unlocks before a does


def test_the_wait_message_names_the_time_and_masks_the_key():
    pool = KeyPool(provider="p", keys=["verylongsecretkey"])
    pool.report_rate_limited("verylongsecretkey")
    message = pool.wait_message()
    assert "rate-limited" in message
    assert "verylongsecretkey" not in message


# -- masking ----------------------------------------------------------------------- #

def test_keys_are_never_shown_in_full():
    pool = KeyPool(provider="p", keys=["sk-abcdefghij123456"])
    masked = pool.next_key()[1]
    assert masked.startswith("sk-abc")
    assert masked.endswith("3456")
    assert "abcdefghij123456" not in masked


def test_a_short_key_still_never_shows_itself():
    pool = KeyPool(provider="p", keys=["abc"])
    assert pool.next_key()[1] != "abc"


def test_the_status_reports_only_masked_keys():
    pool = KeyPool(provider="p", keys=["sk-full-secret-value"])
    for entry in pool.status():
        assert "sk-full-secret-value" not in str(entry)


def test_usage_is_counted_per_key():
    pool = KeyPool(provider="p", keys=["long-key-a", "long-key-b"])
    for _ in range(3):
        pool.next_key()
    pool.report_rate_limited("long-key-a")
    uses = {entry["key"]: entry["uses"] for entry in pool.status()}
    assert sum(uses.values()) == 3
    # The rate limit adds a draw for the retry path — but only there. The
    # report itself never draws a key.
    assert pool.status()[0]["rate_limits"] == 1


# -- the gateway wiring -------------------------------------------------------------- #

def test_the_gateway_builds_a_pool_only_for_multi_key_providers(config):
    from comodor.providers.gateway import Gateway

    config.providers["one"] = ProviderConfig(
        name="one", kind="openai", base_url="https://one.example", api_key="a")
    config.providers["many"] = ProviderConfig(
        name="many", kind="openai", base_url="https://many.example",
        api_key="a", api_keys=["b", "c"])
    gateway = Gateway(config)
    assert gateway.pool("one") is None
    assert gateway.pool("many") is not None
    assert len(gateway.pool("many")) == 3
    assert gateway.pool_status("one") == []


def test_a_pooled_provider_receives_the_pool(config):
    from comodor.providers.gateway import Gateway

    config.providers["many"] = ProviderConfig(
        name="many", kind="openai", base_url="https://many.example",
        api_key="a", api_keys=["b"])
    gateway = Gateway(config)
    provider = gateway.provider("many")
    assert provider.key_pool is not None
    assert len(provider.key_pool) == 2


# -- the adapter retry ------------------------------------------------------------------ #

def test_an_openai_429_rotates_to_the_next_key_before_streaming():
    from comodor.providers.openai_compat import OpenAICompatProvider

    stale, fresh = "sk-stale-key-0001", "sk-fresh-key-0002"
    pool = KeyPool(provider="p", keys=[stale, fresh])
    provider = OpenAICompatProvider(
        name="p", base_url="https://p.example", api_key=stale,
        key_pool=pool)

    responses = {
        stale: _response(429, retry_after="10"),
        fresh: _response(200),
    }

    class FakeSession:
        def post(self, url, json=None, stream=False, headers=None):
            key = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
            return responses[key]

    provider._session = FakeSession()
    body = {"model": "m", "messages": []}
    response = provider._post(body)
    assert response.status_code == 200
    # The stale key cooled down; the fresh one is healthy and marked used.
    states = {entry["key"]: entry for entry in pool.status()}
    assert states[pool._states[0].masked]["healthy"] is False
    assert states[pool._states[1].masked]["healthy"] is True


def test_an_anthropic_429_rotates_to_the_next_key():
    from comodor.providers.anthropic import AnthropicProvider
    from comodor.providers.pool import KeyPool as Pool

    stale, fresh = "sk-ant-stale-0001", "sk-ant-fresh-0002"
    pool = Pool(provider="p", keys=[stale, fresh])
    provider = AnthropicProvider(
        name="p", base_url="https://p.example/v1", api_key=stale,
        key_pool=pool)

    class FakeSession:
        def post(self, url, json=None, stream=False, headers=None):
            key = (headers or {}).get("x-api-key", "")
            return _response(200 if key == fresh else 429)

    provider._session = FakeSession()
    response = provider._send({"model": "m", "messages": []})
    assert response.ok


def _response(status, retry_after=None):
    class FakeResponse:
        ok = status < 400
        status_code = status

        def __init__(self):
            self.headers = {"Retry-After": retry_after} if retry_after else {}

        @property
        def retry_after(self):
            value = self.headers.get("Retry-After")
            return float(value) if value else None

        def close(self):
            pass

    return FakeResponse()
