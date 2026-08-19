"""Keep secrets out of anything that gets rendered, logged, or exported.

The agent reads ``.env`` files, runs commands that echo tokens, and writes
transcripts to disk. Every one of those paths passes through here first. The
patterns cover the common key shapes plus anything that *looks* assigned to a
secret-ish name, because new providers invent new prefixes constantly.
"""

from __future__ import annotations

import re
from typing import Iterable

MASK = "***REDACTED***"

# Well-known credential shapes.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),          # Anthropic
    re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),           # OpenRouter
    re.compile(r"sk-[A-Za-z0-9]{32,}"),                 # OpenAI-style
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),                # Groq
    re.compile(r"tp-[A-Za-z0-9]{30,}"),                 # Xiaomi token-plan
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),                # GitHub
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),                    # AWS access key id
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),             # Google
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),       # Slack
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
)

# `SECRET_NAME = value` in env files, TOML, YAML, shell exports and JSON.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(
        [A-Za-z0-9_\-]*
        (?: api[_\-]?key | secret | password | passwd | token | credential
          | private[_\-]?key | access[_\-]?key | auth )
        [A-Za-z0-9_\-]*
    )
    \s* [:=] \s*
    (["']?)([^\s"',;]{8,})\2
    """
)


def _mask_assignment(match: re.Match[str]) -> str:
    name, quote, value = match.group(1), match.group(2), match.group(3)
    if value.lower() in ("none", "null", "true", "false", "changeme", ""):
        return match.group(0)
    if MASK in value:
        return match.group(0)            # a pattern rule already masked it
    keep = value[:3] if len(value) > 12 else ""
    return f"{name}={quote}{keep}{MASK}{quote}"


def redact(text: str, extra: Iterable[str] = ()) -> str:
    """Mask credentials in ``text``.

    ``extra`` holds values we already know are secret — the API keys of the
    running session — so even an unusual key format never reaches the screen.
    """
    if not text:
        return text

    for secret in extra:
        if secret and len(secret) >= 8:
            text = text.replace(secret, MASK)

    for pattern in _PATTERNS:
        text = pattern.sub(MASK, text)

    return _ASSIGNMENT.sub(_mask_assignment, text)


def redactor(secrets: Iterable[str]) -> "Redactor":
    return Redactor(list(secrets))


class Redactor:
    """A reusable redactor bound to this run's known secrets."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        self.secrets = [s for s in (secrets or []) if s and len(s) >= 8]

    def add(self, secret: str) -> None:
        if secret and len(secret) >= 8 and secret not in self.secrets:
            self.secrets.append(secret)

    def __call__(self, text: str) -> str:
        return redact(text, self.secrets)
