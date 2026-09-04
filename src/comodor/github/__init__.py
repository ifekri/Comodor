"""Repositories on GitHub, reached through a GitHub App.

A provider, in the same sense Telegram and Slack are: something Comodor can
talk to when it is configured, and which nothing else depends on. Every local
operation — reading a checkout, editing it, running its tests — works with none
of this connected, and that separation is deliberate. GitHub is where some
repositories happen to live, not where Comodor lives.

**Where the private key is, and why it is not here.** A GitHub App
authenticates by signing a JWT with an RSA private key. That key belongs to
the app, not to the person running the agent, and putting it on every user's
machine would hand each of them the ability to act as the app against every
installation — including installations belonging to somebody else. So it stays
in one place, on the Worker at `comodor.ai`, and this module never sees it.

What travels instead is an installation access token: minted by the Worker
from that key, scoped to one installation, and valid for an hour. It is
fetched when it is needed and held in memory for as long as it is useful.
Nothing writes one to disk.

    Agent                    Worker (comodor.ai)         GitHub
      |                             |                       |
      |-- POST /token ------------->|                       |
      |   installation_id           |-- sign JWT (RSA) ---->|
      |   connection secret         |<-- installation token-|
      |<-- token, expires_at -------|                       |
      |                                                     |
      |-- GET /repos/... (Bearer token) -------------------->|

The three credentials GitHub defines are kept apart, because conflating them
is the usual way these integrations go wrong:

* an **app JWT** proves "I am this app" and is only ever made server-side;
* an **installation token** authorises repository work and is what this
  module carries;
* an **OAuth user token** would prove "I am this GitHub user" — Comodor needs
  no such claim, so no OAuth flow exists here.
"""

from __future__ import annotations

from .api import GitHub, GitHubError, NotConnected, RateLimited, Refused
from .tokens import InstallationToken, Tokens

__all__ = [
    "GitHub",
    "GitHubError",
    "InstallationToken",
    "NotConnected",
    "RateLimited",
    "Refused",
    "Tokens",
]
