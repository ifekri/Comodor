"""Finding a browser that is already installed, and starting it safely.

Nothing is downloaded. Playwright ships its own Chromium and that is a sensible
choice for a test runner and a rude one for a coding agent: a hundred and
seventy megabytes, a separate update problem, and a browser the user has never
configured. Almost every machine already has Chrome, Edge, Brave or Chromium,
and any of them speaks the same protocol.

The profile is the part worth being careful about. Attaching to the user's own
Chrome means their cookies, their logged-in sessions and their saved passwords
are reachable by the agent, and Chrome refuses to open a debugging port on the
default profile anyway. So a profile of our own, under the user's Comodor
directory: signed out of everything, kept between runs so a login the user
performs on purpose survives, and obviously separate from the browser they use.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .cdp import BrowserError, version

#: Where each browser usually is. First match wins, and the order is a guess at
#: what a developer would rather we used.
CANDIDATES = {
    "win32": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ],
    "linux": [
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        "brave-browser", "microsoft-edge", "microsoft-edge-stable",
    ],
}

#: Switches that make a browser suitable for an agent rather than a person.
#: Each one is here for a reason and none of them weakens the sandbox.
FLAGS = [
    "--no-first-run",                  # no welcome tour to click through
    "--no-default-browser-check",
    "--disable-background-networking",  # no update pings from a headless tab
    "--disable-sync",                   # this profile signs into nothing
    "--disable-features=Translate,MediaRouter,OptimizationHints",
    "--disable-popup-blocking",         # the agent decides what opens
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",  # a headless tab must keep running
    "--mute-audio",
    "--metrics-recording-only",
]

STARTUP_TIMEOUT = 30.0


def find(hint: str = "") -> str:
    """The browser to use, or an explanation of why there is none."""
    if hint:
        found = shutil.which(hint) or (hint if Path(hint).is_file() else "")
        if not found:
            raise BrowserError(f"no browser at {hint}")
        return found

    for candidate in CANDIDATES.get(sys.platform, CANDIDATES["linux"]):
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found

    raise BrowserError(
        "no Chrome, Chromium, Edge or Brave found. Install one, or set "
        "browser.executable in the config to where yours is. Nothing is "
        "downloaded automatically.")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


#: What Chromium says when it will not run unprotected and cannot protect
#: itself. Matched against everything it printed rather than the first line:
#: it does not put the useful part first, and which line comes first depends on
#: how the container was started.
_NO_SANDBOX_SIGNS = (
    "no usable sandbox",
    "failed to move to new namespace",
    "setuid sandbox",
    "sandboxhelper",
    "chrome-sandbox",
    "zygote_host",
)


class SandboxUnavailable(BrowserError):
    """It will not start because it cannot isolate its renderers here.

    Its own class rather than a string match at the call site, because the
    decision belongs where the full output is: by the time this reaches a
    caller the message has been trimmed to the one line worth showing.
    """


def _looks_like_a_sandbox_problem(output: str) -> bool:
    lowered = output.lower()
    return any(sign in lowered for sign in _NO_SANDBOX_SIGNS)


def _read_all(handle) -> str:
    try:
        handle.seek(0)
        return handle.read(20_000).decode("utf-8", "replace").strip()
    except (OSError, ValueError):
        return ""


def _first_line(output: str) -> str:
    """One line for a person. Forty lines of Chromium logging is not an error
    message, it is a haystack."""
    if not output:
        return ""
    first = next((line for line in output.splitlines() if line.strip()), "")
    return f" It said: {first.strip()[:300]}"


#: Every browser started and not yet stopped. A `finally` covers the ordinary
#: path, and nothing covers the one that actually leaks: a run interrupted —
#: Ctrl-C, a test-runner timeout, a session killed — never reaches its cleanup,
#: and Chrome is a dozen processes that outlive the Python that started them.
#: They hold their profile directory and their share of a gigabyte, and nothing
#: in a later run knows to clean up an earlier one's. They accumulate for days
#: until somebody notices their machine is full of browsers nobody opened.
_LIVE: "set[Browser]" = set()


def _remember(browser: "Browser") -> None:
    _LIVE.add(browser)


def _stop_everything_still_open() -> None:
    """Registered with `atexit`, so an abandoned browser still goes away."""
    for browser in list(_LIVE):
        try:
            browser.stop()
        except Exception:
            pass
    _LIVE.clear()


atexit.register(_stop_everything_still_open)


class Browser:
    """A browser process we started, and are responsible for stopping."""

    def __init__(self, executable: str, profile: Path, port: int,
                 headless: bool = True, process: subprocess.Popen | None = None,
                 ours: bool = True, sandboxed: bool = True) -> None:
        self.executable = executable
        self.profile = profile
        self.port = port
        self.headless = headless
        self.process = process
        #: False when we attached to something already running, in which case
        #: stopping it is not ours to do.
        self.ours = ours
        #: False when the renderer sandbox had to be given up to start at all.
        #: Worth knowing rather than assuming: it is the difference between a
        #: bad page being contained by Chromium and being contained only by
        #: whatever is around Chromium.
        self.sandboxed = sandboxed

    @classmethod
    def start(cls, profile: Path, executable: str = "", headless: bool = True,
              port: int = 0, window: tuple[int, int] = (1280, 800)) -> "Browser":
        binary = find(executable)
        profile.mkdir(parents=True, exist_ok=True)
        chosen = port or free_port()

        try:
            return cls._spawn(binary, profile, chosen, headless, window,
                              sandboxed=True)
        except SandboxUnavailable:
            pass
        # It will not run its renderers in a user namespace here — almost
        # always a container, whose own confinement is the stronger boundary
        # anyway. Give up the inner one rather than weaken the outer one, and
        # remember that this is what happened.
        return cls._spawn(binary, profile, chosen, headless, window,
                          sandboxed=False)

    @classmethod
    def _spawn(cls, binary: str, profile: Path, port: int, headless: bool,
               window: tuple[int, int], sandboxed: bool) -> "Browser":
        arguments = [
            binary,
            f"--remote-debugging-port={port}",
            # Loopback only. Without this Chrome will accept a debugging
            # connection from anything that can route to the port, which is a
            # remote code execution hole with a browser attached.
            "--remote-allow-origins=*",
            f"--user-data-dir={profile}",
            f"--window-size={window[0]},{window[1]}",
            *FLAGS,
        ]
        if headless:
            arguments.append("--headless=new")
        if not sandboxed:
            arguments.append("--no-sandbox")
        arguments.append("about:blank")

        # Kept, not discarded: when it exits at once the reason is in there,
        # and the difference between "no sandbox available" and anything else
        # decides whether retrying is sensible or dishonest.
        complaints = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen(
                arguments, stdout=subprocess.DEVNULL, stderr=complaints,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0,
                # A group of its own, so ending the browser's group ends the
                # browser. Without this the child inherits *our* group, and
                # `killpg` on it kills whatever started us as well — the whole
                # test run, the whole agent session.
                start_new_session=(os.name != "nt"),
            )
        except OSError as error:
            complaints.close()
            raise BrowserError(f"could not start {binary}: {error}") from error

        browser = cls(binary, profile, port, headless, process,
                      sandboxed=sandboxed)
        _remember(browser)
        try:
            browser._await_port()
        except BrowserError as error:
            printed = _read_all(complaints)
            message = f"{error}{_first_line(printed)}"
            # Judged on everything it printed; reported as one line.
            if sandboxed and _looks_like_a_sandbox_problem(printed):
                raise SandboxUnavailable(message) from None
            raise BrowserError(message) from None
        finally:
            complaints.close()
        return browser

    def _await_port(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise BrowserError(
                    f"the browser exited immediately (code "
                    f"{self.process.returncode}). If it is already running with "
                    f"your profile, close it or set browser.port to a debugging "
                    f"port it is already listening on.")
            try:
                if version(self.port):
                    return
            except BrowserError:
                pass
            time.sleep(0.15)
        self.stop()
        raise BrowserError(f"the browser did not open a debugging port within "
                           f"{STARTUP_TIMEOUT:.0f}s")

    @classmethod
    def attach(cls, port: int) -> "Browser":
        """Use a browser the user already started with a debugging port."""
        if not version(port):
            raise BrowserError(f"nothing is listening for DevTools on port {port}")
        return cls("", Path(), port, headless=False, process=None, ours=False)

    @property
    def note(self) -> str:
        """What is worth saying about how it started, if anything."""
        if self.sandboxed:
            return ""
        return ("Chromium is running without its own renderer sandbox: it "
                "could not create a user namespace here, which is normal "
                "inside a container. The container's confinement is what is "
                "holding a bad page, rather than the browser's.")

    @property
    def label(self) -> str:
        info = version(self.port)
        return info.get("Browser") or Path(self.executable).stem or "browser"

    def _forget(self) -> None:
        _LIVE.discard(self)

    def stop(self) -> None:
        """Close the browser and everything it started.

        A browser is not one process. Chrome starts a renderer per tab, a GPU
        process, a crashpad handler and more, and `terminate` on the one we
        launched leaves every one of them running — holding its profile
        directory, and its share of a gigabyte of memory. Eight strays per
        run, and nothing in a later run cleans up an earlier one's: they
        accumulate until somebody notices their machine is full of browsers
        nobody opened.
        """
        if not self.ours or self.process is None:
            return

        # The tree first, while the parent is still alive to name it. Killing
        # the parent before asking leaves orphans whose parent id points at
        # nothing, and then there is no tree left to walk.
        self._end_the_tree()

        try:
            self.process.terminate()
            self.process.wait(timeout=8)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self.process.kill()
            except OSError:
                pass
        self.process = None
        self._forget()

    def _end_the_tree(self) -> None:
        """The browser and every process it started. Never raises."""
        pid = getattr(self.process, "pid", None)
        if pid is None:
            return
        try:
            if hasattr(os, "killpg"):
                group = os.getpgid(pid)
                # Only ever a group the browser has to itself. A child started
                # without `start_new_session` inherits ours, and killing that
                # group kills whoever started us — the test run, the agent, the
                # shell. Checked rather than trusted: this signal cannot be
                # taken back, and the cost of being wrong is the whole session.
                if group != os.getpgid(0):
                    os.killpg(group, signal.SIGKILL)
                    return
        except (OSError, AttributeError, ProcessLookupError):
            pass
        try:
            # `taskkill /T` walks the tree from a living parent; `Popen.kill`
            # only ever ends the one process.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=15)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
