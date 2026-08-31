"""The SSRF guard: what the model may point an HTTP tool at.

`web_fetch`, `browse`, `@url` — every URL the *model* can steer — is checked
here before a connection is opened. The danger is specific: an agent running
on a cloud VM or a home server can be talked into fetching
`http://169.254.169.254/latest/meta-data/` or an internal admin panel, and
the response is summarised back to it. Guarding only the hostname is not
enough, so the check is on the resolved address: a DNS name that resolves
into a private range is caught, which is the basic form of DNS rebinding.

Fail-closed throughout: a hostname that will not resolve is refused, not
allowed through on the strength of "maybe it will connect anyway".

The guard never applies to Comodor's own traffic. Provider API calls,
Telegram, Slack — everything the program itself dials — goes through the
same HTTP client with the guard off. The model's path is the only one gated,
because the model is the only component that can be talked into misuse.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

#: Cloud metadata hostnames, blocked by name as well as by address — the
#: address is a link-local literal, but an /etc/hosts alias would not be.
_METADATA_HOSTS = {
    "metadata.google.internal", "metadata.goog",
    "metadata.azure.com", "metadata.internal",
    "instance-data", "instance-data.ec2.internal",
}

#: Reserved ranges a tool has no business reaching.
_PRIVATE_RANGES = tuple(ipaddress.ip_network(range) for range in (
    "127.0.0.0/8",          # loopback
    "10.0.0.0/8",           # RFC1918
    "172.16.0.0/12",        # RFC1918
    "192.168.0.0/16",       # RFC1918
    "169.254.0.0/16",       # link-local — includes cloud metadata
    "100.64.0.0/10",        # CGNAT
    "0.0.0.0/8",            # "this network"
    "fe80::/10",            # IPv6 link-local
    "fc00::/7",             # IPv6 unique-local
    "::1/128",              # IPv6 loopback
))


class UnsafeURL(Exception):
    """A URL the model's tools may not open, with the reason shown to the
    model so it understands the refusal rather than retrying blindly."""


def assert_url_safe(url: str, *, allow_loopback: bool = False,
                    allowlist: list[str] | None = None) -> None:
    """Refuse any URL the tools must not open. Raises :class:`UnsafeURL`.

    ``allow_loopback`` and ``allowlist`` exist because Comodor runs its own
    web server: a user who trusts this machine's localhost (their own dev
    server, for instance) can open it per-project. The default is closed.
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"only http and https can be fetched, not "
                        f"{parts.scheme!r}")
    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise UnsafeURL("the URL has no host")

    if allowlist and _allowlisted(url, allowlist):
        return
    if host in _METADATA_HOSTS:
        raise UnsafeURL(f"{host} is a cloud metadata endpoint — internal "
                        "credentials live there, so it is never fetched")
    if allow_loopback and (host == "localhost" or _is_loopback_literal(host)):
        return

    addresses = _resolve(host)
    for address in addresses:
        _refuse_if_private(address, host)


def assert_redirect_safe(current: str, location: str) -> None:
    """One redirect hop: the destination must pass the same check.

    An external page that redirects to `http://127.0.0.1:8500` is refused at
    the hop, not after it — the connection to the internal address is never
    opened.
    """
    from urllib.parse import urljoin

    assert_url_safe(urljoin(current, location.strip()))


def _allowlisted(url: str, allowlist: list[str]) -> bool:
    """Explicit user trust. Prefix-based: the user wrote the rule, the rule
    says what it trusts."""
    return any(url.startswith(pattern) for pattern in allowlist)


def _is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _resolve(host: str) -> list[ipaddress.IPAddress]:
    """Resolve to addresses, or refuse. Failure is not permission."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise UnsafeURL(f"{host} does not resolve — refusing rather than "
                        "assuming it would be safe") from error
    addresses = []
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UnsafeURL(f"{host} resolved to nothing")
    return addresses


def _refuse_if_private(address: ipaddress.IPAddress, host: str) -> None:
    for network in _PRIVATE_RANGES:
        if address in network:
            raise UnsafeURL(
                f"{host} resolves to {address}, which is inside {network} — "
                "an internal address, and the tools do not open internal "
                "addresses")
