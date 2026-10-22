"""What a friend remembers between sessions.

Two kinds of memory, and they are different problems. **Short-term** is the last few turns of a
conversation: it lives in RAM, in `reply/context.py`, and dies with the process, which is correct.
**Long-term** is what should survive a restart: who you are, when you last spoke, and what you
have left hanging. That is this module.

It is deliberately small and inspectable -- one JSON file per friend under `data/friends/`,
holding a name, a timestamp, a pending invitation and a count of the subjects you raised. No
embeddings, no rolling summaries, nothing a person cannot read in ten seconds. Memory that cannot
be inspected is memory that will surprise you on game night.

Nothing here decides anything. It records what the bot observed, so the layer above can decide
what to do with it -- which is why it has no imports from the reply engine.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ttrpg_chatbots.memory import promote
from ttrpg_chatbots.memory.long import Fact, LongTerm
from ttrpg_chatbots.memory.db import Database, DatabaseError

DEFAULT_DIR = Path("data")
DB_FILENAME = "memory.db"
MEMORY_ENV = "TTRPG_FRIENDS_MEMORY_DIR"

# Mentions that did not earn a place yet are the only part of the file that could grow without
# bound: every refused "i like x" would leave a key for ever. Fifty is far more than a person
# says in the window that matters, and the cap is applied on write so the file cannot creep.
PENDING_LIMIT = 50


class MemoryError(RuntimeError):
    """Raised when a memory file cannot be read or written."""


def migrate_legacy(directory: Path | str | None = None) -> tuple[str, ...]:
    """Import the old per-friend JSON files into the database, once.

    Those files still hold real memory -- the dog's name was learned before the database
    existed -- so the import is part of the upgrade rather than an optional extra. It is
    idempotent: a friend already in the database is left alone.
    """
    inside = os.environ.get(MEMORY_ENV, "").strip()
    base = Path(directory or inside or DEFAULT_DIR)
    return Database(base / DB_FILENAME).import_json(base / "friends")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fact_record(fact: Fact) -> dict[str, Any]:
    """One fact as it goes to disk. Readable on purpose: memory you cannot inspect is memory that
    will surprise you on game night."""
    return {
        "key": fact.key,
        "value": fact.value,
        "said_by": fact.said_by,
        "first_seen": fact.first_seen,
        "last_seen": fact.last_seen,
        "count": fact.count,
        "meta": dict(fact.meta),
    }


def _facts_from_records(records: Any) -> tuple[Fact, ...]:
    """Facts read back from disk. A malformed record is skipped, never fatal."""
    if isinstance(records, dict):  # the older shape, key -> value
        records = [{"key": key, "value": value} for key, value in records.items()]
    facts: list[Fact] = []
    for record in records or ():
        if not isinstance(record, dict):
            continue
        try:
            facts.append(
                Fact(
                    key=str(record.get("key") or ""),
                    value=str(record.get("value") or ""),
                    said_by=str(record.get("said_by") or "them"),
                    first_seen=str(record.get("first_seen") or ""),
                    last_seen=str(record.get("last_seen") or ""),
                    count=int(record.get("count") or 1),
                    meta=dict(record.get("meta") or {}),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(facts)


class FriendMemory:
    """One friend's long-term memory: who, when, what is still open, and what you told them."""

    def __init__(
        self,
        friend: str,
        *,
        directory: Path | None = None,
        person: str = "",
        last_seen: str = "",
        sessions: int = 0,
        pending_plan: bool = False,
        topics: dict[str, int] | None = None,
        facts: Iterable[Fact] = (),
        pending: dict[str, int] | None = None,
    ) -> None:
        self.friend = friend
        inside = os.environ.get(MEMORY_ENV, "").strip()
        base = directory or (Path(inside) if inside else DEFAULT_DIR)
        # One database for every friend, not one document each: measured, the document was rewritten
        # whole on every save, up to four times per message, over NFS. See `memory/db.py`.
        self._db = Database(base / DB_FILENAME)
        self.path = self._db.path
        self.person = person
        self.last_seen = last_seen
        self.sessions = sessions
        self.pending_plan = pending_plan
        self.topics: Counter[str] = Counter(topics or {})
        self._long = LongTerm(facts)
        # Mentions that did not earn a place yet, counted by "key=value". Without this the rule
        # "kept when said twice" could never fire: the first mention left no trace, so the second
        # looked like the first.
        self._pending: Counter[str] = Counter(pending or {})
        # Stories told, in their own table rather than in the capped topic counter.
        self.telling: Counter[str] = Counter()

    @property
    def facts(self) -> tuple[Fact, ...]:
        """Everything he durably knows about this person."""
        return tuple(self._long)

    def fact(self, key: str) -> Fact | None:
        return self._long.get(key)

    def remember_facts(self, candidates: Iterable[Fact], *, now: str = "") -> tuple[Fact, ...]:
        """Keep the facts that earn it, and return what was stored.

        Promotion is the gate that keeps memory from filling with noise: pets and jobs are kept the
        first time, everything else has to be said twice -- which only means anything if the first
        mention is counted, so refusals are remembered in `pending` rather than dropped.
        """
        kept: list[Fact] = []
        for fact in candidates:
            existing = self._long.get(fact.key)
            tally = f"{fact.key}={fact.value}"
            count = (existing.count + 1) if existing else self._pending[tally] + 1
            if not promote.decide(kind=fact.key, count=count, said_by=fact.said_by):
                self._pending[tally] = count
                continue
            kept.append(self._long.add(fact, now=now or _now()))
            self._pending.pop(tally, None)
        return tuple(kept)

    def mark_raised(self, key: str, *, day: str) -> None:
        """Record that he brought this fact up, so he does not bring it up again today."""
        self._long.tag(key, raised=day)

    def forget(self, key: str) -> bool:
        """Drop a fact, because the person asked. Deletes the row and journals it."""
        known = self._long.get(key) is not None
        try:
            dropped = self._db.forget(self.friend, key)
        except DatabaseError as error:
            raise MemoryError(f"cannot write {self.path}: {error}") from error
        self._long.forget(key)
        return known or dropped

    def remember_told(self, story: str) -> None:
        """Count a story told, so he does not lead with it again tomorrow."""
        self.telling[story] += 1
        try:
            self._db.remember_telling(self.friend, story, at=_now())
        except DatabaseError as error:
            raise MemoryError(f"cannot write {self.path}: {error}") from error

    @classmethod
    def load(cls, friend: str, *, directory: Path | None = None) -> FriendMemory:
        """Read a friend's memory. An unknown friend is an empty memory, never an error."""
        memory = cls(friend, directory=directory)
        try:
            data: dict[str, Any] = memory._db.load(friend)
            memory.telling = Counter(data.get("telling") or {})
        except DatabaseError as error:
            raise MemoryError(f"cannot read {memory.path}: {error}") from error
        memory.person = str(data.get("person") or "")
        memory.last_seen = str(data.get("last_seen") or "")
        memory.sessions = int(data.get("sessions") or 0)
        memory.pending_plan = bool(data.get("pending_plan"))
        memory.topics = Counter(
            {str(key): int(value) for key, value in (data.get("topics") or {}).items()}
        )
        memory._long = LongTerm(_facts_from_records(data.get("facts") or ()))
        return memory

    def save(self) -> None:
        """Write this friend's memory, row-scoped and transactional."""
        payload = {
            "person": self.person,
            "last_seen": self.last_seen,
            "sessions": self.sessions,
            "pending_plan": self.pending_plan,
            "topics": dict(self.topics.most_common(20)),
            "facts": [_fact_record(fact) for fact in self._long],
            "pending": dict(self._pending.most_common(PENDING_LIMIT)),
            "telling": dict(self.telling),
        }
        try:
            self._db.save(self.friend, payload, changed=["memory"])
        except DatabaseError as error:
            raise MemoryError(f"cannot write {self.path}: {error}") from error

    def note(self, *, person: str = "", tags: frozenset[str] = frozenset()) -> None:
        """Record that the person spoke: who they are, when, and what they raised."""
        if person.strip():
            self.person = person.strip()
        self.last_seen = _now()
        self.sessions += 1
        self.topics.update(sorted(tags))

    def remember_topic(self, tag: str | None) -> None:
        """Count what this person actually asks about, so he can lead with it later."""
        if tag:
            self.topics[tag] += 1

    def remember_plan(self) -> None:
        """They were invited somewhere and have not answered yet."""
        self.pending_plan = True
        self.last_seen = _now()

    def clear_plan(self) -> None:
        self.pending_plan = False

    @property
    def top_topic(self) -> str | None:
        """The subject this person asks about most, if any."""
        return self.topics.most_common(1)[0][0] if self.topics else None

    def describe(self) -> str:
        """One line for a log: who, when, and anything left open."""
        bits = []
        if self.person:
            bits.append(f"remembers {self.person}")
        if self.last_seen:
            bits.append(f"last seen {self.last_seen}")
        if self.top_topic:
            bits.append(f"asks about {self.top_topic.rsplit(':', 1)[-1]}")
        if self.pending_plan:
            bits.append("has an unanswered invitation")
        return f"{self.friend}: " + (", ".join(bits) if bits else "nothing yet")
