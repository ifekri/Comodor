"""Smart approvals: a cheap model's read on a command the tiers can't classify.

The tier system is the fast path and stays exactly where it is: SAFE tools
run, WRITE tools ask, the deny list refuses. But a user running the same
benign-but-unusual shell command fifty times clicks "approve" fifty times,
and click-training is how approvals stop meaning anything.

Smart mode adds one layer between the deny list and the human, and only for
shell commands that would otherwise prompt: a small model is asked what the
command touches and answers allow, deny, or ask. Allow is labeled as the
model's own judgement everywhere the user can see it. Anything it cannot
judge goes to the human, as before. A timeout is a refusal — the same
fail-closed rule every other question in Comodor follows.

Two things the small model is never allowed to do, no matter what mode is
set or what the user allowlisted:

* it cannot rescue a command on the absolute blocklist — `rm -rf /`, fork
  bombs, `mkfs`, `dd` onto a device, `curl | sh`. Those are refused before
  the model is even asked, and the check runs on every branch of a pipeline,
  not just the first;
* it only ever sees the command line. No file contents travel with the
  question, because the assessment must not become the leak it guards
  against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: How long the assessing model gets. A slow verdict is no verdict: past
#: this the question goes to the human, where it was going anyway.
ASSESS_TIMEOUT_SECONDS = 8.0

#: Commands refused outright, before any model sees them and regardless of
#: every allowlist, mode, or smart verdict above them. Substring match on the
#: whitespace-normalised command, like the user deny list.
UNRECOVERABLE: tuple[str, ...] = (
    "rm -rf /", "rm -rf ~", "mkfs", ":(){:|:&};:", "fork bomb",
    "dd if=", "of=/dev/sd", "of=/dev/disk", "of=/dev/nvme",
    "chmod -r 777 /", "chmod 777 /", "> /dev/sda", "> /dev/nvme",
    "| sh", "| bash", "|zsh", "curl | sh", "wget | sh",
    "| sudo sh", "| sudo bash",
    ":(){ :|:& };:", ":(){:|:&};:",
)

#: Split points for deobfuscation. A command is checked branch by branch:
#: `echo safe && rm -rf ~` is one safe branch hiding an unsafe one.
_SPLIT = re.compile(r"&&|\|\||;|\|")


def command_branches(command: str) -> list[str]:
    """The command split into its pipes, sequences and substitutions.

    Command substitution `$(...)` and backticks are kept inline — the text
    inside is part of the branch that contains it, and the blocklist's
    substring match sees it.
    """
    parts = [part.strip() for part in _SPLIT.split(command) if part.strip()]
    return parts or [command.strip()]


def blocked_absolutely(command: str) -> str:
    """The matched blocklist pattern, or "".

    Runs over every branch, and over the raw command too: a pattern split
    across a pipe boundary must not become two safe halves.
    """
    candidates = [command, *command_branches(command)]
    for candidate in candidates:
        haystack = " ".join(candidate.lower().split())
        for pattern in UNRECOVERABLE:
            needle = " ".join(pattern.lower().split())
            if needle and needle in haystack:
                return pattern
    return ""


@dataclass
class Verdict:
    """What the assessing model concluded, with its words for the record."""

    verdict: str                 # allow | deny | ask
    reason: str = ""

    @property
    def labeled(self) -> str:
        """The reason as the user sees it in the audit trail."""
        who = "smart assessment" if self.verdict == "allow" else "assessment"
        return f"{who}: {self.reason or self.verdict}"


ASSESS_PROMPT = """\
You are assessing one shell command for a coding agent to run in the \
user's project directory. Answer with JSON only:
{"verdict": "allow" | "deny" | "ask", "reason": "<one sentence>"}

- allow: clearly safe development work — builds, tests, linters, git \
status/log/diff, package installs, reading files.
- deny: destroys or overwrites data outside obvious build artifacts, \
writes to system paths or credential files, exfiltrates secrets, or \
downloads-and-executes.
- ask: anything you cannot confidently place. An honest "ask" is worth \
more than a lucky guess.

The command may be one line from a longer pipeline; judge what is shown. \
Never allow a command you do not understand."""


def assess(command: str, gateway: Any, model: str = "",
           timeout: float = ASSESS_TIMEOUT_SECONDS) -> Verdict:
    """One model call, one verdict. Failure of any kind is a request to ask.

    The gateway is the session's own. `collapse` returns the full text of a
    stream; a provider error, a malformed answer, or a hang all end the same
    way — the human decides, because a broken assessor is not permission.
    """
    from ..providers.base import Message, collapse

    prompt = (
        f'{ASSESS_PROMPT}\n\nCommand to assess:\n{command}')
    try:
        answer = collapse(gateway.stream(
            [Message.system(prompt), Message.user(command)],
            model=model, temperature=0.0, max_tokens=120,
            timeout=timeout))
        return parse_verdict(answer)
    except Exception:
        return Verdict("ask", "the assessment could not run")


def parse_verdict(text: str) -> Verdict:
    """The model's JSON out of its reply; anything unreadable is `ask`."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return Verdict("ask", "unparseable assessment")
    try:
        import json

        data = json.loads(match.group(0))
    except ValueError:
        return Verdict("ask", "unparseable assessment")
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("allow", "deny", "ask"):
        return Verdict("ask", "assessment gave no usable verdict")
    return Verdict(verdict, str(data.get("reason", ""))[:200])


def make_assessor(config: Any, gateway: Any) -> Any:
    """The callback for ``PermissionEngine.assess``, or None when off.

    Returns None unless smart approvals are switched on and there is a
    gateway to ask. The gate re-checks the blocklist before trusting any
    allow: the assessor sees the command the same way the blocklist does,
    but belt and braces is the correct number of braces for `rm -rf /`.
    """
    if not getattr(config.safety, "smart_approvals", False):
        return None
    if gateway is None:
        return None

    def assess_command(command: str) -> Verdict:
        if blocked_absolutely(command):
            return Verdict("deny", "the command matches the absolute blocklist")
        return assess(command, gateway, model=config.safety.smart_model)

    return assess_command
