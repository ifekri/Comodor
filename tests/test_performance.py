"""Performance budgets, enforced as tests.

Memory sits between the user pressing Enter and the first token arriving, so a
regression here is felt on every single turn. These are not benchmarks to admire
— they are ceilings. A change that makes recall slow fails the suite.

The budgets are deliberately loose compared to what the code actually achieves
(recall measures around 0.4 ms against a 5 ms ceiling), because CI machines are
noisy and a flaky performance test gets deleted rather than fixed. They are
still tight enough to catch the failure that matters: an accidental return to
scanning the whole table.
"""

from __future__ import annotations

import statistics
import time

import pytest

from comodor.learning import BrainStore
from comodor.learning.store import Lesson

CORPUS = 5000
RECALL_BUDGET_MS = 5.0
DEDUP_BUDGET_MS = 5.0
WRITE_BUDGET_MS = 1.0
WARM_BUDGET_MS = 400.0

WORDS = ("pytest docker migration endpoint router config deploy cache token schema "
         "fixture async lint typing build suite import module package venv alembic "
         "celery redis postgres pydantic fastapi django flask numpy pandas").split()


@pytest.fixture(scope="module")
def big_store(tmp_path_factory):
    """A brain with five thousand lessons, built once for the whole module."""
    import random

    random.seed(11)
    path = tmp_path_factory.mktemp("perf") / "brain.db"
    store = BrainStore(path)
    for index in range(CORPUS):
        store.add_lesson(Lesson(
            scope="project:perf",
            trigger=" ".join(random.sample(WORDS, 4)),
            guidance=" ".join(random.sample(WORDS, 12)),
            confidence=0.6,
            pinned=(index % 1000 == 0),
        ))
    store.flush()
    yield store
    store.close()


def measure(operation, repeats: int = 40) -> tuple[float, float]:
    """Median and p95 of one operation, in milliseconds."""
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1]


def test_recall_stays_under_budget_at_five_thousand_lessons(big_store):
    query = "how do I run the migration for the postgres schema"
    median, p95 = measure(
        lambda: big_store.search_lessons(query, ["global", "project:perf"], limit=18))

    assert p95 < RECALL_BUDGET_MS, f"recall p95 {p95:.2f}ms exceeds {RECALL_BUDGET_MS}ms"
    assert median < RECALL_BUDGET_MS / 2


def test_deduplication_stays_under_budget(big_store):
    """This was 22 ms at three thousand lessons before the RAM mirror existed."""
    text = "running the migration against postgres needs the schema flag"
    median, p95 = measure(
        lambda: big_store.find_similar(text, 0.55, ["global", "project:perf"]))

    assert p95 < DEDUP_BUDGET_MS, f"dedup p95 {p95:.2f}ms exceeds {DEDUP_BUDGET_MS}ms"
    assert median < DEDUP_BUDGET_MS / 2


def test_pinned_lookup_does_not_scan_the_table(big_store):
    median, _ = measure(lambda: big_store.pinned_lessons(["global", "project:perf"]))
    assert median < 1.0, "pinned lessons should come from an index, not a scan"


def test_reinforcement_returns_immediately(big_store):
    """Credit is queued; the caller must never wait for a commit."""
    median, p95 = measure(lambda: big_store.credit([1, 2, 3], won=True), repeats=200)

    assert p95 < WRITE_BUDGET_MS, f"queued write p95 {p95:.2f}ms exceeds budget"
    assert median < 0.1


def test_lookup_cost_does_not_grow_with_the_corpus(tmp_path):
    """The property that matters: a brain that has learned more is not slower."""
    import random

    random.seed(13)
    store = BrainStore(tmp_path / "growth.db")
    query = "deploy the celery worker with the redis broker"
    timings: dict[int, float] = {}

    for target in (500, 5000):
        while len(store.hot) < target:
            store.add_lesson(Lesson(
                scope="project:growth",
                trigger=" ".join(random.sample(WORDS, 4)),
                guidance=" ".join(random.sample(WORDS, 12))))
        median, _ = measure(
            lambda: store.search_lessons(query, ["project:growth"], limit=18))
        timings[target] = median

    small, large = timings[500], timings[5000]
    # Ten times the data must not cost ten times the lookup. Some growth is
    # expected from the FTS side; a linear scan would be an order of magnitude.
    assert large < max(small * 4, 2.0), (
        f"lookup grew from {small:.2f}ms at 500 lessons to {large:.2f}ms at 5000")
    store.close()


def test_warming_the_index_at_startup_is_quick(big_store):
    median, _ = measure(big_store.warm, repeats=5)
    assert median < WARM_BUDGET_MS, (
        f"index build takes {median:.0f}ms, which the user would feel at startup")


def test_the_writer_thread_absorbs_a_burst(big_store):
    """A hundred queued updates must not block, and must all land."""
    started = time.perf_counter()
    for index in range(100):
        big_store.credit([index + 1], won=index % 2 == 0)
    queue_time = (time.perf_counter() - started) * 1000

    assert queue_time < 50, f"queueing 100 writes took {queue_time:.0f}ms"
    assert big_store.flush(timeout=5.0), "queued writes should drain"
    assert big_store.writer is not None and big_store.writer.written > 0
