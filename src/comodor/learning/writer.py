"""Durability, moved off the hot path.

Learning writes happen while the user is waiting: a lesson credited at the end of
a turn, a correction spotted at the start of the next one. Each is individually
tiny, but each is also a transaction, and a transaction means an fsync. Doing
that inline means the agent occasionally pauses for the disk.

So callers hand a statement to this queue and return immediately. One background
thread drains it and commits in batches — many small updates become one
transaction, which is both faster and gentler on the disk.

The trade is explicit: a crash can lose the last unflushed batch. That is the
right call for this data. Memory here is advisory — losing the last few seconds
of reinforcement costs a fraction of one lesson's confidence, while making the
user wait on fsync costs them attention on every single turn.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

FLUSH_INTERVAL = 0.25          # seconds between batch commits
MAX_BATCH = 256                # statements per transaction
SHUTDOWN = object()            # sentinel


@dataclass(slots=True)
class Write:
    """One queued statement."""

    sql: str
    params: tuple[Any, ...] = ()
    callback: Callable[[int], None] | None = None   # receives lastrowid


class AsyncWriter:
    """A single-threaded batching writer for one SQLite database.

    All writes for a database go through one connection on one thread, which
    also removes the lock contention that several threads writing to SQLite
    would otherwise produce.
    """

    def __init__(self, path: str, pragmas: dict[str, str] | None = None) -> None:
        self.path = path
        self.pragmas = pragmas or {}
        self.queue: queue.Queue[Any] = queue.Queue()
        self.written = 0
        self.batches = 0
        self.errors = 0
        self._connection: sqlite3.Connection | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._lock = threading.Lock()

    # -- lifecycle -------------------------------------------------------- #

    def start(self) -> "AsyncWriter":
        with self._lock:
            if self._thread is not None:
                return self
            self._stopped.clear()
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="comodor-brain-writer")
            self._thread.start()
        return self

    def stop(self, timeout: float = 3.0) -> None:
        """Flush everything queued, then shut the thread down."""
        thread = self._thread
        if thread is None:
            return
        self.queue.put(SHUTDOWN)
        thread.join(timeout=timeout)
        self._thread = None

    def flush(self, timeout: float = 3.0) -> bool:
        """Block until the queue is empty. For tests and for exit paths."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.queue.empty() and self._idle.is_set():
                return True
            time.sleep(0.005)
        return self.queue.empty()

    # -- submission ------------------------------------------------------- #

    def submit(self, sql: str, params: tuple[Any, ...] = (),
               callback: Callable[[int], None] | None = None) -> None:
        """Queue a statement. Returns as soon as it is queued — never blocks."""
        self.queue.put(Write(sql=sql, params=params, callback=callback))

    def submit_many(self, statements: list[tuple[str, tuple[Any, ...]]]) -> None:
        for sql, params in statements:
            self.queue.put(Write(sql=sql, params=params))

    @property
    def pending(self) -> int:
        return self.queue.qsize()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- the thread ------------------------------------------------------- #

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15.0)
        for name, value in self.pragmas.items():
            try:
                connection.execute(f"PRAGMA {name}={value}")
            except sqlite3.Error:
                continue
        return connection

    def _run(self) -> None:
        self._connection = self._connect()
        batch: list[Write] = []
        last_flush = time.monotonic()

        while True:
            timeout = max(0.01, FLUSH_INTERVAL - (time.monotonic() - last_flush))
            try:
                item = self.queue.get(timeout=timeout)
            except queue.Empty:
                item = None

            if item is SHUTDOWN:
                self._commit(batch)
                break

            if item is not None:
                self._idle.clear()
                batch.append(item)

            expired = time.monotonic() - last_flush >= FLUSH_INTERVAL
            if len(batch) >= MAX_BATCH or (batch and expired):
                self._commit(batch)
                batch = []
                last_flush = time.monotonic()
            if not batch and self.queue.empty():
                self._idle.set()

        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            self._connection = None
        self._idle.set()
        self._stopped.set()

    def _commit(self, batch: list[Write]) -> None:
        if not batch or self._connection is None:
            return
        connection = self._connection
        try:
            with connection:
                for write in batch:
                    cursor = connection.execute(write.sql, write.params)
                    if write.callback is not None:
                        try:
                            write.callback(int(cursor.lastrowid or 0))
                        except Exception:
                            pass
            self.written += len(batch)
            self.batches += 1
        except sqlite3.Error:
            # One bad statement must not discard the rest of the batch, and a
            # failed write of advisory memory must never surface to the user.
            self.errors += 1
            for write in batch:
                try:
                    with connection:
                        connection.execute(write.sql, write.params)
                    self.written += 1
                except sqlite3.Error:
                    continue
