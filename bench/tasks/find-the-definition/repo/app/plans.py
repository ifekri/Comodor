"""Which plan an account is on."""

from __future__ import annotations

DEFAULT = "starter"

ACCOUNTS = {
    "acme": "growth",
    "hooli": "enterprise",
}


def plan_for(account: str) -> str:
    return ACCOUNTS.get(account, DEFAULT)
