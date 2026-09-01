"""A minimal scan of skill text for the things that should not pass quietly.

A skill is an instruction the model will follow in some future turn, when
nobody is looking at the file it came from. That makes a skill folder a
place an injection can hide: text that reads as documentation to a person
and as an order to a model. This module is the tripwire for the few
patterns that are almost never legitimate in a skill.

Like the linter, it is advisory — telemetry, not a gate. A hit is reported
at write time, in the tool result the person is already reading; nothing
is blocked, deleted, or refused here. The person decides, with the finding
in front of them, which is a heavier judgment than any pattern match.
"""

from __future__ import annotations

import re

#: (compiled pattern, what it means, said plainly)
PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Instructions addressed to the model that override everything else.
    (re.compile(r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)"
                r"\s+instructions", re.I),
     "tells the model to ignore its earlier instructions"),
    (re.compile(r"disregard\s+(all\s+|your\s+)?(rules|instructions|guardrails)",
                re.I),
     "tells the model to disregard its rules"),
    (re.compile(r"forget\s+(everything|all|your)\s+(you|instructions|rules|above)",
                re.I),
     "tells the model to forget what it knows"),
    (re.compile(r"you\s+are\s+now\s+(a|an|no longer)", re.I),
     "reassigns the model's identity mid-task"),
    (re.compile(r"(reveal|print|output|repeat)\s+(your\s+|the\s+)?"
                r"(system\s+prompt|hidden\s+instructions)", re.I),
     "asks for the system prompt"),
    # Exfiltration: code fetched over the network and run unverified, or
    # local material piped out to a remote host.
    (re.compile(r"\b(curl|wget)\b[^|;\n]*\|\s*(sudo\s+)?(ba|z|da)?sh", re.I),
     "pipes a downloaded script straight into a shell"),
    (re.compile(r"\b(curl|wget)\b[^;\n]*(-d|--data|-F|--form|-T|--upload-file)"
                r"[ =]\S+[^;\n]*https?://", re.I),
     "sends local data to a remote host"),
    (re.compile(r"(env|printenv|\$\(.+?\))[^|;\n]*\|\s*(curl|wget|nc\b)", re.I),
     "pipes environment contents to the network"),
    # Destructive one-liners that have no honest place in a procedure.
    (re.compile(r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s+/(?:\s|$)", re.I),
     "deletes from the filesystem root"),
    (re.compile(r"mkfs(\.\w+)?\b", re.I),
     "formats a filesystem"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\}\s*;:", re.I),
     "is a fork bomb"),
    (re.compile(r"chmod\s+-R\s+777\s+/(?:\s|$)", re.I),
     "makes the whole filesystem writable"),
)


def scan(text: str) -> list[str]:
    """Every pattern the text trips, as one plain sentence each.

    Empty means nothing recognised — which is not proof of safety, only
    that nothing known is here. The scan exists to slow down the obvious
    cases, not to certify the rest.
    """
    if not text:
        return []
    found: list[str] = []
    for pattern, meaning in PATTERNS:
        if pattern.search(text):
            found.append(meaning)
    return found
