"""Finding plugins, trusting them, and loading them without letting one
take the session down.

The trust model is the headline. Plugins under the user's own directory are
theirs, and load like any configuration. Plugins that arrived inside a
repository are somebody else's code sitting on disk next to the files the
agent is about to edit, and they stay inert until a person has read what
they do and said so — the same arrangement the workspace guard uses, and
for the same reason.

Loading is by file path into a throwaway module name, and every plugin is
wrapped: one that raises costs itself its place in the list and a line in
`doctor`, never the session. The import scan is deliberately shallow — it
reads the file for the few patterns worth a human's second look before
trust is granted, not a sandbox, which would be a promise it cannot keep.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import PluginContext, PluginError

MANIFEST = "plugin.py"
#: A repo's plugins live inside the project's own Comodor directory, which
#: is the file the project may commit.
PROJECT_DIR = "plugins"

#: Patterns that deserve a second look before a person says yes. Matching is
#: a warning, not a refusal: a logging plugin legitimately imports socket,
#: and the human deciding is the whole point of trust.
SCAN_PATTERNS: list[tuple[str, str]] = [
    (re.compile(r"\bexec\s*\("), "exec() runs any code as any tool here"),
    (re.compile(r"\beval\s*\("), "eval() runs any code as any tool here"),
    (re.compile(r"\b__import__\s*\("), "dynamic import hides what it loads"),
    (re.compile(r"\bgetenv\s*\(\s*['\"](?:OPENAI|ANTHROPIC|GROQ|GEMINI|MEM0)"
                r"[_A-Z]*['\"]"),
     "reads a provider key from the environment"),
    (re.compile(r"[\"'](?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,})"),
     "looks like a hard-coded API key"),
]


@dataclass
class PluginState:
    """One discovered plugin and how it got on (or did not)."""

    name: str
    path: Path
    source: str = ""          # "user" or "project"
    trusted: bool = False
    loaded: bool = False
    error: str = ""
    context: PluginContext | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.loaded and not self.error


def user_dir(paths: Any) -> Path:
    return paths.user / PROJECT_DIR


def project_dir(paths: Any) -> Path:
    return paths.project_dir / PROJECT_DIR


class PluginManager:
    """Every plugin on disk, and the ones allowed to run."""

    def __init__(self, paths: Any, trusted_folders: list[str] | None = None,
                 project_trusted: bool = False) -> None:
        self.paths = paths
        self.project_trusted = project_trusted
        self.trusted_folders = list(trusted_folders or [])
        self.states: dict[str, PluginState] = {}
        self._hooks: dict[str, list[tuple[str, Any]]] = {}

    # -- discovery --------------------------------------------------------- #

    def discover(self) -> list[PluginState]:
        """Find every plugin directory, trusted or not.

        Both roots are first-class. A name in both places resolves to the
        user's copy: their own machine outvotes what a repository shipped.
        """
        found: dict[str, Path] = {}
        sources: dict[str, str] = {}
        for root, source in ((user_dir(self.paths), "user"),
                             (project_dir(self.paths), "project")):
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                manifest = entry / MANIFEST
                if entry.is_dir() and manifest.is_file():
                    found[entry.name] = manifest
                    sources[entry.name] = source

        self.states.clear()
        for name, manifest in sorted(found.items()):
            source = sources[name]
            trusted = (source == "user") or self._project_trusted(manifest)
            self.states[name] = PluginState(
                name=name, path=manifest, source=source, trusted=trusted)
        return list(self.states.values())

    def _project_trusted(self, manifest: Path) -> bool:
        """Whether the project carrying this plugin has been trusted.

        Trust attaches to the *folder* holding the project, exactly as the
        workspace guard remembers it — approving a copy of a repository does
        not approve every copy of it.
        """
        try:
            root = str(manifest.resolve().parents[2])
        except OSError:
            return False
        return any(_same(root, entry) for entry in self.trusted_folders)

    # -- trust ------------------------------------------------------------- #

    def scan(self, name: str) -> list[str]:
        """What a person should see before saying yes. Empty means nothing
        matched — which is not a certificate, and the message says so."""
        state = self.states.get(name)
        if state is None:
            return [f"no plugin called {name!r}"]
        try:
            text = state.path.read_text(encoding="utf-8", errors="replace")
        except OSError as problem:
            return [f"the file could not be read: {problem}"]
        return [why for pattern, why in SCAN_PATTERNS if pattern.search(text)]

    def trust(self, name: str) -> list[str]:
        """Trust a project plugin: record its project root and rescan.

        Returns the scan findings so the caller can show them before and
        after; trusting is a decision for the person running this.
        """
        state = self.states.get(name)
        if state is None or state.source != "project":
            return []
        try:
            root = str(state.path.resolve().parents[2])
        except OSError:
            return ["the project root could not be resolved"]
        if not any(_same(root, entry) for entry in self.trusted_folders):
            self.trusted_folders.append(root)
        state.trusted = True
        return self.scan(name)

    def untrust(self, name: str) -> bool:
        """Forget a project root. The plugin stops loading on the next run."""
        state = self.states.get(name)
        if state is None or state.source != "project":
            return False
        try:
            root = str(state.path.resolve().parents[2])
        except OSError:
            return False
        self.trusted_folders = [entry for entry in self.trusted_folders
                                if not _same(entry, root)]
        state.trusted = False
        return True

    # -- loading ------------------------------------------------------------ #

    def load_all(self) -> list[PluginState]:
        """Load every trusted plugin; report the rest.

        Each import runs inside its own except. A plugin that raises at
        registration has already failed by the time the session sees it,
        which is the only isolation a plugin loaded into this process can
        honestly claim — the rest of the promise is the permission gate.
        """
        if not self.states:
            self.discover()
        for state in self.states.values():
            if not state.trusted:
                continue
            try:
                context = _load_one(state)
                state.context = context
                state.loaded = True
                for hook_kind, callback in context.hooks:
                    self._hooks.setdefault(hook_kind, []).append(
                        (state.name, callback))
            except PluginError as problem:
                state.error = str(problem)
            except Exception as problem:
                state.error = f"{type(problem).__name__}: {problem}"
        return list(self.states.values())

    # -- what the plugins added --------------------------------------------- #

    def hook_callbacks(self, kind: str) -> list[tuple[str, Any]]:
        """(plugin, callback) pairs for one bus kind. Cheap, called per event."""
        return self._hooks.get(kind, [])

    def registered_tools(self) -> list[tuple[str, dict[str, Any]]]:
        """(plugin, tool spec) for every tool the loaded plugins declared."""
        out: list[tuple[str, dict[str, Any]]] = []
        for state in self.states.values():
            if state.ok and state.context:
                for spec in state.context.tools:
                    out.append((state.name, spec))
        return out


def _same(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return left == right


def _load_one(state: PluginState) -> PluginContext:
    """Import one plugin file and call its ``register``.

    The module gets a private name so two plugins, or a plugin and the core,
    cannot see each other's leftovers. Nothing from the module is retained
    except what ``register`` chose to put in the context.
    """
    spec = importlib.util.spec_from_file_location(
        f"_comodor_plugin_{state.name}", state.path)
    if spec is None or spec.loader is None:
        raise PluginError(f"{state.path} could not be imported")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SyntaxError as problem:
        raise PluginError(f"{state.path} does not parse: {problem}") from None

    register = getattr(module, "register", None)
    if not callable(register):
        raise PluginError(
            f"{state.path} defines no register(ctx) function")
    context = PluginContext(state.name)
    try:
        register(context)
    except PluginError:
        raise
    except Exception as problem:
        raise PluginError(
            f"register() failed: {type(problem).__name__}: {problem}") from None
    return context
