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
    carried: str = "",
    polarity: str = "neutral",
) -> Subject | None:
    """The subject this message names, with the fact that fits it -- or nothing.

    Returns nothing when no name is recognised, or when the character is not allowed to know that
    subject. Both mean the same thing to the caller: he has nothing to say, so the turn belongs to a
    hedge.
    """
    named = index.tags_for(text)
    allowed = _allowed(character)
    who = character.id if character is not None else None
    if not named:
        # Nothing was named. A *carried* subject is what the conversation was already about, and it is
        # only offered by the caller for a follow-up -- measured live, "do you think i should try
        # again" three turns into a conversation about a plant hedged, because a subject has to be
        # named in the same sentence or the ladder forgets it.
        if not carried:
            return None
        named = frozenset({carried})
    candidates = _candidates(named, knowledge, allowed, who)
    if not candidates and carried and carried not in named:
        # A name he cannot answer is not a reason to forget the conversation. Measured: "my last one
        # died" named topic:terry-davis (the word "died" was in one of his slot values), which Otto
        # does not know, so the plant he had been asked about two turns earlier was dropped and the
        # answer was "oh".
        named = frozenset({carried})
        candidates = _candidates(named, knowledge, allowed, who)
    if not candidates:
        return None
    # Polarity picks between the items of one subject, and it matters: "i was thinking of getting a
    # plant" is good news, and the closest item by distance was his *sympathy* line ("oh no, i am
    # sorry") because both mention a plant and "my". Sentiment is what tells the two apart.
    preferred = _by_polarity(candidates, polarity)
    if preferred:
        candidates = preferred
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


def _candidates(
    named: frozenset[str],
    knowledge: Sequence[KnowledgeItem],
    allowed: frozenset[str] | None,
    who: str | None,
) -> list[KnowledgeItem]:
    """The items that answer one of these tags, for somebody who may know them."""
    return [
        item
        for item in knowledge
        if item.tags & named and (allowed is None or item.tags & allowed) and item.owned_by(who)
    ]


def _anchor_polarity(item: KnowledgeItem) -> str:
    from ttrpg_chatbots.perceive import sentiment as sentiment_rung

    return sentiment_rung.read(item.text).polarity


def _by_polarity(
    candidates: list[KnowledgeItem], polarity: str
) -> list[KnowledgeItem]:
    """The items that do not contradict the mood, or nothing to change.

    Excluding the *opposite* rather than demanding a *match*, because a subject's anchors are mostly
    neutral: requiring a positive anchor found none, so no filtering happened and the sympathy line
    still won on distance. Measured on "i was thinking of getting a plant".

    Deliberately a preference, not a filter: if everything would be excluded, nothing is.
    """
    tiers = {
        "positive": ("positive", "neutral"),
        "negative": ("negative", "neutral"),
        # A neutral message must not reach for an extreme stance: "i was thinking of getting a plant"
        # is neither good news nor bad, and answering it with "oh no, i am sorry" was the measured
        # failure. So the neutral tier is neutral only, and the extremes are left for a mood that
        # matches them.
        "neutral": ("neutral",),
    }.get(polarity)
    if tiers is None:
        return []
    for tier in tiers:
        keep = [item for item in candidates if _anchor_polarity(item) == tier]
        if keep:
            return keep if len(keep) < len(candidates) else []
    return []


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
