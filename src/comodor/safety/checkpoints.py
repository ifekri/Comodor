"""Undo for an autonomous agent.

Before any tool mutates a file, its previous bytes are copied into
``.comodor/checkpoints/``. ``/undo`` walks the journal backwards and restores
them. Without this, letting a loop run unattended means trusting it never makes
a mistake; with it, a mistake costs one command.

Snapshots are content-addressed, so a file rewritten twenty times in a session
stores each distinct version once. A file that did not exist is recorded with a
``None`` blob, and undoing that deletes it again.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

JOURNAL_NAME = "journal.jsonl"
BLOBS_DIR = "blobs"
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024      # skip snapshots of very large files


@dataclass
class Entry:
    """One recorded mutation."""

    id: str
    path: str
    blob: str | None                       # sha256 of the previous content
    existed: bool
    action: str                            # write | edit | delete | create
    at: float = field(default_factory=time.time)
    tool: str = ""
    note: str = ""
    undone: bool = False
    # sha256 of what the agent left behind. Comparing it against the file's
    # current hash is how a later hand-edit by the user is detected — which is
    # the single most valuable learning signal there is.
    after_blob: str | None = None


class CheckpointStore:
    """Append-only journal plus a content-addressed blob store."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.blobs = self.root / BLOBS_DIR
        self.journal = self.root / JOURNAL_NAME
        self._lock = threading.Lock()

    # -- recording -------------------------------------------------------- #

    def snapshot(self, path: Path | str, action: str = "write", tool: str = "",
                 note: str = "", after: str | bytes | None = None) -> Entry | None:
        """Record the current state of ``path`` before it is changed.

        Returns ``None`` when there is nothing worth recording (an unreadable
        or oversized file); callers treat that as "no undo for this one" rather
        than as a failure, so a huge asset never blocks an edit.
        """
        target = Path(path)
        entry = Entry(id=uuid.uuid4().hex[:12], path=str(target), blob=None,
                      existed=target.exists(), action=action, tool=tool, note=note)

        if entry.existed:
            try:
                if target.stat().st_size > MAX_SNAPSHOT_BYTES:
                    return None
                data = target.read_bytes()
            except OSError:
                return None
            entry.blob = self._store_blob(data)

        if after is not None:
            # Stored, not merely hashed: recognising that a file changed is only
            # half of it. Learning anything from the change needs the text the
            # agent actually wrote, to diff against what the user made of it.
            # Content addressing keeps this nearly free — one write's "after" is
            # usually the next write's "before".
            payload = after.encode("utf-8") if isinstance(after, str) else after
            entry.after_blob = self._store_blob(payload)

        self._append(entry)
        return entry

    def hash_of(self, path: Path | str) -> str | None:
        """The current content hash of a file, or ``None`` if unreadable."""
        try:
            target = Path(path)
            if not target.is_file() or target.stat().st_size > MAX_SNAPSHOT_BYTES:
                return None
            return hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError:
            return None

    def read_blob(self, digest: str | None) -> str:
        """The stored text of a blob, for diffing an agent write against an edit."""
        if not digest:
            return ""
        try:
            return (self.blobs / digest).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def touched_since(self, since: float = 0.0) -> list[Entry]:
        """Agent writes recorded after ``since`` that are still in force.

        Only the newest entry per path is returned: if the agent wrote a file
        three times, the question "did the user change it afterwards" is about
        the last version it left.
        """
        latest: dict[str, Entry] = {}
        for entry in self.entries():
            if entry.undone or entry.at < since or not entry.after_blob:
                continue
            latest[entry.path] = entry
        return list(latest.values())

    def _store_blob(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        self.blobs.mkdir(parents=True, exist_ok=True)
        blob_path = self.blobs / digest
        if not blob_path.exists():
            blob_path.write_bytes(data)
        return digest

    def _append(self, entry: Entry) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    # -- reading ---------------------------------------------------------- #

    def entries(self) -> list[Entry]:
        if not self.journal.exists():
            return []
        records: list[Entry] = []
        with self.journal.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(Entry(**json.loads(line)))
                except (ValueError, TypeError):
                    continue
        return records

    def pending(self) -> list[Entry]:
        """Entries that have not been undone, newest first."""
        return [entry for entry in reversed(self.entries()) if not entry.undone]

    # -- undo ------------------------------------------------------------- #

    def undo_last(self, count: int = 1) -> list[str]:
        """Restore the most recent ``count`` mutations. Returns what changed."""
        remaining = self.entries()
        undone_ids: set[str] = set()
        restored: list[str] = []

        for entry in reversed(remaining):
            if len(restored) >= count:
                break
            if entry.undone:
                continue
            if self._restore(entry):
                restored.append(entry.path)
                undone_ids.add(entry.id)

        if undone_ids:
            self._rewrite(remaining, undone_ids)
        return restored

    def _restore(self, entry: Entry) -> bool:
        target = Path(entry.path)
        try:
            if not entry.existed:
                # The file was created by the agent; undoing means removing it.
                if target.exists():
                    target.unlink()
                return True
            if entry.blob is None:
                return False
            blob_path = self.blobs / entry.blob
            if not blob_path.exists():
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(blob_path, target)
            return True
        except OSError:
            return False

    def _rewrite(self, entries: list[Entry], undone_ids: set[str]) -> None:
        with self._lock:
            with self.journal.open("w", encoding="utf-8") as handle:
                for entry in entries:
                    if entry.id in undone_ids:
                        entry.undone = True
                    handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    # -- housekeeping ----------------------------------------------------- #

    def prune(self, keep: int = 200) -> int:
        """Trim the journal and drop blobs nothing references any more."""
        entries = self.entries()
        if len(entries) <= keep:
            return 0
        kept = entries[-keep:]
        referenced = {entry.blob for entry in kept if entry.blob}

        with self._lock:
            with self.journal.open("w", encoding="utf-8") as handle:
                for entry in kept:
                    handle.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

        removed = 0
        if self.blobs.exists():
            for blob in self.blobs.iterdir():
                if blob.name not in referenced:
                    try:
                        blob.unlink()
                        removed += 1
                    except OSError:
                        pass
        return removed
