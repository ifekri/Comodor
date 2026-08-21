"""BM25 ranking in pure Python.

SQLite's FTS5 already provides ``bm25()`` and is used when the interpreter was
built with it. This module is the fallback for the builds that were not, and it
doubles as the similarity function used to detect that a "new" lesson is really
a restatement of one already stored.

The corpus here is small — a few hundred lessons, not a web index — so a plain
in-memory inverted index is both simpler and fast enough.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

# Split on anything that is not a word character; keep identifiers like
# `read_file` and `src/tools/fs.py` together because those are exactly the terms
# that make a lesson findable. Trailing punctuation is stripped afterwards —
# leaving it on turns "unittest." and "unittest" into different terms, which
# quietly destroys both retrieval and duplicate detection.
#: A word in any script, keeping the shapes a developer types: `src/app.py`,
#: `snake_case`, `kebab-case`, `v1.2`.
#:
#: `\w` rather than `[A-Za-z0-9_]`, and that one character is the difference
#: between a memory that works in Persian and one that has never stored a
#: single thing. The ASCII class matched no Arabic, Cyrillic, Greek, Hebrew or
#: Devanagari at all, so for a user working in any of them `tokenize` returned
#: an empty list — nothing indexed, nothing recalled, and no error to say so.
#:
#: The zero-width non-joiner is inside a word rather than between two: Persian
#: uses it constantly, and splitting `می‌خواهم` into two halves gives the index
#: two fragments and neither of them the word.
ZWNJ = "‌"
_TOKEN = re.compile(rf"\w[\w{ZWNJ}\-./]*", re.UNICODE)
_TRAILING = ".-/_" + ZWNJ

STOPWORDS = frozenset("""
a an and are as at be but by for from has have if in into is it its of on or
that the their then there these this to was were will with you your do does
i we they he she them our us me my than when over while after before also
just so such not no yes can could should would may might must
""".split()) | frozenset("""
از به با در را که این آن های ها یک برای است بود شد می نمی هم یا تا بر هر چه
کن کند کرد باید نباید ای اند ام ات اش شان مان تان روی مورد بین
و في من على إلى عن مع هذا هذه ذلك التي الذي هو هي قد لم لا ما أن إن
של את זה היא הוא עם אל כל לא כן אם
""".split())
"""Common words in the languages this is most often used in.

English, Persian and a little Arabic and Hebrew. A stopword list is not
linguistics — it is a list of terms so common that matching on them tells the
ranking nothing, and every language a user writes in needs one or the index
fills with its equivalents of "the".
"""

K1 = 1.5      # term-frequency saturation
B = 0.75      # length normalisation


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text or ""):
        token = raw.lower().rstrip(_TRAILING)
        if len(token) > 1 and token not in STOPWORDS:
            tokens.append(token)
    return tokens


@dataclass
class BM25Index:
    """An inverted index over ``(doc_id, text)`` pairs."""

    documents: dict[str, list[str]] = field(default_factory=dict)
    frequencies: dict[str, dict[str, int]] = field(default_factory=dict)  # term -> doc -> tf
    lengths: dict[str, int] = field(default_factory=dict)
    _avg_length: float = 0.0

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        self.remove(doc_id)
        self.documents[doc_id] = tokens
        self.lengths[doc_id] = len(tokens)
        for term, count in Counter(tokens).items():
            self.frequencies.setdefault(term, {})[doc_id] = count
        self._avg_length = 0.0

    def remove(self, doc_id: str) -> None:
        tokens = self.documents.pop(doc_id, None)
        if tokens is None:
            return
        self.lengths.pop(doc_id, None)
        for term in set(tokens):
            postings = self.frequencies.get(term)
            if postings:
                postings.pop(doc_id, None)
                if not postings:
                    del self.frequencies[term]
        self._avg_length = 0.0

    @property
    def avg_length(self) -> float:
        if not self._avg_length and self.lengths:
            self._avg_length = sum(self.lengths.values()) / len(self.lengths)
        return self._avg_length or 1.0

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Return ``(doc_id, score)`` pairs, best first."""
        terms = tokenize(query)
        if not terms or not self.documents:
            return []

        total_docs = len(self.documents)
        avg = self.avg_length
        scores: dict[str, float] = {}

        for term in terms:
            postings = self.frequencies.get(term)
            if not postings:
                continue
            # Standard BM25 IDF, floored so a term in nearly every document
            # contributes nothing rather than something negative.
            idf = max(0.0, math.log(
                1 + (total_docs - len(postings) + 0.5) / (len(postings) + 0.5)))
            for doc_id, frequency in postings.items():
                length = self.lengths.get(doc_id, 1)
                denominator = frequency + K1 * (1 - B + B * length / avg)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * frequency * (K1 + 1) / denominator

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return ranked[:limit]

    def __len__(self) -> int:
        return len(self.documents)


def similarity(left: str, right: str) -> float:
    """How much two texts say the same thing, in ``[0, 1]``.

    This uses the overlap coefficient — the intersection over the *smaller*
    token set — rather than Jaccard. Deduplication compares a freshly written
    lesson against a stored one, and the two are rarely the same length; Jaccard
    punishes the longer text for its extra words and scores obvious restatements
    far too low. Very short texts fall back to Jaccard, where the overlap
    coefficient is too easy to satisfy by accident.
    """
    a, b = set(tokenize(left)), set(tokenize(right))
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if min(len(a), len(b)) < 3:
        return shared / len(a | b)
    return shared / min(len(a), len(b))


def coverage(query: str, document: str) -> float:
    """The fraction of the query's terms that appear in the document.

    BM25 is the right ranking function for a large corpus and the wrong one for
    a small one: with a handful of documents the IDF of every term collapses
    toward zero and all scores become indistinguishable noise. A brand-new brain
    is exactly that case — and it is when good recall matters most, because the
    user is deciding whether the learning is worth anything. Coverage stays
    meaningful at any corpus size, so retrieval blends the two.
    """
    terms = set(tokenize(query))
    if not terms:
        return 0.0
    present = set(tokenize(document))
    return len(terms & present) / len(terms)
