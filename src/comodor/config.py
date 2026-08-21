"""Configuration: one JSON file the user never has to hand-edit.

Everything Comodor needs lives in ``~/.comodor/config.json``, written by the
setup wizard on first run. There is no ``.env`` to create, no environment
variable to export and no documentation to read before the first task — the
program asks a few questions once and remembers the answers.

Resolution order, later layers winning:

    1. built-in defaults (this module)
    2. ~/.comodor/config.json           what the wizard wrote
    3. ./.comodor/config.json           per-project overrides, safe to commit
    4. environment variables            an escape hatch for CI, never required
    5. CLI flags                        one-off overrides

The project layer exists so a team can pin a mode or a model in a repository
without anybody's key going with it: API keys are only ever read from the user
file or the environment, and :meth:`Config.to_public_dict` masks them before
anything is displayed, logged or exported.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

from . import catalogue
from .paths import Paths, resolve as resolve_paths

CONFIG_VERSION = 1

# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #


@dataclass
class ProviderConfig:
    """One backend, as configured for this user."""

    name: str
    kind: str = "openai"                 # "openai" | "anthropic" | "fake"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    label: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout: float = 120.0
    #: True once the user has actually set this provider up. Local runtimes
    #: need no key, so without this Comodor would happily auto-select an Ollama
    #: that is not running and fail with a connection error.
    configured: bool = False

    @property
    def display(self) -> str:
        return self.label or self.name.title()

    @property
    def local(self) -> bool:
        return any(host in self.base_url for host in ("localhost", "127.0.0.1", "0.0.0.0"))

    @property
    def ready(self) -> bool:
        """Whether a call could be made right now."""
        return bool(self.base_url) and (bool(self.api_key) or self.local)

    @property
    def selectable(self) -> bool:
        """Whether Comodor may choose this provider on the user's behalf."""
        return self.enabled and self.ready and (self.configured or not self.local)

    def to_json(self) -> dict[str, Any]:
        """Only what is worth persisting; the rest comes from the catalogue."""
        data: dict[str, Any] = {"enabled": self.enabled, "configured": self.configured}
        if self.api_key:
            data["api_key"] = self.api_key
        if self.model:
            data["model"] = self.model
        spec = catalogue.get(self.name)
        if not spec or self.base_url != spec.base_url:
            data["base_url"] = self.base_url
        if self.headers:
            data["headers"] = self.headers
        if self.timeout != 120.0:
            data["timeout"] = self.timeout
        return data


def provider_from_spec(spec: catalogue.ProviderSpec) -> ProviderConfig:
    return ProviderConfig(
        name=spec.id,
        kind=spec.kind,
        base_url=spec.base_url,
        model=spec.default_model,
        label=spec.label,
        headers=dict(spec.headers),
        configured=False,
    )


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #


@dataclass
class UIConfig:
    theme: str = "ember"
    ascii_borders: bool = False          # for terminals without box-drawing glyphs
    mouse: bool = True
    max_fps: int = 20                    # streaming deltas are coalesced to this
    show_timestamps: bool = False
    sidebar: bool = True
    #: Empty means the colour theme picks one that suits it.
    syntax_theme: str = ""


@dataclass
class AgentConfig:
    mode: str = "act"                    # act | plan | chat
    loop: bool = True                    # autonomous multi-step iteration
    max_steps: int = 24                  # hard stop for one task
    max_seconds: float = 900.0
    max_cost_usd: float = 2.0
    context_limit: int = 1_000_000       # the "Context: 1M" gauge
    compact_at: float = 0.75             # summarise history past this fraction
    temperature: float = 0.3
    max_output_tokens: int = 8192
    system_prompt_extra: str = ""
    prompt_cache: bool = True            # let the provider re-serve the prefix
    prompt_cache_ttl: str = "5m"         # "5m" or "1h"; the hour costs more to write


