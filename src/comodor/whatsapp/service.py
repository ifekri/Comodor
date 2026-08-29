"""Running the WhatsApp bot without a terminal holding it open.

The work is in `channels.daemon`, which does the same for Telegram.
"""

from __future__ import annotations

from pathlib import Path

from ..channels import WHATSAPP
from ..channels import daemon as shared
from ..channels.daemon import PATIENCE, State  # noqa: F401  (re-exported)
from ..config import Config


def pid_file(config: Config) -> Path:
    return shared.pid_file(config, WHATSAPP)


def log_file(config: Config) -> Path:
    return shared.log_file(config, WHATSAPP)


def state(config: Config) -> State:
    return shared.state(config, WHATSAPP)


def start(config: Config) -> tuple[bool, str]:
    return shared.start(config, WHATSAPP)


def stop(config: Config) -> tuple[bool, str]:
    return shared.stop(config, WHATSAPP)
