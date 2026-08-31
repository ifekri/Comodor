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
from .paths import Paths
from .paths import resolve as resolve_paths

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
    #: Out of the generated repr on purpose. Any traceback naming a Config
    #: prints one, and pytest prints them on every failure; a key in a bug
    #: report is a key in an issue tracker.
    api_key: str = field(default="", repr=False)
    #: Extra keys for the same provider, forming a pool. `api_key` stays the
    #: canonical first key so every existing reader is unchanged; the pool is
    #: `api_key` plus whatever is listed here, rotated on rate limits. Out of
    #: the repr for the same reason the single key is.
    api_keys: list[str] = field(default_factory=list, repr=False)
    model: str = ""
    label: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout: float = 120.0
    #: True once the user has actually set this provider up. Local runtimes
    #: need no key, so without this Comodor would happily auto-select an Ollama
    #: that is not running and fail with a connection error.
    configured: bool = False

    def __repr__(self) -> str:                     # pragma: no cover - debugging
        """Everything except the key, and whether there is one."""
        inner = ", ".join(f"{f.name}={getattr(self, f.name)!r}"
                          for f in fields(self) if f.repr)
        return f"ProviderConfig({inner}, api_key={'set' if self.api_key else 'unset'})"

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
        if self.api_keys:
            data["api_keys"] = list(self.api_keys)
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
    theme: str = "cyan"
    ascii_borders: bool = False          # for terminals without box-drawing glyphs
    mouse: bool = True
    max_fps: int = 20                    # streaming deltas are coalesced to this
    show_timestamps: bool = False
    sidebar: bool = True
    #: The wordmark at startup. `COMODOR_BANNER=0` switches it off for one run;
    #: this switches it off for good.
    banner: bool = True
    #: Empty means the colour theme picks one that suits it.
    syntax_theme: str = ""


@dataclass
class AgentConfig:
    mode: str = "act"                    # act | plan | ask | chat
    loop: bool = True                    # autonomous multi-step iteration
    #: Steps one task may take. `0` is no limit, and is the default: a
    #: refactor across a dozen files runs out of twenty-four steps mid-thought,
    #: and step count has no relationship to harm - ten steps reading files
    #: cost almost nothing. The ceilings that do map onto harm are the two
    #: below. Set a number here if you want the old behaviour back.
    max_steps: int = 0
    #: Seconds one task may take. `0` is no limit. An hour rather than the
    #: fifteen minutes this used to be: fifteen minutes is an errand.
    max_seconds: float = 3600.0
    #: Dollars one task may spend. `0` is no limit. The ceiling that actually
    #: corresponds to what going wrong costs - where the model has a published
    #: rate. See `doctor`, which says when it cannot be enforced.
    max_cost_usd: float = 2.0
    context_limit: int = 1_000_000       # the "Context: 1M" gauge
    compact_at: float = 0.75             # summarise history past this fraction
    temperature: float = 0.3
    max_output_tokens: int = 8192
    #: Characters one tool result may add to the conversation before the rest
    #: is moved aside. Not a truncation: what does not fit is written to a file
    #: the agent is told how to read, so the cost is bounded and nothing is
    #: lost. Four characters to a token, roughly.
    max_tool_chars: int = 12_000
    #: How many screenshots stay in the history. Each costs its full token
    #: price every turn it remains, and a screen from twenty clicks ago is not
    #: the screen now. Two is enough to compare before with after.
    keep_screenshots: int = 2
    #: Run at the end of any turn that changed a file — your build, your tests,
    #: your type checker. When it fails, the agent is given the output and one
    #: turn to fix it, so "done" comes to mean "done, and the project still
    #: works".
    #:
    #: Empty by default, and deliberately so. Running somebody's whole suite
    #: after every turn is minutes and money they did not ask to spend, and the
    #: right command is different in every project — a guessed one that is slow
    #: or destructive is worse than none. Set it once and it pays for itself.
    verify_command: str = ""
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
    #: The background review of finished turns, which curates the small
    #: facts store (see learning/facts.py). Runs after a turn ends, never
    #: during one; a newer review replaces an in-flight one.
    review: bool = True
    review_model: str = ""               # blank = the active model
    #: On, proposals from the review wait as `staged` until the user
    #: approves them; off, they are written straight in.
    review_write_approval: bool = False
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
class BrowserConfig:
    """The real browser: which one, how large, and whether it is visible."""

    #: Path to a Chrome, Chromium, Edge or Brave. Empty means look in the
    #: usual places. Nothing is ever downloaded.
    executable: str = ""
    #: Headless is the default because an agent browsing should not steal
    #: focus; turn it off to watch what it is doing.
    headless: bool = True
    width: int = 1280
    height: int = 800
    #: A DevTools port of a browser you started yourself. Set this to use one
    #: you are already logged into, rather than handing over your own profile.
    port: int = 0


