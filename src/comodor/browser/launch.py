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

import os
import shutil
import socket
import subprocess
import sys
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


class Browser:
    """A browser process we started, and are responsible for stopping."""

    def __init__(self, executable: str, profile: Path, port: int,
                 headless: bool = True, process: subprocess.Popen | None = None,
                 ours: bool = True) -> None:
        self.executable = executable
        self.profile = profile
        self.port = port
        self.headless = headless
        self.process = process
        #: False when we attached to something already running, in which case
        #: stopping it is not ours to do.
        self.ours = ours

    @classmethod
    def start(cls, profile: Path, executable: str = "", headless: bool = True,
              port: int = 0, window: tuple[int, int] = (1280, 800)) -> "Browser":
        binary = find(executable)
        profile.mkdir(parents=True, exist_ok=True)
        chosen = port or free_port()

        arguments = [
            binary,
            f"--remote-debugging-port={chosen}",
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
        arguments.append("about:blank")

        try:
            process = subprocess.Popen(
                arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0,
            )
        except OSError as error:
            raise BrowserError(f"could not start {binary}: {error}") from error

        browser = cls(binary, profile, chosen, headless, process)
        browser._await_port()
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
    def label(self) -> str:
        info = version(self.port)
        return info.get("Browser") or Path(self.executable).stem or "browser"

    def stop(self) -> None:
        if not self.ours or self.process is None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=8)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self.process.kill()
            except OSError:
                pass
        self.process = None
