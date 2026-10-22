"""Where a friend's memory actually lives.

This replaced one JSON document per friend, and the reason was not the file size -- it was the *write
pattern*. Every save serialised the whole document (every fact, every topic counter, every pending
mention) and rewrote the file, up to four times per answered message. That is O(entire memory) per
message, forever, over NFS. Fine at 594 bytes, wrong at any size, and the shape does not fix itself by
waiting.

What this buys, in the order the arguments were made:

* **Incremental writes.** A save is row-scoped: one friend's memory, not the whole database.
* **Recoverable.** A real journal, `synchronous=FULL`, `PRAGMA integrity_check`, and `backup()` for a
  consistent copy while it is being written. A crash rolls back instead of truncating.
* **Concurrent-safe.** `busy_timeout` plus real file locking, so writers queue instead of clobbering.
  That matters because three bots are planned, not one, and the data sits on NFS.
* **Queryable.** "What did he know last Tuesday" stops being archaeology.
* **Still one file**, in the sense that matters: copy it, inspect it with `sqlite3`, back it up --
  none of which stops being true as it grows, because it is indexed.

SQLite rather than Mongo for now, and the reasons can be rejected: no server to keep up, no
dependency, no network hop for a 594-byte write, and `sqlite3 memory.db .dump` turns it into readable
SQL. If more than one *host* ever writes concurrently, the swap is this module -- `Database` is the
only thing that knows the engine.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DB_ENV = "TTRPG_MEMORY_DB"
DEFAULT_DB = Path("data/memory.db")
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 10_000

# NFSv3 with local_lock=none is the deployment we actually have, and WAL needs shared memory that
# network filesystems do not reliably provide. A rollback journal is slower and portable; WAL is
# faster and wants a local disk. Both are one env var away, and the default is the safe one.
JOURNAL_MODE = os.environ.get("TTRPG_MEMORY_JOURNAL", "DELETE").upper()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS friend (
    friend       TEXT PRIMARY KEY,
    person       TEXT NOT NULL DEFAULT '',
    last_seen    TEXT NOT NULL DEFAULT '',
    sessions     INTEGER NOT NULL DEFAULT 0,
    pending_plan INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fact (
    friend     TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    said_by    TEXT NOT NULL DEFAULT 'them',
    first_seen TEXT NOT NULL DEFAULT '',
    last_seen  TEXT NOT NULL DEFAULT '',
    count      INTEGER NOT NULL DEFAULT 1,
    meta       TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (friend, key)
);

CREATE TABLE IF NOT EXISTS topic (
    friend TEXT NOT NULL,
    tag    TEXT NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (friend, tag)
);

CREATE TABLE IF NOT EXISTS pending (
    friend TEXT NOT NULL,
    tally  TEXT NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (friend, tally)
);

CREATE TABLE IF NOT EXISTS telling (
    friend    TEXT NOT NULL,
    story     TEXT NOT NULL,
    count     INTEGER NOT NULL DEFAULT 0,
    last_told TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (friend, story)
);

-- Append-only and deliberately small: what changed, when, and why. This is what makes a database
-- recoverable rather than merely durable: a bad write can be seen and undone.
CREATE TABLE IF NOT EXISTS journal (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    friend TEXT NOT NULL,
    kind   TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class DatabaseError(RuntimeError):
    """Raised when the database cannot be read or written."""


def path_from_env() -> Path:
    inside = os.environ.get(DB_ENV, "").strip()
    return Path(inside) if inside else DEFAULT_DB
class Database:
    """The one module that knows how memory is stored."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or path_from_env())
        self._ready = False

    # --- plumbing -------------------------------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """A connection per operation, configured for durability over a network filesystem.

        Per operation rather than long-lived because `sqlite3` connections cannot be shared across
        threads and every call here runs inside `asyncio.to_thread`. Opening one takes microseconds.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        except (OSError, sqlite3.Error) as error:
            raise DatabaseError(f"cannot open {self.path}: {error}") from error
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        # FULL rather than NORMAL: a lost memory is a broken friend, and these writes are tiny.
        connection.execute("PRAGMA synchronous = FULL")
        try:
            connection.execute(f"PRAGMA journal_mode = {JOURNAL_MODE}")
        except sqlite3.Error:
            # A filesystem that refuses the mode keeps the default rather than failing.
            pass
        return connection

    def ensure(self) -> None:
        """Create the schema once, and record what version it is."""
        if self._ready:
            return
        try:
            with self.connect() as connection:
                connection.executescript(SCHEMA)
                found = connection.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()
                if found is None:
                    connection.execute(
                        "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
        except sqlite3.Error as error:
            # A file that is not a database is a real failure, not an empty memory: saying nothing
            # would silently forget who the person is.
            raise DatabaseError(f"cannot read {self.path}: {error}") from error
        self._ready = True

    # --- reading --------------------------------------------------------------------------------

    def load(self, friend: str) -> dict[str, Any]:
        """One friend's memory, in the shape the rest of the code already speaks."""
        self.ensure()
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM friend WHERE friend = ?", (friend,)).fetchone()
            facts = connection.execute(
                "SELECT * FROM fact WHERE friend = ? ORDER BY key", (friend,)
            ).fetchall()
            topics = connection.execute(
                "SELECT tag, count FROM topic WHERE friend = ? ORDER BY count DESC", (friend,)
            ).fetchall()
            pending = connection.execute(
                "SELECT tally, count FROM pending WHERE friend = ?", (friend,)
            ).fetchall()
            telling = connection.execute(
                "SELECT story, count FROM telling WHERE friend = ?", (friend,)
            ).fetchall()
        return {
            "person": row["person"] if row else "",
            "last_seen": row["last_seen"] if row else "",
            "sessions": row["sessions"] if row else 0,
            "pending_plan": bool(row["pending_plan"]) if row else False,
            "facts": [
                {
                    "key": item["key"],
                    "value": item["value"],
                    "said_by": item["said_by"],
                    "first_seen": item["first_seen"],
                    "last_seen": item["last_seen"],
                    "count": item["count"],
                    "meta": json.loads(item["meta"] or "{}"),
                }
                for item in facts
            ],
            "topics": {item["tag"]: item["count"] for item in topics},
            "pending": {item["tally"]: item["count"] for item in pending},
            "telling": {item["story"]: item["count"] for item in telling},
        }

    def stories_told(self, friend: str) -> dict[str, int]:
        """How often each story has been told. Its own table, because the topic counter is capped."""
        self.ensure()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT story, count FROM telling WHERE friend = ?", (friend,)
            ).fetchall()
        return {row["story"]: row["count"] for row in rows}



    # --- writing --------------------------------------------------------------------------------

    def save(self, friend: str, payload: dict[str, Any], *, changed: Iterable[str] = ()) -> None:
        """Write one friend's memory, replacing only that friend's rows.

        Row-scoped rather than per-field: the cost is one friend's memory, not the database, and it
        either lands as a transaction or does not land at all.
        """
        self.ensure()
        facts = list(payload.get("facts") or ())
        topics = dict(payload.get("topics") or {})
        pending = dict(payload.get("pending") or {})
        telling = dict(payload.get("telling") or {})
        try:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO friend (friend, person, last_seen, sessions, pending_plan)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(friend) DO UPDATE SET
                        person = excluded.person,
                        last_seen = excluded.last_seen,
                        sessions = excluded.sessions,
                        pending_plan = excluded.pending_plan
                    """,
                    (
                        friend,
                        str(payload.get("person") or ""),
                        str(payload.get("last_seen") or ""),
                        int(payload.get("sessions") or 0),
                        1 if payload.get("pending_plan") else 0,
                    ),
                )
                for fact in facts:
                    connection.execute(
                        """
                        INSERT INTO fact
                            (friend, key, value, said_by, first_seen, last_seen, count, meta)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(friend, key) DO UPDATE SET
                            value = excluded.value,
                            said_by = excluded.said_by,
                            first_seen = excluded.first_seen,
                            last_seen = excluded.last_seen,
                            count = excluded.count,
                            meta = excluded.meta
                        """,
                        (
                            friend,
                            str(fact["key"]),
                            str(fact["value"]),
                            str(fact.get("said_by") or "them"),
                            str(fact.get("first_seen") or ""),
                            str(fact.get("last_seen") or ""),
                            int(fact.get("count") or 1),
                            json.dumps(fact.get("meta") or {}),
                        ),
                    )
                # A fact he has forgotten must not survive in the table.
                keep = [str(fact["key"]) for fact in facts]
                if keep:
                    marks = ",".join("?" for _ in keep)
                    connection.execute(
                        f"DELETE FROM fact WHERE friend = ? AND key NOT IN ({marks})",
                        (friend, *keep),
                    )
                else:
                    connection.execute("DELETE FROM fact WHERE friend = ?", (friend,))
                for table, column, items in (
                    ("topic", "tag", topics),
                    ("pending", "tally", pending),
                    ("telling", "story", telling),
                ):
                    connection.execute(f"DELETE FROM {table} WHERE friend = ?", (friend,))
                    connection.executemany(
                        f"INSERT INTO {table} (friend, {column}, count) VALUES (?, ?, ?)",
                        [(friend, str(key), int(count)) for key, count in items.items()],
                    )
                if changed:
                    self._journal(connection, friend, "save", ", ".join(changed))
        except sqlite3.Error as error:
            raise DatabaseError(f"cannot write {self.path}: {error}") from error


    def forget(self, friend: str, key: str) -> bool:
        """Remove one fact, and say whether there was one."""
        self.ensure()
        try:
            with self.connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM fact WHERE friend = ? AND key = ?", (friend, key)
                )
                if cursor.rowcount:
                    self._journal(connection, friend, "forget", key)
                return bool(cursor.rowcount)
        except sqlite3.Error as error:
            raise DatabaseError(f"cannot write {self.path}: {error}") from error

    def remember_telling(self, friend: str, story: str, *, at: str = "") -> None:
        """Count a story told, in its own table rather than in the capped topic counter."""
        self.ensure()
        try:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO telling (friend, story, count, last_told) VALUES (?, ?, 1, ?)
                    ON CONFLICT(friend, story) DO UPDATE SET
                        count = count + 1,
                        last_told = excluded.last_told
                    """,
                    (friend, story, at),
                )
                self._journal(connection, friend, "story", story)
        except sqlite3.Error as error:
            raise DatabaseError(f"cannot write {self.path}: {error}") from error

    def _journal(self, connection: sqlite3.Connection, friend: str, kind: str, detail: str) -> None:
        connection.execute(
            "INSERT INTO journal (at, friend, kind, detail) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), friend, kind, detail),
        )

    # --- operations -----------------------------------------------------------------------------

    def history(self, friend: str, limit: int = 50) -> tuple[dict[str, str], ...]:
        """What changed recently, newest last. The recovery story, made inspectable."""
        self.ensure()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT at, kind, detail FROM journal WHERE friend = ? ORDER BY id DESC LIMIT ?",
                (friend, int(limit)),
            ).fetchall()
        return tuple(
            {"at": row["at"], "kind": row["kind"], "detail": row["detail"]}
            for row in reversed(rows)
        )

    def check(self) -> str:
        """``PRAGMA integrity_check``: "ok", or the reason it is not."""
        self.ensure()
        with self.connect() as connection:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])

    def backup(self, destination: Path | str) -> Path:
        """A consistent copy, even while the bot is writing. The point of a real database."""
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.ensure()
        with self.connect() as source, sqlite3.connect(target) as copy:
            source.backup(copy)
        return target

    def import_json(self, directory: Path | str) -> tuple[str, ...]:
        """One-shot import of the old per-friend files. Idempotent, and safe to re-run.

        Kept because those files still hold real memory -- the dog's name was learned before this
        module existed -- and a migration that silently drops it is not a migration.
        """
        base = Path(directory)
        imported: list[str] = []
        if not base.is_dir():
            return ()
        for candidate in sorted(base.glob("*.json")):
            friend = candidate.stem
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            existing = self.load(friend)
            if existing["facts"] or existing["person"]:
                continue  # already migrated; the database wins
            # The old shape kept "story:<id>" counts in topics; they belong in their own table.
            topics = dict(payload.get("topics") or {})
            telling = {
                str(key).split(":", 1)[1]: int(value)
                for key, value in topics.items()
                if str(key).startswith("story:")
            }
            for key in telling:
                topics.pop(f"story:{key}", None)
            self.save(
                friend,
                {
                    "person": payload.get("person") or "",
                    "last_seen": payload.get("last_seen") or "",
                    "sessions": payload.get("sessions") or 0,
                    "pending_plan": bool(payload.get("pending_plan")),
                    "facts": payload.get("facts") or (),
                    "topics": topics,
                    "pending": payload.get("pending") or {},
                    "telling": telling,
                },
                changed=["import"],
            )
            imported.append(friend)
        return tuple(imported)


def topics_of(payload: dict[str, Any]) -> Counter[str]:
    """A friend's topic counter, for callers that want it as a ``Counter``."""
    return Counter(payload.get("topics") or {})