@dataclass
class ComputerConfig:
    """Driving the screen, the mouse and the keyboard.

    Off until switched on here, and then still not allowed until granted: this
    only decides whether the tool is offered to the model at all. The grant -
    how long, over what - is asked for at the moment it is needed and is never
    written to a file.
    """

    #: Whether the model is offered the tool. Off by default, and deliberately
    #: not something a first run turns on for you.
    enabled: bool = False
    #: What one screenshot may cost. The dial between legibility and price:
    #: 1600 is readable on every screen tried, 700 is cheap and readable on a
    #: laptop, 4784 is the most the model will accept.
    screenshot_tokens: int = 1600
    #: Seconds a grant lasts when the answer is the plain one.
    grant_seconds: int = 900
    #: How long the pointer takes to travel, in seconds. The reason a person
    #: can see where it is going and stop it; 0 would work and be unwatchable.
    travel_seconds: float = 0.32
    #: Draw the halo, the trail and the caption on screen. Off only for a
    #: machine nobody is sitting at.
    overlay: bool = True
    #: Extra window titles never to touch, on top of the built-in list.
    never: list[str] = field(default_factory=list)


@dataclass
class SkillsConfig:
    """Authored skills: instructions the user writes once and reuses."""

    enabled: bool = True
    #: How many matching skills may be injected into one turn.
    top_k: int = 2
    #: Tokens one turn may spend on skills.
    #:
    #: This was 1,200, which is the size of the sample skill and nothing else.
    #: Real authored skills — a design system, a review procedure — run from
    #: two to ten thousand, so the budget quietly discarded almost every skill
    #: in the published library: matched, correct, never sent. Twelve thousand
    #: admits any single one of them; a second large skill in the same turn is
    #: still refused, and now says so rather than vanishing.
    max_tokens: int = 12_000
    #: Skills present on disk that are not to be used, by name.
    #:
    #: Off rather than gone. A skill folder may have been written by hand over
    #: an afternoon, and "I do not want this one just now" is a different
    #: request from "delete this".
    disabled: list[str] = field(default_factory=list)
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
    """One Model Context Protocol server the user has added.

    Either a `command` to launch or a `url` to reach. The interesting servers
    are increasingly the second kind — hosted, shared by a team, holding
    credentials nobody wants on a laptop — and the difference stops at the
    transport: the same tools arrive, under the same permission gate.
    """

    name: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    #: A Streamable HTTP endpoint, when this server is not a process.
    url: str = ""
    #: Sent as `Authorization: Bearer`. Kept apart from `headers` so it can be
    #: read from the environment and never written to the config file.
    token: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    #: Working directory for the process; empty means the project root.
    cwd: str = ""
    enabled: bool = False
    #: The catalogue entry it came from, when it came from one.
    spec: str = ""

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"enabled": self.enabled}
        if self.url:
            data["url"] = self.url
        else:
            data["command"] = self.command
        if self.headers:
            data["headers"] = dict(self.headers)
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
class TelegramConfig:
    """Reaching the agent from a phone.

    This is a remote control for a machine that edits files and runs commands,
    which makes the two fields below the most consequential settings in this
    file. They are deliberately awkward to set by accident:

    `token` is empty until somebody pastes one, and `allowed` is empty until
    somebody completes a pairing from the terminal. A bot with a token and no
    allowed accounts answers nobody — which is the right thing for it to do,
    because a Telegram bot's address is public and anyone who guesses the
    username can message it.
    """

    enabled: bool = False
    #: From BotFather. Kept here rather than in an environment variable so it
    #: survives a reboot the same way every other credential does.
    token: str = ""
    #: Numeric Telegram user ids that may talk to it. Not usernames: a username
    #: can be given up and taken by somebody else, an id cannot.
    allowed: list[int] = field(default_factory=list)
    #: Whether a turn started from Telegram may edit files and run commands.
    #: Off means the bot is confined to plan and chat however the terminal is
    #: set, because approving a shell command on a phone is a tap made with
    #: less attention than the same approval at a keyboard.
    allow_writes: bool = False
    #: Seconds a pairing code stays valid.
    pair_window: int = 300

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "token": self.token,
            "allowed": list(self.allowed),
            "allow_writes": self.allow_writes,
            "pair_window": self.pair_window,
        }

    def may(self, user_id: int) -> bool:
        return bool(user_id) and int(user_id) in {int(x) for x in self.allowed}