@dataclass
class GatewayConfig:
    """The GW indicator: route across providers instead of pinning one."""

    enabled: bool = False
    policy: str = "quality"              # cost | speed | quality
    chain: list[str] = field(default_factory=list)
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0


@dataclass
class LearningConfig:
    enabled: bool = True
    top_k: int = 6                       # lessons recalled per turn
    max_playbook_tokens: int = 800       # hard cap on injected memory
    reflect: bool = True                 # distil lessons after each task
    reflect_model: str = ""              # blank = the active model
    min_confidence: float = 0.15
    half_life_days: float = 45.0
    share_scope: str = "project"         # project | global
    #: Learn which of your words belong together, from your own finished tasks,
    #: and use it to find lessons phrased differently from the request. Costs
    #: no tokens and no model call — it is counting. See learning/associations.
    associative: bool = True

    # Reflex — the fast lane: deterministic, model-free, always on. It costs no
    # tokens, so it stays enabled even when reflection is switched off.
    corrections: bool = True
    rules: bool = True
    announce: bool = True
    prefetch: bool = True


@dataclass
class SkillsConfig:
    """Authored skills: instructions the user writes once and reuses."""

    enabled: bool = True
    #: How many matching skills may be injected into one turn.
    top_k: int = 2
    max_tokens: int = 1200
    #: Install the starter skills the first time the folder is created.
    install_examples: bool = True
    #: Where the downloadable library is listed. A setting rather than a
    #: constant because a team may keep its own on an internal host, and
    #: should not have to fork the program to point at it.
    catalogue_url: str = (
        "https://raw.githubusercontent.com/ifekri/Comodor/skills/catalogue.json"
    )
    #: Seconds a cached catalogue is used without asking the server at all.
    #: Past it the request is conditional, and the usual answer is 304 with no
    #: body, so this is about round trips rather than bandwidth.
    catalogue_ttl: int = 300


@dataclass
class MCPServerConfig:
    """One Model Context Protocol server the user has added."""

    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: Working directory for the process; empty means the project root.
    cwd: str = ""
    enabled: bool = False
    #: The catalogue entry it came from, when it came from one.
    spec: str = ""

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"command": self.command, "enabled": self.enabled}
        if self.args:
            data["args"] = list(self.args)
        if self.env:
            data["env"] = dict(self.env)
        if self.cwd:
            data["cwd"] = self.cwd
        if self.spec:
            data["spec"] = self.spec
        return data


@dataclass
class MCPConfig:
    """Servers, and the master switch over all of them."""

    enabled: bool = True
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "servers": {name: server.to_json()
                        for name, server in sorted(self.servers.items())},
        }


@dataclass
class SafetyConfig:
    auto_approve_safe: bool = True       # read-only tools never prompt
    auto_approve_writes: bool = False
    auto_approve_shell: bool = False
    checkpoints: bool = True
    allow_commands: list[str] = field(default_factory=list)
    deny_commands: list[str] = field(default_factory=lambda: list(DEFAULT_DENY))
    workspace_only: bool = True
    max_file_read_bytes: int = 512_000
    #: Directories the user has confirmed as a workspace. Exact paths, never
    #: prefixes: approving ~/work/api must not quietly approve ~/work.
    trusted_folders: list[str] = field(default_factory=list)


# Patterns that are never worth running from an agent, however it is prompted.
DEFAULT_DENY: tuple[str, ...] = (
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=", "shutdown", "reboot",
    "format c:", "del /f /s /q c:", ":(){", "> /dev/sda", "chmod -R 777 /",
)

#: Sections that live in the JSON file, in the order they are written.
SECTIONS = ("ui", "agent", "gateway", "learning", "skills", "safety")


