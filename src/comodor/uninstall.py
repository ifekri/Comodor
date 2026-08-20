r"""Taking it all back off the machine.

An installer that cannot be undone is a thing people are right to be wary of,
and this one touches four different places: a data directory holding an API
key and everything the agent has learned, a `.comodor` folder inside every
project it was used in, an isolated environment somewhere under the user's
data home, and a line in a shell profile. Knowing all four is the installer's
job, not the user's.

The command is written the same way `doctor` is, and for the same reason:
**survey first, then act**. `survey()` reads and computes; it opens nothing it
would not open to answer a question, and it deletes nothing. `apply()` is the
only thing here that removes anything. That split is what makes `--dry-run`
truthful — it is the same code path, stopped one step earlier — and it is what
lets the confirmation prompt show the real list rather than a description of
one.

Three things it will not quietly do.

**It will not guess which projects you used it in.** Every session records the
directory it ran in, so the list of `.comodor` folders is recovered from the
sessions themselves rather than by walking your disk. If the session history is
already gone, the folders it cannot name are named as a gap instead.

**It will not strip a directory off your PATH that other programs are still
using.** The installer's line is marked, so it can be identified exactly, but
`~/.local/bin` is a shared address. The line goes only if nothing else is left
in there; otherwise it stays and the report says why.

**It will not pretend to have deleted a file Windows would not let it.** A
running program cannot remove its own executable there, so the environment is
handed to a detached process that waits for this one to exit and then removes
it. That is reported as scheduled, not as done.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Config
from .paths import PROJECT_DIR_NAME, user_root

#: What the installer writes above the line it adds to a shell profile.
PROFILE_MARKER = "# Added by the Comodor installer"

#: Where the shell installer puts the launcher, on every platform it supports.
BIN_DIR = Path.home() / ".local" / "bin"


@dataclass
class Item:
    """One thing that will be removed."""

    #: Grouping for the report: data · project · program · launcher · path
    kind: str
    label: str
    detail: str = ""
    path: Path | None = None
    size: int = 0
    #: Does it, and returns what it did. Raises if it could not.
    remove: Callable[[], str] | None = None
    #: True when the removal can only happen after this process has exited.
    deferred: bool = False


@dataclass
class Survey:
    """Everything found, and everything deliberately left alone."""

    items: list[Item] = field(default_factory=list)
    #: Said out loud in the report: things that are not ours to delete, and
    #: things that could not be located.
    notes: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.size for item in self.items)

    def add(self, item: Item) -> None:
        self.items.append(item)


# --------------------------------------------------------------------------- #
# measuring
# --------------------------------------------------------------------------- #


def directory_size(path: Path) -> int:
    """Bytes on disk, ignoring anything that vanishes while we look."""
    total = 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    for root, _, files in os.walk(path, onerror=lambda _: None):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _size(size: int) -> str:
    """A size a person can read, rounded the way people round."""
    if size < 1024:
        return f"{size} B"
    for unit, scale in (("KB", 1024), ("MB", 1024**2), ("GB", 1024**3)):
        if size < scale * 1024 or unit == "GB":
            value = size / scale
            return f"{value:.0f} {unit}" if value >= 10 else f"{value:.1f} {unit}"
    return f"{size} B"


def _rmtree(path: Path) -> str:
    """Remove a file or a whole tree, and say what went."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return str(path)


# --------------------------------------------------------------------------- #
# where this copy is installed
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Installation:
    """How this copy got here, which decides how it comes off again."""

    #: venv · uv · pipx · pip · source
    method: str
    #: The environment itself. Launchers inside it go with it.
    root: Path | None = None
    detail: str = ""
    #: What actually gets deleted, which is not always the environment. The
    #: installer builds `<data home>/comodor/venv`, so the directory *above*
    #: the environment is its too — deleting only the venv leaves an empty
    #: `comodor` folder behind, which is exactly the kind of leftover this
    #: command exists to prevent.
    owned: Path | None = None


