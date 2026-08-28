"""Finding what is wrong, and putting it right.

`comodor doctor` was a report. Reports are useful when the reader knows what
to do with them, and most of the things that break here have exactly one
correct fix — a stale cache to delete, a permission to tighten, a folder that
should exist. Printing "your search index is corrupt" and leaving it there
serves nobody.

So every check states a fix when it has one, and `--fix` applies it. The split
matters: a diagnostic command that silently rewrites files is worse than one
that only talks, because the next person to run it cannot predict what it will
do. Doctor tells you first, then repairs when asked.

Two rules for anything that calls itself a repair:

**It must be safe to run twice.** Every repair here either does nothing or
reaches the same end state, so a user who runs `--fix` three times in confusion
is no worse off.

**It must never destroy something it cannot rebuild.** Caches, indexes and
temporary files are fair game. A brain full of learned rules, a config holding
an API key and a folder of hand-written skills are not: for those, doctor
reports and stops.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .config import Config


class Status(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class Finding:
    """What one check found."""

    name: str
    status: Status
    detail: str = ""
    #: What would fix it, in words, whether or not doctor can do it.
    remedy: str = ""
    #: Applied by ``--fix``. Returns what it did, or raises.
    repair: Callable[[], str] | None = None

    @property
    def fixable(self) -> bool:
        return self.repair is not None and self.status is not Status.OK


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    @property
    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.status is not Status.OK]

    @property
    def fixable(self) -> list[Finding]:
        return [f for f in self.findings if f.fixable]

    @property
    def worst(self) -> Status:
        if any(f.status is Status.FAIL for f in self.findings):
            return Status.FAIL
        if any(f.status is Status.WARN for f in self.findings):
            return Status.WARN
        return Status.OK


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #


def run_checks(config: Config, online: bool = True) -> Report:
    """Every check, in the order a person would want to read them.

    `online` exists because one check asks the package index whether there is a
    newer release, and everything else here reads the local machine. A caller
    that must not touch the network — a test, or a diagnostic being gathered
    from somewhere with no route out — turns it off and gets the rest.
    """
    checks = [_check_config, _check_config_permissions, _check_provider,
              _check_saved_provider, _check_model, _check_spend_limit,
              _check_brain,
              _check_search_index, _check_skills, _check_leftovers, _check_mcp,
              _check_telegram]
    if online:
        checks.append(_check_version)

    report = Report()
    for check in checks:
        try:
            finding = check(config)
        except Exception as error:                # a check must never be the bug
            finding = Finding(getattr(check, "__name__", "check")[7:].replace("_", " "),
                              Status.WARN, f"could not be checked: {error}")
        if finding is not None:
            report.add(finding)
    return report


def _check_config(config: Config) -> Finding:
    path = config.paths.config_file
    if not path.exists():
        return Finding(
            "config file", Status.FAIL, f"{path} does not exist",
            remedy="run `comodor setup` to answer the four questions once")

    try:
        import json

        json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        # Deliberately no repair. The file holds an API key; overwriting it
        # with defaults would silently destroy the one thing the user cannot
        # regenerate from anything on this machine.
        return Finding(
            "config file", Status.FAIL, f"{path} is not valid JSON: {error}",
            remedy="fix the JSON by hand, or move the file aside and run "
                   "`comodor setup`. It holds your API key, so doctor will not "
                   "overwrite it")

    return Finding("config file", Status.OK, str(path))


def _check_config_permissions(config: Config) -> Finding | None:
    """The config holds an API key, so on Unix it should be owner-only."""
    if os.name == "nt":
        return None
    path = config.paths.config_file
    if not path.exists():
        return None

    mode = stat.S_IMODE(path.stat().st_mode)
    if not mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH):
        return Finding("config permissions", Status.OK, f"{oct(mode)}")

    def repair() -> str:
        path.chmod(0o600)
        return f"tightened {path} to 0600"

    return Finding(
        "config permissions", Status.WARN,
        f"{path} is readable by other users ({oct(mode)})",
        remedy="restrict it to your account", repair=repair)


def _check_provider(config: Config) -> Finding:
    name = config.provider
    entry = config.providers.get(name)

    if entry is None:
        ready = [key for key, value in config.providers.items() if value.ready
                 and value.configured]
        if ready:
            chosen = ready[0]

            def repair() -> str:
                config.provider = chosen
                config.save()
                return f"selected {chosen}, which is configured"

            return Finding(
                "provider", Status.FAIL,
                f"{name!r} is selected but is not a provider Comodor knows",
                remedy=f"switch to one that is set up ({', '.join(ready)})",
                repair=repair)
        return Finding(
            "provider", Status.FAIL, f"{name!r} is not a known provider",
            remedy="run `comodor setup` to choose one")

    if not entry.ready:
        return Finding(
            "provider", Status.FAIL, f"{entry.display} has no API key",
            remedy="run `comodor setup`, or set the provider's environment "
                   "variable")

    return Finding("provider", Status.OK, f"{entry.display} · {entry.model}")


def _check_saved_provider(config: Config) -> Finding | None:
    """The file can name a provider that no longer exists.

    Loading quietly falls back to one that works, which is the right thing to
    do at startup and the wrong thing to leave unmentioned: the file still says
    something untrue, and every future run repeats the guess. Nothing is broken,
    so this is a warning — but it is a warning doctor can act on.
    """
    import json

    path = config.paths.config_file
    if not path.exists():
        return None

    try:
        saved = str(json.loads(path.read_text(encoding="utf-8")).get("provider") or "")
    except (ValueError, OSError):
        return None                       # the config check already reported it

    if not saved or saved == config.provider:
        return None
    if saved in config.providers:
        return None                       # a real provider, just not selected now

    def repair() -> str:
        config.save()
        return f"replaced {saved!r} in the config with {config.provider!r}"

    return Finding(
        "saved provider", Status.WARN,
        f"the config names {saved!r}, which does not exist; "
        f"{config.provider!r} is being used instead",
        remedy="write the one actually in use back to the file", repair=repair)


def _check_model(config: Config) -> Finding | None:
    """A model the provider does not offer fails on the first real request."""
    from . import catalogue

    entry = config.providers.get(config.provider)
    if entry is None or not entry.ready:
        return None

    spec = catalogue.get(config.provider)
    model = config.active_model()

    if not model:
        if spec is not None and spec.default_model:
            def repair() -> str:
                config.model = spec.default_model
                config.save()
                return f"set the model to {spec.default_model}"

            return Finding("model", Status.FAIL, "no model is selected",
                           remedy=f"use {spec.default_model}", repair=repair)
        return Finding("model", Status.FAIL, "no model is selected",
                       remedy="run `comodor setup`")

    # Only a warning. The catalogue lists the models we know about, not every
    # model a provider has ever served, and a new release should not be
    # reported as broken.
    if spec is not None and spec.models and model not in spec.models:
        return Finding(
            "model", Status.WARN,
            f"{model!r} is not in the known list for {spec.label}",
            remedy=f"if requests fail, try {spec.default_model}")

    return Finding("model", Status.OK, model)


def _check_spend_limit(config: Config) -> Finding | None:
    """Whether the money ceiling is a ceiling or a decoration.

    The loop stops a task when the running cost passes `agent.max_cost_usd`.
    That cost comes from the pricing registry, which leaves rates unset for
    models it is not confident about. For one of those the cost is None, the
    meter never leaves zero, and the limit never fires -- silently, which is
    the part worth reporting.
    """
    limit = config.agent.max_cost_usd
    if not limit:
        return None                       # no ceiling asked for, none to check

    model = config.active_model()
    if not model:
        return None                       # a different check already said so

    entry = config.active()
    if entry is not None and entry.local:
        return Finding("spend limit", Status.OK,
                       f"not needed - {entry.display} runs on your machine")

    from .config import unenforceable_budget

    if not unenforceable_budget(config):
        return Finding("spend limit", Status.OK, f"${limit:.2f} per task")

    return Finding(
        "spend limit", Status.WARN,
        f"${limit:.2f} per task cannot be enforced for {model}",
        remedy="No published rate is known for this model, so the cost meter "
               "reads zero and the limit never fires. The step and time limits "
               "still apply: see agent.max_steps and agent.max_seconds.")


def _check_brain(config: Config) -> Finding:
    path = config.paths.brain_db
    if not path.exists():
        return Finding("brain", Status.OK, "no learning recorded yet")

    try:
        result = _quick_check(path)
    except sqlite3.Error as error:
        return Finding(
            "brain", Status.FAIL, f"{path} could not be opened: {error}",
            remedy="move the file aside to start fresh. It holds everything "
                   "Comodor has learned, so doctor will not delete it for you")

    if result and result[0] != "ok":
        return Finding(
            "brain", Status.FAIL, f"{path} is corrupt",
            remedy="move the file aside to start fresh. It holds everything "
                   "Comodor has learned, so doctor will not delete it for you")

    return Finding("brain", Status.OK, str(path))


def _check_search_index(config: Config) -> Finding:
    """The one database that is safe to delete: it rebuilds from transcripts."""
    path = config.paths.user / "sessions" / "search.db"
    if not path.exists():
        return Finding("session search", Status.OK, "not built yet")

    broken = ""
    try:
        result = _quick_check(path)
        if result and result[0] != "ok":
            broken = "the index is corrupt"
    except sqlite3.Error as error:
        broken = f"the index could not be opened: {error}"

    if not broken:
        return Finding("session search", Status.OK, str(path))

    def repair() -> str:
        for suffix in ("", "-wal", "-shm"):
            candidate = path.with_name(path.name + suffix)
            candidate.unlink(missing_ok=True)
        return "deleted the search index; it rebuilds from your transcripts"

    return Finding(
        "session search", Status.WARN, broken,
        remedy="delete it — it is a cache built from the transcripts, so "
               "nothing is lost",
        repair=repair)


def _check_skills(config: Config) -> Finding:
    from .skills import SkillRegistry

    directory = config.paths.skills
    if not directory.exists():
        # Not a fault. The folder is created, with its worked examples, the
        # first time Comodor runs — reporting the ordinary state of a machine
        # that has been set up but not yet used would be noise, and doctor is
        # only worth reading if everything in it matters.
        return Finding("skills", Status.OK,
                       "not created yet; the first run writes it with examples")

    registry = SkillRegistry()
    count = registry.discover(directory, config.paths.project_skills)

    if registry.errors:
        names = ", ".join(Path(path).name for path, _ in registry.errors[:3])
        first = registry.errors[0][1].splitlines()[0]
        # No repair: these are files the user wrote, and guessing at what they
        # meant would be worse than telling them which file and why.
        return Finding(
            "skills", Status.WARN,
            f"{count} loaded, {len(registry.errors)} would not load ({names})",
            remedy=f"first problem: {first}")

    return Finding("skills", Status.OK, f"{count} loaded from {directory}")


def _quick_check(path: Path) -> Any:
    """`PRAGMA quick_check`, always closing the handle.

    Without the `finally` a corrupt file leaves the connection open, and on
    Windows an open handle means the repair that deletes it silently does
    nothing while reporting success.
    """
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()


def _check_leftovers(config: Config) -> Finding:
    """Temporary files from an interrupted write, and stale probe folders."""
    root = config.paths.user
    found: set[Path] = set()
    if root.exists():
        # `config.json.tmp` matches both patterns, so a list would report two
        # files and then remove one — a count that contradicts itself is worse
        # than no count.
        found.update(root.glob("*.tmp"))
        found.update(root.glob("*.json.tmp"))
    probe = root / ".venv-probe"
    if probe.exists():
        found.add(probe)
    stale = sorted(found)

    if not stale:
        return Finding("leftover files", Status.OK, "none")

    def repair() -> str:
        removed = 0
        for path in stale:
            if not path.exists():
                # An earlier repair may have taken it: saving the config writes
                # through `config.json.tmp` and replaces it. Reporting "removed
                # 0" for a file that is correctly gone reads like a failure.
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                removed += 1
            except OSError:
                pass
        if not removed:
            return "the leftover files were already gone"
        return f"removed {removed} leftover file(s)"

    return Finding(
        "leftover files", Status.WARN,
        f"{len(stale)} left behind by an interrupted write",
        remedy="remove them; nothing reads them", repair=repair)


def _check_mcp(config: Config) -> Finding | None:
    """Configured MCP servers that cannot start are worth knowing about."""
    settings = getattr(config, "mcp", None)
    if settings is None or not settings.servers:
        return None

    enabled = [name for name, server in settings.servers.items() if server.enabled]
    if not enabled:
        return Finding("mcp servers", Status.OK,
                       f"{len(settings.servers)} configured, none enabled")

    from .mcp import probe_server

    broken: list[str] = []
    for name in enabled:
        ok, detail = probe_server(settings.servers[name])
        if not ok:
            broken.append(f"{name} ({detail})")

    if broken:
        return Finding(
            "mcp servers", Status.WARN,
            f"{len(enabled)} enabled, {len(broken)} will not start: "
            + ", ".join(broken[:3]),
            remedy="check the command is installed, or disable it with "
                   "`comodor mcp disable <name>`")

    return Finding("mcp servers", Status.OK, f"{len(enabled)} enabled and reachable")


def _check_telegram(config: Config) -> Finding | None:
    """A bot with a token and nobody paired answers nothing, silently.

    That is the correct behaviour — a bot's username is public, so it must
    ignore strangers rather than tell them it exists — but from the outside it
    is indistinguishable from a broken install, and the person who set it up
    has no way to tell which they have. So it is said here.
    """
    settings = getattr(config, "telegram", None)
    if settings is None or not settings.token:
        return None

    writes = "may edit files" if settings.allow_writes else "reads and plans only"

    if not settings.allowed:
        return Finding(
            "telegram", Status.WARN,
            "a bot is connected but nobody is paired, so it answers nobody",
            remedy="`comodor telegram pair` adds your account")

    return Finding("telegram", Status.OK,
                   f"{len(settings.allowed)} account(s) paired, {writes}"
                   + ("" if settings.enabled else ", switched off"))


# --------------------------------------------------------------------------- #
# applying repairs
# --------------------------------------------------------------------------- #


def apply_fixes(report: Report) -> Report:
    """Run every repair the report offers. Safe to call more than once."""
    for finding in report.fixable:
        try:
            report.repaired.append(finding.repair())        # type: ignore[misc]
        except Exception as error:
            report.failed.append(f"{finding.name}: {error}")
    return report


def wait_for(condition: Callable[[], bool], timeout: float = 2.0,
             interval: float = 0.05) -> bool:
    """Poll until true or out of time. Used by checks that touch a subprocess."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def _check_version(config: Config) -> Finding | None:
    """Is there a newer release than the one running?

    Doctor is where people look when something is not working, and "you are
    four versions behind" is often the whole answer. It is not a repair, though
    — `--fix` must never reach out and change what is installed under somebody
    without being asked, so this states the command and stops.

    On a short timeout, and silent when the network is not there. A diagnostic
    that hangs for fifteen seconds on an aeroplane is a worse diagnostic than
    one with a line missing.
    """
    from . import __version__
    from .update import is_newer, latest

    release = latest(timeout=(2.0, 3.0))
    if release is None:
        return None                               # offline; not a fault to report

    if not is_newer(release.version, __version__):
        return Finding("version", Status.OK, f"{__version__} is current")

    return Finding(
        "version", Status.WARN,
        f"{__version__} is installed; {release.version} is out",
        remedy="comodor update",
    )


