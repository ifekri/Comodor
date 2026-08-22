"""The vocabulary the brain learns from its own work.

Recall is term matching, and term matching fails in exactly one way that
matters: the request and the lesson mean the same thing in different words. Ask
for *a spec for the parser* and a lesson reading *use pytest fixtures* shares
not one token — it is the right lesson and it is invisible.

The usual fix is an embedding model, which is a dependency and somebody else's
vocabulary. This counts instead: terms that keep turning up in the same
finished task mean something to each other *here*. What is tested is that the
counting produces something worth having, and — at least as important — that it
stays quiet when it has not learned anything yet.
"""

from __future__ import annotations

import pytest

from comodor.learning.associations import (
    EXPANSION_WEIGHT,
    MAX_EXPANSION,
    MIN_OBSERVATIONS,
    Associations,
)
from comodor.learning.bm25 import tokenize
from comodor.learning.store import coverage

#: A month of plausible work. No synonym list anywhere: the only input is which
#: words turned up in the same piece of work.
WORK = [
    ("add tests for the parser", "pytest fixtures tests/test_parser.py"),
    ("write a spec for the tokenizer", "pytest tests/test_tokenizer.py fixtures"),
    ("the parser spec is failing", "pytest tests/test_parser.py traceback"),
    ("add a spec for the lexer", "pytest fixtures tests/test_lexer.py"),
    ("fix the failing parser tests", "pytest tests/test_parser.py assert"),
    ("write specs for the grammar", "pytest grammar tests/test_grammar.py"),
    ("add auth to the api", "middleware session refresh_token src/auth.py"),
    ("the login flow drops the session", "middleware session src/auth.py cookie"),
    ("rotate refresh tokens on login", "refresh_token session src/auth.py"),
    ("auth middleware rejects cookies", "middleware cookie session src/auth.py"),
    ("یک تست برای پارسر بنویس", "pytest tests/test_parser.py fixtures"),
    ("تست‌های پارسر شکست می‌خورند", "pytest tests/test_parser.py traceback"),
    ("برای توکنایزر تست اضافه کن", "pytest tests/test_tokenizer.py"),
]


@pytest.fixture
def learned() -> Associations:
    table = Associations()
    for goal, touched in WORK:
        table.observe(goal, touched)
    return table


# --------------------------------------------------------------------------- #
# what it learns
# --------------------------------------------------------------------------- #


def test_words_used_for_the_same_work_become_related(learned):
    """`spec` and `pytest` are not synonyms in any dictionary. They are here."""
    assert learned.strength("spec", "pytest") > 0
    assert learned.strength("auth", "session") > 0


def test_words_from_different_work_do_not(learned):
    """Otherwise every term associates with every other and the expansion is noise."""
    assert learned.strength("auth", "tokenizer") == 0
    assert learned.strength("cookie", "grammar") == 0


def test_it_crosses_languages_without_translating_anything(learned):
    """The Persian for "test" links to `pytest` because they happened together.

    This is the part an off-the-shelf embedding would not give: a general model
    knows Persian, but it does not know that *this* person's `تست` means the
    pytest suite in *this* repository.
    """
    assert learned.strength("تست", "pytest") > 0
    assert learned.strength("پارسر", "tests/test_parser.py") > 0


def test_a_pair_seen_once_is_a_coincidence(learned):
    learned.observe("something entirely new", "unrelated words here")

    assert learned.strength("entirely", "unrelated") == 0
    assert learned.pairs["entirely"]["unrelated"] < MIN_OBSERVATIONS


def test_a_term_that_appears_everywhere_associates_with_nothing():
    """Raw counts would make `file` the strongest associate of every word.

    Normalised mutual information asks the better question: do these two occur
    together more often than their own frequencies already predict?
    """
    table = Associations()
    for index in range(20):
        table.observe(f"file topic{index}", f"file subject{index}")

    assert table.strength("topic1", "file") == 0
    assert table.totals["file"] == 20


def test_a_pair_that_only_ever_occurs_together_is_the_strongest_link():
    table = Associations()
    for _ in range(6):
        table.observe("profile the startup", "cProfile import")
        table.observe("something else", "different words")

    assert table.strength("profile", "cprofile") > 0.9


# --------------------------------------------------------------------------- #
# what it does to a query
# --------------------------------------------------------------------------- #


def test_the_case_this_exists_for(learned):
    """The lesson is exactly on topic and shares no word with the request."""
    lesson = "Use pytest fixtures rather than setUp methods"
    query = "write a spec for the parser"

    assert coverage(query, lesson) == 0.0
    assert coverage(learned.enrich(query), lesson) > 0.0


