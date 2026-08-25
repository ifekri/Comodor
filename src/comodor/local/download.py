"""Fetching a model file, which is four gigabytes over somebody's home line.

That size decides everything here.

*It has to resume.* An hour in, a dropped connection cannot mean starting
again. The bytes go to a `.part` file and a restart asks the server to continue
from wherever that file ended, so a laptop that slept overnight picks up where
it stopped.

*It has to be verified.* A truncated GGUF is not obviously broken — it loads,
and then the model produces nonsense, and the person spends an evening
wondering why a well-regarded model is useless. The download is not finished
until the bytes hash to what the catalogue said, and a file that fails is
deleted rather than left to be found later and half-trusted.

*It has to be watchable.* Nobody stares at a still cursor for an hour. Progress
is a callback rather than a print, so the terminal draws a bar and the browser
draws its own from the same numbers, and neither one is the place the logic
lives.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..net import http

#: Read size. Large enough that the hash update is not the bottleneck, small
#: enough that progress moves visibly on a slow line.
CHUNK = 1024 * 1024

#: How often the progress callback fires, at most. A four-gigabyte download is
#: four thousand chunks, and a UI asked to repaint four thousand times spends
#: more effort drawing than the download spends arriving.
EVERY = 0.25

#: A stalled connection has to be given up on, or a download that will never
#: finish holds the terminal until somebody notices.
READ_TIMEOUT = 60.0


class DownloadFailed(RuntimeError):
    """The file did not arrive, or arrived wrong."""


@dataclass(frozen=True)
class Progress:
    """Where a download has got to.

    Everything an interface needs to draw, computed once here rather than three
    times in three places — and `total` is what the catalogue promised, not
    what a server said, so a truncated response shows as a bar that stops
    rather than one that completes early.
    """

    done: int
    total: int
    started: float
    resumed_from: int = 0

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0

    @property
    def percent(self) -> float:
        return self.fraction * 100

    @property
    def elapsed(self) -> float:
        return max(1e-6, time.monotonic() - self.started)

    @property
    def bytes_per_second(self) -> float:
        """Measured over this run only.

        Counting bytes that arrived during a previous, resumed run would report
        a rate nobody is currently getting, and the estimate built on it would
        be wrong in the direction that matters — too optimistic.
        """
        moved = self.done - self.resumed_from
        return moved / self.elapsed if moved > 0 else 0.0

    @property
    def seconds_left(self) -> float | None:
        rate = self.bytes_per_second
        if rate <= 0 or not self.total:
            return None
        return max(0.0, (self.total - self.done) / rate)

    def as_dict(self) -> dict:
        """For the browser, which cannot read a dataclass."""
        # `done_bytes`, not `done`. A field called `done` holding a byte count
        # is truthy for every tick after the first, and a reader testing it for
        # completion — which is the obvious thing to write — treats the first
        # megabyte as the whole file.
        return {
            "done_bytes": self.done,
            "total": self.total,
            "percent": round(self.percent, 1),
            "bytes_per_second": round(self.bytes_per_second),
            "seconds_left": (round(self.seconds_left)
                             if self.seconds_left is not None else None),
            "resumed": self.resumed_from > 0,
        }


Watcher = Callable[[Progress], None]


def human_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(count) < 1024 or unit == "TB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def fetch(url: str, destination: Path, *, expect_size: int = 0,
          expect_sha256: str = "", watch: Watcher | None = None,
          should_stop: Callable[[], bool] | None = None) -> Path:
    """Download one file, resuming and verifying. Returns the finished path.

    Raises :class:`DownloadFailed` for anything that leaves the file unusable,
    having removed it — a half-file left on disk is one that gets found later
    and half-trusted.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    if destination.is_file() and expect_size and destination.stat().st_size == expect_size:
        if not expect_sha256 or _hash(destination, watch, expect_size) == expect_sha256:
            return destination
        destination.unlink()

    have = partial.stat().st_size if partial.is_file() else 0
    if expect_size and have > expect_size:
        # Longer than it should be: the previous attempt was against a
        # different file, or the catalogue changed under it.
        partial.unlink()
        have = 0

    headers: dict[str, str] = {}
    if have:
        headers["Range"] = f"bytes={have}-"

    started = time.monotonic()
    resumed_from = have

    try:
        response = http.get(url, headers=headers, stream=True,
                            timeout=(15.0, READ_TIMEOUT), allow_redirects=True)
    except Exception as problem:
        raise DownloadFailed(f"could not reach {url}: {problem}") from None

    with response:
        if have and response.status_code == 200:
            # The server ignored the range and is sending the whole file. Start
            # over rather than appending it to what is already there, which
            # would produce a file that is the right length and wrong.
            have = resumed_from = 0
            partial.unlink(missing_ok=True)
        elif have and response.status_code != 206:
            raise DownloadFailed(
                f"resuming was refused with {response.status_code}")
        elif not have and response.status_code != 200:
            raise DownloadFailed(f"the server answered {response.status_code}")

        total = expect_size or _declared_total(response, have)

        digest = hashlib.sha256()
        if have:
            # The hash covers the whole file, so what is already on disk has to
            # go through it before the new bytes do.
            _feed(digest, partial, watch, Progress(0, total, started, 0))

        last = 0.0
        try:
            with open(partial, "ab" if have else "wb") as handle:
                for block in response.iter_content(CHUNK):
                    if should_stop is not None and should_stop():
                        raise DownloadFailed("stopped")
                    handle.write(block)
                    digest.update(block)
                    have += len(block)
                    now = time.monotonic()
                    if watch and (now - last >= EVERY):
                        last = now
                        watch(Progress(have, total, started, resumed_from))
        except DownloadFailed:
            raise
        except Exception as problem:
            raise DownloadFailed(f"the transfer failed: {problem}") from None

    if watch:
        watch(Progress(have, total, started, resumed_from))

    if expect_size and have != expect_size:
        partial.unlink(missing_ok=True)
        raise DownloadFailed(
            f"expected {human_bytes(expect_size)}, got {human_bytes(have)}")

    if expect_sha256:
        got = digest.hexdigest()
        if got != expect_sha256:
            partial.unlink(missing_ok=True)
            raise DownloadFailed(
                "the file does not match its checksum — it is corrupt or it is "
                "not the file the catalogue describes")

    os.replace(partial, destination)
    return destination


def _declared_total(response, already: int) -> int:
    """What the server says the whole file is.

    On a resumed request `Content-Length` is only the remaining part, so the
    total has to come from `Content-Range` or be reconstructed. Used only when
    the catalogue did not state a size, which it always should.
    """
    span = response.headers.get("Content-Range", "")
    if "/" in span:
        try:
            return int(span.rsplit("/", 1)[1])
        except ValueError:
            pass
    try:
        return int(response.headers.get("Content-Length", 0)) + already
    except (TypeError, ValueError):
        return 0


def _feed(digest, path: Path, watch: Watcher | None, at: Progress) -> None:
    """Push an existing partial file through the hash."""
    read = 0
    last = 0.0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(CHUNK)
            if not block:
                break
            digest.update(block)
            read += len(block)
            now = time.monotonic()
            if watch and now - last >= EVERY:
                last = now
                # Reported as progress against the same total, because from the
                # outside this is the download still moving — it is just moving
                # through bytes that are already here.
                watch(Progress(read, at.total, at.started, 0))


def _hash(path: Path, watch: Watcher | None, total: int) -> str:
    digest = hashlib.sha256()
    _feed(digest, path, watch, Progress(0, total, time.monotonic(), 0))
    return digest.hexdigest()
