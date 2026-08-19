"""Transient notices.

Short-lived messages — "copied", "compacted 12 messages", "learned 2 lessons" —
that deserve a moment of attention but not a permanent line in the transcript.
They expire on their own so nothing has to be dismissed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import RenderableType
from rich.text import Text

from ..theme import Theme

DEFAULT_TTL = 4.0


@dataclass
class Toast:
    text: str
    tone: str = "dim"               # dim | good | warn | bad | accent
    born: float = field(default_factory=time.monotonic)
    ttl: float = DEFAULT_TTL

    @property
    def expired(self) -> bool:
        return time.monotonic() - self.born > self.ttl


class ToastQueue:
    """A tiny stack of notices; only the newest few are ever shown."""

    def __init__(self, limit: int = 3) -> None:
        self.limit = limit
        self.items: list[Toast] = []

    def push(self, text: str, tone: str = "dim", ttl: float = DEFAULT_TTL) -> None:
        self.items.append(Toast(text=text, tone=tone, ttl=ttl))
        del self.items[:-self.limit]

    def prune(self) -> bool:
        """Drop expired notices; returns True when something changed."""
        before = len(self.items)
        self.items = [item for item in self.items if not item.expired]
        return len(self.items) != before

    @property
    def active(self) -> bool:
        return bool(self.items)

    def render(self, theme: Theme, width: int) -> RenderableType:
        text = Text()
        for index, toast in enumerate(self.items):
            if index:
                text.append("  ")
            text.append(f"{theme.glyphs.bullet} ", style=theme.style(toast.tone))
            text.append(_fit(toast.text, width - 3), style=theme.style(toast.tone))
        return text


def _fit(text: str, width: int) -> str:
    text = " ".join(text.split())
    width = max(8, width)
    return text if len(text) <= width else text[: width - 1] + "…"
