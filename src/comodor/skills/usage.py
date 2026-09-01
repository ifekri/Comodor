"""What happened to each skill, written beside the skills themselves.

One JSON sidecar, one entry per skill. The counts are small and honest:
how many times the skill was matched into a context, how many times its
files were opened, how many times it was changed. Nothing here decides
anything — the numbers are telemetry for the person reading the skill
folder, not a gate the loader consults.

The file is written atomically and guarded by a lock file, in the pattern
the rest of Comodor's stores use, because two sessions can be reading and
counting at once.
"""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from dataclasses import dataclass
from pathlib import Path

NAME = ".usage.json"


@dataclass
class Usage:
    """The record of one skill's life so far."""

    created_by: str = ""             # who made it: "agent" | "user" | "brain"
    created: str = ""                # ISO timestamp
    use_count: int = 0               # matched into a request's context
    view_count: int = 0              # files read from it
    patch_count: int = 0             # times changed
    state: str = "active"            # active | archived | stale
    pinned: bool = False
    #: Unix time of the last recorded use. The curator reads this to decide
    #: whether a skill has gone out of service; a count alone cannot.
    last_used: float = 0.0
    #: Free text for the last thing that happened, so the file reads alone.
    note: str = ""

    def to_json(self) -> dict:
        return {key: getattr(self, key) for key in
                ("created_by", "created", "use_count", "view_count",
                 "patch_count", "state", "pinned", "last_used", "note")}

    @classmethod
    def from_json(cls, data: dict) -> "Usage":
        known = cls()
        for key in ("created_by", "created", "state", "note"):
            setattr(known, key, str(data.get(key) or ""))
        for key in ("use_count", "view_count", "patch_count"):
            try:
                setattr(known, key, int(data.get(key) or 0))
            except (TypeError, ValueError):
                pass
        known.pinned = bool(data.get("pinned", False))
        try:
            known.last_used = float(data.get("last_used") or 0)
        except (TypeError, ValueError):
            pass
        return known


class UsageStore:
    """The sidecar file, behind one process-wide lock."""

    def __init__(self, directory: Path) -> None:
        self.file = Path(directory) / NAME
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Usage]:
        try:
            document = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(document, dict):
            return {}
        return {name: Usage.from_json(entry)
                for name, entry in document.items() if isinstance(entry, dict)}

    def _save(self, entries: dict[str, Usage]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({name: usage.to_json()
                              for name, usage in sorted(entries.items())},
                             indent=2, ensure_ascii=False) + "\n"
        temporary = self.file.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        try:
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        temporary.replace(self.file)

    def get(self, name: str) -> Usage:
        with self._lock:
            return self._load().get(name, Usage())

    def all(self) -> dict[str, Usage]:
        with self._lock:
            return self._load()

    def update(self, name: str, change) -> Usage:
        """Apply `change(usage)` to one skill's entry and save it back."""
        with self._lock:
            entries = self._load()
            current = entries.get(name, Usage())
            changed = change(current)
            entries[name] = changed
            self._save(entries)
            return changed

    def record_use(self, name: str) -> None:
        def bump(usage: Usage) -> Usage:
            usage.use_count += 1
            usage.last_used = time.time()
            return usage

        self.update(name, bump)

    def record_patch(self, name: str, note: str = "") -> None:
        def bump(usage: Usage) -> Usage:
            usage.patch_count += 1
            if note:
                usage.note = note
            return usage

        self.update(name, bump)
