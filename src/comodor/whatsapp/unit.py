"""Handing the WhatsApp bot to the operating system.

The work is in `channels.unit`, which does the same for Telegram.
"""

from __future__ import annotations

from ..channels import WHATSAPP
from ..channels import unit as shared
from ..channels.unit import Unit  # noqa: F401  (re-exported)
from ..config import Config


def plan(config: Config) -> Unit:
    return shared.plan(config, WHATSAPP)


def install(config: Config) -> tuple[bool, str, Unit]:
    return shared.install(config, WHATSAPP)


def uninstall(config: Config) -> tuple[bool, str]:
    return shared.uninstall(config, WHATSAPP)


def installed(config: Config) -> bool:
    return shared.installed(config, WHATSAPP)