@dataclass
class WhatsAppConfig:
    """The same thing through WhatsApp, which is a different shape.

    Telegram hands you one token and lets you long-poll for messages. WhatsApp
    is Meta's Cloud API: a token *and* a phone number id to send from, and
    inbound messages arrive as webhooks — Meta posts them to a URL, which means
    something of yours has to be reachable from the internet. There is no
    polling equivalent, so the fields below carry a webhook's worth of settings
    that Telegram simply does not need.

    Same rule about who it answers, for the same reason and more sharply: a
    WhatsApp business number is a phone number, and phone numbers get messaged
    by strangers all day. `allowed` holds the wa_ids that get a reply, and
    everybody else gets silence.
    """

    enabled: bool = False
    #: A permanent access token from a Meta system user. Temporary tokens from
    #: the app dashboard expire in twenty-four hours, which is long enough to
    #: finish setting it up and short enough to look like a bug the next day.
    token: str = ""
    #: Which of the business account's numbers to send from. Not the number
    #: itself: Meta addresses it by id.
    phone_number_id: str = ""
    #: The app secret, used to check the signature on every webhook. Without it
    #: anything that can reach the endpoint can impersonate Meta.
    app_secret: str = ""
    #: The string echoed back during Meta's one-time endpoint verification.
    #: Generated rather than chosen, because it is a shared secret and people
    #: choose badly.
    verify_token: str = ""
    #: wa_ids — a phone number in full international form, no `+`, no spaces.
    allowed: list[str] = field(default_factory=list)
    #: Whether a turn started from WhatsApp may edit files and run commands.
    allow_writes: bool = False
    #: Seconds a pairing code stays valid.
    pair_window: int = 300
    #: Where the webhook listens. Bound to localhost: this is meant to sit
    #: behind a tunnel or a reverse proxy that terminates TLS, because Meta
    #: will only deliver to HTTPS and will not deliver to a self-signed
    #: certificate.
    host: str = "127.0.0.1"
    port: int = 8770
    #: The path Meta posts to.
    path: str = "/whatsapp"
    #: The public HTTPS address of that path, for the dashboard. Remembered so
    #: `comodor whatsapp status` can print the thing you have to paste.
    public_url: str = ""
    #: Which Graph API version to call. Pinned, because Meta deprecates
    #: versions on a schedule and a floating version breaks on their calendar
    #: rather than on yours.
    api_version: str = "v21.0"

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "token": self.token,
            "phone_number_id": self.phone_number_id,
            "app_secret": self.app_secret,
            "verify_token": self.verify_token,
            "allowed": list(self.allowed),
            "allow_writes": self.allow_writes,
            "pair_window": self.pair_window,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "public_url": self.public_url,
            "api_version": self.api_version,
        }

    def may(self, wa_id: str) -> bool:
        """Whether this number gets an answer.

        Compared as digits. The same number reaches us written `+9715…`,
        `009715…` and `9715…` depending on where it came from, and three
        spellings of one person is three people to a naive comparison.
        """
        wanted = _digits(wa_id)
        return bool(wanted) and wanted in {_digits(x) for x in self.allowed}


def _digits(value: Any) -> str:
    """A phone number reduced to the digits, with a leading 00 dropped."""
    kept = "".join(char for char in str(value or "") if char.isdigit())
    return kept[2:] if kept.startswith("00") else kept


@dataclass
class SlackConfig:
    """Reaching the agent from a Slack workspace.

    Two tokens, because Slack has two kinds. The *bot* token does everything
    the bot does in the workspace; the *app-level* token does one thing —
    open the websocket Socket Mode runs on — and that is what keeps this
    channel as easy to set up as Telegram. Slack's other delivery method posts
    to a URL and would need a public HTTPS address, a certificate and a tunnel,
    which is the whole of what makes WhatsApp hard.

    A workspace can have hundreds of people in it, and this is an agent that
    reads and writes somebody's files. `allowed` holds the Slack user ids it
    answers; everybody else is ignored.
    """

    enabled: bool = False
    #: `xoxb-…`, from OAuth & Permissions after the app is installed.
    bot_token: str = ""
    #: `xapp-…`, from Basic Information → App-Level Tokens, scope
    #: `connections:write`. Only ever used to open the socket.
    app_token: str = ""
    #: Slack user ids — `U…` or `W…`. Not display names: a display name can be
    #: changed by the person holding it, and an id cannot.
    allowed: list[str] = field(default_factory=list)
    #: Whether a turn started from Slack may edit files and run commands.
    allow_writes: bool = False
    #: Seconds a pairing code stays valid.
    pair_window: int = 300
    #: The workspace it was connected to, remembered so `status` can name it
    #: without a round trip.
    team: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "bot_token": self.bot_token,
            "app_token": self.app_token,
            "allowed": list(self.allowed),
            "allow_writes": self.allow_writes,
            "pair_window": self.pair_window,
            "team": self.team,
        }

    def may(self, user_id: str) -> bool:
        return bool(user_id) and str(user_id) in {str(x) for x in self.allowed}


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
class DelegationConfig:
    """Background delegates: how many at once, and what one may hold."""

    #: Slots for delegates running alongside the parent's own turn. When all
    #: are busy a new background request is refused, not queued — a pile of
    #: half-finished children no one is watching is cost with no oversight.
    max_background: int = 3
    #: Characters of a finished delegate's answer that reach the parent's
    #: conversation inline. The rest is moved aside by the usual overflow
    #: rule, which is transfer rather than deletion.
    completion_summary_max: int = 24_000
    #: Seconds between progress checks on each running delegate.
    stall_check_seconds: float = 30.0

