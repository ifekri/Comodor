"""The parts of reaching Comodor from a phone that do not depend on which app.

Telegram and WhatsApp are different enough at the surface that sharing their
conversation code would be a lie dressed as an abstraction: one long-polls and
the other is webhooked, one edits a message to stream a reply and the other
cannot edit at all, one draws a grid of eleven buttons and the other is allowed
three.

What *is* the same is everything underneath. Both run a process that has to
survive the terminal closing. Both want the operating system to start them at
login. Both answer a fixed list of accounts filled by a one-time code typed at
a terminal, because both have a public address that anybody can message. Those
are the three things in here, and they are written once.

A `Channel` names which one is being managed. It carries no behaviour beyond
what differs — a name for the files, a label for the messages, and the question
"is this configured enough to run".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..config import Config


@dataclass(frozen=True)
class Channel:
    """One way of reaching the agent from a phone."""

    #: The subcommand and the stem of every file: `telegram`, `whatsapp`.
    name: str
    #: What it is called in a sentence: `Telegram`, `WhatsApp`.
    label: str
    #: The `Config` attribute holding its settings.
    section: str
    #: Whether it is configured enough to start, and what to say if not.
    ready: Callable[[Any], tuple[bool, str]]

    def settings(self, config: Config) -> Any:
        return getattr(config, self.section)

    def can_run(self, config: Config) -> tuple[bool, str]:
        return self.ready(self.settings(config))


def _telegram_ready(settings: Any) -> tuple[bool, str]:
    if not settings.token:
        return False, ("No bot is connected. `comodor telegram connect "
                       "<token>` first.")
    if not settings.allowed:
        return False, ("Nobody is paired, so the bot would answer nobody. "
                       "`comodor telegram pair` first.")
    return True, ""


def _whatsapp_ready(settings: Any) -> tuple[bool, str]:
    if not settings.token or not settings.phone_number_id:
        return False, ("Not connected. `comodor whatsapp connect` sets up the "
                       "number and the token.")
    if not settings.allowed:
        return False, ("Nobody is paired, so it would answer nobody. "
                       "`comodor whatsapp pair` first.")
    return True, ""


TELEGRAM = Channel(name="telegram", label="Telegram", section="telegram",
                   ready=_telegram_ready)
WHATSAPP = Channel(name="whatsapp", label="WhatsApp", section="whatsapp",
                   ready=_whatsapp_ready)

CHANNELS = (TELEGRAM, WHATSAPP)
