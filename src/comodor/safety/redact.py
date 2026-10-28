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
)

# Each base64url run is considered once. A bare regex search would retry at
# every `eyJ` inside an unmatched run, even with possessive segment matching.
_JWT_RUN = re.compile(r"[A-Za-z0-9_\-]+")
_JWT = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}+\.[A-Za-z0-9_\-]{10,}+\.[A-Za-z0-9_\-]{10,}+")
_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


def _jwt_spans(text: str) -> Iterable[tuple[int, int]]:
    end = 0
    for run in _JWT_RUN.finditer(text):
        if run.start() < end or run.end() - run.start() < 13:
            continue
        start = text.find("eyJ", run.start(), run.end() - 10)
        # All starts in this run share the same following segments. If the
        # earliest eligible start fails, no later one can make a valid token.
        if start >= 0 and (match := _JWT.match(text, start)):
            end = match.end()
            yield start, end


def _private_key_spans(text: str) -> Iterable[tuple[int, int]]:
    at = 0
    # Keep the first BEGIN and the next END, just as the previous lazy body
    # match did, without rescanning the body for every unmatched BEGIN.
    while begin := _KEY_BEGIN.search(text, at):
        end = _KEY_END.search(text, begin.end())
        if end is None:
            return
        yield begin.start(), end.end()
        at = end.end()


def _mask_spans(text: str, spans: Iterable[tuple[int, int]]) -> str:
    parts = []
    end = 0
    for start, stop in spans:
        parts.extend((text[end:start], MASK))
        end = stop
    parts.append(text[end:])
    return "".join(parts)

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


def contains_credential(text: str) -> bool:
    """Does `text` hold one of the well-known credential shapes above?

    An aid, not a guarantee: a secret in a shape these patterns do not know
    is not found. The assignment rule (`API_KEY = …`) is left out, because
    ordinary source names its variables that way.
    """
    return (any(pattern.search(text) for pattern in _PATTERNS)
            or any(_jwt_spans(text)) or any(_private_key_spans(text)))


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
    text = _mask_spans(text, _jwt_spans(text))
    text = _mask_spans(text, _private_key_spans(text))

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
