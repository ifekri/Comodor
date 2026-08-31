"""Approval mining: what this user keeps saying yes to, said back to them.

Every time a person clicks "allow" on a shell command, the command is written
to one log. After a couple of weeks that log is a portrait of the project's
routine — the same test command, the same build line, approved one click at a
time. Mining reads the log, normalises what it finds, and proposes the
allowlist entries the evidence supports.

The proposals are exactly that: printed for the user, applied only when they
say so. And two rules bound what may be proposed:

* only whole command stems are proposed (`pytest`, never `pytest -k slow`);
  the allowlist matches the first word, so a stem is the honest size of the
  evidence anyway;
* a stem is never proposed if anything ever refused matches a destructive
  class — an rm, a curl-to-shell, a disk write — because one `rm -rf build`
  approved once must not become `rm` forever.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: How many times a stem must have been approved before it is worth
#: proposing. One approval is an accident of timing; three is a habit.
MIN_APPROVALS = 3

#: Stems that are never proposed, however often they are approved. A stem
#: whose commands can destroy things does not get promoted from "the human
#: checked this one" to "the machine may run this class".
NEVER_PROPOSE = frozenset({
    "rm", "rmdir", "shred", "dd", "mkfs", "sh", "bash", "zsh", "eval",
    "sudo", "doas", "su", "chmod", "chown", "curl", "wget", "nc", "ncat",
    "ssh", "scp", "kill", "killall", "pkill", "shutdown", "reboot",
    "mv", "truncate", "reset", "git",
})
# `git` is on the list deliberately: `git clean -fdx`, `git reset --hard` and
# `git push --force` all hide behind the same first word as `git status`.


@dataclass
class Proposal:
    """One allowlist entry the evidence supports, with its evidence."""

    stem: str
    approvals: int
    examples: list[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return (f"approved {self.approvals} times, "
                f"most recently {self.examples[-1]!r}")


def load_approvals(path: Path) -> list[str]:
    """Every approved command in the log, oldest first. A corrupt line is
    skipped — the log is evidence, not a database, and half of one is fine."""
    commands: list[str] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            command = str(record.get("command", "")).strip()
            if command:
                commands.append(command)
    except OSError:
        return []
    return commands


def stem_of(command: str) -> str:
    """The first word of the first branch — what an allowlist entry covers."""
    from .smart import command_branches

    for branch in command_branches(command):
        parts = branch.split()
        if parts:
            return parts[0].lower()
    return ""


def propose(path: Path, min_approvals: int = MIN_APPROVALS) -> list[Proposal]:
    """The allowlist entries the approval log supports, most-approved first.

    Stems on the never-propose list are excluded before counting: a dozen
    approved `git` invocations still say nothing about the one `git clean`
    the stem would also approve.
    """
    commands = load_approvals(path)
    counted: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for command in commands:
        stem = stem_of(command)
        if not stem or stem in NEVER_PROPOSE:
            continue
        counted[stem] += 1
        examples.setdefault(stem, []).append(command)
    return [
        Proposal(stem=stem, approvals=count, examples=examples[stem][:3])
        for stem, count in counted.most_common()
        if count >= min_approvals
    ]


def apply_proposals(config: Any, stems: list[str]) -> list[str]:
    """Add the stems to the project allowlist and save the user's config.

    Returns the stems actually added — ones already present are not counted
    or written twice.
    """
    added: list[str] = []
    current = list(config.safety.allow_commands)
    for stem in stems:
        clean = stem.strip().lower()
        if clean and clean not in current:
            current.append(clean)
            added.append(clean)
    if added:
        config.safety.allow_commands = current
        config.save()
    return added
