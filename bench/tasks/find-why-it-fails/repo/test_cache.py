from cache import Cache


def test_it_holds_what_it_was_given():
    cache = Cache(size=3)
    cache.put("a", 1)
    assert cache.get("a") == 1


def test_it_does_not_grow_past_its_size():
    cache = Cache(size=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert len(cache) == 2


def test_reading_an_entry_keeps_it_alive():
    """Least-recently-*used*, so a read counts as a use."""
    cache = Cache(size=2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")            # "a" is now the most recently used
    cache.put("c", 3)         # so "b" is the one that should go
    assert cache.get("a") == 1
    assert cache.get("b") is None
