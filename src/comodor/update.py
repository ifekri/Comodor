"""Moving to the version that is out now.

There are four ways Comodor gets onto a machine and each of them wants a
different command to change it. `pip install --upgrade` inside a uv tool
environment appears to work and leaves uv's record pointing at a version that
is no longer there; `uv tool upgrade` on a plain pip install fails outright.
Guessing wrong is worse than not offering the command, so this asks the same
question `uninstall` asks — how did this copy get here — and then does the one
thing that is right for the answer.

Three things it will not do.

**It will not upgrade a source checkout.** A working tree is under somebody's
own version control, and overwriting it with a release is throwing away work
that was never committed. It says which directory it found and stops.

**It will not claim a version it has not seen.** The new one is run and asked
what it is, and that answer is what gets printed. An upgrade that reports
success by echoing the number it was aiming at is how a silently failed
install goes unnoticed for a week.

**It will not lie about Windows.** A running program cannot overwrite its own
executable there, so the upgrade is handed to a detached process that waits
for this one to exit — and is reported as started, not as finished, because
nothing here can see how it ends.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import __version__
from .net import http
from .uninstall import Installation, detect_installation, find_tool

#: Where the published versions are listed.
INDEX = "https://pypi.org/pypi/comodor/json"
#: Long enough for a slow connection, short enough not to look hung.
TIMEOUT = (10.0, 15.0)


# --------------------------------------------------------------------------- #
# comparing versions
# --------------------------------------------------------------------------- #

_VERSION = re.compile(
    r"^v?(?P<release>\d+(?:\.\d+)*)"
    r"(?:(?P<kind>a|b|rc|alpha|beta|c|pre|preview)\.?(?P<pre>\d*))?"
    r"(?:\.?(?:dev)\.?(?P<dev>\d*))?"
    r"(?:\+.*)?$",
    re.IGNORECASE,
)

#: dev is older than any pre-release, which is older than the release itself.
_STAGE = {"dev": -2, "a": -1, "alpha": -1, "b": 0, "beta": 0,
          "c": 1, "rc": 1, "pre": 1, "preview": 1, "": 2}


def parse(version: str) -> tuple | None:
    """A sortable key for a version, or None if it is not one.

    A useful subset of PEP 440 rather than the whole of it: releases,
    pre-releases and dev builds, which is everything this project publishes and
    everything `hatch-vcs` generates between tags. The local part after `+` is
    deliberately ignored — `0.3.1.dev4+g56b14a7` and `0.3.1.dev4+gabc1234` are
    the same point in the sequence and neither is newer than the other.
    """
    match = _VERSION.match((version or "").strip())
    if match is None:
        return None

    release = tuple(int(part) for part in match.group("release").split("."))
    # Padded, so 0.3 and 0.3.0 compare equal instead of 0.3 being smaller.
    release = release + (0,) * (4 - len(release)) if len(release) < 4 else release

    if match.group("dev") is not None:
        return release, _STAGE["dev"], int(match.group("dev") or 0)
    kind = (match.group("kind") or "").lower()
    if kind:
        return release, _STAGE[kind], int(match.group("pre") or 0)
    return release, _STAGE[""], 0


def is_newer(candidate: str, than: str) -> bool:
    left, right = parse(candidate), parse(than)
    if left is None or right is None:
        return False
    return left > right


# --------------------------------------------------------------------------- #
# what is out there
# --------------------------------------------------------------------------- #


@dataclass
class Release:
    version: str
    summary: str = ""
    url: str = ""


def latest(timeout: tuple[float, float] | None = None) -> Release | None:
    """Ask the index what the newest published version is.

    The timeout is a parameter because the two callers want different ones.
    `update` is a command somebody ran on purpose and can afford to wait; the
    version check inside `doctor` is one line of a report that has to finish on
    a machine with no network at all.
    """
    try:
        response = http.get(INDEX, timeout=timeout or TIMEOUT,
                            headers={"Accept": "application/json"})
    except http.RequestError:
        return None

    with response:
        if not response.ok:
            return None
        try:
            data = json.loads(response.text)
        except ValueError:
            return None

    info = data.get("info") or {}
    version = str(info.get("version") or "")
    if not version:
        return None
    return Release(version=version,
                   summary=str(info.get("summary") or ""),
                   url=str(info.get("release_url") or info.get("package_url") or ""))


# --------------------------------------------------------------------------- #
# doing it
# --------------------------------------------------------------------------- #


@dataclass
class Plan:
    """How this copy would be upgraded, and whether it can be."""

    method: str
    command: list[str]
    #: Said out loud in the report.
    detail: str = ""
    #: Set when there is nothing to run: a checkout, or a manager we cannot find.
    blocked: str = ""
    #: True where the upgrade cannot happen while this process is alive.
    deferred: bool = False
    #: What to run when the polite command reports success and moves nothing.
    #: `uv tool upgrade` and `pipx upgrade` both honour the requirement that
    #: was recorded at install time, so a tool installed as `comodor==0.2.3`
    #: is already at the newest version it is allowed to have — and says so by
    #: exiting zero. Reinstalling from the index is what "update" was asked
    #: for, so that is the second attempt.
    fallback: list[str] = field(default_factory=list)


def plan(install: Installation | None = None) -> Plan:
    """The one command that is right for how this copy was installed."""
    install = install or detect_installation()
    windows = sys.platform == "win32"

    if install.method == "source":
        checkout = Path(__file__).resolve().parents[2]
        return Plan("source", [], blocked=(
            f"this is a source checkout at {checkout} — it is yours, and under "
            f"your own version control. `git pull` is the upgrade."))

    if install.method in ("uv", "pipx"):
        executable = find_tool(install.method)
        if executable is None:
            return Plan(install.method, [], blocked=(
                f"{install.method} installed this and is not on the machine any "
                f"more. Reinstall with the one-liner at https://comodor.ai, or "
                f"put {install.method} back."))
        if install.method == "uv":
            command = [executable, "tool", "upgrade", "comodor"]
            fallback = [executable, "tool", "install", "--force", "comodor"]
        else:
            command = [executable, "upgrade", "comodor"]
            fallback = [executable, "install", "--force", "comodor"]
        return Plan(install.method, command, detail=install.detail,
                    deferred=windows, fallback=fallback)

    if install.method == "venv" and install.root:
        # The environment's own Python, not this process's - they are the same
        # here, but naming it makes the command copyable and the report honest.
        python = install.root / ("Scripts" if windows else "bin") / (
            "python.exe" if windows else "python")
        runner = str(python) if python.exists() else sys.executable
        return Plan("venv", [runner, "-m", "pip", "install", "--upgrade", "comodor"],
                    detail=install.detail, deferred=windows)

    return Plan("pip", [sys.executable, "-m", "pip", "install", "--upgrade", "comodor"],
                detail=install.detail, deferred=windows)


def apply(step: Plan) -> tuple[bool, str]:
    """Run it. Returns whether it worked and what to tell the user."""
    if step.blocked:
        return False, step.blocked
    if not step.command:
        return False, "nothing to run"

    if step.deferred:
        try:
            _schedule(step.command)
        except Exception as error:                    # noqa: BLE001 - reported
            return False, f"could not start the upgrade: {error}"
        return True, ("started — Windows will not let a running program replace "
                      "its own executable, so it finishes once this one exits")

    try:
        result = subprocess.run(step.command, capture_output=True, text=True,
                                timeout=600)
    except Exception as error:                        # noqa: BLE001 - reported
        return False, str(error)

    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip().splitlines()
        return False, output[-1][:300] if output else f"exited {result.returncode}"
    return True, ""


@dataclass
class Outcome:
    """What happened, and what to tell the user about it."""

    ok: bool
    #: What the command reports now. Empty when it could not be asked.
    version: str = ""
    message: str = ""
    #: The upgrade is running in another process and cannot be confirmed here.
    deferred: bool = False
    #: The recorded requirement had to be overridden to move at all.
    forced: bool = False


def upgrade(step: Plan, target: str) -> Outcome:
    """Do it, then ask what version answers — and try harder if it did not move.

    The asking is the point. `uv tool upgrade` on a tool that was installed
    pinned exits zero having done nothing at all, and an upgrade command that
    reports success by echoing the number it was aiming at would call that a
    win. This one notices, and reinstalls from the index instead.
    """
    ok, message = apply(step)
    if not ok:
        return Outcome(False, message=message)
    if step.deferred:
        return Outcome(True, message=message, deferred=True)

    now = installed_version()
    if now and not is_newer(target, now):
        return Outcome(True, version=now)

    if step.fallback:
        ok, message = apply(replace(step, command=step.fallback, fallback=[]))
        if ok:
            after = installed_version()
            if after and not is_newer(target, after):
                return Outcome(True, version=after, forced=True)
            now = after or now

    if not now:
        return Outcome(True, message="could not find `comodor` on PATH to confirm it")
    return Outcome(False, version=now, message=(
        f"it still reports {now}. Another copy may be earlier on your PATH."))


def installed_version(command: str = "comodor") -> str:
    """Ask the command on PATH what it is now.

    Asked rather than assumed. An upgrade that reports success by echoing the
    number it was aiming at is how a silently failed install goes unnoticed.
    """
    executable = find_tool(command)
    if executable is None:
        return ""
    try:
        result = subprocess.run([executable, "--version"], capture_output=True,
                                text=True, timeout=60)
    except Exception:                                 # noqa: BLE001
        return ""
    parts = (result.stdout or result.stderr).strip().split()
    return parts[-1] if parts else ""


def _schedule(command: list[str]) -> None:
    """Run this once this process is gone.

    Windows will not unlink or overwrite a running executable, and the console
    script being replaced is this one. Rather than fail with "access is denied"
    and leave the user to work out what to do, the work is handed to a detached
    PowerShell that waits on this process id first.
    """
    import os

    quoted = ",".join(f"'{part.replace(chr(39), chr(39) * 2)}'" for part in command)
    script = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue;"
        f"Start-Sleep -Milliseconds 400;"
        f"$argv = @({quoted});"
        f"& $argv[0] $argv[1..($argv.Length - 1)] | Out-Null"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", script],
        creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                       | getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def current() -> str:
    return __version__
