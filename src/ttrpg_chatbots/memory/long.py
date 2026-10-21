"""What we durably know.

A fact is a key, a value, who said it, and how many times. Same key means same fact: saying "my dog
is called Otis" twice does not create two dogs, and saying
"my dog is called Rufus" replaces the name rather than living beside it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable


@dataclass(frozen=True)
class Fact:
    """One thing worth keeping: ``pet.name`` = ``Otis``."""

    key: str
    value: str
    said_by: str = "them"
    first_seen: str = ""
    last_seen: str = ""
    count: int = 1
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("a fact needs a key")
        if not self.value.strip():
            raise ValueError(f"fact {self.key!r} has no value")


class LongTerm:
    """Facts by key. Adding a fact with a known key updates it."""

    def __init__(self, facts: Iterable[Fact] = ()) -> None:
        self._facts: dict[str, Fact] = {fact.key: fact for fact in facts}

    def __len__(self) -> int:
        return len(self._facts)

    def __iter__(self):
        return iter(self._facts.values())

    def get(self, key: str) -> Fact | None:
        return self._facts.get(key)

    def add(self, fact: Fact, *, now: str = "") -> Fact:
        """Store a fact, bumping its count if the key is already known."""
        existing = self._facts.get(fact.key)
        if existing is None:
            stored = replace(fact, first_seen=fact.first_seen or now, last_seen=now or fact.last_seen)
        else:
            stored = replace(
                existing,
                value=fact.value,
                said_by=fact.said_by,
                last_seen=now or existing.last_seen,
                count=existing.count + 1,
            )
        self._facts[stored.key] = stored
        return stored

    def by_prefix(self, prefix: str) -> tuple[Fact, ...]:
        return tuple(fact for key, fact in sorted(self._facts.items()) if key.startswith(prefix))

    def to_records(self) -> dict[str, Any]:
        return {"facts": {key: fact.value for key, fact in sorted(self._facts.items())}}

    @classmethod
    def from_records(cls, data: dict[str, Any]) -> LongTerm:
        facts = [
            Fact(key=key, value=str(value))
            for key, value in (data.get("facts") or {}).items()
        ]
        return cls(facts)
