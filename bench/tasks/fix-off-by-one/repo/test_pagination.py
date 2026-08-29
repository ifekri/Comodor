from pagination import page, page_count


def test_a_full_page_is_one_page():
    assert page_count(10, 10) == 1


def test_an_empty_list_has_no_pages():
    assert page_count(0, 10) == 0


def test_a_remainder_still_needs_a_page():
    assert page_count(11, 10) == 2


def test_the_last_partial_page_is_counted():
    assert page_count(25, 10) == 3


def test_pages_are_numbered_from_one():
    assert page(list(range(30)), 1, per_page=10) == list(range(10))
    assert page(list(range(30)), 3, per_page=10) == list(range(20, 30))
