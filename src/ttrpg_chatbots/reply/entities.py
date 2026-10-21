"""Which subject a message is about, even when it is not shaped like a question.

Compression distance is a shape metric. "howre the rangers doing?" is not shaped like "what about
the rangers?", so it scored above the ceiling and was refused -- on 2026-10-21, with the word
"rangers" right there in the message. Distance is good at "does this read like that"; it is bad at
"did they name the thing".

So the classifier gets a second, much dumber signal: a vocabulary of the names each subject goes
by, assembled from the tag itself and the slot values already in the dataset. A word either
appears as a whole word or it does not -- no fuzz, no stemming, no embeddings. Fuzzy entity
matching is how a bot decides the weather is about hockey.

This is a *narrower* signal than distance, not a replacement: it says which subject, never which
fact. The fact is still chosen by distance within that subject.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ttrpg_chatbots.reply.text import normalise_typing
from ttrpg_chatbots.reply.types import KnowledgeItem

# Words too common to identify anything. Kept short and obvious: the point is to catch the
# generic nouns that live in slot values ("the game", "the shot"), not to be a real stoplist.
_IGNORED = frozenset(
    {
        "about",
        "after",
        "best",
        "game",
        "games",
        "history",
        "life",
        "little",
        "much",
        "place",
        "really",
        "round",
        "season",
        "shot",
        "something",
        "subject",
        "team",
        "teams",
        "that",
        "their",
        "there",
        "these",
        "thing",
        "things",
        "this",
        "topic",
        "what",
        "when",
        "where",
        "which",
        "with",
        "your",
    }
)

MIN_TERM = 4
_WORDS = re.compile(r"[a-z0-9]+")


def _terms(text: str) -> Iterable[str]:
    for word in _WORDS.findall((text or "").lower().replace("-", " ").replace("_", " ")):
        if len(word) >= MIN_TERM and word not in _IGNORED:
            yield word


class EntityIndex:
    """Maps a name to the subjects that go by it. Built once, from the dataset."""

    def __init__(self, items: Iterable[KnowledgeItem]) -> None:
        self._tags: dict[str, frozenset[str]] = {}
        index: dict[str, set[str]] = {}
        for item in items:
            for source in self._names_of(item):
                for term in _terms(source):
                    index.setdefault(term, set()).update(item.tags)
        self._tags = {term: frozenset(tags) for term, tags in index.items()}

    @staticmethod
    def _names_of(item: KnowledgeItem) -> tuple[str, ...]:
        """Every name this item's subject goes by: its tags, and its slot values."""
        names = [tag.rsplit(":", 1)[-1] for tag in item.tags]
        names.extend(item.slots.values())
        return tuple(names)

    @property
    def vocabulary(self) -> tuple[str, ...]:
        return tuple(sorted(self._tags))

    def tags_for(self, text: str) -> frozenset[str]:
        """Subjects named anywhere in this message, in any order."""
        found: set[str] = set()
        for word in _WORDS.findall(normalise_typing(text)):
            found.update(self._tags.get(word, ()))
        return frozenset(found)
