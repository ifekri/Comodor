"""Subscriptions: which paths exist, and what an accepted event becomes.

One subscription is one external system's agreement with this machine: it
names a path, a shared secret, and a prompt template that turns the event's
payload into a task. The file lives under the user's directory at 0600 —
every secret in it is one that lets somebody hand the agent instructions,
so it is held to the same standard as the config file itself.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config

#: Bigger than any plausible webhook payload and small enough that a
#: hostile body cannot be used to exhaust memory.
MOST_BYTES = 256 * 1024


@dataclass
class Sub:
    """One external system, one path, one prompt."""

    name: str
    path: str                              # e.g. "/gh"
    secret: str
    #: The prompt template. ``{payload}`` is the whole JSON body; a
    #: ``{.path.to.field}`` picks one value out of it.
    template: str = "{payload}"
    #: Where the finished answer is delivered when the run is over, if
    #: anywhere. Empty means nowhere: the event is logged and that is all.
    reply_url: str = ""
    #: Whether the agent may edit files and run commands on this
    #: subscription's behalf. False, and false on purpose: the default
    #: posture for a machine talking to a machine is read and plan only.
    allow_writes: bool = False

    def to_json(self) -> dict[str, Any]:
        return {"path": self.path, "secret": self.secret,
                "template": self.template, "reply_url": self.reply_url,
                "allow_writes": self.allow_writes}


def render(template: str, payload: dict[str, Any]) -> str:
    """The template against the payload, with the two placeholders.

    ``{payload}`` is the body as JSON, which is always safe to fill in. A
    ``{.a.b.c}`` path picks one field; a path that names nothing renders as
    nothing rather than raising, because a webhook that 500s on an optional
    field is a webhook its owner stops trusting — but the missing field is
    *named* in the prompt, so the agent knows the event arrived half-formed
    instead of quietly answering as though it had read it.
    """
    text = template.replace("{payload}", json.dumps(payload, ensure_ascii=False))

    def one(match: Any) -> str:
        path = match.group(1).strip().split(".")
        value: Any = payload
        for part in path:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return f"[{match.group(0)[1:-1]}: missing]"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return "" if value is None else str(value)

    import re

    return re.sub(r"\{\.([A-Za-z0-9_.\-]+)\}", one, text)


class Subscriptions:
    """The list, read from and written to one small file."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "subs.json"

    def load(self) -> list[Sub]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [Sub(name=str(item.get("name") or ""),
                    path=str(item.get("path") or ""),
                    secret=str(item.get("secret") or ""),
                    template=str(item.get("template") or "{payload}"),
                    reply_url=str(item.get("reply_url") or ""),
                    allow_writes=bool(item.get("allow_writes")))
                for item in document.get("subs", []) if item.get("name")]

    def save(self, subs: list[Sub]) -> None:
        """Written atomically and 0600, like every file full of secrets."""
        document = {"subs": [{"name": sub.name, **sub.to_json()}
                             for sub in subs]}
        handle, temp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                json.dump(document, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def by_path(self, path: str) -> Sub | None:
        return next((sub for sub in self.load() if sub.path == path), None)

    def add(self, sub: Sub) -> None:
        subs = [item for item in self.load() if item.name != sub.name]
        subs.append(sub)
        self.save(subs)

    def remove(self, name: str) -> bool:
        subs = self.load()
        kept = [item for item in subs if item.name != name]
        if len(kept) == len(subs):
            return False
        self.save(kept)
        return True


def load(config: Config) -> Subscriptions:
    return Subscriptions(config.paths.user / "webhook")


def a_secret() -> str:
    """A fresh shared secret, generated rather than chosen."""
    return secrets.token_urlsafe(24)
