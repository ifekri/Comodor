"""One REST service, speaking for all of them.

Every cloud memory service that matters has the same skeleton: POST an
entry, GET entries matching a query. The differences are field names and
one auth header shape. Rather than a module per vendor — eight modules
repeating the same two calls — this speaks one small JSON dialect over
``net/http`` and the config maps a service onto it:

* writes go to ``{base_url}/entries`` as ``{"text": ..., "kind": ...}``
* reads go to ``{base_url}/search?q=...`` and read back a list of
  ``{"text": ...}`` (or a bare list of strings)

Services that do not fit the dialect get a real adapter later, on
evidence, not on speculation — the abstract shape in ``base.py`` is the
contract, and this is its cheapest tenant. ``mem0`` is accepted as an alias
of this kind because its public API is exactly the dialect above with a
``Authorization: Token`` header.
"""

from __future__ import annotations

from typing import Any

from ...net.http import Session
from .base import Provider, Settings

#: Network patience. A mirror must never be the slowest thing in a turn:
#: if the service has not answered in this long, it has nothing to add.
TIMEOUT = (3.0, 8.0)
#: The augmentation budget, in tokens of roughly four characters. Small on
#: purpose: what a provider adds is seasoning, not the meal.
MOST_AUGMENT_CHARS = 400 * 4


class HttpGeneric(Provider):
    """The dialect above, with the key in one header."""

    def __init__(self, settings: Settings, key: str) -> None:
        self.settings = settings
        self.key = key
        self.base = settings.base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}"}
        self.session = Session(headers=self.headers, timeout=TIMEOUT)

    def mirror_write(self, text: str, kind: str) -> bool:
        try:
            answer = self.session.post(f"{self.base}/entries",
                                       json={"text": text, "kind": kind})
        except Exception:
            return False
        return answer.ok

    def augment_recall(self, query: str) -> list[str]:
        try:
            answer = self.session.get(f"{self.base}/search", params={"q": query})
        except Exception:
            return []                     # fail-open: an addition, not a gate
        if not answer.ok:
            return []
        return _capped(_texts(answer))

    def status(self) -> str:
        try:
            answer = self.session.get(f"{self.base}/health",
                                      params={}, timeout=(2.0, 4.0))
        except Exception as problem:
            return f"unreachable ({type(problem).__name__})"
        if answer.ok:
            return f"reachable ({self.settings.kind})"
        return f"answered {answer.status_code}"


def _texts(answer: Any) -> list[str]:
    """The texts out of a search reply, in the two shapes services send."""
    try:
        payload = answer.json()
    except Exception:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("results") or payload.get("memories") or []
    else:
        return []
    found = []
    for item in items:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            found.append(item["text"])
    return found


def _capped(texts: list[str]) -> list[str]:
    """As many as fit the augmentation budget, whole lines only."""
    kept: list[str] = []
    used = 0
    for text in texts:
        if used + len(text) > MOST_AUGMENT_CHARS:
            break
        kept.append(text)
        used += len(text)
    return kept
