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
#: The learned vocabulary runs on every recall, so it has to be a rounding
#: error against the recall budget rather than a share of it. It measures
#: around 0.01 ms.
EXPAND_BUDGET_MS = 0.5
OBSERVE_BUDGET_MS = 2.0

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


# --------------------------------------------------------------------------- #
# the learned vocabulary
# --------------------------------------------------------------------------- #


def big_vocabulary():
    """Four thousand finished tasks — more than a year of heavy use."""
    from comodor.learning.associations import Associations

    table = Associations()
    for index in range(4000):
        topic = index % 120
        table.observe(f"task about topic{topic} and thing{index % 300}",
                      f"src/module{topic}.py helper{index % 90} pytest")
    return table


def test_expanding_a_query_is_a_rounding_error():
    """It sits inside recall, which sits between Enter and the first token."""
    table = big_vocabulary()
    query = "add a spec for topic17 in module17"

    timings = []
    for _ in range(200):
        start = time.perf_counter()
        table.enrich(query)
        timings.append((time.perf_counter() - start) * 1000)

    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 < EXPAND_BUDGET_MS, f"expansion p95 {p95:.3f}ms exceeds budget"


def test_learning_from_a_finished_task_is_not_felt():
    """It runs when a task ends, against work that has just taken seconds."""
    table = big_vocabulary()

    timings = []
    for index in range(200):
        start = time.perf_counter()
        table.observe(f"another task {index}", "src/module3.py pytest helper3")
        timings.append((time.perf_counter() - start) * 1000)

    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 < OBSERVE_BUDGET_MS, f"observe p95 {p95:.3f}ms exceeds budget"


def test_the_vocabulary_stays_a_reasonable_size_on_disk():
    """It is one blob in the brain, read at start-up. Megabytes would be felt."""
    import json

    table = big_vocabulary()
    table.prune()
    size = len(json.dumps(table.to_dict()))

    assert size < 2_000_000, f"{size / 1024:.0f} KB of associations"


# --------------------------------------------------------------------------- #
# what the store costs at a size nobody reaches by accident
# --------------------------------------------------------------------------- #


def test_the_hot_index_does_not_load_the_whole_table():
    """Startup grows with the table if it does, and it is paid before the first
    prompt: measured at 1.15 seconds for fifty thousand lessons.

    The mirror is a cache of what can plausibly be recalled — recall multiplies
    relevance by confidence and discards what scores near zero — so the decayed
    tail cannot win however well it matches, and loading it finds nothing.
    """
    from comodor.learning.store import HOT_LESSONS

    assert HOT_LESSONS < 50_000, "the cap is not a cap"


def test_starting_up_with_a_large_brain_is_not_felt(tmp_path):
    store = BrainStore(tmp_path / "brain.db")
    for index in range(8000):
        store.add_lesson(Lesson(kind="style", scope="global",
                                trigger=f"trigger {index}",
                                guidance=f"guidance {index} pytest fixture router"))
    store.flush()
    store.close()

    start = time.perf_counter()
    store = BrainStore(tmp_path / "brain.db")
    elapsed = (time.perf_counter() - start) * 1000
    store.close()

    assert elapsed < WARM_BUDGET_MS, f"opening took {elapsed:.0f}ms"


def test_a_common_word_is_dropped_from_the_full_text_query():
    """One term matching most of the table makes the union enormous whatever
    else is in the query — 20 ms against 0.12 ms once it is removed. Ordering
    by rarity does nothing at all; the common ones have to go.
    """
    from comodor.learning.hotindex import HotIndex

    index = HotIndex()
    index.rebuild([("lesson", i, f"common word{i % 3} rare{i}", "global")
                   for i in range(1000)])

    kept = index.selective(["common", "rare7"])

    assert "rare7" in kept
    assert "common" not in kept, "a term in every document was kept"


def test_a_query_of_only_common_words_still_searches_for_something():
    """A search that returns nothing is worse than a slow one."""
    from comodor.learning.hotindex import HotIndex

    index = HotIndex()
    index.rebuild([("lesson", i, "common everywhere", "global") for i in range(200)])

    assert index.selective(["common", "everywhere"]), "everything was dropped"
