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
DEFAULT_PROFILE = "default"


def profile_name() -> str:
    """Which profile this run belongs to, from the flag or the environment.

    The default needs no name: it is the data directory the program has always
    used, and somebody who has never heard of profiles must not find one day
    that their brain has moved.
    """
    name = os.environ.get("COMODOR_PROFILE", "").strip()
    return name or DEFAULT_PROFILE


def user_root() -> Path:
    """Per-user data directory, honouring the platform's conventions.

    A named profile (``--profile work`` or ``COMODOR_PROFILE=work``) gets its
    own subtree under ``profiles/`` — its own brain, sessions, skills and
    config — so two profiles can run at once without sharing a single learned
    lesson. The default profile is the root itself, not a member of
    ``profiles/``, so an installation predating profiles needs no migration.
    """
    override = os.environ.get("COMODOR_HOME")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "win32":
        base_env = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        base = Path(base_env) / "Comodor" if base_env \
            else Path.home() / f".{APP_DIR_NAME}"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Comodor"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = (Path(xdg) / APP_DIR_NAME if xdg
                else Path.home() / f".{APP_DIR_NAME}")

    name = profile_name()
    if name != DEFAULT_PROFILE:
        return base / "profiles" / name
    return base



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
    def approvals(self) -> Path:
        """The record of shell commands a person said yes to.

        One JSON line per approval. Nothing reads it while decisions are
        being made — it exists so approval mining can look at what this user
        actually approves and propose an allowlist from evidence rather than
        guesswork.
        """
        return self.user / "approvals.jsonl"

    def delivery_ledger(self, platform: str) -> Path:
        """The outbound-delivery ledger of one channel daemon.

        Per platform, because each daemon recovers its own sends on start
        and one file per platform keeps the recovery pass single-threaded
        by construction.
        """
        return self.user / "delivery" / f"{platform}.jsonl"

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
