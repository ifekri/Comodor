"""The production TUI runtime: where the packaged renderer lives, and where
the development one is found in a source checkout.

Two locations, one rule. An installed package carries the renderer under the
`comodor.tui` package — `importlib.resources` finds it regardless of where the
interpreter or the working directory sits, and no path is ever computed from
the executable's location. A source checkout has no such package, and the
development tree (`apps/tui`) is used instead, so iterating on the renderer
never requires a rebuild.

Everything here returns a directory that either contains `main.js` or is
honestly said not to. Nothing downloads anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

#: The package that owns the shipped renderer. `dist/` holds the bundle and
#: its manifest; `dist/node_modules` holds the OpenTUI native backend the
#: current platform needs at runtime.
PACKAGE = "comodor.tui"

#: Inside the package's `dist/`, the entry the launcher runs.
ENTRY_NAME = "main.js"

#: The oldest Bun the renderer runs on. OpenTUI binds native code through
#: `bun:ffi`, which exists from 1.3; the CI pins a newer one, but the
#: requirement is the runtime's, not the build's.
MIN_BUN = (1, 3)

#: The OpenTUI native backend this machine needs, as the package names it.
def current_native_package() -> str:
    import platform
    import sys

    system, machine = sys.platform, platform.machine().lower()
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64",
            "aarch64": "arm64"}.get(machine, machine)
    family = {"win32": "win32", "darwin": "darwin", "linux": "linux"}.get(
        system, system)
    return f"@opentui/core-{family}-{arch}"


def packaged_dist() -> Path | None:
    """The installed package's renderer directory, if one is present.

    `importlib.resources.files` is the package-resource answer: it resolves
    against the package as Python sees it, never against the repository or
    the current directory, and it works the same in a venv, pipx, uv and an
    editable install.
    """
    try:
        dist = resources.files(PACKAGE) / "dist"
    except ModuleNotFoundError:
        return None
    entry = dist / ENTRY_NAME
    try:
        if entry.is_file():
            return Path(str(dist))
    except (OSError, TypeError):
        return None
    return None


def checkout_entry() -> Path | None:
    """The development renderer, when this is a source checkout.

    Computed from this file's location *within the checkout*, which is the
    only place the repository layout is a promise rather than a guess. An
    installed package has no `apps/` above it and this returns None.
    """
    here = Path(__file__).resolve()
    # src/comodor/tui/runtime.py -> repository root is parents[3].
    entry = here.parents[3] / "apps" / "tui" / "src" / "main.tsx"
    return entry if entry.is_file() else None


def renderer() -> tuple[Path | None, str]:
    """Where the TUI should run from, and why.

    Returns (path, origin) where origin is "package", "checkout" or "". The
    launcher prefers the package — that is the artifact whose integrity doctor
    verifies — and falls back to the development tree only when there is no
    packaged renderer at all.
    """
    dist = packaged_dist()
    if dist is not None:
        return dist, "package"
    entry = checkout_entry()
    if entry is not None:
        return entry, "checkout"
    return None, ""


def manifest(dist: Path) -> dict:
    """The manifest the build wrote, or an empty mapping if unreadable."""
    try:
        return json.loads((dist / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def verify(dist: Path) -> list[str]:
    """What is wrong with a packaged renderer, if anything.

    A list of problems, empty when the artifact is whole. Checking the
    manifest's hashes is what makes "the bundle on disk is the bundle that
    was built" a fact rather than an assumption.
    """
    problems: list[str] = []
    entry = dist / ENTRY_NAME
    if not entry.is_file():
        return [f"no renderer entry at {entry}"]
    data = manifest(dist)
    hashes = data.get("sha256")
    if not isinstance(hashes, dict):
        return [f"no readable manifest at {dist / 'manifest.json'}"]
    for name, expected in sorted(hashes.items()):
        target = dist / name
        if not target.is_file():
            problems.append(f"missing {name}")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            problems.append(f"{name} does not match the manifest")
    # The native backend is what makes the bundle loadable at all on this
    # platform. The artifact may carry several (a release wheel carries all of
    # them); what must be present is the one *this* machine needs.
    wanted = current_native_package().split("/")[-1]
    natives = data.get("natives") or ([data["native"]] if data.get("native")
                                      else [])
    if natives and wanted not in natives:
        problems.append(f"no native backend for this platform ({wanted}) "
                        f"in the packaged renderer")
    elif natives:
        backend = dist / "node_modules" / "@opentui" / wanted
        if not backend.is_dir():
            problems.append(f"native backend {wanted} is listed but missing "
                            "from the packaged renderer")
    return problems


def bun() -> str | None:
    """The Bun executable, if the machine has one."""
    return shutil.which("bun")


def bun_version(executable: str) -> tuple[int, ...] | None:
    """What `bun --version` says, as a comparable tuple, or None if unreadable."""
    try:
        out = subprocess.run([executable, "--version"], capture_output=True,
                             text=True, timeout=10.0)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.match(r"^\s*(\d+)\.(\d+)", out.stdout or "")
    return (int(match.group(1)), int(match.group(2))) if match else None
