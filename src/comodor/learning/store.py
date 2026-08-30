"""The brain's storage: SQLite, with FTS5 when the build has it.

Everything Comodor learns lives in one file at ``~/.comodor/brain.db``, shared
across every project. That is the point — a lesson about how the user likes
commit messages, or about a library that always needs an extra flag, should not
have to be relearned in the next repository. Project-specific findings are kept
apart by their ``scope`` instead.

Retrieval uses FTS5's built-in ``bm25()`` where available and falls back to the
pure-Python index otherwise, so the feature degrades rather than disappears on
an unusual Python build.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from .bm25 import BM25Index, coverage
from .hotindex import HotIndex
from .writer import AsyncWriter

SCHEMA_VERSION = 2
DAY = 86400.0

# How many agreeing observations a rule needs before it shapes the prompt,
# by where the evidence came from.
FLOORS: dict[str, int] = {
    "user": 1,             # stated outright
    "correction": 2,       # the user changed what the agent produced, or refused it
    "evidence": 2,         # the environment demonstrated it, more than once
    "observation": 4,      # merely how the existing code happens to look
}

# WAL keeps readers from blocking the writer; the memory settings matter because
# recall reads the same few pages thousands of times in a session and there is no
# reason for them ever to leave RAM.
#: How many lessons the RAM mirror holds. It is a cache of what can plausibly
#: be recalled, not the record: recall multiplies relevance by confidence and
#: throws away anything scoring near zero, so the decayed tail of a large table
#: cannot win however well it matches. Loading it anyway cost 1.15 seconds of
#: startup at fifty thousand lessons, paid before every first prompt.
HOT_LESSONS = 6_000
#: How many terms of a query reach FTS5. Twelve unioned across a large table
#: measured at 20 ms; the rarest five find the same rows in a fraction of it.
FTS_TERMS = 5

PRAGMAS: dict[str, str] = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "temp_store": "MEMORY",
    "cache_size": "-16000",          # ~16 MB, negative means kibibytes
    "mmap_size": "268435456",        # 256 MB
    "busy_timeout": "5000",
}


if TYPE_CHECKING:                      # a cycle at runtime, not to a type checker
    from .associations import Associations


# --------------------------------------------------------------------------- #
# records
# --------------------------------------------------------------------------- #


@dataclass
class Lesson:
    """One durable thing the agent has learned."""

    id: int = 0
    kind: str = "heuristic"          # preference | fact | heuristic | pitfall | env
    scope: str = "global"            # global | project:<key> | lang:<x> | tool:<x>
    trigger: str = ""                # when it applies
    guidance: str = ""               # what to do
    confidence: float = 0.5
    uses: int = 0
    wins: int = 0
    losses: int = 0
    pinned: bool = False
    source: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_used: float = 0.0

    @property
    def text(self) -> str:
        return f"{self.trigger} {self.guidance}".strip()

    def effective_confidence(self, half_life_days: float = 45.0) -> float:
        """Confidence after decay, and after the win/loss record is folded in.

        A lesson that keeps being present when things go well grows more
        trusted; one that is around for failures fades. Age decays everything,
        so stale beliefs about a moving codebase do not linger forever.
        """
        if self.pinned:
            return 1.0
        evidence = (self.wins + 1) / (self.wins + self.losses + 2)   # Laplace
        blended = 0.5 * self.confidence + 0.5 * evidence
        age_days = max(0.0, (time.time() - self.updated_at) / DAY)
        decay = 0.5 ** (age_days / max(1.0, half_life_days))
        return max(0.0, min(1.0, blended * decay))

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "scope": self.scope,
            "trigger": self.trigger, "guidance": self.guidance,
            "confidence": round(self.effective_confidence(), 3),
            "uses": self.uses, "wins": self.wins, "losses": self.losses,
            "pinned": self.pinned,
        }


@dataclass
class Skill:
    """A reusable procedure distilled from a successful multi-step task."""

    id: int = 0
    name: str = ""
    description: str = ""
    steps: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    scope: str = "global"
    uses: int = 0
    wins: int = 0
    losses: int = 0
    avg_duration: float = 0.0
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0

    @property
    def text(self) -> str:
        return f"{self.name} {self.description} {' '.join(self.tags)} {' '.join(self.steps)}"

    @property
    def success_rate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total) if total else 0.5

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description,
                "steps": self.steps, "tags": self.tags, "uses": self.uses,
                "success_rate": round(self.success_rate, 2)}


@dataclass
class Rule:
    """A convention learned by observation rather than by asking a model.

    Rules differ from lessons in where they come from and how much they are
    trusted. A lesson is prose a model wrote about a task; a rule is a counted
    fact about how this user works — "31 of 34 string literals use single
    quotes" — so it carries its evidence and can be shown as a number.
    """

    id: int = 0
    category: str = "style"          # style | workflow | preference | avoid
    key: str = ""                    # stable identity, e.g. "python.quotes"
    statement: str = ""              # the instruction given to the model
    detail: str = ""                 # human-readable evidence
    scope: str = "global"
    support: int = 0                 # observations agreeing
    against: int = 0                 # observations disagreeing
    source: str = "observation"      # observation | correction | user
    pinned: bool = False
    active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def text(self) -> str:
        return f"{self.key} {self.statement} {self.detail}".strip()

    @property
    def total(self) -> int:
        return self.support + self.against

    @property
    def strength(self) -> float:
        """Agreement rate, smoothed so one observation is not proof."""
        return (self.support + 1) / (self.total + 2)

    @property
    def confident(self) -> bool:
        """Whether this rule has earned a place in the prompt.

        How much evidence is needed depends on where it came from. Watching the
        codebase is weak evidence — plenty of code is written a certain way by
        accident. A user editing what the agent produced, or refusing a command,
        is a deliberate statement and needs far less repetition. Something the
        environment demonstrated twice sits in between, but is verified fact.
        """
        if self.pinned or self.source == "user":
            return True
        floor = FLOORS.get(self.source, 4)
        return self.support >= floor and self.strength >= 0.7

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "category": self.category, "key": self.key,
                "statement": self.statement, "detail": self.detail,
                "support": self.support, "against": self.against,
                "strength": round(self.strength, 2), "source": self.source,
                "pinned": self.pinned, "active": self.active}


@dataclass
class Signal:
    """One observed user action that carries a preference."""

    id: int = 0
    kind: str = ""                   # correction | undo | denial | rephrase | retry
    session_id: str = ""
    episode_id: int = 0
    subject: str = ""                # file path, command, tool name
    payload: str = ""                # the diff or detail, already redacted
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


@dataclass
class Episode:
    """One completed task, kept so reflection has something to look at."""

    id: int = 0
    session_id: str = ""
    goal: str = ""
    scope: str = "global"
    success: bool = True
    stopped: str = "done"
    steps: int = 0
    elapsed: float = 0.0
    tools_used: list[str] = field(default_factory=list)
    error_kind: str = ""
    created_at: float = field(default_factory=time.time)
    # Metrics behind /progress — the numbers that make "it improves" checkable.
    corrections: int = 0
    approvals_asked: int = 0
    retries: int = 0
    tokens: int = 0
    rules_active: int = 0


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #


class BrainStore:
    """SQLite-backed persistence with full-text retrieval."""

    def __init__(self, path: Path | str, async_writes: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.Lock()
        self.fts_available = False
        self._fallback = BM25Index()
        self._fallback_loaded = False
        self.hot = HotIndex()
        self._migrate()

        # Reinforcement and signals go through a background writer so nothing
        # user-facing ever waits on a commit. Inserts that need their row id
        # back still run inline — they are rare and the caller needs the id.
        self.writer = AsyncWriter(str(self.path), PRAGMAS) if async_writes else None
        if self.writer is not None:
            self.writer.start()
        self.warm()

    # -- connection ------------------------------------------------------- #

    @property
    def connection(self) -> sqlite3.Connection:
        """One connection per thread — SQLite objects are not shareable."""
        existing = getattr(self._local, "connection", None)
        if existing is None:
            existing = sqlite3.connect(self.path, timeout=15.0)
            existing.row_factory = sqlite3.Row
            for name, value in PRAGMAS.items():
                try:
                    existing.execute(f"PRAGMA {name}={value}")
                except sqlite3.Error:
                    continue
            self._local.connection = existing
        return existing

    def close(self) -> None:
        if self.writer is not None:
            self.writer.stop()
        existing = getattr(self._local, "connection", None)
        if existing is not None:
            existing.close()
            self._local.connection = None

    def flush(self, timeout: float = 3.0) -> bool:
        """Wait for queued writes to land. Used at exit and in tests."""
        return self.writer.flush(timeout) if self.writer is not None else True

    # -- the RAM mirror --------------------------------------------------- #

    def warm(self, limit: int = HOT_LESSONS) -> int:
        """Load what can plausibly win into the hot index.

        Not everything, which is what this used to do. Startup cost grows
        linearly with the table, and measured at fifty thousand lessons that
        was 1.15 seconds before the first prompt appeared — felt, and paid on
        every single run.

        The mirror is a cache of what is likely to be recalled, not the record.
        Recall multiplies relevance by confidence and discards anything scoring
        near zero, so a decayed lesson at the bottom of the table cannot win
        however well it matches; loading fifty thousand of those to find six is
        work with no possible outcome. The strongest and most recently useful
        are held in memory, and the tail stays reachable through FTS, which is
        consulted exactly when the mirror comes up short.

        Rules are loaded whole. There are tens of them, not thousands.
        """
        records = [("lesson", lesson.id, lesson.text, lesson.scope)
                   for lesson in self.hot_lessons(limit)]
        records += [("rule", rule.id, rule.text, rule.scope)
                    for rule in self.all_rules()]
        return self.hot.rebuild(records)

    def hot_lessons(self, limit: int = HOT_LESSONS) -> list[Lesson]:
        """The lessons worth keeping in memory, best first.

        Pinned before anything else — the user asked for those every time —
        then by confidence, then by how recently one earned its place.
        """
        rows = self.connection.execute(
            """SELECT * FROM lessons
               ORDER BY pinned DESC, confidence DESC, last_used DESC, updated_at DESC
               LIMIT ?""", (limit,))
        return [self._row_to_lesson(row) for row in rows]

    # -- schema ----------------------------------------------------------- #

    def _migrate(self) -> None:
        connection = self.connection
        with self._lock, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY, value TEXT
                );
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL DEFAULT 'heuristic',
                    scope TEXT NOT NULL DEFAULT 'global',
                    trigger_text TEXT NOT NULL,
                    guidance TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    uses INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    pinned INTEGER NOT NULL DEFAULT 0,
                    source TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_used REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_lessons_scope ON lessons(scope);
                -- Partial: pinned lessons are fetched on every single recall,
                -- and there are only ever a handful of them.
                CREATE INDEX IF NOT EXISTS idx_lessons_pinned ON lessons(scope)
                    WHERE pinned = 1;
                CREATE TABLE IF NOT EXISTS skills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    steps TEXT NOT NULL DEFAULT '[]',
                    tags TEXT NOT NULL DEFAULT '[]',
                    scope TEXT NOT NULL DEFAULT 'global',
                    uses INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    avg_duration REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_used REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'global',
                    success INTEGER NOT NULL DEFAULT 1,
                    stopped TEXT NOT NULL DEFAULT 'done',
                    steps INTEGER NOT NULL DEFAULT 0,
                    elapsed REAL NOT NULL DEFAULT 0,
                    tools_used TEXT NOT NULL DEFAULT '[]',
                    error_kind TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_kind TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    signal REAL NOT NULL,
                    note TEXT DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'style',
                    key TEXT NOT NULL,
                    statement TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL DEFAULT 'global',
                    support INTEGER NOT NULL DEFAULT 0,
                    against INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'observation',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(key, scope)
                );
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    episode_id INTEGER NOT NULL DEFAULT 0,
                    subject TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL DEFAULT '',
                    weight REAL NOT NULL DEFAULT 1.0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_signals_kind ON signals(kind, created_at);
                CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at);
                """
            )
            self._add_missing_columns(connection)
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)",
                (str(SCHEMA_VERSION),),
            )

        self._setup_fts()

    @staticmethod
    def _add_missing_columns(connection: sqlite3.Connection) -> None:
        """Bring an older brain forward without losing what it has learned.

        A brain accumulated over months is the whole point of this feature, so
        upgrades add columns in place rather than rebuilding the database.
        """
        additions = {
            "episodes": [
                ("corrections", "INTEGER NOT NULL DEFAULT 0"),
                ("approvals_asked", "INTEGER NOT NULL DEFAULT 0"),
                ("retries", "INTEGER NOT NULL DEFAULT 0"),
                ("tokens", "INTEGER NOT NULL DEFAULT 0"),
                ("rules_active", "INTEGER NOT NULL DEFAULT 0"),
            ],
        }
        for table, columns in additions.items():
            existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns:
                if name not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _setup_fts(self) -> None:
        """Create the FTS mirrors, or fall back to the Python index."""
        connection = self.connection
        try:
            with self._lock, connection:
                connection.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts
                        USING fts5(trigger_text, guidance, content='lessons',
                                   content_rowid='id', tokenize='porter unicode61');
                    CREATE TRIGGER IF NOT EXISTS lessons_ai AFTER INSERT ON lessons BEGIN
                        INSERT INTO lessons_fts(rowid, trigger_text, guidance)
                        VALUES (new.id, new.trigger_text, new.guidance);
                    END;
                    CREATE TRIGGER IF NOT EXISTS lessons_ad AFTER DELETE ON lessons BEGIN
                        INSERT INTO lessons_fts(lessons_fts, rowid, trigger_text, guidance)
                        VALUES ('delete', old.id, old.trigger_text, old.guidance);
                    END;
                    CREATE TRIGGER IF NOT EXISTS lessons_au AFTER UPDATE ON lessons BEGIN
                        INSERT INTO lessons_fts(lessons_fts, rowid, trigger_text, guidance)
                        VALUES ('delete', old.id, old.trigger_text, old.guidance);
                        INSERT INTO lessons_fts(rowid, trigger_text, guidance)
                        VALUES (new.id, new.trigger_text, new.guidance);
                    END;
                    CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts
                        USING fts5(name, description, body, content='');
                    """
                )
            self.fts_available = True
        except sqlite3.OperationalError:
            # No FTS5 in this build: the Python BM25 index takes over.
            self.fts_available = False

    # -- lessons: write --------------------------------------------------- #

    def add_lesson(self, lesson: Lesson) -> Lesson:
        now = time.time()
        with self._lock, self.connection as connection:
            cursor = connection.execute(
                """INSERT INTO lessons(kind, scope, trigger_text, guidance, confidence,
                                       uses, wins, losses, pinned, source,
                                       created_at, updated_at, last_used)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (lesson.kind, lesson.scope, lesson.trigger, lesson.guidance,
                 lesson.confidence, lesson.uses, lesson.wins, lesson.losses,
                 int(lesson.pinned), lesson.source, now, now, lesson.last_used),
            )
            lesson.id = int(cursor.lastrowid or 0)
        lesson.created_at = lesson.updated_at = now
        self.hot.add("lesson", lesson.id, lesson.text, lesson.scope)
        if not self.fts_available:
            self._fallback.add(f"lesson:{lesson.id}", lesson.text)
        return lesson

    def update_lesson(self, lesson: Lesson) -> None:
        with self._lock, self.connection as connection:
            connection.execute(
                """UPDATE lessons SET kind=?, scope=?, trigger_text=?, guidance=?,
                       confidence=?, uses=?, wins=?, losses=?, pinned=?,
                       updated_at=?, last_used=? WHERE id=?""",
                (lesson.kind, lesson.scope, lesson.trigger, lesson.guidance,
                 lesson.confidence, lesson.uses, lesson.wins, lesson.losses,
                 int(lesson.pinned), time.time(), lesson.last_used, lesson.id),
            )
        self.hot.add("lesson", lesson.id, lesson.text, lesson.scope)
        if not self.fts_available:
            self._fallback.add(f"lesson:{lesson.id}", lesson.text)

    def delete_lesson(self, lesson_id: int) -> bool:
        with self._lock, self.connection as connection:
            cursor = connection.execute("DELETE FROM lessons WHERE id=?", (lesson_id,))
        self.hot.remove("lesson", lesson_id)
        self._fallback.remove(f"lesson:{lesson_id}")
        return cursor.rowcount > 0

    def credit(self, lesson_ids: Iterable[int], won: bool) -> None:
        """Reinforce or penalise the lessons that were in play.

        Queued rather than committed inline: this runs at the end of every turn
        and nothing downstream needs it to have landed yet.
        """
        ids = [int(value) for value in lesson_ids]
        if not ids:
            return
        column = "wins" if won else "losses"
        placeholders = ",".join("?" * len(ids))
        now = time.time()
        sql = (f"UPDATE lessons SET {column} = {column} + 1, uses = uses + 1, "
               f"last_used = ?, updated_at = ? WHERE id IN ({placeholders})")
        self._write(sql, (now, now, *ids))

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        """Queue a statement, or run it inline when there is no writer."""
        if self.writer is not None and self.writer.running:
            self.writer.submit(sql, params)
            return
        with self._lock, self.connection as connection:
            connection.execute(sql, params)

    # -- lessons: read ---------------------------------------------------- #

    def _row_to_lesson(self, row: sqlite3.Row) -> Lesson:
        return Lesson(
            id=row["id"], kind=row["kind"], scope=row["scope"],
            trigger=row["trigger_text"], guidance=row["guidance"],
            confidence=row["confidence"], uses=row["uses"], wins=row["wins"],
            losses=row["losses"], pinned=bool(row["pinned"]), source=row["source"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            last_used=row["last_used"],
        )

    def all_lessons(self, scopes: list[str] | None = None) -> list[Lesson]:
        query = "SELECT * FROM lessons"
        params: tuple[Any, ...] = ()
        if scopes:
            query += f" WHERE scope IN ({','.join('?' * len(scopes))})"
            params = tuple(scopes)
        query += " ORDER BY updated_at DESC"
        return [self._row_to_lesson(row) for row in self.connection.execute(query, params)]

    def pinned_lessons(self, scopes: list[str] | None = None) -> list[Lesson]:
        """Pinned entries only — a narrow query, not a table scan.

        This runs on every single recall, so it must not pull the whole table
        through SQLite the way ``all_lessons`` does.
        """
        sql = "SELECT * FROM lessons WHERE pinned = 1"
        params: tuple[Any, ...] = ()
        if scopes:
            sql += f" AND scope IN ({','.join('?' * len(scopes))})"
            params = tuple(scopes)
        sql += " ORDER BY updated_at DESC"
        return [self._row_to_lesson(row) for row in self.connection.execute(sql, params)]

    def lessons_by_id(self, ids: Iterable[int]) -> dict[int, Lesson]:
        """Fetch exactly the rows the hot index pointed at."""
        wanted = [int(value) for value in ids]
        if not wanted:
            return {}
        placeholders = ",".join("?" * len(wanted))
        rows = self.connection.execute(
            f"SELECT * FROM lessons WHERE id IN ({placeholders})", wanted)
        return {row["id"]: self._row_to_lesson(row) for row in rows}

    def search_lessons(self, query: str, scopes: list[str] | None = None,
                       limit: int = 20) -> list[tuple[Lesson, float]]:
        """Rank lessons against a query. Returns ``(lesson, relevance)``.

        The RAM mirror answers first because it is bounded and fast — measured
        at a fraction of a millisecond where the FTS join costs several. FTS is
        consulted only when the mirror comes back short, which is where it earns
        its cost: its porter stemming matches "running" against "run", and plain
        token overlap does not.
        """
        results = self._search_fallback(query, scopes, limit)
        if len(results) >= limit or not self.fts_available:
            return results

        seen = {lesson.id for lesson, _ in results}
        for lesson, relevance in self._search_fts(query, scopes, limit):
            if lesson.id not in seen:
                results.append((lesson, relevance))
                seen.add(lesson.id)
        return results[:limit]

    def _search_fts(self, query: str, scopes: list[str] | None,
                    limit: int) -> list[tuple[Lesson, float]]:
        match = _to_fts_query(query, self.hot)
        if not match:
            return []
        sql = ["""SELECT lessons.*, bm25(lessons_fts) AS rank
                  FROM lessons_fts JOIN lessons ON lessons.id = lessons_fts.rowid
                  WHERE lessons_fts MATCH ?"""]
        params: list[Any] = [match]
        if scopes:
            sql.append(f"AND lessons.scope IN ({','.join('?' * len(scopes))})")
            params.extend(scopes)
        sql.append("ORDER BY rank LIMIT ?")
        params.append(limit)

        try:
            rows = self.connection.execute(" ".join(sql), params).fetchall()
        except sqlite3.OperationalError:
            return self._search_fallback(query, scopes, limit)

        results: list[tuple[Lesson, float]] = []
        for row in rows:
            # FTS5 bm25() is negative, more negative meaning a better match.
            relevance = max(0.0, -float(row["rank"]))
            results.append((self._row_to_lesson(row), relevance))
        return results

    def _search_fallback(self, query: str, scopes: list[str] | None,
                         limit: int) -> list[tuple[Lesson, float]]:
        """Retrieval without FTS5, served entirely from the RAM mirror.

        Scores are coverage fractions in ``[0, 1]`` rather than BM25 magnitudes;
        :func:`score` treats both the same way, taking whichever signal is
        stronger, so the two paths rank consistently.
        """
        ranked = self.hot.coverage_scan(query, kind="lesson", scopes=scopes,
                                        limit=limit)
        if not ranked:
            return []
        lessons = self.lessons_by_id(doc.id for doc, _ in ranked)
        return [(lessons[doc.id], value) for doc, value in ranked
                if doc.id in lessons]

    def find_similar(self, text: str, threshold: float = 0.6,
                     scopes: list[str] | None = None) -> Lesson | None:
        """The existing lesson that already says this, if there is one.

        Served from the RAM mirror. The previous version re-tokenised every
        stored lesson on each call, which reached 22 ms at three thousand
        lessons — on the path of every reflection.
        """
        doc, _ = self.hot.nearest(text, threshold=threshold, kind="lesson",
                                  scopes=scopes)
        if doc is None:
            return None
        return self.lessons_by_id([doc.id]).get(doc.id)

    # -- skills ----------------------------------------------------------- #

    def add_skill(self, skill: Skill) -> Skill:
        now = time.time()
        with self._lock, self.connection as connection:
            cursor = connection.execute(
                """INSERT INTO skills(name, description, steps, tags, scope, uses,
                                      wins, losses, avg_duration, created_at, last_used)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                       description=excluded.description,
                       steps=excluded.steps,
                       tags=excluded.tags""",
                (skill.name, skill.description, json.dumps(skill.steps),
                 json.dumps(skill.tags), skill.scope, skill.uses, skill.wins,
                 skill.losses, skill.avg_duration, now, skill.last_used),
            )
            skill.id = int(cursor.lastrowid or 0)
        return skill

    def _row_to_skill(self, row: sqlite3.Row) -> Skill:
        return Skill(
            id=row["id"], name=row["name"], description=row["description"],
            steps=json.loads(row["steps"] or "[]"), tags=json.loads(row["tags"] or "[]"),
            scope=row["scope"], uses=row["uses"], wins=row["wins"], losses=row["losses"],
            avg_duration=row["avg_duration"], created_at=row["created_at"],
            last_used=row["last_used"],
        )

    def all_skills(self) -> list[Skill]:
        return [self._row_to_skill(row) for row in
                self.connection.execute("SELECT * FROM skills ORDER BY uses DESC")]

    def search_skills(self, query: str, limit: int = 3) -> list[tuple[Skill, float]]:
        """Skills are few, so a direct similarity scan is the simplest thing."""
        index = BM25Index()
        skills = {skill.id: skill for skill in self.all_skills()}
        for skill in skills.values():
            index.add(f"skill:{skill.id}", skill.text)
        results = []
        for doc_id, score in index.search(query, limit=limit):
            skill = skills.get(int(doc_id.split(":")[1]))
            if skill is not None:
                results.append((skill, score))
        return results

    # -- rules ------------------------------------------------------------ #

    def _row_to_rule(self, row: sqlite3.Row) -> Rule:
        return Rule(
            id=row["id"], category=row["category"], key=row["key"],
            statement=row["statement"], detail=row["detail"], scope=row["scope"],
            support=row["support"], against=row["against"], source=row["source"],
            pinned=bool(row["pinned"]), active=bool(row["active"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def observe_rule(self, key: str, scope: str, *, agrees: bool = True,
                     category: str = "style", statement: str = "",
                     detail: str = "", source: str = "observation",
                     weight: int = 1) -> Rule:
        """Record one observation for a convention, creating it if it is new.

        Every observation of the same convention lands on the same row, so a
        rule's support count is a real tally rather than a pile of duplicates.
        """
        now = time.time()
        with self._lock, self.connection as connection:
            connection.execute(
                """INSERT INTO rules(category, key, statement, detail, scope,
                                     support, against, source, created_at, updated_at)
                   VALUES(?,?,?,?,?,0,0,?,?,?)
                   ON CONFLICT(key, scope) DO NOTHING""",
                (category, key, statement, detail, scope, source, now, now),
            )
            column = "support" if agrees else "against"
            # A correction outranks a passive observation, so it also upgrades
            # the recorded source and refreshes the wording.
            connection.execute(
                f"""UPDATE rules SET {column} = {column} + ?, updated_at = ?,
                        statement = CASE WHEN ? <> '' THEN ? ELSE statement END,
                        detail = CASE WHEN ? <> '' THEN ? ELSE detail END,
                        source = CASE WHEN source = 'observation' AND ? <> 'observation'
                                      THEN ? ELSE source END
                    WHERE key = ? AND scope = ?""",
                (weight, now, statement, statement, detail, detail,
                 source, source, key, scope),
            )
            row = connection.execute(
                "SELECT * FROM rules WHERE key = ? AND scope = ?", (key, scope)
            ).fetchone()

        rule = self._row_to_rule(row)
        self.hot.add("rule", rule.id, rule.text, rule.scope)
        return rule

    def all_rules(self, scopes: list[str] | None = None,
                  active_only: bool = False) -> list[Rule]:
        sql = "SELECT * FROM rules"
        clauses: list[str] = []
        params: list[Any] = []
        if scopes:
            clauses.append(f"scope IN ({','.join('?' * len(scopes))})")
            params.extend(scopes)
        if active_only:
            clauses.append("active = 1")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY support DESC, updated_at DESC"
        return [self._row_to_rule(row) for row in self.connection.execute(sql, params)]

    def confident_rules(self, scopes: list[str] | None = None) -> list[Rule]:
        """Rules that have earned their place in the prompt."""
        return [rule for rule in self.all_rules(scopes, active_only=True)
                if rule.confident]

    def set_rule_flags(self, rule_id: int, *, pinned: bool | None = None,
                       active: bool | None = None) -> bool:
        updates: list[str] = []
        params: list[Any] = []
        if pinned is not None:
            updates.append("pinned = ?")
            params.append(int(pinned))
        if active is not None:
            updates.append("active = ?")
            params.append(int(active))
        if not updates:
            return False
        params.extend([time.time(), rule_id])
        with self._lock, self.connection as connection:
            cursor = connection.execute(
                f"UPDATE rules SET {', '.join(updates)}, updated_at = ? WHERE id = ?",
                params)
        return cursor.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        with self._lock, self.connection as connection:
            cursor = connection.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.hot.remove("rule", rule_id)
        return cursor.rowcount > 0

    # -- signals ---------------------------------------------------------- #

    def add_signal(self, signal: Signal) -> None:
        """Queue an observed user action. Never blocks the caller."""
        self._write(
            """INSERT INTO signals(kind, session_id, episode_id, subject, payload,
                                   weight, created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (signal.kind, signal.session_id, signal.episode_id, signal.subject,
             signal.payload, signal.weight, signal.created_at),
        )

    def recent_signals(self, kind: str = "", limit: int = 50) -> list[Signal]:
        sql = "SELECT * FROM signals"
        params: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [
            Signal(id=row["id"], kind=row["kind"], session_id=row["session_id"],
                   episode_id=row["episode_id"], subject=row["subject"],
                   payload=row["payload"], weight=row["weight"],
                   created_at=row["created_at"])
            for row in self.connection.execute(sql, params)
        ]

    # -- episodes and feedback -------------------------------------------- #

    def add_episode(self, episode: Episode) -> Episode:
        with self._lock, self.connection as connection:
            cursor = connection.execute(
                """INSERT INTO episodes(session_id, goal, scope, success, stopped,
                                        steps, elapsed, tools_used, error_kind, created_at,
                                        corrections, approvals_asked, retries, tokens,
                                        rules_active)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (episode.session_id, episode.goal, episode.scope, int(episode.success),
                 episode.stopped, episode.steps, episode.elapsed,
                 json.dumps(episode.tools_used), episode.error_kind, episode.created_at,
                 episode.corrections, episode.approvals_asked, episode.retries,
                 episode.tokens, episode.rules_active),
            )
            episode.id = int(cursor.lastrowid or 0)
        return episode

    def episodes(self, limit: int = 200, scope: str = "") -> list[Episode]:
        """Recent episodes, oldest first — the series behind /progress."""
        sql = "SELECT * FROM episodes"
        params: list[Any] = []
        if scope:
            sql += " WHERE scope = ?"
            params.append(scope)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = list(self.connection.execute(sql, params))
        return [
            Episode(
                id=row["id"], session_id=row["session_id"], goal=row["goal"],
                scope=row["scope"], success=bool(row["success"]), stopped=row["stopped"],
                steps=row["steps"], elapsed=row["elapsed"],
                tools_used=json.loads(row["tools_used"] or "[]"),
                error_kind=row["error_kind"], created_at=row["created_at"],
                corrections=row["corrections"], approvals_asked=row["approvals_asked"],
                retries=row["retries"], tokens=row["tokens"],
                rules_active=row["rules_active"],
            )
            for row in reversed(rows)
        ]

    def add_feedback(self, target_kind: str, target_id: int, signal: float,
                     note: str = "") -> None:
        with self._lock, self.connection as connection:
            connection.execute(
                """INSERT INTO feedback(target_kind, target_id, signal, note, created_at)
                   VALUES(?,?,?,?,?)""",
                (target_kind, target_id, signal, note, time.time()),
            )

    # -- housekeeping ----------------------------------------------------- #

    # -- the association table --------------------------------------------- #

    def load_associations(self) -> "Associations":
        """The learned vocabulary, or an empty one on a first run.

        Kept as one JSON blob in `meta` rather than as a table of pairs. It is
        read once at start-up and written once at shutdown, never queried, so a
        row per pair would buy nothing but an index to maintain — and a hundred
        thousand tiny rows to vacuum.
        """
        from .associations import Associations

        with self._lock, self.connection as connection:
            row = connection.execute(
                "SELECT value FROM meta WHERE key = 'associations'").fetchone()
        if row is None:
            return Associations()
        try:
            return Associations.from_dict(json.loads(row["value"]))
        except (ValueError, TypeError, KeyError):
            return Associations()          # unreadable is the same as absent

    def save_associations(self, table: "Associations") -> None:
        """Written directly, not queued.

        This happens once, at shutdown, and it is the only copy of a month of
        counting. The write queue exists to keep small frequent writes off the
        hot path; handing it the one write that must not be lost — moments
        before the queue is drained and closed — is the wrong side of that
        trade.
        """
        with self._lock, self.connection as connection:
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('associations', ?)",
                (json.dumps(table.to_dict(), ensure_ascii=False),),
            )

    def consolidate(self, min_confidence: float, half_life_days: float) -> int:
        """Drop lessons that decayed below the floor. Returns how many went."""
        removed = 0
        for lesson in self.all_lessons():
            if lesson.pinned:
                continue
            # Give every lesson a grace period; a brand new one has no record
            # yet and would otherwise be pruned before it is ever used.
            if lesson.uses < 2 and time.time() - lesson.created_at < 7 * DAY:
                continue
            if lesson.effective_confidence(half_life_days) < min_confidence:
                self.delete_lesson(lesson.id)
                removed += 1
        return removed

    def stats(self) -> dict[str, Any]:
        connection = self.connection
        def count(table: str) -> int:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        wins, losses = connection.execute(
            "SELECT COALESCE(SUM(wins),0), COALESCE(SUM(losses),0) FROM lessons"
        ).fetchone()
        successes = connection.execute(
            "SELECT COALESCE(SUM(success),0) FROM episodes"
        ).fetchone()[0]
        episodes = count("episodes")
        return {
            "lessons": count("lessons"),
            "skills": count("skills"),
            "rules": count("rules"),
            "rules_active": len(self.confident_rules()),
            "signals": count("signals"),
            "episodes": episodes,
            "success_rate": (successes / episodes) if episodes else 0.0,
            "reinforcements": int(wins) + int(losses),
            "fts": self.fts_available,
            "indexed": len(self.hot),
            "queued_writes": self.writer.pending if self.writer else 0,
            "path": str(self.path),
        }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _to_fts_query(text: str, index: Any = None) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Every term is quoted so that user text containing FTS operators (``AND``,
    ``*``, ``"``) is treated as words rather than syntax — otherwise a search
    for ``a "quoted" phrase`` raises instead of returning results.
    """
    from .bm25 import tokenize

    terms = list(set(tokenize(text)))
    if not terms:
        return ""

    # The selective terms, and few of them. Length used to stand in for
    # selectivity, which is only loosely true — `middleware` is long and common
    # in a web project — and twelve terms unioned across a large table measured
    # at 20 ms.
    #
    # Ordering them by rarity turned out to change nothing at all, which is
    # why the ceiling is here: one term appearing in most of the table makes
    # the union enormous whatever is ranked ahead of it. The common ones are
    # dropped, not demoted.
    if index is not None:
        terms = index.selective(terms)
    else:
        terms.sort(key=len, reverse=True)
    return " OR ".join(f'"{term}"' for term in terms[:FTS_TERMS])


def score(relevance: float, lesson: Lesson, half_life_days: float,
          query: str = "") -> float:
    """Final ranking score: how well it matches, times how much we trust it.

    Relevance comes from two sources because neither alone is reliable across
    the lifetime of a brain. BM25 is well behaved once there are hundreds of
    lessons but degenerates toward zero on a nearly empty one, so it is blended
    with term coverage, which is stable at any size. The two are combined with
    ``max`` rather than an average: a strong signal from either is enough.
    """
    confidence = lesson.effective_confidence(half_life_days)
    # Compress BM25 so one very strong keyword match cannot drown out a lesson
    # that is slightly less on-topic but far better established.
    ranked = math.log1p(max(0.0, relevance)) / math.log1p(8.0)
    overlap = coverage(query, lesson.text) if query else 0.0
    return min(1.0, max(ranked, overlap)) * confidence