@dataclass
class Config:
    provider: str = ""
    model: str = ""
    ui: UIConfig = field(default_factory=UIConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    paths: Paths = field(default_factory=resolve_paths)
    #: True when the user file was missing — the wizard should run.
    first_run: bool = False

    # -- helpers ---------------------------------------------------------- #

    def active(self) -> ProviderConfig | None:
        return self.providers.get(self.provider)

    def available(self) -> list[ProviderConfig]:
        """Providers Comodor is willing to use without being told to."""
        return [entry for entry in self.providers.values() if entry.selectable]

    def configured(self) -> list[ProviderConfig]:
        """Providers the user has set up, whether or not they are selected."""
        return [entry for entry in self.providers.values() if entry.configured]

    def active_model(self) -> str:
        if self.model:
            return self.model
        entry = self.active()
        return entry.model if entry else ""

    @property
    def needs_setup(self) -> bool:
        """Whether there is anything usable at all."""
        return not self.available()

    def use(self, provider_id: str, api_key: str = "", model: str = "",
            base_url: str = "") -> ProviderConfig:
        """Configure a provider and make it the active one."""
        entry = self.providers.get(provider_id)
        if entry is None:
            spec = catalogue.get(provider_id)
            entry = provider_from_spec(spec) if spec else ProviderConfig(name=provider_id)
            self.providers[provider_id] = entry
        if api_key:
            entry.api_key = api_key.strip()
        if base_url:
            entry.base_url = base_url.strip().rstrip("/")
        if model:
            entry.model = model.strip()
        entry.enabled = True
        entry.configured = True
        self.provider = provider_id
        self.model = entry.model
        return entry

    def to_public_dict(self) -> dict[str, Any]:
        """Config with every secret removed — safe to display or export."""
        data = _as_dict(self)
        for entry in data.get("providers", {}).values():
            if entry.get("api_key"):
                entry["api_key"] = "***"
            entry.pop("headers", None)
        data.pop("paths", None)
        return data

    # -- persistence ------------------------------------------------------ #

    def to_json(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "version": CONFIG_VERSION,
            "provider": self.provider,
            "model": self.model,
        }
        for name in SECTIONS:
            document[name] = _as_dict(getattr(self, name))
        document["providers"] = {
            entry.name: entry.to_json()
            for entry in self.providers.values()
            if entry.configured or entry.api_key
        }
        # Not one of SECTIONS: it holds a map of dataclasses rather than flat
        # settings, so the generic reader would flatten it into nonsense.
        document["mcp"] = self.mcp.to_json()
        return document

    def save(self, path: Path | None = None) -> Path:
        """Write the user configuration, readable only by its owner."""
        target = Path(path) if path else self.paths.config_file
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"

        # Written via a temporary file so an interrupted save cannot leave a
        # truncated config behind — losing the API key to a crash mid-write
        # would mean running setup again for no reason.
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        _restrict(temporary)
        temporary.replace(target)
        _restrict(target)
        return target


def _restrict(path: Path) -> None:
    """Owner-only permissions, where the platform has them.

    The file holds API keys. On Windows the user profile is already
    per-account, and chmod has no real meaning, so this is a no-op there.
    """
    if os.name == "nt":
        return
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #


def _as_dict(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _as_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_dict(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _apply(section: Any, values: dict[str, Any]) -> None:
    """Copy known keys onto a dataclass, ignoring unknown ones.

    Unknown keys are tolerated rather than fatal: a config written by a newer
    Comodor should not stop an older one from starting.
    """
    valid = {f.name for f in fields(section)}
    for key, value in values.items():
        if key not in valid:
            continue
        current = getattr(section, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value)
        else:
            setattr(section, key, value)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        # A broken config must never prevent startup; defaults carry the run and
        # `comodor doctor` reports the file as unreadable.
        return {}
    return data if isinstance(data, dict) else {}


def _build_providers() -> dict[str, ProviderConfig]:
    """Start from the catalogue, so every provider is offerable."""
    return {spec.id: provider_from_spec(spec) for spec in catalogue.CATALOGUE}


def _apply_provider_settings(providers: dict[str, ProviderConfig],
                             stored: dict[str, Any]) -> None:
    for name, values in (stored or {}).items():
        if not isinstance(values, dict):
            continue
        entry = providers.get(name)
        if entry is None:
            entry = ProviderConfig(name=name, label=name.title())
            providers[name] = entry
        _apply(entry, values)


def _apply_environment(providers: dict[str, ProviderConfig]) -> None:
    """Environment variables, for CI and containers.

    Never required — the JSON file is the documented path — but a key in the
    environment must win, or a pipeline could not override what a developer's
    machine happens to have saved.
    """
    for spec in catalogue.CATALOGUE:
        entry = providers.get(spec.id)
        if entry is None:
            continue
        key = os.environ.get(spec.env_key, "").strip() if spec.env_key else ""
        endpoint = (os.environ.get(f"{spec.id.upper()}_BASE_URL")
                    or os.environ.get(f"{spec.id.upper()}_ENDPOINT") or "")
        model = os.environ.get(f"{spec.id.upper()}_MODEL", "").strip()
        if key:
            entry.api_key = key
            entry.configured = True
        if endpoint:
            entry.base_url = endpoint.rstrip("/")
            entry.configured = True
        if model:
            entry.model = model


def load(cwd: Path | str | None = None, overrides: dict[str, Any] | None = None,
         use_environment: bool = True) -> Config:
    """Resolve the full configuration for one run."""
    paths = resolve_paths(cwd).ensure()
    config = Config(paths=paths)
    config.providers = _build_providers()

    user_document = _read_json(paths.config_file)
    project_document = _read_json(paths.project_config_file)
    config.first_run = not paths.config_file.exists()

    for document in (user_document, project_document):
        if not document:
            continue
        for name in SECTIONS:
            values = document.get(name)
            if isinstance(values, dict):
                _apply(getattr(config, name), values)
        _apply_provider_settings(config.providers, document.get("providers", {}))
        _apply_mcp(config.mcp, document.get("mcp"))
        if document.get("provider"):
            config.provider = str(document["provider"])
        if document.get("model"):
            config.model = str(document["model"])

    if use_environment:
        _apply_environment(config.providers)
        _apply_environment_sections(config)

    if overrides:
        _apply(config, overrides)

    _choose_active(config)
    return config


def _apply_mcp(settings: MCPConfig, document: Any) -> None:
    """Merge the mcp block. A project may add servers; it may not remove yours."""
    if not isinstance(document, dict):
        return
    if isinstance(document.get("enabled"), bool):
        settings.enabled = document["enabled"]

    for name, values in (document.get("servers") or {}).items():
        if not isinstance(values, dict) or not values.get("command"):
            continue
        settings.servers[str(name)] = MCPServerConfig(
            name=str(name),
            command=str(values["command"]),
            args=[str(item) for item in values.get("args") or []],
            env={str(key): str(value)
                 for key, value in (values.get("env") or {}).items()},
            cwd=str(values.get("cwd") or ""),
            enabled=bool(values.get("enabled")),
            spec=str(values.get("spec") or ""),
        )


def _apply_environment_sections(config: Config) -> None:
    """A couple of settings CI genuinely needs to force."""
    provider = os.environ.get("COMODOR_PROVIDER", "").strip()
    model = os.environ.get("COMODOR_MODEL", "").strip()
    if provider:
        config.provider = provider
    if model:
        config.model = model


def _choose_active(config: Config) -> None:
    """Pick a usable provider, honouring the saved choice when it still works."""
    entry = config.providers.get(config.provider)
    if entry is not None and entry.ready:
        if not config.model:
            config.model = entry.model
        return

    for candidate in config.available():
        config.provider = candidate.name
        config.model = candidate.model
        return

    config.provider = config.provider or ""
    config.model = config.model or ""


def save_user_config(config: Config) -> Path:
    """Kept for callers that read better this way."""
    return config.save()
