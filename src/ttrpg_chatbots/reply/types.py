"""Value types for the compression-classified reply engine.

These are the stable part of the design: datasets load into them, the classifier
consumes them, and templates render from them. Nothing here knows about files,
JSONL or compressors, so the storage format can change without touching them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class ReplyError(RuntimeError):
    """Base class for reply-engine failures."""


class DatasetError(ReplyError):
    """Raised when dataset files are missing, malformed or inconsistent."""


class UnknownCharacter(DatasetError):
    """Raised when a reply is requested for a character that does not exist."""


class ReplyUnavailable(ReplyError):
    """Raised when no template can produce a reply for a character."""


@dataclass(frozen=True)
class KnowledgeItem:
    """One tagged fact a character may know.

    ``slots`` holds the madlib vocabulary that goes with the fact ("the Sunken
    Crown", "Greyfall"); it is also searched, so a question about the crown
    matches even when the prose alone would not.

    ``reply`` is what the character *says* when this item is matched, and it is
    deliberately not what gets searched. Compression distance rewards an item that
    is shaped like the question, while a person in a mood speaks in sentences
    shaped like a person in a mood -- measured on the friends world, a spoken
    stance as the search text scored 0.69-0.86 against the questions it answered,
    while a question-shaped anchor plus a separate reply scored 0.18-0.50. So the
    anchor does the matching and ``spoken`` does the talking; when ``reply`` is
    absent the two are the same thing, which is what every lore item wants.
    """

    id: str
    text: str
    tags: frozenset[str]
    slots: Mapping[str, str] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)
    reply: str | None = None
    character: str = "*"

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("knowledge id must not be empty")
        if not self.text.strip():
            raise ValueError(f"knowledge {self.id!r} has no text")
        if not self.tags or any(not tag.strip() for tag in self.tags):
            raise ValueError(f"knowledge {self.id!r} must have non-blank tags")
        if self.reply is not None and not self.reply.strip():
            raise ValueError(f"knowledge {self.id!r} has an empty reply")

    def owned_by(self, who: str | None) -> bool:
        """May this character say it? Shared lines belong to everybody.

        Two friends can hold the same subject without sharing a mouth: `topic:computers` is one tag,
        but Terry's line about machines is not Otto's, and a shared tag alone used to mean whichever
        line happened to score closest got spoken -- by either of them.
        """
        return who is None or self.character == "*" or self.character == who

    @property
    def search_text(self) -> str:
        """Prose plus slot values -- what compression distance is measured on."""
        parts = [self.text, *self.slots.values()]
        return " ".join(part for part in parts if part)

    @property
    def spoken(self) -> str:
        """What to say when this item is matched: the reply, else the text itself."""
        return self.reply.strip() if self.reply else self.text


@dataclass(frozen=True)
class ResponseTemplate:
    """An in-character madlib. ``character`` may be ``"*"`` for any character."""

    id: str
    character: str
    tags: frozenset[str]
    template: str
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("response id must not be empty")
        if not self.character.strip():
            raise ValueError(f"response {self.id!r} has no character")
        if not self.tags or any(not tag.strip() for tag in self.tags):
            raise ValueError(f"response {self.id!r} must have non-blank tags")
        if not self.template.strip():
            raise ValueError(f"response {self.id!r} has an empty template")


@dataclass(frozen=True)
class Character:
    """A character: what it knows, what it *is*, and how it sounds.

    ``known_tags`` gates knowledge -- a character may only speak about these.
    ``tags`` describe the character itself (``role:scholar``, ``species:dwarf``) and
    are what voice casting matches on. The two are deliberately separate: knowing
    about relics and being a dwarf are different kinds of fact.
    """

    id: str
    name: str
    known_tags: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    fallback_tag: str = "fallback"
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("character id must not be empty")
        if not self.name.strip():
            raise ValueError(f"character {self.id!r} has no name")
        if not self.fallback_tag.strip():
            raise ValueError(f"character {self.id!r} has a blank fallback_tag")

    @property
    def aliases(self) -> frozenset[str]:
        return frozenset({self.id, self.name})


@dataclass(frozen=True)
class Match:
    """One knowledge item ranked against a query."""

    ref: str
    distance: float


@dataclass(frozen=True)
class TagScore:
    """The best distance any knowledge item carrying ``tag`` achieved."""

    tag: str
    distance: float
    ref: str


@dataclass(frozen=True)
class Classification:
    """Provenance for a decision, so callers can log or explain it."""

    query: str
    compressor: str
    tags: tuple[TagScore, ...]
    matches: tuple[Match, ...]
    best_item: KnowledgeItem | None

    @property
    def best_tag(self) -> str | None:
        return self.tags[0].tag if self.tags else None

    @property
    def distance(self) -> float | None:
        return self.tags[0].distance if self.tags else None


@dataclass(frozen=True)
class Reply:
    """A rendered in-character line and where every part of it came from.

    ``detail`` carries anything the caller should log but not say: the acts this message
    could have been, the turn it followed, the sequence it landed in. It is metadata, so
    it never affects the text.
    """

    text: str
    character: str
    tag: str | None
    knowledge_id: str | None
    template_id: str
    distance: float | None = None
    known: bool = True
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("reply text must not be empty")


@dataclass(frozen=True)
class World:
    """A loaded dataset: who exists, what is known, what can be said."""

    name: str
    knowledge: tuple[KnowledgeItem, ...]
    responses: tuple[ResponseTemplate, ...]
    characters: tuple[Character, ...]

    def character(self, name_or_id: str) -> Character:
        wanted = name_or_id.strip().lower()
        for character in self.characters:
            if wanted in {alias.lower() for alias in character.aliases}:
                return character
        known = ", ".join(character.id for character in self.characters)
        raise UnknownCharacter(f"unknown character {name_or_id!r}; known characters: {known}")

    @property
    def tags(self) -> frozenset[str]:
        return frozenset(tag for item in self.knowledge for tag in item.tags)
