"""The circuit breaker: five failing sends pause an adapter; a human's
/platform command is what brings it back."""

from __future__ import annotations

from comodor.channels.breaker import CircuitBreaker

# -- tripping ---------------------------------------------------------------- #

def test_a_few_failures_do_not_trip_it():
    breaker = CircuitBreaker("telegram")
    for _ in range(4):
        assert breaker.fail("timeout") is False
    assert breaker.paused is False


def test_five_consecutive_failures_trip_it():
    breaker = CircuitBreaker("telegram")
    for _ in range(5):
        tripped = breaker.fail("timeout")
    assert tripped is True
    assert breaker.paused is True


def test_a_success_resets_the_streak():
    breaker = CircuitBreaker("telegram")
    for _ in range(4):
        breaker.fail("timeout")
    breaker.ok()
    assert breaker.fail("timeout") is False, "one clean send means start over"


def test_a_tripped_breaker_announces_once():
    breaker = CircuitBreaker("telegram", trip_after=2)
    assert breaker.fail("first") is False
    assert breaker.fail("second") is True
    assert breaker.fail("third") is False, "already paused — no second notice"


def test_resume_clears_it():
    breaker = CircuitBreaker("telegram")
    for _ in range(5):
        breaker.fail("timeout")
    breaker.resume()
    assert breaker.paused is False
    assert breaker.fail("timeout") is False, "the streak starts over"


# -- what the human is told --------------------------------------------------- #

def test_describe_tells_a_paused_adapter_and_how_back():
    breaker = CircuitBreaker("telegram")
    for _ in range(5):
        breaker.fail("the network is gone")
    text = breaker.describe()
    assert "paused" in text
    assert "the network is gone" in text
    assert "/platform" in text


def test_describe_tells_a_healthy_adapter():
    assert "up" in CircuitBreaker("slack").describe()


def test_describe_mentions_a_recent_streak_before_tripping():
    breaker = CircuitBreaker("slack")
    breaker.fail("timeout")
    assert "1 send(s)" in breaker.describe()


def test_describe_is_thread_safe_enough_to_read_paused():
    breaker = CircuitBreaker("slack")
    for _ in range(5):
        breaker.fail("gone")
    assert breaker.paused is True