@dataclass
class MediaConfig:
    """Files sent in from the channels: voice notes, images, documents.

    Everything arrives in one managed directory, typed by its own bytes and
    never executed. A file nobody can read — an image sent to a model without
    vision, a voice note with no transcription — is kept and its path offered,
    not quietly discarded.
    """

    enabled: bool = True
    #: Ceiling per download. The adapters cap what they fetch; this catches
    #: whatever slips past them.
    max_download_mb: float = 25.0
    #: Transcribe voice notes. Needs a transcription setting; without one a
    #: voice note is answered with a line saying so rather than silence.
    voice_to_text: bool = True
    #: Send images to models that have vision. Without it the image is saved
    #: and its path handed to the model as a file to read with tools.
    images_to_vision: bool = True
    #: Where downloads land, under the user's own directory. Sessions share
    #: it; names are content-hashed, so the same photo twice costs nothing.
    save_dir: str = ""                    # blank = <user>/media

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_download_mb": self.max_download_mb,
            "voice_to_text": self.voice_to_text,
            "images_to_vision": self.images_to_vision,
            "save_dir": self.save_dir,
        }


@dataclass
class CronConfig:
    """Scheduled agent runs.

    Everything here is conservative by default: the scheduler is off until it
    is asked for, and a job that keeps failing stops being trusted after a few
    tries rather than failing forever in the background.
    """

    enabled: bool = False
    #: Blank = whatever model the session that adds the job was using. A
    #: pinned model that is unavailable fails the run — never a silent
    #: fallback to a different one, because a task run on a model the user
    #: did not choose is a task run at an unknown cost.
    model: str = ""
    #: Minutes after the fire time a missed job may still run. A laptop waking
    #: from sleep fires everything it slept through once, late — not never.
    misfire_grace_minutes: int = 10
    #: Consecutive failures before a job is auto-paused.
    failure_streak: int = 3
    #: How many agent turns the scheduler may run at once.
    max_concurrency: int = 2

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "model": self.model,
            "misfire_grace_minutes": self.misfire_grace_minutes,
            "failure_streak": self.failure_streak,
            "max_concurrency": self.max_concurrency,
        }


@dataclass
class ShellConfig:
    """Where shell commands run: this machine, a container, or another box.

    The backend is a project setting on purpose — a repository can pin the
    container its tests need — but everything here is on the host-settable
    list only in the directions that cannot hurt a fresh clone: a project may
    name an image, never point the agent at an SSH box or turn hardening off.
    """

    backend: str = "host"                 # host | docker | ssh
    #: Docker: the image commands run in. Pulled on first use.
    docker_image: str = "python:3.13-slim"
    #: Mount the project into the container. Read-only by default; read-write
    #: is the choice that makes checkpoints and verify see host files.
    docker_mount: str = "ro"              # "" | ro | rw
    #: Hardened invocation (no capabilities, no new privileges, capped
    #: processes). Auto-approval refuses to run a container without it.
    docker_harden: bool = True
    #: SSH: where to connect. The key is read from ~/.ssh and never copied.
    ssh_host: str = ""
    ssh_user: str = ""
    ssh_port: int = 22
    ssh_key_path: str = ""
    #: Seconds before a remote command is killed. Long enough for a test
    #: suite, short enough that a dead network does not hang the turn.
    timeout: float = 180.0

    def to_json(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "docker_image": self.docker_image,
            "docker_mount": self.docker_mount,
            "docker_harden": self.docker_harden,
            "ssh_host": self.ssh_host,
            "ssh_user": self.ssh_user,
            "ssh_port": self.ssh_port,
            "ssh_key_path": self.ssh_key_path,
            "timeout": self.timeout,
        }

