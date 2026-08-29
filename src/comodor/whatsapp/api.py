"""Meta's WhatsApp Cloud API, over the HTTP client this project already has.

The official one. The alternative most projects reach for is a library that
drives WhatsApp Web through a headless browser — `whatsapp-web.js`, Baileys and
their descendants. Those need Node, they break whenever WhatsApp changes its
web client, and they are against the terms of service the account is held to:
the failure mode is somebody's phone number being banned, which is not a
failure mode a coding tool gets to hand its users. So: the Cloud API, which is
a documented REST endpoint Meta supports.

**How this differs from Telegram, which is most of the design.**

*Sending is a POST and receiving is not a GET.* There is no `getUpdates`. Meta
delivers inbound messages by posting them to a URL, which means something of
yours has to be reachable from the internet over HTTPS. `webhook.py` is that
endpoint; this file is only the outbound half.

*Messages cannot be edited.* Telegram streams a reply by editing one message as
the tokens arrive. Nothing here can do that, so a turn sends a short
acknowledgement and then the answer, and long answers are split.

*Buttons are rationed.* Three reply buttons per message, twenty characters per
label. More than three choices has to be a list message — one button that opens
a sheet of up to ten rows. `menu.py` decides which shape a given set of choices
takes.

*The identifier is a phone number.* Telegram gives a bot a username that a
stranger has to find; a WhatsApp business number is a phone number, and phone
numbers are messaged by strangers as a matter of course. The allow-list matters
more here, not less.
"""

from __future__ import annotations

import time
from typing import Any

from ..net import http

#: Meta's limit on the `body` of a text message. Longer is refused rather than
#: truncated, so it is split before sending.
MOST_CHARACTERS = 4096

#: Interactive messages are stricter, and each of these is a hard API error
#: rather than something Meta trims for you.
MOST_BUTTONS = 3
BUTTON_TITLE = 20
BUTTON_ID = 256
MOST_ROWS = 10
ROW_TITLE = 24
ROW_DESCRIPTION = 72
ROW_ID = 200
LIST_BODY = 4096
BUTTON_BODY = 1024
FOOTER = 60
HEADER = 60


class WhatsAppError(RuntimeError):
    """The API refused, or could not be reached."""


class Unauthorised(WhatsAppError):
    """The token is wrong, expired, or lacks the permission."""


class OutsideWindow(WhatsAppError):
    """The last message from this person was more than 24 hours ago.

    Meta only allows free-form messages inside a day of the user's last one;
    outside it, only a pre-approved template. It is a distinct class because it
    is not a fault to be retried — it means the conversation went cold, and the
    only thing that reopens it is the person writing again.
    """


