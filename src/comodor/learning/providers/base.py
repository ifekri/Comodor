"""The shape one external memory provider has, and how one is built.

Three methods. Anything more and a provider author is implementing our
opinions instead of their service; anything fewer and the mirror either
writes blind or reads nothing. Everything a provider needs to reach its
service comes from the config plus one environment variable named by it —
the key never travels through a file this program writes.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...config import Config


class ProviderError(RuntimeError):
    """A setup problem with the provider — named, not guessed around."""


@dataclass
class Settings:
    """What the `learning.provider` config section holds, resolved."""

    kind: str = ""
    base_url: str = ""
    key_env: str = ""
    mirror_writes: bool = True
    read_augment: bool = False

    @classmethod
    def from_config(cls, config: Config) -> "Settings":
        section = getattr(config.learning, "provider", None)
        if section is None:
            return cls()
        return cls(
            kind=str(getattr(section, "kind", "") or ""),
            base_url=str(getattr(section, "base_url", "") or ""),
            key_env=str(getattr(section, "key_env", "") or ""),
            mirror_writes=bool(getattr(section, "mirror_writes", True)),
            read_augment=bool(getattr(section, "read_augment", False)),
        )


class Provider(ABC):
    """One external memory service, doing at most three things."""

    @abstractmethod
    def mirror_write(self, text: str, kind: str) -> bool:
        """One settled local fact, offered to the service.

        Returns whether it landed. False is ordinary — services time out,
        keys expire — and the caller logs it and moves on: the local fact
        was already true.
        """

    @abstractmethod
    def augment_recall(self, query: str) -> list[str]:
        """What the service would add to a recall, already capped.

        The strings are *lines offered to the briefing*, not facts to be
        trusted: they are marked as coming from outside and limited to the
        augmentation budget before they get anywhere near a prompt.
        """

    @abstractmethod
    def status(self) -> str:
        """One honest line for `doctor` and `/memory` — reachable or why not."""


def build(config: Config) -> Provider | None:
    """The one configured provider, or None — refusing bad setups loudly.

    The one place the rules live. A kind nobody builds, a base URL missing
    where one is needed, a key absent from the environment: each is a
    :class:`ProviderError` naming what to fix, because a mirror configured
    wrong must never degrade into a silent half-mirror.
    """
    settings = Settings.from_config(config)
    if not settings.kind:
        return None

    key = os.environ.get(settings.key_env, "") if settings.key_env else ""
    if not key:
        raise ProviderError(
            f"the memory provider's key must be in ${settings.key_env} — "
            "keys are never read from the config file")
    if not settings.base_url:
        raise ProviderError("the memory provider needs a base_url")

    from .http_generic import HttpGeneric

    if settings.kind in ("http_generic", "mem0"):
        return HttpGeneric(settings, key)
    raise ProviderError(
        f"no memory provider called {settings.kind!r} — "
        "known: http_generic, mem0")


def provider_from_config(config: Config, *, needed: bool = False) -> Provider | None:
    """The configured provider when one is wanted, else None.

    ``needed`` is for the paths where a misconfiguration should stop the
    show (set-up commands); the turn path calls with it False and treats
    every refusal as "no augmentation today".
    """
    try:
        return build(config)
    except ProviderError:
        if needed:
            raise
        return None
