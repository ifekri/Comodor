"""Learning what your words mean to each other.

Recall is term matching, and term matching has one failure that dominates all
the others: the request and the lesson are about the same thing in different
words. Ask for *tests for the parser* and a lesson that reads *use pytest
fixtures rather than setUp* scores exactly zero, because not one word is
shared. It is the right lesson and it is invisible.

The usual answer is an embedding model. That is a dependency, a download, a
few hundred megabytes and a latency budget, and it buys a vocabulary somebody
else learned from somebody else's corpus. This project has one dependency and a
recall budget measured in fractions of a millisecond, so that answer is closed.

The answer taken instead is the one the rest of the product already takes:
**learn it by counting.** Every finished task is a bag of words that turned out
to belong to one piece of work — the request, the files touched, the lessons
credited. Terms that keep turning up in the same task are terms that mean
something to each other *here*, in this codebase, to this person. Count the
pairs, and the vocabulary emerges from the work.

What that gives, which a general-purpose embedding does not:

* **Your words.** If this team says `spec` where the tests are called `pytest`,
  those two link, and nobody had to write a synonym list.
* **Your names.** `auth` links to `middleware`, `Session`, `refresh_token` —
  the specific things that co-occur in this repository and nowhere else.
* **Your languages.** A task written in Persian whose lessons are in English
  links the two, because they occurred together. Cross-language recall falls
  out of the same counting, with no translation anywhere.

The weights are association strengths, not probabilities, and they are held
deliberately weak: an expanded term contributes a fraction of a real one, so a
wrong guess costs a little relevance and never outranks an actual match. That
is the trade — the expansion is allowed to be sometimes wrong because it can
only ever nudge.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .bm25 import tokenize

#: How many terms of one task are worth relating. The interesting words in a
#: task are few; past this it is the long tail, and pairing everything with
#: everything is quadratic in the tail.
TERMS_PER_EPISODE = 14
#: How many associates one term may contribute to a query.
BRANCHES = 3
#: How many expanded terms a whole query may gain. More than this and the
#: expansion is the query.
MAX_EXPANSION = 6
#: An expanded term is worth this fraction of one the user actually typed.
EXPANSION_WEIGHT = 0.35
#: Pairs seen once are coincidence. Twice is the beginning of a pattern.
MIN_OBSERVATIONS = 2


@dataclass
class Associations:
    """Which terms turn up together, and how strongly.

    Symmetric: ``pairs[a][b]`` and ``pairs[b][a]`` are the same count, stored
    twice so that a lookup is one dictionary access rather than a scan. The
    table is small — a few thousand terms after a year of use — and it is worth
    the duplication to keep expansion off the critical path.
    """

    pairs: dict[str, Counter] = field(default_factory=dict)
    #: How many episodes each term appeared in. The denominator that stops a
    #: term which appears in everything from associating with everything.
    totals: Counter = field(default_factory=Counter)
    episodes: int = 0

    # -- learning ---------------------------------------------------------- #

    def observe(self, *texts: str) -> int:
        """Record one task's worth of co-occurrence. Returns terms related.

        The whole task is one bag: the goal, the files, the lessons that came
        out of it. Order is not used and neither is distance — two terms in the
        same task are related whether they were a word apart or a hundred,
        because a task is the unit of work and that is what is being learned.
        """
        counted = Counter()
        for text in texts:
            counted.update(tokenize(text or ""))
        if len(counted) < 2:
            return 0

        # The most frequent terms of this task, not of the corpus: within one
        # task, repetition is emphasis.
        terms = [term for term, _ in counted.most_common(TERMS_PER_EPISODE)]

        self.episodes += 1
        for term in terms:
            self.totals[term] += 1

        for index, left in enumerate(terms):
            row = self.pairs.setdefault(left, Counter())
            for right in terms[index + 1:]:
                row[right] += 1
                self.pairs.setdefault(right, Counter())[left] += 1
        return len(terms)

    # -- using ------------------------------------------------------------- #

    def strength(self, left: str, right: str) -> float:
        """How related two terms are, in ``[0, 1]``.

        Pointwise mutual information, normalised. A raw count would make every
        term associate with whatever is most common — `file`, `test`, `error`
        turn up everywhere and would dominate every expansion. PMI asks
        something better: do these two occur together *more often than their
        own frequencies would predict*? A term that appears in half the
        episodes has to co-occur very often indeed to clear that bar.
        """
        together = self.pairs.get(left, {}).get(right, 0)
        if together < MIN_OBSERVATIONS or not self.episodes:
            return 0.0

        left_count = self.totals.get(left, 0)
        right_count = self.totals.get(right, 0)
        if not left_count or not right_count:
            return 0.0

        joint = together / self.episodes
        expected = (left_count / self.episodes) * (right_count / self.episodes)
        if joint <= 0 or expected <= 0:
            return 0.0

        pmi = math.log(joint / expected)
        if pmi <= 0:
            return 0.0                     # together less often than by chance
        # Normalised PMI: divide by the self-information of the pair, which
        # bounds it at 1 for terms that only ever appear together.
        bound = -math.log(joint)
        return min(1.0, pmi / bound) if bound > 0 else 0.0

    def expand(self, query: str, limit: int = MAX_EXPANSION) -> list[tuple[str, float]]:
        """Terms this query implies, with what each is worth.

        Never a term the query already has, and never enough of them to become
        the query: the expansion is a nudge toward lessons phrased differently,
        not a second search.
        """
        terms = tokenize(query)
        if not terms:
            return []

        original = set(terms)
        candidates: Counter = Counter()

        for term in original:
            row = self.pairs.get(term)
            if not row:
                continue
            scored = sorted(
                ((other, self.strength(term, other))
                 for other, _ in row.most_common(30) if other not in original),
                key=lambda pair: pair[1], reverse=True,
            )
            for other, value in scored[:BRANCHES]:
                if value <= 0:
                    break
                # A term reached from two different query words is a better
                # guess than one reached from a single word, so the strengths
                # add rather than replace.
                candidates[other] = max(candidates[other], 0.0) + value

        best = candidates.most_common(limit)
        top = best[0][1] if best else 1.0
        return [(term, EXPANSION_WEIGHT * value / top)
                for term, value in best if value > 0]

    def enrich(self, query: str) -> str:
        """The query with its associates appended, for a text-matching search.

        Repetition is the only way to weight a term in a bag-of-words search, so
        a strong associate is repeated and a weak one appears once. Crude, and
        exactly as expressive as the thing it is feeding.
        """
        additions: list[str] = []
        for term, weight in self.expand(query):
            additions.extend([term] * (2 if weight > EXPANSION_WEIGHT * 0.6 else 1))
        if not additions:
            return query
        return f"{query} {' '.join(additions)}"

    # -- persistence -------------------------------------------------------- #

    def prune(self, keep: int = 20_000) -> int:
        """Forget the pairs that never became a pattern.

        Association tables grow quadratically in the vocabulary and most of
        that growth is noise: two words that shared one task and never met
        again. Dropping everything below the observation floor keeps the table
        proportional to what was actually learned rather than to how much was
        typed.
        """
        removed = 0
        for left in list(self.pairs):
            row = self.pairs[left]
            for right in list(row):
                if row[right] < MIN_OBSERVATIONS:
                    del row[right]
                    removed += 1
            if not row:
                del self.pairs[left]

        total = sum(len(row) for row in self.pairs.values())
        if total > keep:
            # Still too large: keep the strongest, by raw count.
            flat = sorted(
                ((left, right, count)
                 for left, row in self.pairs.items() for right, count in row.items()),
                key=lambda triple: triple[2], reverse=True,
            )[:keep]
            self.pairs = {}
            for left, right, count in flat:
                self.pairs.setdefault(left, Counter())[right] = count
            removed += total - keep
        return removed

    def to_dict(self) -> dict:
        return {
            "episodes": self.episodes,
            "totals": dict(self.totals),
            "pairs": {left: dict(row) for left, row in self.pairs.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Associations":
        table = cls(episodes=int(data.get("episodes") or 0))
        table.totals = Counter(data.get("totals") or {})
        for left, row in (data.get("pairs") or {}).items():
            table.pairs[left] = Counter(row)
        return table

    @property
    def size(self) -> int:
        return sum(len(row) for row in self.pairs.values())