class Cloud:
    """One WhatsApp business number, and the calls Comodor makes against it."""

    def __init__(self, token: str, phone_number_id: str,
                 version: str = "v21.0", timeout: float = 20.0) -> None:
        if not token:
            raise WhatsAppError("no access token")
        if not str(phone_number_id).isdigit():
            raise WhatsAppError(
                "the phone number id is the numeric id Meta shows next to the "
                "number, not the number itself")
        self._token = token
        self.phone_number_id = str(phone_number_id)
        self.version = version
        self.timeout = timeout

    def __repr__(self) -> str:      # pragma: no cover - debugging only
        return f"<Cloud number={self.phone_number_id}>"

    #: Below this a "token" is not a credential, and blanking it out of every
    #: message does more harm than good: a one-character token turns every
    #: instance of that letter in an error into `<token>`, which mangles the
    #: sentence explaining what went wrong. Real Meta tokens are well over a
    #: hundred characters.
    SHORTEST_SECRET = 12

    def _hide(self, text: str) -> str:
        """The token never appears in anything raised from here."""
        if not self._token or len(self._token) < self.SHORTEST_SECRET:
            return text
        return text.replace(self._token, "<token>")

    # -- the wire ---------------------------------------------------------- #

    def call(self, path: str, body: dict[str, Any] | None = None,
             method: str = "POST") -> dict[str, Any]:
        """One Graph API call. Raises rather than returning an error shape."""
        url = f"https://graph.facebook.com/{self.version}/{path}"
        headers = {"Authorization": f"Bearer {self._token}",
                   "Content-Type": "application/json"}
        try:
            if method == "GET":
                response = http.get(url, headers=headers,
                                    timeout=(10.0, self.timeout))
            else:
                response = http.post(url, json=body or {}, headers=headers,
                                     timeout=(10.0, self.timeout))
        except Exception as problem:
            raise WhatsAppError(
                self._hide(f"could not reach WhatsApp: {problem}")) from None

        try:
            payload = response.json()
        except ValueError:
            raise WhatsAppError(
                f"WhatsApp answered {response.status_code} with something "
                f"that was not JSON") from None

        if response.status_code >= 400 or "error" in payload:
            raise self._trouble(response.status_code, payload)
        return payload

    def _trouble(self, status: int, payload: dict[str, Any]) -> WhatsAppError:
        """Meta's error shape, turned into something worth reading.

        Their errors carry a `code`, a `message`, and — usually — an
        `error_data.details` that is the only part saying what actually went
        wrong. A handler that prints `message` alone reports "Unsupported post
        request" for everything.
        """
        error = payload.get("error") or {}
        code = error.get("code")
        detail = (error.get("error_data") or {}).get("details") or ""
        why = detail or error.get("message") or "no reason given"

        if status in (401, 403) or code in (190, 200, 10):
            return Unauthorised(self._hide(
                f"{why} — the token may have expired; a temporary one from "
                f"the app dashboard lasts twenty-four hours"))
        #: 131047 is "message outside the 24 hour window".
        if code == 131047 or "24 hour" in str(why).lower():
            return OutsideWindow(self._hide(str(why)))
        return WhatsAppError(self._hide(f"{why} (code {code})"))

    # -- what Comodor actually calls --------------------------------------- #

    def me(self) -> dict[str, Any]:
        """The number this is sending from, to prove the token works."""
        return self.call(f"{self.phone_number_id}"
                         "?fields=display_phone_number,verified_name",
                         method="GET")

    def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.call(f"{self.phone_number_id}/messages", body)

    def send(self, to: str, text: str, preview: bool = False) -> dict[str, Any]:
        """One text message. Long text is the caller's problem — see `split`."""
        return self._send({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to),
            "type": "text",
            "text": {"body": text[:MOST_CHARACTERS],
                     "preview_url": bool(preview)},
        })

    def send_buttons(self, to: str, text: str,
                     buttons: list[tuple[str, str]],
                     footer: str = "") -> dict[str, Any]:
        """Up to three reply buttons under a message.

        `buttons` is `(id, label)`. Both are clipped here rather than at the
        call sites: Meta rejects the whole message for one over-long label, and
        a menu that fails to send is indistinguishable from a bot that is down.
        """
        if not 1 <= len(buttons) <= MOST_BUTTONS:
            raise WhatsAppError(
                f"WhatsApp takes one to {MOST_BUTTONS} reply buttons, "
                f"not {len(buttons)} — a longer list has to be a list message")
        interactive: dict[str, Any] = {
            "type": "button",
            "body": {"text": text[:BUTTON_BODY]},
            "action": {"buttons": [
                {"type": "reply",
                 "reply": {"id": key[:BUTTON_ID], "title": label[:BUTTON_TITLE]}}
                for key, label in buttons
            ]},
        }
        if footer:
            interactive["footer"] = {"text": footer[:FOOTER]}
        return self._send({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to),
            "type": "interactive",
            "interactive": interactive,
        })

    def send_list(self, to: str, text: str, open_label: str,
                  rows: list[tuple[str, str, str]], header: str = "",
                  footer: str = "", section: str = "") -> dict[str, Any]:
        """A sheet of up to ten rows behind one button.

        `rows` is `(id, title, description)`. Ten is the limit across every
        section combined, not per section.
        """
        if not 1 <= len(rows) <= MOST_ROWS:
            raise WhatsAppError(
                f"WhatsApp takes one to {MOST_ROWS} rows in a list, "
                f"not {len(rows)}")
        interactive: dict[str, Any] = {
            "type": "list",
            "body": {"text": text[:LIST_BODY]},
            "action": {
                "button": open_label[:BUTTON_TITLE],
                "sections": [{
                    "title": (section or "Choose")[:24],
                    "rows": [
                        {"id": key[:ROW_ID], "title": title[:ROW_TITLE],
                         **({"description": note[:ROW_DESCRIPTION]} if note
                            else {})}
                        for key, title, note in rows
                    ],
                }],
            },
        }
        if header:
            interactive["header"] = {"type": "text", "text": header[:HEADER]}
        if footer:
            interactive["footer"] = {"text": footer[:FOOTER]}
        return self._send({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to),
            "type": "interactive",
            "interactive": interactive,
        })

    def mark_read(self, message_id: str) -> None:
        """The two blue ticks, so somebody knows it arrived.

        Best effort. Failing to tick a message is not a reason to fail the turn
        that message asked for.
        """
        try:
            self._send({"messaging_product": "whatsapp", "status": "read",
                        "message_id": message_id})
        except WhatsAppError:
            pass


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


def split(text: str, limit: int = MOST_CHARACTERS) -> list[str]:
    """Break a long answer where a reader would, not at the byte count.

    Paragraphs first, then lines, then — only if one line is longer than a
    whole message — the hard limit. The same rule as the Telegram client, for
    the same reason: a cut mid-word reads as a bug in the tool rather than as a
    limit of the medium.
    """
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


def bold(text: str) -> str:
    """WhatsApp's emphasis, which is asterisks and not HTML.

    Telegram takes `<b>`; WhatsApp takes `*bold*`, `_italic_` and triple
    backticks. Sending one's markup to the other prints the tags.
    """
    return f"*{text}*"


def mono(text: str) -> str:
    return f"```{text}```"


def backoff(attempt: int) -> float:
    """Seconds to wait before trying again. Doubling, and capped."""
    return min(60.0, 2.0 ** min(attempt, 6))


def now() -> float:
    return time.time()