def test_the_same_case_in_persian(learned):
    lesson = "Use pytest fixtures rather than setUp methods"
    query = "یک تست برای پارسر بنویس"

    assert coverage(query, lesson) == 0.0
    assert coverage(learned.enrich(query), lesson) > 0.0


def test_the_expansion_never_replaces_the_query(learned):
    """A nudge toward differently phrased lessons, not a second search."""
    added = learned.expand("write a spec for the parser")

    assert len(added) <= MAX_EXPANSION
    assert all(weight <= EXPANSION_WEIGHT for _, weight in added)


def test_it_never_suggests_a_word_the_query_already_has(learned):
    query = "pytest fixtures for the parser"
    original = set(tokenize(query))

    assert not {term for term, _ in learned.expand(query)} & original


def test_an_empty_brain_suggests_nothing():
    """A first run must not invent associations out of one task."""
    table = Associations()

    assert table.expand("write a spec for the parser") == []
    assert table.enrich("anything") == "anything"


def test_a_query_of_only_stopwords_expands_to_nothing(learned):
    assert learned.expand("the and of to") == []


def test_a_term_reached_from_two_query_words_ranks_above_one(learned):
    """Two independent routes to the same term is better evidence than one."""
    added = dict(learned.expand("the parser spec"))
    single = dict(learned.expand("grammar"))

    assert added, "nothing was suggested for a query with two related terms"
    assert max(added.values()) >= max(single.values(), default=0)


# --------------------------------------------------------------------------- #
# keeping it small
# --------------------------------------------------------------------------- #


def test_the_table_forgets_what_never_became_a_pattern():
    """Association tables grow quadratically, and most of that growth is noise."""
    table = Associations()
    for index in range(40):
        table.observe(f"unique{index} words", f"never{index} again")
    for _ in range(3):
        table.observe("this pair", "keeps happening")

    before = table.size
    table.prune()

    assert table.size < before
    assert table.strength("pair", "happening") > 0


def test_a_very_large_table_is_capped(learned):
    for index in range(200):
        learned.observe(f"alpha{index} beta{index}", f"gamma{index} delta{index}")
        learned.observe(f"alpha{index} beta{index}", f"gamma{index} delta{index}")

    learned.prune(keep=500)

    assert learned.size <= 500


def test_one_task_of_a_single_word_relates_nothing():
    table = Associations()

    assert table.observe("hello") == 0
    assert table.episodes == 0


# --------------------------------------------------------------------------- #
# surviving a restart
# --------------------------------------------------------------------------- #


def test_the_vocabulary_survives_being_written_and_read(learned):
    restored = Associations.from_dict(learned.to_dict())

    assert restored.episodes == learned.episodes
    assert restored.strength("spec", "pytest") == learned.strength("spec", "pytest")
    assert restored.expand("a spec for the parser") == \
        learned.expand("a spec for the parser")


def test_an_unreadable_table_is_the_same_as_no_table(tmp_path):
    """It is a cache of counting. Losing it costs accuracy, never correctness."""
    from comodor.learning.store import BrainStore

    store = BrainStore(tmp_path / "brain.db")
    with store._lock, store.connection as connection:
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('associations', ?)",
            ("{ not json",))

    table = store.load_associations()

    assert table.episodes == 0
    store.close()


def test_it_round_trips_through_the_brain(tmp_path, learned):
    from comodor.learning.store import BrainStore

    store = BrainStore(tmp_path / "brain.db")
    store.save_associations(learned)
    restored = store.load_associations()
    store.close()

    assert restored.strength("تست", "pytest") == learned.strength("تست", "pytest")


# --------------------------------------------------------------------------- #
# every script, which is the bug that made this necessary
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("text, expected", [
    ("یک تست برای پارسر بنویس", ["تست", "پارسر", "بنویس"]),
    ("добавь тест", ["добавь", "тест"]),
    ("הוסף בדיקה", ["הוסף", "בדיקה"]),
    ("προσθήκη δοκιμής", ["προσθήκη", "δοκιμής"]),
    ("src/app.py and snake_case", ["src/app.py", "snake_case"]),
])
def test_the_tokenizer_reads_every_script(text, expected):
    """It matched `[A-Za-z0-9_]` and nothing else, so for a user working in any
    of these the whole memory was a no-op: nothing indexed, nothing recalled,
    and no error anywhere to say so."""
    assert tokenize(text) == expected


def test_a_persian_word_is_not_split_at_its_zero_width_joiner():
    """Persian uses it constantly. Splitting gives the index two fragments and
    neither of them the word."""
    assert tokenize("می‌خواهم") == ["می‌خواهم"]