@dataclass
class SafetyConfig:
    auto_approve_safe: bool = True       # read-only tools never prompt
    auto_approve_writes: bool = False
    auto_approve_shell: bool = False
    checkpoints: bool = True
    #: Parse a file after writing it and tell the model what it broke, in the
    #: same tool result. It costs microseconds for Python, JSON and TOML — they
    #: are parsed in this process — and it never refuses a write, so the worst
    #: it can do is add a line the model did not need. Off is for somebody
    #: editing a dialect our parsers do not know.
    verify_edits: bool = True
    #: Commands auto-approved without a prompt, matched per branch after the
    #: deny list has refused. The first token is what an "always allow" in the
    #: UI grants, so `git` here approves `git status`, `git log` and every
    #: other git subcommand — write one line per command stem.
    allow_commands: list[str] = field(default_factory=list)
    deny_commands: list[str] = field(default_factory=lambda: list(DEFAULT_DENY))
    #: Smart approvals, off by default. When on, a shell command that would
    #: otherwise prompt is first shown to a cheap model for a risk read:
    #: allow runs it (labeled as the model's call), deny refuses, ask sends it
    #: to the human as before. A slow or broken assessment is an "ask", never
    #: a yes.
    smart_approvals: bool = False
    #: The model the assessment runs on. Empty means the session's current
    #: provider default; name something small and fast — this is a
    #: classification job, not a reasoning one.
    smart_model: str = ""
    workspace_only: bool = True
    max_file_read_bytes: int = 512_000
    #: How large a file `read_file` will scan to find the lines asked for. It
    #: streams, so this bounds time rather than memory, and it is far above the
    #: read limit on purpose: a slice of a large log has to be reachable, or
    #: the advice to take one is advice that cannot be followed.
    max_file_scan_bytes: int = 64_000_000
    #: Directories the user has confirmed as a workspace. Exact paths, never
    #: prefixes: approving ~/work/api must not quietly approve ~/work.
    trusted_folders: list[str] = field(default_factory=list)
    #: Whether the model's URL tools may reach this machine's own loopback.
    #: Comodor runs a web server of its own, and a user whose dev server is
    #: on localhost can open this per-project; the default stays closed
    #: because a cloud VM's loopback holds internal services the model has no
    #: business summarising.
    ssrf_allow_loopback: bool = False
    #: URLs the tools may always open, guard aside. Prefix matching: the user
    #: wrote the rule, the rule says what it trusts.
    ssrf_allowlist: list[str] = field(default_factory=list)


# Patterns that are never worth running from an agent, however it is prompted.
DEFAULT_DENY: tuple[str, ...] = (
    "rm -rf /", "rm -rf ~", "mkfs", "dd if=", "shutdown", "reboot",
    "format c:", "del /f /s /q c:", ":(){", "> /dev/sda", "chmod -R 777 /",
)

#: Sections that live in the JSON file, in the order they are written.
#: The sections `load` applies and `save` writes. A dataclass on `Config` that
#: is not named here is silently ignored - which is what happened to `browser`
#: for its whole existence: `headless: false` in a config file did nothing and
#: said nothing.
SECTIONS = ("ui", "agent", "gateway", "learning", "skills", "safety",
            "browser", "computer", "telegram", "whatsapp", "slack", "cron",
            "media", "delegation", "shell")


