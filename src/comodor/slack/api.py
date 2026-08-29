"""Slack's Web API, over the HTTP client this project already has.

No new dependency. `slack_sdk` is the obvious import and it brings aiohttp, its
own retry machinery and a framework that wants the event loop — for what is,
underneath, `POST /api/chat.postMessage` with a bearer token.

**Two tokens, and they are not interchangeable.** A *bot* token (`xoxb-…`)
authenticates everything the bot does in a workspace: posting, editing, opening
a DM. An *app-level* token (`xapp-…`, scope `connections:write`) does exactly
one thing — open the websocket that Socket Mode runs over. Confusing them is
the most common way this fails, so the constructor refuses each in the other's
place by name rather than letting Slack answer `invalid_auth` an hour later.

**Slack lets a message be edited**, which puts it with Telegram rather than
WhatsApp: a reply can be one message that grows as the answer arrives, instead
of a notification per paragraph.
"""

from __future__ import annotations

import time
from typing import Any

from ..net import http

#: Slack truncates a message past this and the rest is silently gone, so it is
#: split before sending. Their documented limit is 4000 characters; the round
#: number below leaves room for the formatting wrapped around it.
MOST_CHARACTERS = 3900

#: How often a streamed reply may be rewritten. Slack rate-limits `chat.update`
#: at roughly one per second per channel, and a burst gets the whole app
#: throttled — which shows up as a reply that stops moving.
EDIT_EVERY = 1.2


class SlackError(RuntimeError):
    """The API refused, or could not be reached."""


class Unauthorised(SlackError):
    """The token is wrong, revoked, or missing the scope for this call."""


class RateLimited(SlackError):
    """Too many calls. Carries how long Slack asked us to wait."""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _looks_like(token: str, prefix: str) -> bool:
    return token.startswith(prefix)


class Slack:
    """One workspace, and the calls Comodor makes against it."""

    def __init__(self, bot_token: str, app_token: str = "",
                 timeout: float = 20.0) -> None:
        if not bot_token:
            raise SlackError("no bot token")
        if _looks_like(bot_token, "xapp-"):
            raise SlackError(
                "that is the app-level token — the bot token starts `xoxb-` "
                "and is under OAuth & Permissions")
        if not _looks_like(bot_token, "xoxb-"):
            raise SlackError(
                "a bot token starts `xoxb-`; this does not look like one")
        if app_token and _looks_like(app_token, "xoxb-"):
            raise SlackError(
                "that is the bot token — the app-level token starts `xapp-` "
                "and is under Basic Information → App-Level Tokens")

        self._bot = bot_token
        self._app = app_token
        self.timeout = timeout

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return "<Slack workspace>"

    def _hide(self, text: str) -> str:
        """Neither token ever appears in anything raised from here."""
        for secret in (self._bot, self._app):
            if secret and len(secret) > 12:
                text = text.replace(secret, "<token>")
        return text

    # -- the wire ---------------------------------------------------------- #

    def call(self, method: str, body: dict[str, Any] | None = None,
             app_level: bool = False) -> dict[str, Any]:
        """One Web API method. Raises rather than returning an error shape."""
        token = self._app if app_level else self._bot
        if not token:
            raise SlackError(
                "no app-level token — Socket Mode needs one, from Basic "
                "Information → App-Level Tokens with `connections:write`")

        url = f"https://slack.com/api/{method}"
        headers = {"Authorization": f"Bearer {token}",
                   "Content-Type": "application/json; charset=utf-8"}
        try:
            response = http.post(url, json=body or {}, headers=headers,
                                 timeout=(10.0, self.timeout))
        except Exception as problem:
            raise SlackError(
                self._hide(f"could not reach Slack: {problem}")) from None

        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After") or 1)
            raise RateLimited(f"{method} is rate limited", wait)

        try:
            payload = response.json()
        except ValueError:
            raise SlackError(
                f"Slack answered {response.status_code} with something that "
                f"was not JSON") from None

        if not payload.get("ok"):
            raise self._trouble(method, payload)
        return payload

    def _trouble(self, method: str, payload: dict[str, Any]) -> SlackError:
        why = str(payload.get("error") or "no reason given")
        needed = payload.get("needed") or ""

        if why in ("invalid_auth", "not_authed", "account_inactive",
                   "token_revoked", "token_expired"):
            return Unauthorised(self._hide(
                f"{method}: {why} — the token is wrong or has been revoked"))
        if why in ("missing_scope", "not_allowed_token_type"):
            return Unauthorised(self._hide(
                f"{method}: {why}"
                + (f" — it needs `{needed}`. Add the scope, then "
                   f"*reinstall the app*: a scope added without reinstalling "
                   f"does not reach the token you already have." if needed
                   else "")))
        if why == "ratelimited":
            return RateLimited(f"{method} is rate limited", 1.0)
        return SlackError(self._hide(f"{method}: {why}"))

    # -- what Comodor actually calls --------------------------------------- #

    def me(self) -> dict[str, Any]:
        """Who this token is, which proves it works and names the workspace."""
        return self.call("auth.test")

    def open_dm(self, user: str) -> str:
        """The channel id for a direct message to one person.

        A user id is not a channel id. Posting to `U…` sometimes works and
        sometimes silently does not, depending on the workspace, so the
        conversation is opened explicitly and its id used.
        """
        found = self.call("conversations.open", {"users": user})
        return str((found.get("channel") or {}).get("id") or "")

    def send(self, channel: str, text: str,
             blocks: list[dict[str, Any]] | None = None,
             thread: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"channel": channel, "text": text[:MOST_CHARACTERS]}
        if blocks:
            body["blocks"] = blocks
        if thread:
            body["thread_ts"] = thread
        return self.call("chat.postMessage", body)

    def edit(self, channel: str, ts: str, text: str,
             blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"channel": channel, "ts": ts,
                                "text": text[:MOST_CHARACTERS]}
        # An explicit empty list, not omission: leaving `blocks` out of an
        # update keeps whatever was there, so a finished reply would keep the
        # buttons of the one that was still running.
        body["blocks"] = blocks or []
        return self.call("chat.update", body)

    def open_socket(self) -> str:
        """A fresh websocket address for Socket Mode. App-level token only."""
        found = self.call("apps.connections.open", app_level=True)
        return str(found.get("url") or "")


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


def split(text: str, limit: int = MOST_CHARACTERS) -> list[str]:
    """Break a long answer where a reader would, not at the character count."""
    text = text or ""
    if len(text) <= limit:
        return [text]

    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 4:
            cut = window.rfind("\n")
        if cut < limit // 4:
            cut = window.rfind(" ")
        if cut < limit // 4:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        pieces.append(rest)
    return pieces


def escape(text: str) -> str:
    """The three characters Slack reads as markup in ordinary text.

    Not the full mrkdwn escape — asterisks and underscores are wanted, because
    the bot writes with them. These three are the ones that make Slack try to
    parse a link or an entity out of something that is neither.
    """
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def code(text: str) -> str:
    return f"```{text}```"


def backoff(attempt: int) -> float:
    """Seconds before trying the socket again. Doubling, and capped."""
    return min(60.0, 2.0 ** min(attempt, 6))


def now() -> float:
    return time.time()
