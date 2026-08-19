"""Searching everything you have ever asked.

Transcripts already sit on disk as JSON Lines; until now nothing could look
inside them. That is a strange gap, because the most valuable thing an agent
accumulates is not its lessons — it is the record of the last four hundred
problems it worked on with you. "How did we fix that import error in March" has
an exact answer, and it is already written down.

Two design choices worth stating:

**The index is derived, never authoritative.** It is a cache built from the
JSONL files. Delete `search.db` and the next search rebuilds it; delete a
session and its rows go with it. Nothing here is a second source of truth to
keep in sync.

**Search does not call a model.** FTS5 ranks with `bm25()` in under a
millisecond, and when the SQLite build has no FTS5 the same Python index the
brain uses takes over. Summarising the hits is the caller's job — when the agent
searches, the results land in its context and it summarises them as part of the
answer it was already writing, so nothing costs an extra round trip.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ..learning.hotindex import HotIndex

#: Roles worth searching. Tool output is noise — it is mostly file contents and
#: command spew, and matching it would bury the conversation it belongs to.
INDEXED_ROLES = ("user", "assistant")
#: Below this a message is a fragment, not something anyone will want back.
MIN_LENGTH = 12
MAX_SNIPPET = 240
#: FTS5 treats these as syntax; a user typing them means them literally.
FTS_SYNTAX = re.compile(r'["*:^()-]')


@dataclass
class Hit:
    """One matching message."""

    session_id: str
    role: str
    text: str
    at: float
    score: float = 0.0

    @property
    def when(self) -> str:
        delta = time.time() - self.at
        if delta < 3600:
            return f"{max(int(delta // 60), 1)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        if delta < 86400 * 30:
            return f"{int(delta // 86400)}d ago"
        return time.strftime("%d %b %Y", time.localtime(self.at))

    def snippet(self, width: int = MAX_SNIPPET) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= width else text[: width - 1] + "…"


class SessionIndex:
    """A full-text index over stored transcripts."""

    def __init__(self, store, path: Path | None = None) -> None:
        self.store = store
        self.path = Path(path) if path else Path(store.root) / "search.db"
        self.fts_available = False
        self._fallback = HotIndex()
        self._fallback_docs: dict[int, Hit] = {}
        self._next_id = 1
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._prepare()

    # -- schema ------------------------------------------------------------ #

    def _prepare(self) -> None:
        self._db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE IF NOT EXISTS indexed (
                session_id TEXT PRIMARY KEY,
                mtime      REAL NOT NULL,
                lines      INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS turns (
                id         INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                body       TEXT NOT NULL,
                at         REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS turns_by_session ON turns(session_id);
            """
        )
        try:
            self._db.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts
                    USING fts5(body, content='turns', content_rowid='id');
                """
            )
            self.fts_available = True
        except sqlite3.OperationalError:
            # A SQLite built without FTS5. Rare, but it happens on trimmed
            # platform builds, and the feature has to work there too.
            self.fts_available = False
        self._db.commit()

    # -- building ---------------------------------------------------------- #

    def refresh(self) -> int:
        """Index whatever has changed since last time. Returns turns added.

        Cheap enough to call on every start: sessions that have not moved are
        skipped on an mtime comparison, and the one that has usually grew by a
        handful of lines.
        """
        known = {row["session_id"]: (row["mtime"], row["lines"])
                 for row in self._db.execute("SELECT * FROM indexed")}
        added = 0
        seen: set[str] = set()

        for path in sorted(Path(self.store.root).glob("*.jsonl")):
            session_id = path.stem
            seen.add(session_id)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if session_id in known and known[session_id][0] >= mtime:
                continue
            added += self._index_file(path, session_id,
                                      skip=known.get(session_id, (0.0, 0))[1])

        # A session deleted from disk must vanish from search too, or `/resume`
        # would be offered a transcript that no longer exists.
        for gone in set(known) - seen:
            self.forget(gone)

        self._db.commit()
        return added

    def _index_file(self, path: Path, session_id: str, skip: int) -> int:
        added = 0
        line_number = 0
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line_number += 1
                    if line_number <= skip:
                        continue
                    record = _record(line)
                    if record is None:
                        continue
                    role, body, at = record
                    self._insert(session_id, role, body, at)
                    added += 1
        except OSError:
            return added

        self._db.execute(
            "INSERT INTO indexed(session_id, mtime, lines) VALUES(?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET mtime=excluded.mtime, "
            "lines=excluded.lines",
            (session_id, path.stat().st_mtime, line_number))
        return added

    def _insert(self, session_id: str, role: str, body: str, at: float) -> None:
        cursor = self._db.execute(
            "INSERT INTO turns(session_id, role, body, at) VALUES(?, ?, ?, ?)",
            (session_id, role, body, at))
        rowid = cursor.lastrowid
        if self.fts_available:
            self._db.execute("INSERT INTO turns_fts(rowid, body) VALUES(?, ?)",
                             (rowid, body))
        else:
            identifier = self._next_id
            self._next_id += 1
            self._fallback.add("turn", identifier, body, role)
            self._fallback_docs[identifier] = Hit(session_id, role, body, at)

    def forget(self, session_id: str) -> None:
        """Drop one session from the index."""
        if self.fts_available:
            rows = self._db.execute("SELECT id, body FROM turns WHERE session_id = ?",
                                    (session_id,)).fetchall()
            for row in rows:
                self._db.execute(
                    "INSERT INTO turns_fts(turns_fts, rowid, body) VALUES('delete', ?, ?)",
                    (row["id"], row["body"]))
        self._db.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        self._db.execute("DELETE FROM indexed WHERE session_id = ?", (session_id,))
        self._db.commit()

    # -- searching --------------------------------------------------------- #

    def search(self, query: str, limit: int = 8,
               exclude_session: str = "") -> list[Hit]:
        """Rank past turns against a query, newest-first among equals."""
        words = [word for word in re.split(r"\W+", query) if len(word) > 1]
        if not words:
            return []

        if self.fts_available:
            hits = self._search_fts(words, limit * 3)
        else:
            hits = self._search_fallback(query, limit * 3)

        if exclude_session:
            # The current session is already in front of the user; repeating it
            # back at them is the least useful result available.
            hits = [hit for hit in hits if hit.session_id != exclude_session]
        return hits[:limit]

    def _search_fts(self, words: list[str], limit: int) -> list[Hit]:
        # Everything is quoted and OR-joined: a user searching "auth error"
        # means those words, not an FTS5 expression, and an unescaped `-` or
        # `*` would otherwise be a syntax error rather than a search.
        expression = " OR ".join(f'"{FTS_SYNTAX.sub(" ", word)}"' for word in words)
        try:
            rows = self._db.execute(
                """
                SELECT t.session_id, t.role, t.body, t.at, bm25(turns_fts) AS rank
                FROM turns_fts JOIN turns t ON t.id = turns_fts.rowid
                WHERE turns_fts MATCH ?
                ORDER BY rank LIMIT ?
                """, (expression, limit)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [Hit(row["session_id"], row["role"], row["body"], row["at"],
                    -float(row["rank"])) for row in rows]

    def _search_fallback(self, query: str, limit: int) -> list[Hit]:
        results: list[Hit] = []
        for doc, score in self._fallback.coverage_scan(query, kind="turn", limit=limit):
            hit = self._fallback_docs.get(doc.doc_id)
            if hit is not None:
                results.append(Hit(hit.session_id, hit.role, hit.text, hit.at, score))
        return results

    def stats(self) -> dict[str, int]:
        turns = self._db.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"]
        sessions = self._db.execute("SELECT COUNT(*) AS n FROM indexed").fetchone()["n"]
        return {"turns": int(turns), "sessions": int(sessions)}

    def close(self) -> None:
        try:
            self._db.commit()
            self._db.close()
        except sqlite3.Error:
            pass


def _record(line: str) -> tuple[str, str, float] | None:
    """One JSONL line, if it is a message worth indexing."""
    try:
        data = json.loads(line)
    except (ValueError, TypeError):
        return None
    role = str(data.get("role", ""))
    if role not in INDEXED_ROLES:
        return None
    body = str(data.get("content") or "").strip()
    if len(body) < MIN_LENGTH:
        return None
    return role, body, float(data.get("at") or 0.0)