@dataclass
class Config:
    provider: str = ""
    model: str = ""
    ui: UIConfig = field(default_factory=UIConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    computer: ComputerConfig = field(default_factory=ComputerConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    cron: CronConfig = field(default_factory=CronConfig)
    media: MediaConfig = field(default_factory=MediaConfig)
    delegation: DelegationConfig = field(default_factory=DelegationConfig)
    shell: ShellConfig = field(default_factory=ShellConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    paths: Paths = field(default_factory=resolve_paths)
    #: True when the user file was missing — the wizard should run.
    first_run: bool = False
    #: The user's own file, as a document, before anything else was merged in.
    #: What `save` falls back to for a value that came from somewhere else.
    _mine: dict[str, Any] = field(default_factory=dict, repr=False)
    #: Dotted path -> the value a borrowed layer supplied, recorded at load.
    #: A value that still matches is one the user has not chosen for themselves.
    _borrowed: dict[str, Any] = field(default_factory=dict, repr=False)
    #: Keys a project's own config file asked for and was not allowed to set.
    #: Kept so the interface can say so: silently ignoring somebody's file is
    #: its own kind of unhelpful.
    project_refused: list[str] = field(default_factory=list)
    #: Settings that were the wrong type and were left at their default.
    complaints: list[str] = field(default_factory=list)
    #: What the closing question of `comodor setup` was answered with —
    #: `interface`, `telegram`, `both` or `nothing`. Held here rather than
    #: returned separately so the wizard can answer it and the command line can
    #: act on the half it owns. Never written to the config file: it is about
    #: one run, not about how this machine is set up.
    start_after_setup: str = field(default="nothing", repr=False)

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

    def mine_only(self) -> dict[str, Any]:
        """The document to write: this configuration, minus what it borrowed.

        A repository's `.comodor/config.json`, the environment and the command
        line all merge into the object the agent runs on. Writing that object
        into the user's own file would make a cloned repository's spend ceiling
        their permanent default, and would copy an API key they kept in their
        environment onto disk.

        A borrowed value that is still exactly what the borrowed layer supplied
        goes back to whatever their own file said. A value they changed during
        the session -- `/model`, `/approve`, the setup wizard -- is their own
        choice and is written.
        """
        document = self.to_json()

        # Objects their file never held at all are settled whole. Restoring
        # one value at a time inside such an object can leave half of it: an
        # MCP server a repository named, switched on and saved, kept the
        # `enabled` they changed and dropped the command they did not.
        settled: set[str] = set()
        for path in _adopted_wholesale(document, self._mine):
            here = {dotted: value for dotted, value in _leaves(document).items()
                    if _under(path, dotted)}
            lent = {dotted: value for dotted, value in self._borrowed.items()
                    if _under(path, dotted)}
            settled.update(here)
            settled.update(lent)
            if here == lent:              # untouched: none of it is theirs
                _put(document, path.split("."), None, keep=False)

        for dotted, lent in self._borrowed.items():
            if dotted in settled:
                continue
            steps = dotted.split(".")
            if _leaf(document, steps) != lent:
                continue                  # changed since: the user means it
            was, had = _leaf(self._mine, steps, missing=_ABSENT), True
            if was is _ABSENT:
                was, had = None, False
            _put(document, steps, was, keep=had)
        return document

    def save(self, path: Path | None = None) -> Path:
        """Write the user configuration, readable only by its owner."""
        target = Path(path) if path else self.paths.config_file
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.mine_only(), indent=2, ensure_ascii=False) + "\n"

        # Written via a temporary file so an interrupted save cannot leave a
        # truncated config behind — losing the API key to a crash mid-write
        # would mean running setup again for no reason.
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        _restrict(temporary)
        temporary.replace(target)
        _restrict(target)
        return target


class _Absent:
    """Distinguishes "their file said null" from "their file did not say"."""

    def __repr__(self) -> str:                    # pragma: no cover - debugging
        return "<absent>"


_ABSENT = _Absent()


def _leaves(document: Any, prefix: str = "") -> dict[str, Any]:
    """Every scalar in a document, by dotted path.

    A list is a leaf: half-merging one produces something nobody wrote.
    """
    found: dict[str, Any] = {}
    if isinstance(document, dict):
        for key, value in document.items():
            found.update(_leaves(value, f"{prefix}.{key}" if prefix else str(key)))
    elif prefix:
        found[prefix] = document
    return found


def _under(prefix: str, dotted: str) -> bool:
    return dotted == prefix or dotted.startswith(prefix + ".")


def _adopted_wholesale(document: Any, mine: Any, prefix: str = "") -> list[str]:
    """The largest objects in `document` that `mine` does not have at all.

    Descent stops at the first missing one: if their file has never heard of
    `mcp.servers.files`, nothing inside it is theirs either, and the decision
    belongs to the whole entry rather than to each of its values.
    """
    found: list[str] = []
    if not isinstance(document, dict):
        return found
    for key, value in document.items():
        if not isinstance(value, dict):
            continue
        here = f"{prefix}.{key}" if prefix else str(key)
        theirs = mine.get(key) if isinstance(mine, dict) else None
        if not isinstance(theirs, dict):
            found.append(here)
        else:
            found.extend(_adopted_wholesale(value, theirs, here))
    return found


def _leaf(document: Any, steps: list[str], missing: Any = None) -> Any:
    for step in steps:
        if not isinstance(document, dict) or step not in document:
            return missing
        document = document[step]
    return document


def _put(document: Any, steps: list[str], value: Any, keep: bool) -> None:
    """Restore a value their file had, or remove one it never mentioned."""
    for step in steps[:-1]:
        if not isinstance(document, dict) or step not in document:
            return
        document = document[step]
    if not isinstance(document, dict):
        return
    if keep:
        document[steps[-1]] = value
    else:
        document.pop(steps[-1], None)


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
        # Underscored fields are bookkeeping, not settings. `_mine` in
        # particular holds a second copy of the user's document -- API key
        # included -- and `to_public_dict` masks the key it knows about, not
        # one nested inside a field it has never heard of.
        return {f.name: _as_dict(getattr(obj, f.name))
                for f in fields(obj) if not f.name.startswith("_")}
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_dict(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


#: What a project's own `.comodor/config.json` is allowed to set.
#:
#: An allow-list, because this file comes from a repository the user has just
#: cloned and has not read. Everything here is something a team might
#: reasonably pin and nothing here can be turned against the person who cloned
#: it: which model, what mode, the budgets, how it looks.
#:
#: Everything else is refused with a notice — in particular anything under
#: `providers` (the address a key is sent to), anything under `safety` (the
#: boundary and the deny list), `mcp` (process execution) and
#: `agent.system_prompt_extra` (instructions in the user's name).
PROJECT_SETTABLE: dict[str, frozenset[str] | None] = {
    "provider": None,
    "model": None,
    "ui": frozenset({"theme", "ascii_borders", "syntax_theme", "show_timestamps",
                     "sidebar", "banner", "max_fps", "mouse"}),
    "agent": frozenset({"mode", "loop", "max_steps", "max_seconds", "max_cost_usd",
                        "context_limit", "compact_at", "temperature",
                        "max_output_tokens", "max_tool_chars",
                        "keep_screenshots"}),
    "learning": frozenset({"enabled", "reflect", "top_k", "max_playbook_tokens"}),
    "skills": frozenset({"enabled", "top_k", "max_tokens"}),
    # A repository may say which image its commands run in — that is what a
    # Dockerfile is, in another accent. It may not choose the backend itself,
    # point the agent at a remote box, or turn the container's hardening off:
    # those are the user's, because they say where the user's machine spends
    # its trust.
    "shell": frozenset({"docker_image", "docker_mount"}),
    # Servers only, and they arrive switched off — a project saying what it
    # uses is useful; a project starting a process is not its decision. The
    # master switch is deliberately absent.
    "mcp": frozenset({"servers"}),
    # `browser`, `computer`, `telegram`, `whatsapp` and `slack` are
    # deliberately absent,
    # and this is the note for whoever is tempted to add them. A project that
    # could set `browser.executable` names a binary for the agent to launch.
    # One that could set `computer.enabled` asks the machine it was just cloned
    # onto for its mouse and keyboard. One that could set `telegram.allowed` or
    # `whatsapp.allowed` or `slack.allowed` adds its author to the list of
    # people who may drive that machine from a phone — and unlike the other
    # two, nothing on screen would ever show it happening. None of the five
    # belongs to a repository.
}


def project_filtered(document: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """A project document reduced to what a project may set, and what was dropped."""
    kept: dict[str, Any] = {}
    refused: list[str] = []

    for key, value in document.items():
        if key not in PROJECT_SETTABLE:
            refused.append(key)
            continue
        allowed = PROJECT_SETTABLE[key]
        if allowed is None:
            kept[key] = value
            continue
        if not isinstance(value, dict):
            refused.append(key)
            continue
        inner = {name: item for name, item in value.items() if name in allowed}
        refused.extend(f"{key}.{name}" for name in value if name not in allowed)
        if inner:
            kept[key] = inner
    return kept, refused


def _coerce(key: str, value: Any, current: Any) -> tuple[bool, Any, str]:
    """Make a value match the type of the setting, or refuse it.

    Returns ``(ok, value, why)``. Coercion is done only where it is
    unambiguous: `1` is a fine float, and `"1"` is a fine int in a file typed
    by hand. `"yes"` is not a bool, because `"false"` is also not one and
    guessing there gets it exactly backwards.
    """
    if value is None:
        return False, None, "is null"
    if current is None:
        return True, value, ""

    wanted = type(current)
    if wanted is bool:
        if isinstance(value, bool):
            return True, value, ""
        return False, None, "must be true or false"
    if isinstance(value, bool):
        return False, None, f"must be {wanted.__name__}, not true/false"
    if wanted is int:
        if isinstance(value, int):
            return True, value, ""
        if isinstance(value, float) and value.is_integer():
            return True, int(value), ""
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return True, int(value), ""
        return False, None, "must be a whole number"
    if wanted is float:
        if isinstance(value, (int, float)):
            return True, float(value), ""
        if isinstance(value, str):
            try:
                return True, float(value), ""
            except ValueError:
                return False, None, "must be a number"
        return False, None, "must be a number"
    if wanted is str:
        if isinstance(value, str):
            return True, value, ""
        return False, None, "must be text"
    if wanted in (list, tuple):
        if isinstance(value, list):
            return True, value, ""
        return False, None, "must be a list"
    if wanted is dict:
        if isinstance(value, dict):
            return True, value, ""
        return False, None, "must be an object"
    return True, value, ""

def _apply(section: Any, values: dict[str, Any], where: str = "",
           complaints: list[str] | None = None) -> None:
    """Copy known keys onto a dataclass, ignoring unknown ones.

    Unknown keys are tolerated rather than fatal: a config written by a newer
    Comodor should not stop an older one from starting.

    A key of the wrong type is *not* tolerated, and that is the difference
    between a setting that does nothing and one that breaks an hour later:
    `"max_steps": "lots"` used to be stored as the string and raise a
    TypeError in the middle of a task, and `"loop": "false"` used to be stored
    as a string that is true.
    """
    valid = {f.name for f in fields(section)}
    for key, value in values.items():
        if key not in valid:
            continue
        current = getattr(section, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value, f"{where}{key}.", complaints)
            continue
        ok, coerced, why = _coerce(key, value, current)
        if not ok:
            if complaints is not None:
                complaints.append(f"{where}{key} {why}; keeping {current!r}")
            continue
        setattr(section, key, coerced)


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
        # Additional keys from the environment: OPENROUTER_API_KEY_2 and up
        # join the pool. Numbered suffixes stop at the first gap, so a stray
        # _4 does not invent a key that was never exported.
        extra: list[str] = list(entry.api_keys)
        for number in range(2, 100):
            found = os.environ.get(f"{spec.env_key}_{number}", "").strip() \
                if spec.env_key else ""
            if not found:
                break
            if found not in extra:
                extra.append(found)
        if extra and extra != entry.api_keys:
            entry.api_keys = extra
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

    # The project's file arrived with a repository and is read before anybody
    # has looked at it, so it may only set what cannot be turned against the
    # person who cloned it. The user's own file is theirs and is trusted.
    if project_document:
        project_document, refused = project_filtered(project_document)
        config.project_refused = refused

    # What their own file alone produces. Recorded before anything else is
    # merged in, because `save` has to be able to put a borrowed value back to
    # whatever they themselves had.
    mine = Config(paths=paths)
    mine.providers = _build_providers()
    if user_document:
        _apply_user_layer(mine, user_document)
    # The same derived correction the real configuration gets. Without it, a
    # saved provider that no longer exists reads as borrowed - `_choose_active`
    # replaced it, and the merged document no longer matches their file - so
    # `doctor --fix` would repair it in memory and then write the broken name
    # back out. Correcting the baseline the same way makes the two agree, and
    # leaves genuinely borrowed choices (a provider picked only because the
    # environment supplied its key) still borrowed.
    _choose_active(mine)
    config._mine = mine.to_json()

    for document, trusted in ((user_document, True), (project_document, False)):
        if not document:
            continue
        for name in SECTIONS:
            values = document.get(name)
            if isinstance(values, dict):
                _apply(getattr(config, name), values, f"{name}.",
                       config.complaints)
        if trusted:
            _apply_provider_settings(config.providers,
                                     document.get("providers", {}))
        # A project may say which servers it uses; they arrive switched off.
        _apply_mcp(config.mcp, document.get("mcp"), trusted=trusted)
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

    # Everything the merged configuration says that their own file did not.
    # `save` uses this to tell a setting they chose from one a repository, the
    # environment or a flag happened to supply.
    theirs = _leaves(config._mine)
    config._borrowed = {dotted: value
                        for dotted, value in _leaves(config.to_json()).items()
                        if dotted not in theirs or theirs[dotted] != value}
    return config


def _apply_user_layer(config: Config, document: dict[str, Any]) -> None:
    """The user's own file, applied on its own, with nothing merged over it."""
    for name in SECTIONS:
        values = document.get(name)
        if isinstance(values, dict):
            _apply(getattr(config, name), values, f"{name}.", [])
    _apply_provider_settings(config.providers, document.get("providers", {}))
    _apply_mcp(config.mcp, document.get("mcp"), trusted=True)
    if document.get("provider"):
        config.provider = str(document["provider"])
    if document.get("model"):
        config.model = str(document["model"])


def _apply_mcp(settings: MCPConfig, document: Any, trusted: bool = True) -> None:
    """Merge the mcp block. A project may add servers; it may not remove yours.

    Nor may it start them. An MCP server entry is a command, its arguments and
    its environment, so a repository that could arrive with one already enabled
    could run anything on the machine of whoever cloned it. Untrusted entries
    land switched off and are listed, which keeps the useful half of the
    feature — a project saying what it needs — and gives the decision to the
    person whose machine it is.
    """
    if not isinstance(document, dict):
        return
    # The master switch is never a project's to throw.
    if trusted and isinstance(document.get("enabled"), bool):
        settings.enabled = document["enabled"]

    for name, values in (document.get("servers") or {}).items():
        if not isinstance(values, dict):
            continue
        if not values.get("command") and not values.get("url"):
            continue
        # A project's suggestion arrives switched off, whatever it asked for.
        wanted = bool(values.get("enabled")) if trusted else False
        settings.servers[str(name)] = MCPServerConfig(
            name=str(name),
            command=str(values.get("command") or ""),
            url=str(values.get("url") or ""),
            token=str(values.get("token") or ""),
            headers={str(key): str(value)
                     for key, value in (values.get("headers") or {}).items()},
            args=[str(item) for item in values.get("args") or []],
            env={str(key): str(value)
                 for key, value in (values.get("env") or {}).items()},
            cwd=str(values.get("cwd") or ""),
            enabled=wanted,
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


def unenforceable_budget(config: Config) -> str:
    """Why the spend ceiling cannot fire, or empty when it can.

    Here rather than in either caller, because `doctor` and the interface both
    have to answer it and an answer that drifts between the two is worse than
    one place getting it wrong.
    """
    limit = config.agent.max_cost_usd
    model = config.active_model()
    if not limit or not model:
        return ""
    entry = config.active()
    if entry is not None and entry.local:
        return ""                          # runs on their machine; costs nothing

    from .providers import registry

    if registry.lookup(model).priced:
        return ""
    return (f"the ${limit:.2f} spend limit cannot be enforced for {model} - "
            f"no published rate is known, so the cost meter reads zero. "
            f"The step and time limits still apply.")


def save_user_config(config: Config) -> Path:
    """Kept for callers that read better this way."""
    return config.save()
