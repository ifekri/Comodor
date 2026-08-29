"""Running the Telegram bot without a terminal holding it open.

The work is in `channels.daemon`, which does the same for WhatsApp. This binds
it to this channel so the rest of the Telegram code — and anything that already
imported these names — keeps calling `service.start(config)` with one argument.
"""

from __future__ import annotations

from pathlib import Path

from ..channels import TELEGRAM
from ..channels import daemon as shared
from ..channels.daemon import PATIENCE, State  # noqa: F401  (re-exported)
from ..config import Config


def pid_file(config: Config) -> Path:
    return shared.pid_file(config, TELEGRAM)


def log_file(config: Config) -> Path:
    return shared.log_file(config, TELEGRAM)


def state(config: Config) -> State:
    return shared.state(config, TELEGRAM)


def start(config: Config) -> tuple[bool, str]:
    return shared.start(config, TELEGRAM)


def stop(config: Config) -> tuple[bool, str]:
    return shared.stop(config, TELEGRAM)


def _alive(pid: int) -> bool:                      # kept for the tests
    return shared._alive(pid)


def _command_of(pid: int) -> str:                  # kept for the tests
    return shared._command_of(pid)