def detect_installation() -> Installation:
    """Work out how the running copy was installed.

    From `sys.prefix` rather than from a marker file, because a marker file is
    a thing that can go missing, and because it identifies a pipx or uv
    environment even when Comodor was installed by hand rather than by the
    installer script.
    """
    prefix = Path(sys.prefix).resolve()
    parts = [part.lower() for part in prefix.parts]

    if "pipx" in parts:
        return Installation("pipx", prefix, "installed with pipx")
    if "uv" in parts and "tools" in parts:
        return Installation("uv", prefix, "installed as a uv tool")

    if _is_editable():
        return Installation("source", None,
                            "installed from a source checkout with `pip install -e`")

    if prefix != Path(sys.base_prefix).resolve():
        managed = _installer_venv()
        if managed and prefix == managed.resolve():
            return Installation("venv", prefix,
                                "the environment the installer built",
                                owned=managed.parent)
        # Somebody else's environment, which may hold other things. Only the
        # package comes out of it.
        return Installation("venv", prefix, "an environment you created")

    return Installation("pip", None, "installed with pip")


def _installer_venv() -> Path | None:
    """The environment path the shell and PowerShell installers use."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) / "Comodor" / "venv" if base else None
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "comodor" / "venv"


def _is_editable() -> bool:
    """Is the package being imported straight out of a working tree?"""
    package = Path(__file__).resolve().parent
    # An installed package sits under site-packages; an editable one does not.
    return not any(part == "site-packages" for part in package.parts)


def _launchers() -> list[Path]:
    """Every file on disk that starts Comodor."""
    names = ["comodor", "comodor.exe", "comodor.cmd", "comodor-script.py"]
    found: list[Path] = []
    seen: set[Path] = set()

    directories = [BIN_DIR, Path(sys.prefix) / ("Scripts" if sys.platform == "win32"
                                                else "bin")]
    # Where `pip install --user` puts scripts, which is not on either of those.
    try:
        import sysconfig

        user_scripts = sysconfig.get_path("scripts", f"{os.name}_user")
        if user_scripts:
            directories.append(Path(user_scripts))
    except Exception:
        pass

    for directory in directories:
        for name in names:
            candidate = directory / name
            resolved = candidate.absolute()
            if resolved in seen:
                continue
            seen.add(resolved)
            # `exists()` follows symlinks, and the installer's launcher *is* a
            # symlink — one that will be dangling by the time we look, if the
            # environment it points into has already gone.
            if candidate.is_symlink() or candidate.exists():
                found.append(candidate)
    return found


# --------------------------------------------------------------------------- #
# projects
# --------------------------------------------------------------------------- #


def project_directories(root: Path, extra: Path | None = None) -> tuple[list[Path], bool]:
    """Every `.comodor` folder this installation is known to have created.

    Recovered from the session metadata, each file of which records the
    directory that session ran in. Walking the filesystem instead would be
    slower, would need permission to read everything, and would still miss a
    project on another drive. The second return value is whether the session
    history was there to read at all — a caller that cannot see it should say
    so rather than report an empty list as "none".
    """
    sessions = root / "sessions"
    found: list[Path] = []
    seen: set[Path] = set()

    def consider(candidate: Path | None) -> None:
        if candidate is None:
            return
        directory = candidate / PROJECT_DIR_NAME
        key = directory.resolve() if directory.exists() else directory
        if key in seen:
            return
        seen.add(key)
        if directory.is_dir():
            found.append(directory)

    consider(extra)

    if not sessions.is_dir():
        return found, False

    for meta in sorted(sessions.glob("*.meta.json")):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cwd = data.get("cwd")
        if isinstance(cwd, str) and cwd:
            consider(Path(cwd))

    return found, True


# --------------------------------------------------------------------------- #
# the shell profile
# --------------------------------------------------------------------------- #


PROFILES = (".bashrc", ".bash_profile", ".zshrc", ".profile",
            ".config/fish/config.fish")


def profile_edits(bin_dir: Path = BIN_DIR) -> list[tuple[Path, str]]:
    """Profiles carrying the block the installer added, and the block itself."""
    edits: list[tuple[Path, str]] = []
    zdotdir = os.environ.get("ZDOTDIR")
    candidates = [Path.home() / name for name in PROFILES]
    if zdotdir:
        candidates.append(Path(zdotdir) / ".zshrc")

    for profile in candidates:
        try:
            text = profile.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if PROFILE_MARKER in text and str(bin_dir) in text:
            edits.append((profile, PROFILE_MARKER))
    return edits


def strip_profile(profile: Path) -> str:
    """Remove the installer's block, and nothing either side of it.

    The block is the marker comment and the single line under it. Everything
    else in the file is somebody's, and a profile is not a file to be
    rewritten generously.
    """
    lines = profile.read_text(encoding="utf-8").splitlines(keepends=True)
    kept: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() == PROFILE_MARKER:
            # The marker, the line it introduces, and the blank line the
            # installer put in front of it.
            while kept and kept[-1].strip() == "":
                kept.pop()
            index += 2
            continue
        kept.append(lines[index])
        index += 1

    profile.write_text("".join(kept), encoding="utf-8")
    return f"{profile} (PATH line)"


def windows_path_entry(bin_dir: Path = BIN_DIR) -> bool:
    """Is the launcher directory in the user's PATH in the registry?"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "PATH")
    except (ImportError, OSError):
        return False
    return str(bin_dir).lower() in [part.strip().lower()
                                    for part in str(value).split(";")]


