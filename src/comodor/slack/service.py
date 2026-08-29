"""Running the Slack bot without a terminal holding it open.

The work is in `channels.daemon`, which does the same for the others.
"""

from __future__ import annotations

from pathlib import Path

from ..channels import SLACK
from ..channels import daemon as shared
from ..channels.daemon import PATIENCE, State  # noqa: F401  (re-exported)
from ..config import Config


def pid_file(config: Config) -> Path:
    return shared.pid_file(config, SLACK)


def log_file(config: Config) -> Path:
    return shared.log_file(config, SLACK)


def state(config: Config) -> State:
    return shared.state(config, SLACK)


def start(config: Config) -> tuple[bool, str]:
    return shared.start(config, SLACK)


def stop(config: Config) -> tuple[bool, str]:
    return shared.stop(config, SLACK)
