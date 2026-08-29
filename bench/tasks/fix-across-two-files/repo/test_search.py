from search import rank, score
from tokens import terms


def test_stopwords_are_dropped():
    assert terms("the cost of a plan") == ["cost", "plan"]


def test_repeats_are_dropped():
    assert terms("plan plan cost") == ["plan", "cost"]


def test_a_query_of_only_stopwords_finds_nothing():
    assert terms("the a of") == []
    assert score("anything at all", "the a of") == 0.0


def test_a_whole_word_is_needed_not_a_fragment():
    """`plan` must not match `planet`. A fragment match makes every short
    query return the whole corpus."""
    assert score("a distant planet", "plan") == 0.0
    assert score("the growth plan", "plan") == 1.0


def test_ranking_puts_the_best_first():
    documents = ["the growth plan costs less",
                 "a distant planet",
                 "plan"]
    assert [document for document, _ in rank(documents, "plan cost")] == [
        "the growth plan costs less", "plan"]


def test_ties_keep_their_original_order():
    documents = ["plan one", "plan two"]
    assert [document for document, _ in rank(documents, "plan")] == [
        "plan one", "plan two"]
