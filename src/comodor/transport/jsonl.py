"""One JSON object per line, and nothing else on the pipe.

The framing is the whole of this file: read a line, parse it; write a line,
flush it. No length prefixes, no headers. That is enough because the protocol
forbids an embedded newline — `json.dumps` escapes them — and it makes the one
rule that matters absolute and checkable:

    stdout is protocol. stderr is everything else.

A client reads every line it is given. A stray `print` in an unrelated module
is a parse error at the far end, and a startup banner is several. So the
moment a channel is opened, the real stdout is taken away from the rest of the
program and `sys.stdout` is pointed at stderr — the same technique the ACP
transport uses, for the same reason. Anything that prints afterwards is
diagnostics, and lands where diagnostics belong.

Writes are locked because events arrive on worker threads while the reader
loop is on the main one, and two half-written lines interleaved are two
messages nobody can parse.

This module knows nothing about methods, sessions or the agent. It moves
lines. `transport/server.py` gives them meaning.
"""

from __future__ import annotations

import io
import json
import sys
import threading
from typing import Any, Callable, Iterator, TextIO

__all__ = ["Channel", "own_stdout"]


class Channel:
    """A line-delimited JSON pipe.

    Constructed with explicit streams so a test drives it with `StringIO` and
    never touches the process's real ones — which is also what makes the
    stdout-purity test possible.
    """

    def __init__(self, reader: TextIO, writer: TextIO,
                 log: TextIO | None = None) -> None:
        self.reader = reader
        self.writer = writer
        self.log = log if log is not None else sys.stderr
        self._write_lock = threading.Lock()
        self._closed = False

    # -- reading ----------------------------------------------------------- #

    def lines(self) -> Iterator[str]:
        """Every non-empty line, until the other end goes away.

        Blank lines are skipped rather than reported: a pipe that ends with a
        newline yields one, and answering `parse_error` to it would be a
        refusal aimed at nobody.
        """
        for raw in self.reader:
            if self._closed:
                return
            line = raw.strip()
            if line:
                yield line

    # -- writing ----------------------------------------------------------- #

    def send(self, message: dict[str, Any]) -> None:
        """One message, one line, flushed.

        Failures are swallowed. A closed pipe means the client is gone, and
        raising here would turn an ordinary disconnect into a traceback on the
        way out — including from a worker thread emitting an event, where
        nothing is waiting to catch it.
        """
        try:
            text = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as problem:
            self.warn(f"could not encode a message: {problem}")
            return
        with self._write_lock:
            if self._closed:
                return
            try:
                self.writer.write(text + "\n")
                self.writer.flush()
            except Exception:
                self._closed = True

    def warn(self, text: str) -> None:
        """To stderr, the only place anything that is not a message may go."""
        try:
            self.log.write(text.rstrip() + "\n")
            self.log.flush()
        except Exception:
            pass

    def close(self) -> None:
        with self._write_lock:
            self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


def own_stdout() -> tuple[TextIO, Callable[[], None]]:
    """Take stdout for the protocol and give everything else stderr.

    Returns the real stream to write messages on, and a callable that puts
    `sys.stdout` back — so a core embedded in another process does not leave
    the interpreter permanently rewired.

    Reconfigured rather than wrapped where possible: the framing is UTF-8 and
    line-based, and a Windows console defaulting to cp1252 would mangle a
    Persian answer on its way to the client. `write_through` because a message
    sitting in a buffer is a message the client is still waiting for.
    """
    original = sys.stdout
    channel: TextIO = sys.stdout
    try:
        channel.reconfigure(encoding="utf-8", newline="\n", write_through=True)
    except (AttributeError, ValueError):
        channel = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                   newline="\n", write_through=True)
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    # The line that keeps a stray `print` from ending the session.
    sys.stdout = sys.stderr

    def restore() -> None:
        sys.stdout = original

    return channel, restore
