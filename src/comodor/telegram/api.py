"""The Telegram Bot API, over the HTTP client this project already has.

No new dependency. `python-telegram-bot` is the obvious import and it brings
asyncio, its own HTTP stack and a framework that wants to own the process —
for what is, underneath, `GET /bot<token>/getUpdates` in a loop and `POST
/bot<token>/sendMessage`. Comodor hand-rolls its HTTP client, its SSE reader
and its WebSocket for exactly this reason, and one more package here would be
the largest thing in the wheel.

Two things this file is careful about.

*The token is a secret and it lives in the URL.* Every Bot API path contains
it, so anything that logs a URL logs the credential. Every error raised here
has the token stripped out of it, and `__repr__` never carries it.

*Long polling is a request that is supposed to take a long time.* A read
timeout shorter than the poll is a client that reconnects every few seconds and
looks like a network fault. The read timeout is deliberately longer than the
poll it is waiting on.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..net import http

#: How long Telegram holds a `getUpdates` open with nothing to say. Fifty
#: seconds is their documented maximum and the fewest round trips.
POLL_SECONDS = 50

#: Longer than the poll, or every idle poll ends in a timeout the caller has to
#: treat as normal — which means a real fault stops being distinguishable.
READ_TIMEOUT = POLL_SECONDS + 15

#: Telegram's own limit on one message. Anything longer is refused outright
#: rather than truncated, so it is split before sending.
MOST_CHARACTERS = 4096


class TelegramError(RuntimeError):
    """The API refused, or could not be reached."""


class Unauthorised(TelegramError):
    """The token is wrong, revoked, or for a bot that no longer exists."""


class Bot:
    """One bot, and the calls Comodor makes against it."""

    def __init__(self, token: str, timeout: float = 20.0) -> None:
        if not token or ":" not in token:
            raise TelegramError(
                "that does not look like a bot token — BotFather issues them "
                "as `<digits>:<letters>`")
        self._token = token
        self.timeout = timeout
        #: The last update this bot has acknowledged. Telegram will re-send
        #: anything below it, which is what makes a restart lose nothing.
        self.offset = 0

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return f"<Bot {self.id_hint}>"

    @property
    def id_hint(self) -> str:
        """The numeric half of the token, which is the bot's id and public."""
        return self._token.split(":", 1)[0]

    def _hide(self, text: str) -> str:
        return text.replace(self._token, f"{self.id_hint}:<token>")

    def call(self, method: str, wait: float | None = None,
             **params: Any) -> Any:
        """One Bot API method. Raises rather than returning an error shape.

        The client-side deadline is called `wait` and not `timeout` on purpose:
        `getUpdates` takes a parameter of its own called `timeout`, and a
        signature carrying both means the long poll cannot say how long to hold
        the connection without colliding with how long to wait for it.
        """
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        body = {k: v for k, v in params.items() if v is not None}
        for key, value in list(body.items()):
            # Telegram wants nested structures as JSON in a form field.
            if isinstance(value, (dict, list)):
                body[key] = json.dumps(value, ensure_ascii=False)

        try:
            response = http.post(url, data=body,
                                 timeout=(10.0, wait or self.timeout))
        except Exception as problem:
            raise TelegramError(self._hide(f"could not reach Telegram: {problem}")) \
                from None

        try:
            payload = response.json()
        except ValueError:
            raise TelegramError(
                f"Telegram answered {response.status_code} with something that "
                f"was not JSON") from None

        if not payload.get("ok"):
            why = payload.get("description", "no reason given")
            if response.status_code in (401, 404):
                raise Unauthorised(self._hide(why))
            if response.status_code == 429:
                after = (payload.get("parameters") or {}).get("retry_after", 1)
                raise TelegramError(f"rate limited; retry after {after}s")
            raise TelegramError(self._hide(f"{method}: {why}"))

        return payload.get("result")

    # -- what Comodor actually uses ---------------------------------------- #

    def me(self) -> dict[str, Any]:
        """Who this token belongs to. The cheapest check that it works."""
        return self.call("getMe")

    def updates(self, timeout: int = POLL_SECONDS) -> list[dict[str, Any]]:
        """Wait for something to happen, and acknowledge what came before.

        `offset` is the acknowledgement: sending it tells Telegram everything
        below it was handled and may be dropped. Without it a restart replays
        the whole backlog, and every message the bot ever received is answered
        again — which, for an agent that runs commands, is not merely noisy.
        """
        got = self.call(
            "getUpdates",
            wait=READ_TIMEOUT,
            offset=self.offset or None,
            timeout=timeout,
            # Only the kinds this bot acts on. Anything else is bandwidth and a
            # branch nobody has written.
            allowed_updates=["message", "callback_query"],
        ) or []
        for update in got:
            self.offset = max(self.offset, int(update["update_id"]) + 1)
        return got

    def send(self, chat: int | str, text: str, *, keyboard: Any = None,
             quiet: bool = False, reply_to: int | None = None,
             preview: bool = False) -> dict[str, Any] | None:
        """One message, split if Telegram would refuse its length."""
        pieces = split(text)
        sent = None
        for index, piece in enumerate(pieces):
            sent = self.call(
                "sendMessage",
                chat_id=chat,
                text=piece,
                parse_mode="HTML",
                link_preview_options={"is_disabled": not preview},
                disable_notification=quiet,
                reply_to_message_id=reply_to if index == 0 else None,
                # The keyboard goes on the last piece, where the reader ends up.
                reply_markup=keyboard if index == len(pieces) - 1 else None,
            )
        return sent

    def edit(self, chat: int | str, message: int, text: str,
             keyboard: Any = None) -> dict[str, Any] | None:
        """Replace a message in place, which is how a live answer streams.

        Telegram refuses an edit that changes nothing, with an error that means
        exactly "you sent the same text twice". That is a normal thing to do
        while streaming, so it is swallowed rather than raised.
        """
        try:
            return self.call("editMessageText", chat_id=chat,
                             message_id=message, text=text[:MOST_CHARACTERS],
                             parse_mode="HTML",
                             link_preview_options={"is_disabled": True},
                             reply_markup=keyboard)
        except TelegramError as problem:
            if "not modified" in str(problem).lower():
                return None
            raise

    def answer_callback(self, query: str, text: str = "",
                        alert: bool = False) -> None:
        """Stop the spinner on a tapped button.

        Telegram shows a loading state on the button until this is sent, and
        leaves it spinning for a while if it never is — so a handler that
        forgets looks like a bot that has hung.
        """
        try:
            self.call("answerCallbackQuery", callback_query_id=query,
                      text=text[:200] or None, show_alert=alert)
        except TelegramError:
            # The query expires after a minute; answering late is not a fault
            # worth ending a turn over.
            pass

    def typing(self, chat: int | str) -> None:
        """The `typing…` line, which is the only sign a long turn is alive."""
        try:
            self.call("sendChatAction", chat_id=chat, action="typing")
        except TelegramError:
            pass

    def commands(self, entries: list[tuple[str, str]]) -> None:
        """Register the slash commands, so Telegram offers them as you type."""
        self.call("setMyCommands", commands=[
            {"command": name, "description": what} for name, what in entries])

    def drop_webhook(self) -> None:
        """Long polling and a webhook are mutually exclusive.

        A webhook left over from another tool makes `getUpdates` fail with a
        message about conflict that does not say what to do about it.
        """
        try:
            self.call("deleteWebhook", drop_pending_updates=False)
        except TelegramError:
            pass


def split(text: str, limit: int = MOST_CHARACTERS) -> list[str]:
    """Break a long message where a reader would, not at the character count.

    Telegram refuses anything over the limit outright. Cutting mid-word — or
    worse, mid-tag, which breaks the HTML for the whole message — is avoidable
    by preferring a paragraph break, then a line, then a space.
    """
    text = text or ""
    if len(text) <= limit:
        return [text] if text else [""]

    pieces: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        pieces.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        pieces.append(text)
    return pieces


def backoff(attempt: int, most: float = 60.0) -> float:
    """How long to wait before trying the network again.

    Doubling, capped. A bot that retries a dead connection every second is a
    bot that spends the day being rate limited by the thing it is trying to
    reach.
    """
    return min(most, 2.0 ** min(attempt, 6))


def now() -> float:
    return time.monotonic()
