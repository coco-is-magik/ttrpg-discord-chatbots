"""What a friend knows, one subject area at a time.

The third kind of corpus. The other two answer different questions:

* **phrasebooks** -- *how* he says a thing, by job, overridable per friend;
* **life** -- what is happening to him (activities, grievances, stories, plans);
* **domains** -- what he knows and can talk about in depth, **one folder per subject area**.

Why a folder per area rather than one big file: the corpus is going to grow, and it has to grow in precise
places. `knowledge.jsonl` is 294 lines covering every subject for every friend, so adding depth to *trains*
means editing a file where a mistake lands on Rome. A domain is the unit of expansion -- add a folder, or add
one aspect to one folder -- and everything else is untouched. See `docs/CORPUS.md`.

The shape of a domain:

    domains/trains/domain.json    the area: how it is referred to, and its aspects
    domains/trains/friend-b.jsonl one friend's material in that area, tagged by aspect

An **aspect** is the part of an area a conversation can actually reach: "the old ones", "the timetable". Each
aspect carries the questions a friend might ask about it and, per friend, the lines he can answer with. That
is what makes a hook takeable -- "i have been rearranging my shelf" is a hook, "what is on it?" is a dig, and
an answer needs both sides to have material for *the shelf* rather than for shelves in general.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

#: Where domains live inside a world.
DOMAIN_DIR = "domains"
DOMAIN_FILE = "domain.json"


class DomainError(RuntimeError):
    """Raised when a domain file cannot be used."""


@dataclass(frozen=True)
class Aspect:
    """One reachable part of a subject area: how it is named, and what can be asked about it."""

    name: str
    names: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainError("an aspect needs a name")
        if not self.names:
            raise DomainError(f"aspect {self.name!r} needs names: without them nothing can reach it")
        if not self.questions:
            raise DomainError(f"aspect {self.name!r} needs questions: nothing can be asked about it")


@dataclass
class Domain:
    """A subject area, with the aspects a conversation can reach."""

    id: str
    names: tuple[str, ...]
    aspects: dict[str, Aspect] = field(default_factory=dict)
    #: One friend's lines, by aspect. Answers to a dig come from here.
    answers: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise DomainError("a domain needs an id")
        if not self.names:
            raise DomainError(f"domain {self.id!r} needs names: nothing can mention it")


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9']+", text.lower()) if word]


def _mentioned(name: str, words: set[str], text: str) -> bool:
    """Whether a name is present as a whole phrase."""
    parts = _words(name)
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in words
    return " ".join(parts) in " ".join(_words(text))


@dataclass
class DomainBook:
    """Every domain in a world, plus one friend's material in all of them."""

    domains: dict[str, Domain] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.domains)

    def find(self, text: str) -> tuple[Domain, Aspect] | None:
        """Which aspect of which area this mentions, if any.

        Whole words only, and the longest name wins: "the old ones" beats "the old", and "train" does not
        match "training". Same discipline as the entity index -- fuzzy matching here is how a bot decides the
        weather is about trains.
        """
        words = set(_words(text))
        if not words:
            return None
        best: tuple[int, Domain, Aspect] | None = None
        for domain in self.domains.values():
            for aspect in domain.aspects.values():
                for name in aspect.names:
                    if _mentioned(name, words, text):
                        score = len(name)
                        if best is None or score > best[0]:
                            best = (score, domain, aspect)
        if best is not None:
            return best[1], best[2]
        for domain in self.domains.values():
            for name in domain.names:
                if _mentioned(name, words, text):
                    # The area is mentioned but no aspect of it: the first aspect is the way in.
                    first = next(iter(domain.aspects.values()), None)
                    if first is not None:
                        return domain, first
        return None

    def questions(self, aspect: Aspect, *, avoid: Iterable[str] = ()) -> tuple[str, ...]:
        """Questions for this aspect, minus any asked recently."""
        used = {question.strip().lower() for question in avoid}
        return tuple(question for question in aspect.questions if question.strip().lower() not in used)

    def answers(self, domain: Domain, aspect: Aspect, *, avoid: Iterable[str] = ()) -> tuple[str, ...]:
        """One friend's lines for this aspect, minus any he has already used."""
        used = {line.strip().lower() for line in avoid}
        lines = domain.answers.get(aspect.name, [])
        fresh = [line for line in lines if line.strip().lower() not in used]
        return tuple(fresh or lines)


def _aspect(record: Mapping[str, Any], *, where: str) -> Aspect:
    name = str(record.get("name") or "").strip()
    if not name:
        raise DomainError(f"{where}: an aspect needs a name")
    return Aspect(
        name=name,
        names=tuple(str(item) for item in record.get("names") or ()),
        questions=tuple(str(item) for item in record.get("questions") or ()),
    )


def load(folder: Path | str, *, friend: str | None = None) -> DomainBook:
    """Every domain under a world's ``domains/`` folder, with one friend's material merged in."""
    base = Path(folder)
    book = DomainBook()
    if not base.exists():
        return book
    for path in sorted(base.glob(f"*/{DOMAIN_FILE}")):
        record = json.loads(path.read_text(encoding="utf-8"))
        identifier = str(record.get("id") or path.parent.name).strip()
        aspects = {
            aspect.name: aspect
            for aspect in (_aspect(item, where=str(path)) for item in record.get("aspects") or ())
        }
        if not aspects:
            raise DomainError(f"{path}: no aspects, so nothing in this domain can be reached")
        domain = Domain(
            id=identifier,
            names=tuple(str(item) for item in record.get("names") or (identifier,)),
            aspects=aspects,
        )
        if friend:
            material = path.parent / f"{friend}.jsonl"
            if material.exists():
                for line in material.read_text(encoding="utf-8").splitlines():
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    item = json.loads(line)
                    text = str(item.get("text") or "").strip()
                    aspect = str(item.get("aspect") or "").strip()
                    if not text or not aspect:
                        raise DomainError(f"{material}: every line needs text and an aspect")
                    if aspect not in domain.aspects:
                        raise DomainError(
                            f"{material}: aspect {aspect!r} is not in {path.name} "
                            f"({sorted(domain.aspects)})"
                        )
                    domain.answers.setdefault(aspect, []).append(text)
        book.domains[identifier] = domain
    return book
