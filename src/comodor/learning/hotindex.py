"""The RAM mirror that makes memory instant.

Retrieval used to go through SQL and re-tokenise every stored lesson on every
call. That is fine at ten lessons and unacceptable at three thousand: measured
before this module existed, deduplication took 22 ms and recall pulled the whole
table through SQLite. Both sat directly on the path between the user pressing
Enter and the first token arriving.

The fix is boring and effective: keep the whole corpus in memory with its tokens
already computed, plus a term to id inverted index. Lookups then touch only the
documents that share a word with the query — a set intersection over a handful
of candidates instead of a scan over everything.

The trade is memory: a few hundred bytes per lesson, so ten thousand lessons cost
single-digit megabytes. That is the right side of the trade for something on the
critical path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from itertools import islice
from typing import Iterable, Iterator

from .bm25 import tokenize

EMPTY: frozenset[str] = frozenset()

# Ceiling on how many documents a single lookup will score. Bounding the work
# is what makes recall cost the same at ten lessons and at ten thousand.
MAX_CANDIDATES = 400


@dataclass(slots=True)
class Doc:
    """One indexed record: its id, its scope, and its tokens."""

    id: int
    kind: str                    # lesson | rule | skill
    scope: str
    tokens: frozenset[str]
    text: str = ""

    @property
    def key(self) -> tuple[str, int]:
        return (self.kind, self.id)


class HotIndex:
    """An in-memory inverted index, maintained incrementally.

    Thread-safe because reflection writes from a background thread while the UI
    thread prefetches recall. The lock is held only for the pointer swaps, never
    across scoring, so a slow query cannot block a write.
    """

    def __init__(self) -> None:
        self._docs: dict[tuple[str, int], Doc] = {}
        self._terms: dict[str, set[tuple[str, int]]] = {}
        self._lock = threading.RLock()

    # -- maintenance ------------------------------------------------------ #

    def add(self, kind: str, doc_id: int, text: str, scope: str = "global") -> Doc:
        """Index one record, replacing any earlier version of it."""
        tokens = frozenset(tokenize(text))
        doc = Doc(id=doc_id, kind=kind, scope=scope, tokens=tokens, text=text)
        with self._lock:
            self._remove_locked(doc.key)
            self._docs[doc.key] = doc
            for term in tokens:
                self._terms.setdefault(term, set()).add(doc.key)
        return doc

    def remove(self, kind: str, doc_id: int) -> bool:
        with self._lock:
            return self._remove_locked((kind, doc_id))

    def _remove_locked(self, key: tuple[str, int]) -> bool:
        doc = self._docs.pop(key, None)
        if doc is None:
            return False
        for term in doc.tokens:
            postings = self._terms.get(term)
            if postings is not None:
                postings.discard(key)
                if not postings:
                    del self._terms[term]
        return True

    def rebuild(self, records: Iterable[tuple[str, int, str, str]]) -> int:
        """Replace the whole index. Used once at startup."""
        docs: dict[tuple[str, int], Doc] = {}
        terms: dict[str, set[tuple[str, int]]] = {}
        for kind, doc_id, text, scope in records:
            tokens = frozenset(tokenize(text))
            doc = Doc(id=doc_id, kind=kind, scope=scope, tokens=tokens, text=text)
            docs[doc.key] = doc
            for term in tokens:
                terms.setdefault(term, set()).add(doc.key)
        with self._lock:
            self._docs, self._terms = docs, terms
        return len(docs)

    def selective(self, terms: list[str], ceiling: float = 0.1) -> list[str]:
        """The terms worth searching on, rarest first, commonest dropped.

        Ordering alone does nothing, which was worth finding out by measuring
        rather than assuming: a single term that appears in most of the table
        makes the union enormous whatever else is in the query, so ranking the
        others ahead of it changes neither the rows scanned nor the time. It
        has to be *removed*.

        Which is the same thing IDF says — a term in most documents separates
        nothing — arrived at from the cost side. The posting lists are already
        in memory, so knowing which terms those are is a dictionary lookup.

        Everything is dropped only if everything is common; then the caller
        gets the rarest few back, because a search that returns nothing is
        worse than a slow one.
        """
        with self._lock:
            total = max(1, len(self._docs))
            ranked = sorted(terms, key=lambda term: len(self._terms.get(term, ())))
            keep = [term for term in ranked
                    if len(self._terms.get(term, ())) <= ceiling * total]
        return keep or ranked

    def clear(self) -> None:
        with self._lock:
            self._docs.clear()
            self._terms.clear()

    # -- lookup ----------------------------------------------------------- #

    def candidates(self, query: str, kind: str = "",
                   scopes: Iterable[str] | None = None,
                   max_candidates: int = MAX_CANDIDATES) -> tuple[set[str], list[Doc]]:
        """Documents sharing at least one term with the query.

        Rare terms are expanded first and the candidate set is capped, which is
        what keeps lookup flat as the brain grows. The reasoning is the same one
        behind IDF: a term that appears in most of the corpus barely changes the
        ranking but costs the most to scan, so once there are enough candidates
        the common terms are not worth expanding. Anything they would have added
        would have scored near the bottom anyway.

        Returns the query tokens too, because every caller needs them next and
        tokenising twice is pure waste on a hot path.
        """
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return query_tokens, []

        allowed = set(scopes) if scopes else None
        with self._lock:
            postings = sorted(
                (self._terms.get(term, EMPTY) for term in query_tokens),
                key=len,
            )
            keys: set[tuple[str, int]] = set()
            for matches in postings:
                room = max_candidates - len(keys)
                if room <= 0:
                    break
                if len(matches) <= room:
                    keys |= matches                        # type: ignore[arg-type]
                else:
                    # This term is too common to be selective, so the documents
                    # it would add are near-random with respect to relevance.
                    # Take a bounded slice: the genuinely informative matches
                    # already came from the rarer terms processed before it.
                    keys.update(islice(matches, room))
                    break
            docs = [self._docs[key] for key in keys if key in self._docs]

        return query_tokens, [
            doc for doc in docs
            if (not kind or doc.kind == kind) and (allowed is None or doc.scope in allowed)
        ]

    def coverage_scan(self, query: str, kind: str = "",
                      scopes: Iterable[str] | None = None,
                      limit: int = 20) -> list[tuple[Doc, float]]:
        """Rank candidates by how much of the query they cover.

        Coverage rather than BM25 because this index exists to be fast and
        stable at any corpus size; BM25's IDF is meaningless on a small brain.
        The caller blends this with FTS ranking where that is available.
        """
        query_tokens, docs = self.candidates(query, kind, scopes)
        if not query_tokens or not docs:
            return []
        size = len(query_tokens)
        scored = [(doc, len(query_tokens & doc.tokens) / size) for doc in docs]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def nearest(self, text: str, threshold: float = 0.55, kind: str = "",
                scopes: Iterable[str] | None = None) -> tuple[Doc | None, float]:
        """The closest existing record, for duplicate detection.

        Uses the overlap coefficient, matching
        :func:`comodor.learning.bm25.similarity`, so deduplication behaves the
        same whether it runs through here or through the store.
        """
        query_tokens, docs = self.candidates(text, kind, scopes)
        if not query_tokens:
            return None, 0.0

        best: Doc | None = None
        best_score = threshold
        for doc in docs:
            if not doc.tokens:
                continue
            smaller = min(len(query_tokens), len(doc.tokens))
            if smaller < 3:
                score = len(query_tokens & doc.tokens) / len(query_tokens | doc.tokens)
            else:
                score = len(query_tokens & doc.tokens) / smaller
            if score > best_score:
                best, best_score = doc, score
        return best, (best_score if best is not None else 0.0)

    # -- introspection ---------------------------------------------------- #

    def get(self, kind: str, doc_id: int) -> Doc | None:
        with self._lock:
            return self._docs.get((kind, doc_id))

    def of_kind(self, kind: str) -> Iterator[Doc]:
        with self._lock:
            return iter([doc for doc in self._docs.values() if doc.kind == kind])

    def __len__(self) -> int:
        with self._lock:
            return len(self._docs)

    @property
    def terms(self) -> int:
        with self._lock:
            return len(self._terms)

    def stats(self) -> dict[str, int]:
        with self._lock:
            kinds: dict[str, int] = {}
            for doc in self._docs.values():
                kinds[doc.kind] = kinds.get(doc.kind, 0) + 1
            postings = sum(len(keys) for keys in self._terms.values())
        return {"documents": len(self._docs), "terms": len(self._terms),
                "postings": postings, **{f"kind_{k}": v for k, v in kinds.items()}}
