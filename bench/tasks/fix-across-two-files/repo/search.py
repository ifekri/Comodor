"""Ranking documents against a query."""

from __future__ import annotations

from tokens import terms


def score(document: str, query: str) -> float:
    """How well `document` answers `query`, between 0 and 1.

    The share of the query's terms that appear in the document.
    """
    wanted = terms(query)
    if not wanted:
        return 0.0
    body = document.lower()
    hits = sum(1 for term in wanted if term in body)
    return hits / len(wanted)


def rank(documents: list[str], query: str) -> list[tuple[str, float]]:
    """Documents that match at all, best first, ties in original order."""
    scored = [(document, score(document, query)) for document in documents]
    matched = [pair for pair in scored if pair[1] > 0]
    return sorted(matched, key=lambda pair: pair[1], reverse=True)
