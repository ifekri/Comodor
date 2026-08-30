"""Putting records in."""

from __future__ import annotations

from .keys import mk_k


class Writer:
    def __init__(self, backing: dict[str, str]) -> None:
        self.backing = backing

    def save(self, kind: str, identifier: str, body: str) -> str:
        key = mk_k(kind, identifier)
        self.backing[key] = body
        return key

    def save_many(self, kind: str, records: dict[str, str]) -> list[str]:
        return [self.save(kind, identifier, body)
                for identifier, body in sorted(records.items())]
