"""Handing the Slack bot to the operating system."""

from __future__ import annotations

from ..channels import SLACK
from ..channels import unit as shared
from ..channels.unit import Unit  # noqa: F401  (re-exported)
from ..config import Config


def plan(config: Config) -> Unit:
    return shared.plan(config, SLACK)


def install(config: Config) -> tuple[bool, str, Unit]:
    return shared.install(config, SLACK)


def uninstall(config: Config) -> tuple[bool, str]:
    return shared.uninstall(config, SLACK)


def installed(config: Config) -> bool:
    return shared.installed(config, SLACK)
