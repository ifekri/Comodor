from retry import backoff


def test_the_first_attempt_does_not_wait():
    assert backoff(1) == 0.0


def test_each_wait_doubles():
    assert backoff(2, base=0.1) == 0.1
    assert backoff(3, base=0.1) == 0.2
    assert backoff(4, base=0.1) == 0.4