def _check_script(config: Config) -> Finding | None:
    """Can this terminal show the writing systems the user is using?

    Only reported when there is something to report. The check reads what the
    agent has actually been asked, because a machine that has only ever seen
    English has no reason to be told about Persian fonts.

    It cannot be repaired from here and it is not a fault in Comodor. A program
    writes characters; the terminal emulator picks the glyphs, and no
    application can reach in and change the font. So this says which setting to
    change and where, and stops.
    """
    from .ui.bidi import has_rtl

    sessions = config.paths.user / "sessions"
    if not sessions.is_dir():
        return None

    # The most recent few. Reading a year of transcripts to render one line of
    # a report is not a trade worth making.
    recent = sorted(sessions.glob("*.jsonl"),
                    key=lambda path: path.stat().st_mtime if path.exists() else 0,
                    reverse=True)[:5]
    for path in recent:
        try:
            sample = path.read_text(encoding="utf-8", errors="ignore")[:20_000]
        except OSError:
            continue
        if has_rtl(sample):
            return Finding(
                "right-to-left", Status.OK,
                "Persian, Arabic or Hebrew in your history",
                remedy=("the terminal picks the font, not Comodor — set Tahoma "
                        "(or any face with Arabic-script coverage) in your "
                        "terminal's settings if the letters come out as boxes"),
            )
    return None
