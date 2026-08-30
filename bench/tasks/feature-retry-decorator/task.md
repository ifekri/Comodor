Add a `retry` decorator to `retry.py`.

    @retry(times=3, base=0.1, catch=(ConnectionError,))
    def fetch(url): ...

- It calls the wrapped function up to `times` times.
- It waits `backoff(attempt, base)` seconds before each attempt after the
  first, using the `backoff` already in the file.
- It only retries exceptions that are instances of `catch`. Anything else
  propagates immediately, unwrapped.
- When every attempt has failed it raises `Exhausted`, with the last failure
  as the `__cause__`.
- On success it returns the wrapped function's return value.
- `times`, `base` and `catch` all have sensible defaults, and `catch` defaults
  to `Exception`.
- The decorated function keeps its own `__name__` and `__doc__`.

Do not change `backoff` or `Exhausted`. Keep the existing tests passing.
