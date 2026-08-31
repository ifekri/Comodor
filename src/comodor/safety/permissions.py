"""Who is allowed to do what, and when to stop and ask.

Three risk tiers drive everything:

``SAFE``       reading, listing, searching — no side effects, never prompts.
``WRITE``      creates or changes files — shows a diff and asks.
``DANGEROUS``  runs commands or reaches the network — always asks.

Mode is the outer gate. **Plan** and **Ask** mode allow only ``SAFE`` tools, so
neither can quietly modify the repository; **Chat** mode allows none at all.

A grant can be given for one call, for the whole session, or written into the
project allowlist. Session grants live in memory only — restarting Comodor puts
the guardrails back up, which is the behaviour people expect from a permission
prompt.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Callable

from ..config import Config
from ..events import EventBus, Request


class Risk(IntEnum):
    SAFE = 0
    WRITE = 1
    DANGEROUS = 2


class Mode(str):
    ACT = "act"
    PLAN = "plan"
    ASK = "ask"
    CHAT = "chat"


ALLOW = "allow"
ALLOW_ALWAYS = "allow_always"
DENY = "deny"


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    remembered: bool = False

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class PermissionEngine:
    """Evaluates every tool call before it runs."""

    config: Config
    bus: EventBus | None = None
    prompt_timeout: float = 600.0
    # Set by the app so a refusal becomes a learned preference, not just a "no".
    on_denied: Callable[[str, str], None] | None = None
    asked: int = 0
    denials: list[tuple[str, str]] = field(default_factory=list)
    _session_grants: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- policy ----------------------------------------------------------- #

    def mode_allows(self, risk: Risk) -> tuple[bool, str]:
        mode = (self.config.agent.mode or Mode.ACT).lower()
        if mode == Mode.CHAT:
            return False, "Chat mode has tools switched off — press F3 to switch to Act."
        if mode in (Mode.PLAN, Mode.ASK) and risk > Risk.SAFE:
            return False, (f"{mode.capitalize()} mode is read-only, so this "
                           "step was skipped. Switch to Act mode to let it run.")
        return True, ""

    def auto_approved(self, risk: Risk) -> bool:
        safety = self.config.safety
        if risk is Risk.SAFE:
            return safety.auto_approve_safe
        if risk is Risk.WRITE:
            return safety.auto_approve_writes
        return safety.auto_approve_shell

    def denied_command(self, command: str) -> str:
        """Return the matched deny pattern, or an empty string.

        Matching is substring-based and case-insensitive on purpose: these are
        the shapes that are never acceptable regardless of how they are dressed
        up, and a regex would be easier to slip past.
        """
        haystack = " ".join(command.lower().split())
        for pattern in self.config.safety.deny_commands:
            needle = " ".join(str(pattern).lower().split())
            if needle and needle in haystack:
                return str(pattern)
        return ""

    def path_allowed(self, path: Path) -> tuple[bool, str]:
        """Keep writes inside the project unless the user opted out."""
        if not self.config.safety.workspace_only:
            return True, ""
        root = self.config.paths.project.resolve()
        try:
            resolved = Path(path).resolve()
        except OSError:
            return False, f"cannot resolve path: {path}"
        if resolved == root or root in resolved.parents:
            return True, ""
        return False, (f"{resolved} is outside the workspace ({root}). "
                       "Set safety.workspace_only = false to allow it.")

    # -- the gate --------------------------------------------------------- #

    def check(self, tool: str, risk: Risk, summary: str, detail: str = "",
              key: str = "") -> Decision:
        """Decide whether one call may proceed, prompting the user if needed."""
        allowed, reason = self.mode_allows(risk)
        if not allowed:
            return Decision(False, reason)

        grant_key = key or tool
        with self._lock:
            if grant_key in self._session_grants:
                return Decision(True, "approved earlier this session", remembered=True)

        if self.auto_approved(risk):
            return Decision(True, "auto-approved by policy")

        if self.bus is None:
            # Headless with no answering surface: refuse rather than assume yes.
            return Decision(False, "no interactive approval available "
                                   "(enable auto-approval in settings for headless runs)")

        request = Request(
            id=f"perm_{uuid.uuid4().hex[:8]}",
            prompt=summary,
            options=[ALLOW, ALLOW_ALWAYS, DENY],
            detail=detail,
            kind="permission",
            meta={"tool": tool, "risk": int(risk)},
        )
        self.asked += 1
        answer = self.bus.ask(request).wait(self.prompt_timeout)

        if answer == ALLOW_ALWAYS:
            with self._lock:
                self._session_grants.add(grant_key)
            return Decision(True, "approved for this session", remembered=True)
        if answer == ALLOW:
            return Decision(True, "approved")

        # A refusal names one thing this user does not want done. It is the
        # clearest preference signal the interface ever collects, so it is
        # handed to the learning engine rather than just returned.
        self.denials.append((tool, summary))
        if self.on_denied is not None:
            try:
                self.on_denied(tool, summary)
            except Exception:
                pass
        return Decision(False, "declined by the user")

    def take_stats(self) -> tuple[int, list[tuple[str, str]]]:
        """Prompts asked and refusals since the last call, then reset."""
        with self._lock:
            asked, denials = self.asked, list(self.denials)
            self.asked, self.denials = 0, []
        return asked, denials

    # -- grants ----------------------------------------------------------- #

    def grant(self, key: str) -> None:
        with self._lock:
            self._session_grants.add(key)

    @property
    def grants(self) -> list[str]:
        with self._lock:
            return sorted(self._session_grants)
