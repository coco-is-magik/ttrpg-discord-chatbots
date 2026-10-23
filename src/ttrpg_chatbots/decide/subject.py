"""Is this about something he actually knows, and what does he say about it?

The last piece that was still on the old path. Until now a subject question ("do you like hockey?",
"who is terry davis") went to the compression classifier, which meant one conversation was answered by
two engines with two sets of rules: the ladder's answers were one to four words and never ended on a
beat, the classifier's were paragraphs. This module gives the ladder a *tool* instead of a second
brain: it answers one question -- which subject did they name, and which of his facts fits it -- and
returns a value the phrasebooks can use like any other.

Two signals, in this order, and the order matters:

1. **The name**, from `reply.entities` -- a vocabulary of the words each subject goes by. "howre the
   rangers doing?" names the Rangers whether or not it is shaped like a question.
2. **Distance**, from `reply.ncd`, but only *within* the subject the name found -- to choose which of
   that subject's facts fits best. It is never asked "is this about hockey at all".

There is deliberately **no distance ceiling here**, and that is a measured decision rather than an
omission. A ceiling answers "is this close enough to be about this subject?", which is the question
the entity index has already answered by naming it. Applied on top, it refused
`howre the rangers doing?` at 0.651 -- a message with the word *rangers* in it -- and, absurdly,
refused the correctly spelled version at 0.662 as well. The name is the gate; distance only ranks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ttrpg_chatbots.reply.compression import DEFAULT as DEFAULT_COMPRESSOR
from ttrpg_chatbots.reply.entities import EntityIndex
from ttrpg_chatbots.reply.ncd import get as compressor, rank
from ttrpg_chatbots.reply.types import Character, KnowledgeItem


@dataclass(frozen=True)
class Subject:
    """A subject they named, and what he has to say about it."""

    tag: str
    item_id: str
    text: str  # the fact, or the stance when the item has one
    distance: float

    @property
    def is_stance(self) -> bool:
        return bool(self.text)


def choose(
    *,
    text: str,
    index: EntityIndex,
    knowledge: Sequence[KnowledgeItem],
    character: Character | None = None,
) -> Subject | None:
    """The subject this message names, with the fact that fits it -- or nothing.

    Returns nothing when no name is recognised, or when the character is not allowed to know that
    subject. Both mean the same thing to the caller: he has nothing to say, so the turn belongs to a
    hedge.
    """
    named = index.tags_for(text)
    if not named:
        return None
    allowed = _allowed(character)
    who = character.id if character is not None else None
    candidates = [
        item
        for item in knowledge
        if item.tags & named
        and (allowed is None or item.tags & allowed)
        and item.owned_by(who)
    ]
    if not candidates:
        return None
    ranked = rank(text, candidates, compressor(DEFAULT_COMPRESSOR))
    if not ranked:
        return None
    best = ranked[0]
    item = next((candidate for candidate in candidates if candidate.id == best.ref), None)
    if item is None:  # pragma: no cover - rank only returns ids from the corpus
        return None
    return Subject(
        tag=_best_tag(item.tags & named),
        item_id=item.id,
        text=_spoken(item),
        distance=best.distance,
    )


def _allowed(character: Character | None) -> frozenset[str] | None:
    """The subjects this character may speak about, or ``None`` for "anything"."""
    if character is None:
        return None
    return character.known_tags or None


def _best_tag(tags: Iterable[str]) -> str:
    return sorted(tags)[0] if tags else ""


def _spoken(item: KnowledgeItem) -> str:
    """What he says: the stance when the item has one, the fact otherwise."""
    return (item.reply or item.text).strip()
