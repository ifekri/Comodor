"""Reaching Comodor from a phone.

A Telegram bot that runs the same agent session the browser interface does, so
a task can be started, watched, answered and stopped without going to a
terminal.

Three files:

``api``       the Bot API over this project's own HTTP client, no new dependency
``keyboard``  the buttons, and the words on them
``bot``       the poll loop, and one conversation per chat

The security posture is the interesting part and it is deliberately strict. A
bot's username is public, so this one answers a fixed list of numeric user ids
and is silent to everybody else; the list is filled by typing a code from the
terminal, where somebody is already trusted. And because approving a shell
command with a thumb is a decision made with less care than the same approval
at a keyboard, a Telegram session is held in plan mode until writes are
switched on deliberately.
"""

from __future__ import annotations

from .api import Bot, TelegramError, Unauthorised, split  # noqa: F401
from .bot import Conversation, Service, escape  # noqa: F401

__all__ = ["Bot", "Conversation", "Service", "TelegramError", "Unauthorised",
           "escape", "split"]
