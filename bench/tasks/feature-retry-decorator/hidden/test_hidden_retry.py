"""The spec, as assertions. Added after the run, never visible to the agent.

Held back because a spec in prose and a spec as tests are different problems.
Handing over the tests turns "build what was described" into "make these
pass", and the second is the easier one — it is the difference between reading
a requirement and being given the answer.
"""

import pytest
from retry import Exhausted, retry


def test_a_call_that_works_is_not_retried():
    calls = []

    @retry(times=3, base=0.0)
    def works():
        calls.append(1)
        return "done"

    assert works() == "done"
    assert len(calls) == 1


def test_it_tries_the_number_of_times_it_was_given():
    calls = []

    @retry(times=3, base=0.0, catch=(ConnectionError,))
    def always_fails():
        calls.append(1)
        raise ConnectionError("no route")

    with pytest.raises(Exhausted):
        always_fails()
    assert len(calls) == 3, f"called {len(calls)} times, expected 3"


def test_it_stops_as_soon_as_one_works():
    calls = []

    @retry(times=5, base=0.0, catch=(ConnectionError,))
    def works_third_time():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("not yet")
        return "third"

    assert works_third_time() == "third"
    assert len(calls) == 3


def test_something_it_was_not_asked_to_catch_comes_straight_out():
    calls = []

    @retry(times=3, base=0.0, catch=(ConnectionError,))
    def wrong_kind():
        calls.append(1)
        raise ValueError("a bug, not a blip")

    with pytest.raises(ValueError):
        wrong_kind()
    assert len(calls) == 1, "a ValueError was retried"


def test_the_last_failure_is_the_cause():
    last = ConnectionError("the final one")
    attempts = []

    @retry(times=2, base=0.0, catch=(ConnectionError,))
    def fails():
        attempts.append(1)
        raise last

    with pytest.raises(Exhausted) as caught:
        fails()
    assert caught.value.__cause__ is last


def test_the_wrapped_function_keeps_its_identity():
    @retry(times=2, base=0.0)
    def named():
        """What it says about itself."""
        return 1

    assert named.__name__ == "named"
    assert named.__doc__ == "What it says about itself."


def test_arguments_reach_the_function():
    @retry(times=2, base=0.0)
    def add(left, right, scale=1):
        return (left + right) * scale

    assert add(2, 3, scale=10) == 50


def test_it_waits_between_attempts():
    """Measured on the clock rather than by patching `time.sleep`.

    Patching would pin *how* the waiting is done — `import time` versus
    `from time import sleep` — and the spec does not say. What it says is that
    the wait happens, and three attempts at `base=0.1` means `backoff(2)` plus
    `backoff(3)`, which is 0.3 seconds of it.
    """
    import time as clock

    @retry(times=3, base=0.1, catch=(ConnectionError,))
    def fails():
        raise ConnectionError("no")

    started = clock.monotonic()
    with pytest.raises(Exhausted):
        fails()
    elapsed = clock.monotonic() - started

    assert elapsed >= 0.25, f"three attempts took {elapsed:.2f}s — it did not wait"
    assert elapsed < 3.0, f"three attempts took {elapsed:.2f}s — far too long"


def test_the_first_attempt_is_not_delayed():
    import time as clock

    @retry(times=3, base=5.0)
    def works():
        return "now"

    started = clock.monotonic()
    assert works() == "now"
    assert clock.monotonic() - started < 1.0, "it waited before the first try"


def test_the_defaults_are_usable_without_arguments():
    calls = []

    @retry()
    def fails():
        calls.append(1)
        raise RuntimeError("anything")

    with pytest.raises(Exhausted):
        fails()
    assert len(calls) > 1, "the default should retry more than once"
