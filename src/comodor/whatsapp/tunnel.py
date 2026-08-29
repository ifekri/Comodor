"""A public HTTPS address for the webhook, without opening a port.

Meta will only deliver to HTTPS and will not accept a self-signed certificate,
so the hardest step in setting WhatsApp up is not the API at all — it is
getting a certificate and a public name in front of a process listening on
localhost. This runs `cloudflared` and reads the address back out of it, so
nobody has to own a domain, forward a port, or understand any of that.

**The distinction that matters, and the reason this file is careful about it.**

A *quick* tunnel needs no account and takes two seconds. It also gets a
**different random hostname every single time it starts** — which is fine for
setting things up and wrong for anything that runs for weeks, because Meta
delivers to the address you gave it and that address will be gone after a
restart. Somebody who wires a quick tunnel into a service and walks away has a
bot that works until the first reboot and then silently stops receiving
anything.

A *named* tunnel has a hostname that does not move. It needs a Cloudflare
account and a one-off `cloudflared tunnel create`, and it is the only honest
answer for a bot that is meant to keep working.

So both are supported, the difference is stated rather than buried, and when a
quick tunnel comes back with an address different from the one Meta was given,
that is reported loudly instead of looking like an outage.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

#: What the binary is called, and where a package manager tends to leave it
#: when the directory is not on a non-interactive shell's PATH.
BINARIES = ("cloudflared", "cloudflared.exe")

LIKELY = (
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
    Path("/opt/homebrew/bin"),
    Path("/usr/bin"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
    Path(os.environ.get("ProgramFiles", "")) / "cloudflared",
)

#: The address a quick tunnel prints, once, in among its log lines.
QUICK = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

#: How long to wait for that line before giving up. Cloudflare is usually
#: under three seconds; a minute is generous enough that a slow network is not
#: mistaken for a failure.
PATIENCE = 60.0

HOW_TO_GET_IT = {
    "win32": "winget install --id Cloudflare.cloudflared",
    "darwin": "brew install cloudflared",
}
FALLBACK = ("https://developers.cloudflare.com/cloudflare-one/"
            "connections/connect-networks/downloads/")


def find_binary() -> Path | None:
    """`cloudflared`, wherever it is. PATH first, then where installers put it."""
    for name in BINARIES:
        found = shutil.which(name)
        if found:
            return Path(found)
    for folder in LIKELY:
        for name in BINARIES:
            candidate = folder / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


def how_to_install() -> str:
    import sys

    return HOW_TO_GET_IT.get(sys.platform, f"see {FALLBACK}")


@dataclass
class Tunnel:
    """One `cloudflared` process, and the address it answers on."""

    url: str = ""
    #: `quick` — a fresh random hostname each run. `named` — a hostname that
    #: stays. The difference decides whether Meta has to be told again.
    kind: str = "quick"
    process: subprocess.Popen | None = None
    log: list[str] = None            # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = []

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def stable(self) -> bool:
        return self.kind == "named"

    def webhook(self, path: str = "/whatsapp") -> str:
        return f"{self.url.rstrip('/')}{path}" if self.url else ""

    def stop(self) -> None:
        if self.process is None:
            return
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        except Exception:
            pass
        self.process = None


def start_quick(port: int, host: str = "127.0.0.1",
                patience: float = PATIENCE) -> tuple[Tunnel | None, str]:
    """A throwaway public address for this run. Returns (tunnel, why-not).

    The address is *new every time*. Good for setting up and for testing; for
    anything long-running see `start_named`, because Meta keeps delivering to
    whatever it was told and that hostname will not exist after a restart.
    """
    binary = find_binary()
    if binary is None:
        return None, ("cloudflared is not installed. "
                      f"{how_to_install()}")

    command = [str(binary), "tunnel", "--no-autoupdate",
               "--url", f"http://{host}:{port}"]
    return _run(command, "quick", patience)


def start_named(name: str, port: int, host: str = "127.0.0.1",
                patience: float = PATIENCE) -> tuple[Tunnel | None, str]:
    """Run a tunnel that was created beforehand, with a hostname that stays.

    `cloudflared tunnel create <name>` and a DNS route are one-off steps done
    with a Cloudflare account; this only runs what they produced. The address
    is not printed by the process — it is whatever the route says — so the
    caller supplies it.
    """
    binary = find_binary()
    if binary is None:
        return None, f"cloudflared is not installed. {how_to_install()}"

    command = [str(binary), "tunnel", "--no-autoupdate", "run",
               "--url", f"http://{host}:{port}", name]
    tunnel, why = _run(command, "named", patience, expect_url=False)
    return tunnel, why


def _run(command: list[str], kind: str, patience: float,
         expect_url: bool = True) -> tuple[Tunnel | None, str]:
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
    except Exception as problem:
        return None, f"could not start cloudflared: {problem}"

    tunnel = Tunnel(kind=kind, process=process)
    found = threading.Event()

    def watch() -> None:
        # cloudflared writes its banner to stderr, merged into stdout here.
        # The address appears once, inside a box of log lines, and the process
        # keeps running afterwards — so this reads for the whole lifetime and
        # keeps the tail for a failure message.
        assert process.stdout is not None
        for line in process.stdout:
            tunnel.log.append(line.rstrip())
            del tunnel.log[:-40]
            if not tunnel.url:
                match = QUICK.search(line)
                if match:
                    tunnel.url = match.group(0)
                    found.set()

    threading.Thread(target=watch, name="comodor-cloudflared",
                     daemon=True).start()

    if not expect_url:
        # A named tunnel prints no address; give it a moment to fail loudly
        # rather than reporting success for a process that is already gone.
        time.sleep(2.0)
        if not tunnel.running:
            return None, _why_it_died(tunnel)
        return tunnel, ""

    deadline = time.time() + patience
    while time.time() < deadline:
        if found.wait(0.4):
            return tunnel, ""
        if not tunnel.running:
            return None, _why_it_died(tunnel)

    tunnel.stop()
    return None, ("cloudflared started but never printed an address "
                  "within " f"{int(patience)}s")


def _why_it_died(tunnel: Tunnel) -> str:
    tail = [line for line in tunnel.log if line.strip()][-4:]
    return ("cloudflared stopped straight away"
            + (":\n  " + "\n  ".join(tail) if tail else ""))
