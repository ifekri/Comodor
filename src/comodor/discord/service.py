"""Running the Discord bot without a terminal holding it open.

The work is in `channels.daemon`, which does the same for the others.
"""

from __future__ import annotations

from pathlib import Path

from ..channels import DISCORD
from ..channels import daemon as shared
from ..channels.daemon import PATIENCE, State  # noqa: F401  (re-exported)
from ..config import Config


def pid_file(config: Config) -> Path:
    return shared.pid_file(config, DISCORD)

def log_file(config: Config) -> Path:
    return shared.log_file(config, DISCORD)

def state(config: Config) -> State:
    return shared.state(config, DISCORD)

def start(config: Config) -> tuple[bool, str]:
    return shared.start(config, DISCORD)

def stop(config: Config) -> tuple[bool, str]:
    return shared.stop(config, DISCORD)
