"""The SSRF guard: what the model's tools may point at."""

from __future__ import annotations

import pytest

from comodor.safety.ssrf import UnsafeURL, assert_url_safe

# -- the refusals ------------------------------------------------------------ #

@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # cloud metadata
    "http://127.0.0.1:8500/",                     # loopback
    "http://10.0.0.5/",                           # RFC1918
    "http://172.16.0.1/",                         # RFC1918
    "http://192.168.1.1/",                        # RFC1918
    "http://100.64.0.1/",                         # CGNAT
    "http://0.0.0.0/",                            # this network
    "http://[::1]/",                              # IPv6 loopback
    "http://[fe80::1]/",                          # IPv6 link-local
    "http://[fc00::1]/",                          # IPv6 unique-local
    "http://metadata.google.internal/",           # metadata by name
    "ftp://example.com/",                         # not http(s)
])
def test_internal_addresses_are_refused(url):
    with pytest.raises(UnsafeURL):
        assert_url_safe(url)


def test_a_metadata_alias_is_refused_by_name():
    with pytest.raises(UnsafeURL) as refused:
        assert_url_safe("http://metadata.google.internal/computeMetadata/")
    assert "metadata" in str(refused.value)


def test_dns_failure_is_refused_not_ignored():
    with pytest.raises(UnsafeURL) as refused:
        assert_url_safe("http://this-host-does-not-exist-6f3a2b.invalid/")
    assert "resolve" in str(refused.value).lower()


# -- the openings ------------------------------------------------------------- #

def test_a_public_address_is_allowed():
    # TEST-NET-3 (203.0.113/24) is documentation space: public, never routed,
    # and no DNS lookup is needed for a literal.
    assert_url_safe("http://203.0.113.10/page")


def test_loopback_opens_when_allowed():
    assert_url_safe("http://127.0.0.1:3000/", allow_loopback=True)
    assert_url_safe("http://localhost:3000/", allow_loopback=True)


def test_the_allowlist_overrides_the_guard():
    assert_url_safe("http://127.0.0.1:8500/",
                    allowlist=["http://127.0.0.1:8500/"])


def test_the_allowlist_is_narrow():
    with pytest.raises(UnsafeURL):
        assert_url_safe("http://10.0.0.1/",
                        allowlist=["http://127.0.0.1:8500/"])


def test_metadata_stays_blocked_even_with_loopback_allowed():
    with pytest.raises(UnsafeURL):
        assert_url_safe("http://169.254.169.254/", allow_loopback=True)


# -- redirects ------------------------------------------------------------------ #

def test_a_redirect_into_the_inside_is_refused():
    from comodor.safety.ssrf import assert_redirect_safe

    with pytest.raises(UnsafeURL):
        assert_redirect_safe("https://example.com/page", "http://127.0.0.1:8500/")


def test_a_redirect_to_a_public_host_is_fine():
    from comodor.safety.ssrf import assert_redirect_safe

    assert_redirect_safe("https://example.com/page", "https://203.0.113.10/page")


# -- the tool surface -------------------------------------------------------------- #

def test_web_fetch_refuses_an_internal_address(tool_context):
    from comodor.tools.web import WebFetch

    result = WebFetch().invoke(tool_context, {"url": "http://169.254.169.254/"})
    assert not result.ok
    assert "refused" in result.content
    assert "metadata" in result.content or "internal" in result.content


def test_web_fetch_refuses_a_non_resolving_host(tool_context):
    from comodor.tools.web import WebFetch

    result = WebFetch().invoke(
        tool_context, {"url": "http://no-such-host-6f3a2b.invalid/"})
    assert not result.ok
    assert "resolve" in result.content.lower()