def strip_windows_path(bin_dir: Path = BIN_DIR) -> str:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        value, kind = winreg.QueryValueEx(key, "PATH")
        parts = [part for part in str(value).split(";")
                 if part.strip().lower() != str(bin_dir).lower()]
        winreg.SetValueEx(key, "PATH", 0, kind, ";".join(parts))
    return f"{bin_dir} removed from your PATH"


# --------------------------------------------------------------------------- #
# the survey
# --------------------------------------------------------------------------- #


def survey(config: Config | None = None, cwd: Path | None = None) -> Survey:
    """Find everything, and remove nothing."""
    found = Survey()
    root = config.paths.user if config else user_root()
    install = detect_installation()

    # -- the data ---------------------------------------------------------- #

    if root.is_dir():
        parts = []
        for name, label in (("config.json", "settings and your API key"),
                            ("brain.db", "learned rules and lessons"),
                            ("sessions", "conversation history"),
                            ("skills", "skills")):
            target = root / name
            if not target.exists():
                continue
            if name == "skills":
                count = len(list(target.glob("*")))
                parts.append(f"{count} skill{'s' if count != 1 else ''}")
            elif name == "sessions":
                count = len(list(target.glob("*.jsonl")))
                parts.append(f"{count} session{'s' if count != 1 else ''}")
            else:
                parts.append(label)

        found.add(Item(
            kind="data",
            label="everything it has learned and everything you told it",
            detail=" · ".join(parts) if parts else "empty",
            path=root,
            size=directory_size(root),
            remove=lambda path=root: _rmtree(path),
        ))
    else:
        found.notes.append(f"no data directory at {root}")

    if os.environ.get("COMODOR_HOME"):
        found.notes.append(
            "COMODOR_HOME is set, so the data directory above is the one it "
            "points at rather than the default")

    # -- the projects ------------------------------------------------------ #

    projects, had_history = project_directories(root, cwd)
    for directory in projects:
        found.add(Item(
            kind="project",
            label=f"{directory.parent.name}",
            detail="checkpoints, project settings, project skills",
            path=directory,
            size=directory_size(directory),
            remove=lambda path=directory: _rmtree(path),
        ))
    if not had_history:
        found.notes.append(
            "the session history is gone, so any .comodor folder in a project "
            "you used cannot be named here — delete those by hand")

    # -- the program ------------------------------------------------------- #

    if install.method == "source":
        found.notes.append(
            f"running from a source checkout at {Path(__file__).parents[2]} — "
            "that is yours, and is left alone")
    elif install.method in ("uv", "pipx"):
        tool = install.method
        found.add(Item(
            kind="program",
            label=f"the {tool} installation",
            detail=install.detail,
            path=install.root,
            size=directory_size(install.root) if install.root else 0,
            remove=lambda tool=tool: _run_uninstaller(tool),
            deferred=sys.platform == "win32",
        ))
    elif install.method == "venv" and install.owned:
        found.add(Item(
            kind="program",
            label="the isolated environment",
            detail=install.detail,
            path=install.owned,
            size=directory_size(install.owned),
            remove=lambda path=install.owned: _rmtree(path),
            deferred=sys.platform == "win32",
        ))
    elif install.method == "venv":
        # An environment the user made and put other things in. Take the
        # package out of it and leave the environment standing.
        found.add(Item(
            kind="program",
            label="the package, from your environment",
            detail=install.detail,
            path=install.root,
            remove=lambda: _run_uninstaller("pip"),
            deferred=sys.platform == "win32",
        ))
    else:
        found.add(Item(
            kind="program",
            label="the installed package",
            detail=install.detail,
            remove=lambda: _run_uninstaller("pip"),
            deferred=sys.platform == "win32",
        ))

    for launcher in _launchers():
        # The launcher inside an environment goes with the environment.
        if install.root and _within(launcher, install.root):
            continue
        found.add(Item(
            kind="launcher",
            label="the `comodor` command",
            detail="a link" if launcher.is_symlink() else "",
            path=launcher,
            size=0 if launcher.is_symlink() else directory_size(launcher),
            remove=lambda path=launcher: _rmtree(path),
            deferred=sys.platform == "win32" and launcher.suffix == ".exe",
        ))

    # -- the PATH ---------------------------------------------------------- #

    others = _other_launchers(BIN_DIR)
    if others:
        found.notes.append(
            f"{BIN_DIR} stays on your PATH: {others} other program"
            f"{'s' if others != 1 else ''} live there")
    else:
        for profile, _ in profile_edits(BIN_DIR):
            found.add(Item(
                kind="path",
                label="the PATH line the installer added",
                detail=f"which put {BIN_DIR} on your PATH",
                path=profile,
                remove=lambda path=profile: strip_profile(path),
            ))
        if windows_path_entry(BIN_DIR):
            found.add(Item(
                kind="path",
                label="the PATH entry the installer added",
                detail=str(BIN_DIR),
                remove=lambda directory=BIN_DIR: strip_windows_path(directory),
            ))

    found.notes.append(
        "packages that MCP servers pulled into the npm or uv caches are not "
        "Comodor's to delete, and are left where they are")

    return found


