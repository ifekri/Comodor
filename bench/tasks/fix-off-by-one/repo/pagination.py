"""Splitting a list of results into pages."""


def page_count(total: int, per_page: int) -> int:
    """How many pages `total` items need."""
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    return total // per_page


def page(items: list, number: int, per_page: int = 10) -> list:
    """One page of `items`, numbered from 1."""
    if number < 1:
        raise ValueError("pages are numbered from 1")
    start = (number - 1) * per_page
    return items[start:start + per_page]
