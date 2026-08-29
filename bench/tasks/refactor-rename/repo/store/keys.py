"""Building the keys records are filed under."""

from __future__ import annotations


def mk_k(kind: str, identifier: str) -> str:
    """The key one record is stored at."""
    return f"{kind}:{identifier}"


def mk_k_prefix(kind: str) -> str:
    """Everything of one kind."""
    return f"{kind}:"
