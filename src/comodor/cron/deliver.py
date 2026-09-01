"""Where a finished job's answer goes.

The scheduler records the answer on the job either way; this module is only
about the "and tell somebody" part. A job's ``delivery`` field names targets:
``origin`` means nowhere but the job record — the terminal user reads the
history there — and ``channel:key`` names a chat one of the channel daemons
knows, ``telegram:123456`` or ``slack:U04ABC`` or ``whatsapp:1555…``.

Delivery to a channel goes through that platform's ledger, so a crash
between the run finishing and the message landing is recovered the same way
a chat reply is. A target nobody can resolve is reported on the job rather
than invented: the scheduler never guesses who was meant.
"""

from __future__ import annotations

from typing import Any, Callable

#: Per-platform senders: a callable taking (chat_id, body) and sending it.
#: Filled lazily by each caller that has the adapters available — the
#: scheduler process may not have a Telegram token configured, and building
#: one from nothing would fail anyway.
Senders = dict[str, Callable[[Any, str], Any]]


def targets(job: Any) -> list[tuple[str, str]]:
    """The delivery targets as (platform, chat_id) pairs.

    ``origin`` is not a channel and is left off: its delivery is the job
    record itself, already written by the scheduler.
    """
    pairs: list[tuple[str, str]] = []
    for entry in getattr(job, "delivery", None) or []:
        text = str(entry)
        if text == "origin" or ":" not in text:
            continue
        platform, _, chat_id = text.partition(":")
        if platform and chat_id:
            pairs.append((platform, chat_id))
    return pairs


def deliver(answer: str, pairs: list[tuple[str, str]], config: Any) -> list[str]:
    """Send the answer to each target through its platform's ledger.

    Returns what failed, as readable strings. One dead channel does not
    stop the others, and nothing here raises: delivery failure must never
    read back as the job having failed.
    """
    failures: list[str] = []
    if not pairs or not answer.strip():
        return failures
    from ..channels.ledger import DeliveryLedger

    for platform, chat_id in pairs:
        try:
            sender = _sender(platform, config)
            if sender is None:
                failures.append(f"{platform}:{chat_id} — the channel is not "
                                "configured on this machine")
                continue
            ledger = DeliveryLedger(
                config.paths.delivery_ledger(platform), platform)
            ledger.send(chat_id, answer, sender)
        except Exception as problem:
            failures.append(f"{platform}:{chat_id} — {problem}")
    return failures


def _sender(platform: str, config: Any) -> Callable[[Any, str], Any] | None:
    """The send function of one configured channel, or None.

    Built on demand and only for the channel actually named: a delivery
    target is the user saying "this one", not an invitation to construct
    every adapter there is.
    """
    if platform == "telegram":
        token = getattr(config.telegram, "token", "")
        if not token:
            return None
        from ..telegram.api import Bot

        bot = Bot(token)
        return lambda chat, body: bot.send(chat, body)
    if platform == "whatsapp":
        settings = config.whatsapp
        if not getattr(settings, "token", "") or \
                not getattr(settings, "phone_number_id", ""):
            return None
        from ..whatsapp.api import Cloud

        cloud = Cloud(settings.token, settings.phone_number_id,
                      version=settings.api_version)
        return cloud.send
    if platform == "slack":
        settings = config.slack
        if not getattr(settings, "bot_token", ""):
            return None
        from ..slack.api import Slack

        slack = Slack(settings.bot_token, getattr(settings, "app_token", ""))
        return lambda chat, body: slack.send(str(chat), body)
    return None
