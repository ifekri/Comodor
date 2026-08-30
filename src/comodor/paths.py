r"""Where Comodor keeps its files.

Two roots, deliberately separate:

* the **user root** (``~/.comodor`` or ``%APPDATA%\Comodor``) holds things that
  should follow you between projects — config, the learning brain, logs;
* the **project root** (``./.comodor``) holds things that belong to one codebase
  — checkpoints, a project allowlist, project-scoped settings.

Keeping the brain user-global is what lets a lesson learned in one repository
help in the next one, while checkpoints stay next to the code they can restore.
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "comodor"
PROJECT_DIR_NAME = ".comodor"


def user_root() -> Path:
    """Per-user data directory, honouring the platform's conventions."""
    override = os.environ.get("COMODOR_HOME")
    if override:
        return Path(override).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Comodor"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Comodor"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            return Path(xdg) / APP_DIR_NAME

    return Path.home() / f".{APP_DIR_NAME}"


def project_root(cwd: Path | str | None = None) -> Path:
    """The nearest enclosing project, detected by its usual markers.

    We walk upward from ``cwd`` looking for a repository or package marker so
    that running Comodor from ``src/deep/nested`` still scopes memory and
    checkpoints to the project as a whole.
    """
    start = Path(cwd).resolve() if cwd else Path.cwd().resolve()
    markers = (".git", ".hg", ".comodor", "pyproject.toml", "package.json",
               "Cargo.toml", "go.mod", ".svn")
    for candidate in (start, *start.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return start


def project_key(root: Path | None = None) -> str:
    """Stable short identifier for a project, used to scope learned lessons."""
    resolved = (root or project_root()).resolve()
    digest = hashlib.sha256(str(resolved).lower().encode("utf-8")).hexdigest()
    return f"{resolved.name}-{digest[:8]}"


@dataclass(frozen=True)
class Paths:
    """Resolved locations for one run."""

    user: Path
    project: Path

    @property
    def config_file(self) -> Path:
        return self.user / "config.json"

    @property
    def project_config_file(self) -> Path:
        return self.project / PROJECT_DIR_NAME / "config.json"

    @property
    def skills(self) -> Path:
        """Where authored skills live, shared across every project."""
        return self.user / "skills"

    @property
    def project_skills(self) -> Path:
        """Skills belonging to one codebase, committable with it."""
        return self.project / PROJECT_DIR_NAME / "skills"

    @property
    def brain_db(self) -> Path:
        return self.user / "brain.db"

    @property
    def log_file(self) -> Path:
        return self.user / "logs" / "comodor.log"

    @property
    def checkpoints(self) -> Path:
        return self.project / PROJECT_DIR_NAME / "checkpoints"

    @property
    def exports(self) -> Path:
        return self.user / "exports"

    @property
    def project_dir(self) -> Path:
        return self.project / PROJECT_DIR_NAME

    def ensure(self) -> "Paths":
        """Create the directories we are about to write into.

        The project directory is created lazily by the writers instead of here,
        so simply starting Comodor inside a repository does not litter it.
        """
        (self.user / "logs").mkdir(parents=True, exist_ok=True)
        self.exports.mkdir(parents=True, exist_ok=True)
        return self


def resolve(cwd: Path | str | None = None) -> Paths:
    return Paths(user=user_root(), project=project_root(cwd))