def _within(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        return True
    except ValueError:
        return False


def _other_launchers(directory: Path) -> int:
    """How many programs besides ours live in the launcher directory."""
    if not directory.is_dir():
        return 0
    ours = {"comodor", "comodor.exe", "comodor.cmd", "comodor-script.py"}
    try:
        return sum(1 for entry in directory.iterdir() if entry.name not in ours)
    except OSError:
        return 0


def _run_uninstaller(tool: str) -> str:
    """Hand the package back to whatever installed it."""
    commands = {
        "uv": ["uv", "tool", "uninstall", "comodor"],
        "pipx": ["pipx", "uninstall", "comodor"],
        "pip": [sys.executable, "-m", "pip", "uninstall", "-y", "comodor"],
    }
    command = commands[tool]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip()[:200]
                           or f"{tool} exited {result.returncode}")
    return " ".join(command[-3:] if tool != "pip" else command[1:])


# --------------------------------------------------------------------------- #
# doing it
# --------------------------------------------------------------------------- #


def apply(found: Survey) -> Survey:
    """Remove everything in the survey, deferring what cannot go yet.

    Order matters: the data and the projects first, the program last. If
    something fails halfway, what is left behind is the thing that can still
    uninstall the rest.
    """
    order = {"data": 0, "project": 1, "path": 2, "launcher": 3, "program": 4}
    deferred: list[Path] = []

    for item in sorted(found.items, key=lambda i: order.get(i.kind, 9)):
        if item.remove is None:
            continue
        if item.deferred and item.path is not None:
            deferred.append(item.path)
            continue
        try:
            found.removed.append(item.remove())
        except Exception as error:                    # noqa: BLE001 - reported
            found.failed.append(f"{item.path or item.label}: {error}")

    if deferred:
        try:
            _schedule(deferred)
            for path in deferred:
                found.removed.append(f"{path} (after this process exits)")
        except Exception as error:                    # noqa: BLE001 - reported
            for path in deferred:
                found.failed.append(f"{path}: {error}")

    return found


def _schedule(paths: list[Path]) -> None:
    """Delete these once this process is gone.

    Windows will not unlink a running executable or a loaded DLL, and the
    environment being removed contains both. Rather than report a failure the
    user then has to clean up by hand, the work is handed to a detached
    PowerShell that waits on this process id and then does it.
    """
    quoted = ",".join(f"'{str(path).replace(chr(39), chr(39) * 2)}'"
                      for path in paths)
    script = (
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue;"
        f"Start-Sleep -Milliseconds 400;"
        f"foreach ($p in @({quoted})) {{"
        f" Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue }}"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", script],
        creationflags=(getattr(subprocess, "DETACHED_PROCESS", 0)
                       | getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
