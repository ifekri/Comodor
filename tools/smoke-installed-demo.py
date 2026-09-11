#!/usr/bin/env python3
"""Start the installed demo and prove the packaged renderer drew something.

Run from CI against a wheel installed into a clean virtualenv, outside the
checkout, with `COMODOR_HOME` pointed somewhere disposable:

    python tools/smoke-installed-demo.py

It exits 0 when the interface came up, and non-zero — saying which marker was
missing — when it did not.

Two things about how it runs the demo are deliberate, and both are here
because the obvious way hung a Windows runner for six hours.

**Output goes to files, not pipes.** `comodor` starts the renderer as a child
of its own, and that grandchild inherits the standard streams. With pipes,
killing `comodor` on timeout leaves the grandchild holding the write end, the
read side never sees EOF, and `subprocess.run(capture_output=True, timeout=…)`
blocks inside `communicate()` for ever — the timeout it promised is never
raised. A file has no other end to wait on: `wait(timeout)` returns, and
whatever was written is on disk to be read afterwards.

**On timeout the whole tree is killed.** `Popen.kill()` reaches one process.
On Windows that leaves the renderer and the core running until the job's own
cleanup finds them; on POSIX a new session lets the group be signalled as one.

A closed stdin ends a session on POSIX, so there the demo normally exits on
its own. Where it does not — a Windows console with no console — the bound
is the exit, and the markers are still required: a demo that ran for a
minute and drew nothing is not a demo that started.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: Long enough for a cold install to import, start Bun and paint once.
BOUND = 60.0

MARKERS = (
    (b"Comodor", "no interface was drawn at all"),
    (b"comodor-demo", "the demo provider never reached the header"),
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="comodor-demo-") as scratch:
        out_path = Path(scratch) / "out.bin"
        err_path = Path(scratch) / "err.bin"
        with out_path.open("wb") as out, err_path.open("wb") as err:
            started = subprocess.Popen(
                [sys.executable, "-m", "comodor", "--demo"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                **_group_kwargs(),
            )
            how = _watch(started, out_path, err_path)

        seen = out_path.read_bytes() + err_path.read_bytes()

    for marker, complaint in MARKERS:
        if marker not in seen:
            sys.stderr.write(f"installed demo: {complaint} ({how})\n")
            sys.stderr.write(f"--- captured {len(seen)} bytes ---\n")
            sys.stderr.write(seen[-4000:].decode("utf-8", "replace") + "\n")
            return 1

    print(f"installed demo: ok ({how})")
    return 0


def _watch(process: subprocess.Popen, out_path: Path, err_path: Path) -> str:
    """Wait for the demo to exit, to paint what is asked of it, or to run out
    of time — whichever comes first — and say which it was.

    Stopping once every marker is on disk is what keeps the Windows leg to a
    few seconds: there the demo does not end on a closed stdin, and without
    this it would sit at the bound every run to prove something it had
    already proved.
    """
    deadline = time.monotonic() + BOUND
    while True:
        remaining = deadline - time.monotonic()
        try:
            code = process.wait(timeout=max(0.0, min(0.5, remaining)))
            return f"exited {code}"
        except subprocess.TimeoutExpired:
            pass
        seen = out_path.read_bytes() + err_path.read_bytes()
        if all(marker in seen for marker, _ in MARKERS):
            _kill_tree(process)
            return "drew the interface; stopped"
        if remaining <= 0:
            _kill_tree(process)
            return f"still running after {BOUND:.0f}s; stopped"


def _group_kwargs() -> dict:
    """Start the demo so its whole process tree can be stopped at once."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _kill_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        # `/T` is the tree; `/F` because a renderer in the alternate screen
        # does not answer a polite close it cannot see.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
