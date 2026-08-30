"""Getting records back out."""

from __future__ import annotations

from .keys import mk_k, mk_k_prefix


class Reader:
    def __init__(self, backing: dict[str, str]) -> None:
        self.backing = backing

    def load(self, kind: str, identifier: str) -> str | None:
        return self.backing.get(mk_k(kind, identifier))

    def all_of(self, kind: str) -> list[str]:
        prefix = mk_k_prefix(kind)
        return [body for key, body in sorted(self.backing.items())
                if key.startswith(prefix)]
