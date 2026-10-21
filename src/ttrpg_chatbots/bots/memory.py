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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path("data/friends")
MEMORY_ENV = "TTRPG_FRIENDS_MEMORY_DIR"
SCHEMA_VERSION = 1


class MemoryError(RuntimeError):
    """Raised when a memory file cannot be read or written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FriendMemory:
    """One friend's long-term memory: who, when, and what is still open."""

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
    ) -> None:
        self.friend = friend
        inside = os.environ.get(MEMORY_ENV, "").strip()
        base = directory or (Path(inside) if inside else DEFAULT_DIR)
        self.path = base / f"{friend}.json"
        self.person = person
        self.last_seen = last_seen
        self.sessions = sessions
        self.pending_plan = pending_plan
        self.topics: Counter[str] = Counter(topics or {})

    @classmethod
    def load(cls, friend: str, *, directory: Path | None = None) -> FriendMemory:
        """Read a friend's memory; a missing file is an empty memory, never an error."""
        memory = cls(friend, directory=directory)
        if not memory.path.is_file():
            return memory
        try:
            data: dict[str, Any] = json.loads(memory.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise MemoryError(f"cannot read {memory.path}: {error}") from error
        memory.person = str(data.get("person") or "")
        memory.last_seen = str(data.get("last_seen") or "")
        memory.sessions = int(data.get("sessions") or 0)
        memory.pending_plan = bool(data.get("pending_plan"))
        memory.topics = Counter(
            {str(key): int(value) for key, value in (data.get("topics") or {}).items()}
        )
        return memory

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "friend": self.friend,
            "person": self.person,
            "last_seen": self.last_seen,
            "sessions": self.sessions,
            "pending_plan": self.pending_plan,
            "topics": dict(self.topics.most_common(20)),
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            temporary.replace(self.path)
        except OSError as error:
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
