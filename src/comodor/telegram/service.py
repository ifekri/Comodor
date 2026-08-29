"""Running the bot without a terminal holding it open.

`comodor telegram start` blocks. That is the right shape for watching it work
and the wrong shape for the thing people actually want, which is a bot that
answers while nobody is at the machine — the whole point of reaching the agent
from a phone is that you are not at the keyboard.

So there are two ways to run it and they are the same process:

* **In the foreground**, holding the terminal, showing what it does. For
  setting it up and for seeing why it is not working.
* **In the background**, detached from the terminal that started it, writing to
  a log instead of a screen. It survives closing the terminal, logging out, and
  the session that started it.

Neither survives a reboot. That is what `comodor telegram service install`
is for, and it is a different thing: a unit the operating system starts, which
belongs to systemd, launchd or the Task Scheduler rather than to us.

**No dependency for any of it.** Process management here is `subprocess` and
`os.kill`, and the checks below are the ones that stop a recycled process id
from being mistaken for a running bot — a stale pid file naming a number the
kernel has since handed to somebody else's process is how a `stop` command
kills the wrong thing.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Config

#: How long `stop` waits for a polite exit before it insists.
PATIENCE = 6.0


def pid_file(config: Config) -> Path:
    return Path(config.paths.user) / "telegram.pid"


def log_file(config: Config) -> Path:
    return Path(config.paths.user) / "telegram.log"


@dataclass
class State:
    """What is running, if anything."""

    pid: int = 0
    since: float = 0.0
    log: Path | None = None

    @property
    def running(self) -> bool:
        return self.pid > 0

    def uptime(self) -> str:
        if not self.since:
            return ""
        seconds = max(0, int(time.time() - self.since))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m"
        if seconds < 86400:
            return f"{seconds // 3600}h {seconds % 3600 // 60}m"
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"


# --------------------------------------------------------------------------- #
# is it alive, and is it ours
# --------------------------------------------------------------------------- #


def _alive(pid: int) -> bool:
    """Whether a process with this id exists at all."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        #: PROCESS_QUERY_LIMITED_INFORMATION — enough to ask whether it is
        #: there, and the one right that does not need to be an administrator.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(code))
            #: 259 is STILL_ACTIVE. A process that has exited keeps its handle
            #: openable until every handle is closed, so "the handle opened"
            #: alone is not "it is running".
            return bool(ok) and code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Somebody else's process, which means the id has been recycled.
        return False
    return True


def _command_of(pid: int) -> str:
    """The command line of a process, where the platform will say. Best effort.

    This is what separates "process 4821 exists" from "process 4821 is the bot
    we started". Process ids are recycled, and a stale pid file naming a number
    the kernel has since given to somebody else is how a `stop` command kills
    an unrelated program.
    """
    try:
        if sys.platform.startswith("linux"):
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            return raw.replace(b"\0", b" ").decode("utf-8", "replace")
        if sys.platform == "darwin":
            done = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                                  capture_output=True, text=True, timeout=4)
            return done.stdout.strip()
        if os.name == "nt":
            done = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=8)
            return done.stdout.strip()
    except Exception:
        return ""
    return ""


def _ours(pid: int) -> bool:
    """Whether that process is a Comodor bot rather than a recycled id."""
    command = _command_of(pid).lower()
    if not command:
        # The platform would not say. Liveness is all there is to go on, which
        # is weaker than we would like and still better than refusing to
        # manage the process at all.
        return True
    if "comodor" in command:
        return True
    # A detached child on Windows reports as `python.exe`; the module it is
    # running is not in the task list. Accept the interpreter, refuse anything
    # that is plainly something else.
    return any(name in command for name in ("python", "pythonw"))


def state(config: Config) -> State:
    """Whether the bot is running in the background, and since when."""
    path = pid_file(config)
    try:
        pid = int(path.read_text(encoding="utf-8").strip().split()[0])
    except Exception:
        return State()

    if not _alive(pid) or not _ours(pid):
        # Tidy up rather than reporting a bot that is not there. A pid file
        # left behind by a crash otherwise makes `start` refuse forever.
        try:
            path.unlink()
        except OSError:
            pass
        return State()

    try:
        since = path.stat().st_mtime
    except OSError:
        since = 0.0
    return State(pid=pid, since=since, log=log_file(config))


