"""A tiny in-memory cache with a size limit."""

from __future__ import annotations


class Cache:
    """Least-recently-used, up to `size` entries."""

    def __init__(self, size: int = 3) -> None:
        self.size = size
        self._entries: dict[str, object] = {}

    def get(self, key: str, default=None):
        return self._entries.get(key, default)

    def put(self, key: str, value: object) -> None:
        if key not in self._entries and len(self._entries) >= self.size:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
        self._entries[key] = value

    def __len__(self) -> int:
        return len(self._entries)
