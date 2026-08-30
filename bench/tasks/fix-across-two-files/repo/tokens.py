"""Splitting a search query into terms."""

from __future__ import annotations

import re

WORD = re.compile(r"[\w']+")

#: Words too common to be worth matching on.
STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "is"}


def terms(query: str) -> list[str]:
    """The words worth searching for, lowercased, in order, without repeats."""
    seen = []
    for match in WORD.finditer(query.lower()):
        word = match.group(0)
        if word in STOPWORDS:
            continue
        if word not in seen:
            seen.append(word)
    return seen