# --------------------------------------------------------------------------- #
# starting and stopping
# --------------------------------------------------------------------------- #


def start(config: Config) -> tuple[bool, str]:
    """Run the bot detached from this terminal. Returns (started, why)."""
    if not config.telegram.token:
        return False, ("No bot is connected. `comodor telegram connect "
                       "<token>` first.")
    if not config.telegram.allowed:
        return False, ("Nobody is paired, so the bot would answer nobody. "
                       "`comodor telegram pair` first.")

    already = state(config)
    if already.running:
        return False, f"Already running (pid {already.pid})."

    root = Path(config.paths.user)
    root.mkdir(parents=True, exist_ok=True)
    log = log_file(config)

    # Appended, not truncated: the reason a bot stopped last night is in the
    # lines a restart would otherwise erase.
    handle = open(log, "a", encoding="utf-8", errors="replace")
    handle.write(f"\n--- started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    handle.flush()

    # `-m comodor` rather than the console script, because the console script
    # is not always on PATH — a `pipx` install puts it somewhere that a
    # detached process started from a different shell may not see.
    command = [sys.executable, "-m", "comodor", "telegram", "start"]
    # The child loads the configuration for itself, and it must load the same
    # one the parent is holding — otherwise a `--background` started against
    # one settings directory silently starts a bot reading another.
    environment = dict(os.environ)
    environment["COMODOR_HOME"] = str(root)
    environment.setdefault("PYTHONIOENCODING", "utf-8")

    options: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "cwd": str(config.paths.project),
        "env": environment,
    }
    if os.name == "nt":
        #: DETACHED_PROCESS so closing the console does not take the bot with
        #: it, and a new process group so Ctrl-C in the parent terminal is not
        #: delivered to it.
        options["creationflags"] = 0x00000008 | 0x00000200
    else:
        #: Its own session, so it has no controlling terminal to be hung up on
        #: when the one that started it closes.
        options["start_new_session"] = True

    try:
        child = subprocess.Popen(command, **options)
    except Exception as problem:
        handle.close()
        return False, f"Could not start it: {problem}"
    finally:
        try:
            handle.close()
        except Exception:
            pass

    pid_file(config).write_text(str(child.pid), encoding="utf-8")

    # Give it long enough to fail. A token Telegram refuses, a port already
    # taken, a missing dependency — all of those end the process in under a
    # second, and reporting "started" for something that is already gone is
    # worse than reporting the failure.
    time.sleep(1.5)
    if child.poll() is not None:
        try:
            pid_file(config).unlink()
        except OSError:
            pass
        tail = _tail(log, 6)
        return False, ("It started and stopped immediately."
                       + (f"\n\n{tail}" if tail else ""))

    return True, f"Running in the background (pid {child.pid})."


def stop(config: Config) -> tuple[bool, str]:
    """Ask the background bot to finish. Returns (stopped, why)."""
    here = state(config)
    if not here.running:
        return False, "It is not running."

    try:
        if os.name == "nt":
            import ctypes

            #: PROCESS_TERMINATE. There is no SIGTERM on Windows, and
            #: CTRL_BREAK only reaches a process that shares a console — this
            #: one deliberately does not have ours.
            handle = ctypes.windll.kernel32.OpenProcess(0x0001, False, here.pid)
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle, 0)
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            os.kill(here.pid, signal.SIGTERM)
    except Exception as problem:
        return False, f"Could not stop it: {problem}"

    deadline = time.time() + PATIENCE
    while time.time() < deadline:
        if not _alive(here.pid):
            break
        time.sleep(0.2)
    else:
        # It would not go politely. On POSIX there is one more thing to try;
        # on Windows termination is not polite in the first place.
        if os.name != "nt":
            try:
                os.kill(here.pid, signal.SIGKILL)
            except Exception:
                pass

    try:
        pid_file(config).unlink()
    except OSError:
        pass
    return True, f"Stopped (pid {here.pid})."


def _tail(path: Path, lines: int) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8",
                                        errors="replace").splitlines()[-lines:])
    except Exception:
        return ""
