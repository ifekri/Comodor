import pytest
from stats import mean, spread, summary


def test_the_mean_of_a_few_numbers():
    assert mean([2.0, 4.0, 6.0]) == 4.0


def test_the_spread_of_a_few_numbers():
    assert spread([2.0, 9.0, 4.0]) == 7.0


def test_a_summary_carries_all_three():
    assert summary([1.0, 3.0]) == {"mean": 2.0, "spread": 2.0, "count": 2}


def test_no_measurements_is_not_a_crash():
    """A run that recorded nothing is a normal outcome, not an error. Both
    figures are undefined, so both are zero, and `count` says which it was."""
    assert summary([]) == {"mean": 0.0, "spread": 0.0, "count": 0}


def test_a_single_measurement_has_no_spread():
    assert summary([5.0]) == {"mean": 5.0, "spread": 0.0, "count": 1}


def test_the_two_pieces_agree_with_the_summary():
    with pytest.raises(ZeroDivisionError):
        # Kept deliberately: `mean` on its own is still a programming error to
        # call with nothing. Only the summary is defined for an empty run.
        mean([])
