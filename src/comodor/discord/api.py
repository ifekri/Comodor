"""Discord's REST API, over the HTTP client this project already has.

No new dependency. `discord.py` is the obvious import and it brings an event
loop, a gateway of its own and a cache that wants to own the process — for
what is, underneath, `POST /channels/{id}/messages` with a bearer token and a
websocket with a ping in it.

**The rate limits are the sharpest of any channel here.** Discord throttles
per *route* — per channel, not per token — and edits are capped at roughly
five per two seconds per message. A reply that streams by editing must space
its edits wider than Telegram's, or the first long answer hits the ceiling
and Discord answers 429 with a Retry-After that applies to *everything*
global. When that happens the header is read, the wait is taken, and it is
raised as an error carrying the number so the poll loop can decide.

**Snowflakes.** Every id Discord issues is a snowflake — a number, encoded as
a string in the API's JSON. This module returns them as strings and lets the
bot layer convert where it compares.
"""

from __future__ import annotations

from typing import Any

from ..net import http

#: Discord refuses one message past this outright, so it is split before
#: sending. The documented limit is 2000 characters; the margin below leaves
#: room for the formatting wrapped around it.
MOST_CHARACTERS = 1900

#: How often a streamed reply may be rewritten. Discord allows about five
#: edits per two seconds per channel; a third of that is what survives a
#: conversation where several replies are growing at once.
EDIT_EVERY = 2.0

#: The Discord REST base. The token rides in a header, not in the URL —
#: unlike Telegram, so an error message here is safe by construction.
BASE = "https://discord.com/api/v10"


class DiscordError(RuntimeError):
    """The API refused, or could not be reached."""


class Unauthorised(DiscordError):
    """The token is wrong, revoked, or for a bot that no longer exists."""


class RateLimited(DiscordError):
    """Too many calls. Carries how long Discord asked us to wait."""

    def __init__(self, message: str, retry_after: float = 1.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Bot:
    """One bot, and the REST calls Comodor makes against it."""

    def __init__(self, token: str, timeout: float = 20.0) -> None:
        if not token or "." not in token:
            raise DiscordError(
                "that does not look like a bot token — the developer portal "
                "issues them as three base64 parts joined by dots")
        self._token = token
        self.timeout = timeout

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return "<Discord bot>"

    def _hide(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    # -- the wire ---------------------------------------------------------- #

    def call(self, method: str, path: str, body: dict[str, Any] | None = None,
             wait: float | None = None) -> Any:
        """One REST call. Raises rather than returning an error shape.

        `path` is the route after the version, without a leading slash —
        `/channels/…`, `/users/@me`.
        """
        headers = {"Authorization": f"Bot {self._token}",
                   "Content-Type": "application/json; charset=utf-8"}
        try:
            response = http.request(
                method, f"{BASE}/{path}", json=body, headers=headers,
                timeout=(10.0, wait or self.timeout))
        except Exception as problem:
            raise DiscordError(
                self._hide(f"could not reach Discord: {problem}")) from None

        if response.status_code == 429:
            retry = response.retry_after or float(
                response.headers.get("Retry-After") or 1)
            raise RateLimited(f"{path} is rate limited", retry)
        if response.status_code in (401, 403):
            raise Unauthorised(
                "Discord refused the token — check it in the developer "
                "portal, and that the bot was invited to this server")
        if response.status_code >= 400:
            raise DiscordError(self._hide(
                f"{path}: {response.status_code} {response.text[:200]}"))

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise DiscordError(
                f"Discord answered {response.status_code} with something "
                "that was not JSON") from None

    # -- what Comodor actually calls --------------------------------------- #

    def me(self) -> dict[str, Any]:
        """Who this token is — the proof it works, and the id to not answer."""
        return self.call("GET", "users/@me")

    def send(self, channel: str | int, text: str,
             reply_to: str | int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"content": text}
        if reply_to is not None:
            body["message_reference"] = {"message_id": str(reply_to)}
        return self.call("POST", f"channels/{channel}/messages", body)

    def edit(self, channel: str | int, message: str | int,
             text: str) -> dict[str, Any]:
        return self.call("PATCH", f"channels/{channel}/messages/{message}",
                         {"content": text})

    def typing(self, channel: str | int) -> None:
        """The `…` indicator. Nothing breaks if it fails, so it does not raise.

        A conversation where every long turn is silent feels dead; a typing
        call refused is invisible either way, so it is swallowed here rather
        than making every caller try.
        """
        try:
            self.call("POST", f"channels/{channel}/typing", {})
        except DiscordError:
            pass


def split(text: str, limit: int = MOST_CHARACTERS) -> list[str]:
    """Break a long message where a reader would, not at the character count.

    Discord refuses anything over the limit outright. Cutting mid-word — or
    mid-code-fence, which turns the rest of the answer into monospace — is
    avoidable by preferring a paragraph break, then a line, then a space; and
    an odd number of fences in one piece is closed before it is sent.
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
        piece = text[:cut].rstrip()
        if piece.count("```") % 2:
            piece += "\n```"
        pieces.append(piece)
        text = text[cut:].lstrip()
    if text:
        pieces.append(text)
    return pieces
