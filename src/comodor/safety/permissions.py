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

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

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
    # Set by the app when safety.smart_approvals is on: a callable taking the
    # command line and returning a Verdict. Kept as a callback rather than a
    # gateway reference so the engine stays free of provider plumbing and a
    # test can script verdicts directly.
    assess: Callable[[str], Any] | None = None
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
        up, and a regex would be easier to slip past. Every branch of a
        pipeline is checked — `echo hi && rm -rf ~` is two commands, one of
        which is on the list, and the list is not fooled by which half runs
        first.
        """
        return self._match_command(command, self.config.safety.deny_commands)

    def _match_command(self, command: str, patterns: Any) -> str:
        """The first matched pattern across the whole command and each branch."""
        from .smart import blocked_absolutely, command_branches

        # The absolute blocklist runs over the raw command as well as its
        # branches, so a pattern split across a pipe cannot become two halves.
        # It lives in `smart.py` but it is not part of smart mode: it binds
        # every mode, allowlist and assessor equally.
        absolute = blocked_absolutely(command)
        if absolute:
            return absolute
        for candidate in command_branches(command):
            haystack = " ".join(candidate.lower().split())
            for pattern in patterns:
                needle = " ".join(str(pattern).lower().split())
                if needle and needle in haystack:
                    return str(pattern)
        return ""

    def allowed_command(self, command: str) -> str:
        """The matched allowlist entry, or an empty string.

        The user allowlist is layer three: it approves without a prompt and
        without a model, but only after the deny list has had its say, and
        only for whole command stems (`git` approves `git status` because that
        is the shape an "always allow" in the UI records too).
        """
        from .smart import command_branches

        first = command.split()[0] if command.split() else ""
        if first and first in self.config.safety.allow_commands:
            return first
        for candidate in command_branches(command):
            head = candidate.split()[0] if candidate.split() else ""
            if head and head in self.config.safety.allow_commands:
                return head
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

        # Shell commands carry their own three layers, in order: the deny
        # list (which the tool re-checks at run time too), the user's
        # allowlist, then the smart assessor. The command text rides in the
        # summary or detail; preferring the detail keeps long commands whole.
        if tool == "run_shell":
            command = detail.removeprefix("$ ") if detail.startswith("$ ") \
                else summary.removeprefix("run: ")
            blocked = self.denied_command(command)
            if blocked:
                return Decision(False, f"matches the blocked pattern {blocked!r}")
            if self.allowed_command(command):
                return Decision(True, "allowed by your command allowlist")
            if self.assess is not None:
                verdict = self.assess(command)
                if verdict.verdict == "allow":
                    return Decision(True, verdict.labeled)
                if verdict.verdict == "deny":
                    return Decision(False, verdict.labeled)
                # "ask" — or a timed-out assessment — falls through to the
                # human, which is where the question was going anyway.

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
            if tool == "run_shell":
                self._record(command)
            return Decision(True, "approved for this session", remembered=True)
        if answer == ALLOW:
            if tool == "run_shell":
                self._record(command)
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

    def _record(self, command: str) -> None:
        """Write one human approval to the mining log. Failure is silent:
        the approval stands whether or not the record got written."""
        try:
            path = self.config.paths.approvals
            path.parent.mkdir(parents=True, exist_ok=True)
            record = json.dumps(
                {"at": time.time(), "command": " ".join(command.split())},
                ensure_ascii=False)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(record + "\n")
        except Exception:
            pass

    # -- grants ----------------------------------------------------------- #

    def grant(self, key: str) -> None:
        with self._lock:
            self._session_grants.add(key)

    @property
    def grants(self) -> list[str]:
        with self._lock:
            return sorted(self._session_grants)
