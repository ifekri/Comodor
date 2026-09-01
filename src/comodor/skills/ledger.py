"""The ledger of every change to a skill, and the backups it points at.

Each mutation appends one line: who did it, what kind of change, the sha256
of the skill's text before and after. The full text of every version lives
in a backups directory, named by its hash — so restoring is copying a file
back, and the same content stored twice is stored once.

The ledger is telemetry, not a gate. A failure to record — a read-only
directory, a full disk, a corrupt line — is noted and swallowed; work never
stops because the diary could not be written. Rollback is a manual command
for exactly this reason: nothing here makes decisions about a skill's text,
it only keeps the history that makes a human decision reversible.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

NAME = ".ledger.jsonl"


@dataclass
class Entry:
    """One recorded mutation."""

    when: str                        # ISO timestamp
    actor: str                       # "agent" | "user" | "brain"
    action: str                      # create | patch | edit | delete | restore
    skill: str                       # skill name
    before: str                      # sha256 of the text before, "" if none
    after: str                       # sha256 of the text after, "" if deleted

    def to_json(self) -> dict:
        return {"when": self.when, "actor": self.actor, "action": self.action,
                "skill": self.skill, "before": self.before, "after": self.after}

    @classmethod
    def from_json(cls, data: dict) -> "Entry":
        return cls(when=str(data.get("when") or ""),
                   actor=str(data.get("actor") or ""),
                   action=str(data.get("action") or ""),
                   skill=str(data.get("skill") or ""),
                   before=str(data.get("before") or ""),
                   after=str(data.get("after") or ""))


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Ledger:
    """The append-only history, and the version blocks it can restore."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.file = self.directory / NAME
        self._lock = threading.Lock()

    @property
    def backups(self) -> Path:
        return self.directory / ".skills-backup"

    def record(self, *, actor: str, action: str, skill: str,
               before: str = "", after: str = "") -> None:
        """Append one entry and keep the version blocks it names.

        Every failure is swallowed on purpose. A ledger that can refuse to
        let a skill be edited is a gate, and this is not a gate.
        """
        try:
            entry = Entry(when=datetime.now().isoformat(timespec="seconds"),
                          actor=actor, action=action, skill=skill,
                          before=before, after=after)
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                with self.file.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry.to_json(),
                                            ensure_ascii=False) + "\n")
        except OSError:
            return

    def keep(self, text: str) -> str:
        """Store one version's text under its hash; returns the hash."""
        try:
            content = text.encode("utf-8")
            name = hashlib.sha256(content).hexdigest()
            self.backups.mkdir(parents=True, exist_ok=True)
            target = self.backups / name
            if not target.exists():
                target.write_bytes(content)
            return name
        except OSError:
            return digest(text)      # the hash is still the truth, the copy is lost

    def restore_block(self, sha: str) -> str | None:
        """The text a hash names, or None when the block is gone."""
        try:
            return (self.backups / sha).read_text(encoding="utf-8")
        except OSError:
            return None

    def entries(self, skill: str | None = None) -> list[Entry]:
        """The history, oldest first, optionally for one skill."""
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        found = []
        for line in lines:
            try:
                entry = Entry.from_json(json.loads(line))
            except ValueError:
                continue                # a torn line is history lost, not a crash
            if skill is None or entry.skill == skill:
                found.append(entry)
        return found

    def last_version_before(self, skill: str) -> str | None:
        """The hash of the newest version that is not the current state.

        Rollback wants "what it was before the last change", which is the
        newest `before` block among this skill's mutations.
        """
        for entry in reversed(self.entries(skill)):
            if entry.before:
                return entry.before
        return None
