"""Retrying a call that fails for a reason that might not recur.

`retry` is not written yet. Everything it needs to fit into is here.
"""

from __future__ import annotations


class Exhausted(Exception):
    """Every attempt failed. Carries the last failure as its cause."""


def backoff(attempt: int, base: float = 0.1) -> float:
    """Seconds to wait before attempt `attempt`, numbered from 1.

    Doubles each time: 0 before the first, then base, 2×base, 4×base…
    """
    if attempt <= 1:
        return 0.0
    return base * (2 ** (attempt - 2))
