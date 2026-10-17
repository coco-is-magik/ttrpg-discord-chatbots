"""Compression-classified, template-driven replies.

Pipeline per query:

1. rank knowledge items by Normalised Compression Distance (no model, no training);
2. fold the ranking into per-tag scores;
3. refuse if the character does not know the winning tag -- that is the whole
   point of the tagging system;
4. pick an in-character template for that tag and fill it with the matched fact.

Deflections use the character's fallback templates with a *restricted* slot set, so
a character that does not know a fact can never leak it.
"""

from __future__ import annotations

import hashlib
from typing import Mapping, Sequence

from ttrpg_chatbots.reply import compression, madlib
from ttrpg_chatbots.reply.ncd import DEFAULT_TOP_K, Classification, classify, normalise
from ttrpg_chatbots.reply.types import (
    Character,
    KnowledgeItem,
    Reply,
    ReplyUnavailable,
    ResponseTemplate,
    TagScore,
    UnknownCharacter,
    World,
)

WILDCARD = "*"


def _humanise(tag: str) -> str:
    """``lore:tide_gates`` -> ``tide gates``, for templates that echo the topic."""
    tail = tag.rsplit(":", 1)[-1]
    return tail.replace("_", " ").replace("-", " ")


def _sentence_case(text: str) -> str:
    """Capitalise the opening letter; templates often start with a slot."""
    return text[:1].upper() + text[1:]


class Replier:
    """Answers questions from tagged knowledge in a character's voice."""

    def __init__(
        self,
        world: World,
        *,
        compressor: compression.Compressor | None = None,
        top_k: int = DEFAULT_TOP_K,
        max_distance: float | None = None,
        margin: float = 0.0,
        seed: str = "",
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if margin < 0:
            raise ValueError("margin must not be negative")
        self._world = world
        self._compressor = (
            compressor if compressor is not None else compression.get(compression.DEFAULT)
        )
        self._top_k = top_k
        self._max_distance = max_distance
        self._margin = margin
        self._seed = seed
        self._items = {item.id: item for item in world.knowledge}
        self._index: dict[tuple[str, str], list[ResponseTemplate]] = {}
        for template in world.responses:
            for target in self._targets(template.character):
                for tag in template.tags:
                    self._index.setdefault((target, tag), []).append(template)

    @property
    def world(self) -> World:
        return self._world

    def _targets(self, character: str) -> tuple[str, ...]:
        """A template may name a character id, a display name, or ``*``."""
        if character == WILDCARD:
            return (WILDCARD,)
        try:
            return (self._world.character(character).id,)
        except UnknownCharacter:  # a hand-built World may be inconsistent
            return ()

    def classify(self, query: str) -> Classification:
        """Tag ranking for a query, with no character gating applied."""
        return classify(query, self._world.knowledge, self._compressor, top_k=self._top_k)

    def reply(self, query: str, character: str, *, speaker: str | None = None) -> Reply:
        """Answer ``query`` as ``character``, or deflect in character.

        The tag is chosen *within the character's knowledge*. When one fact carries
        several tags (a battle that is both history and geography), a historian and
        a guide can both answer it, each from their own tag.
        """
        who = self._world.character(character)
        classification = self.classify(query)
        chosen = self._select(who, classification)
        if chosen is None:
            return self._deflect(who, classification, speaker)
        item = self._items[chosen.ref]
        return self._answer(who, chosen.tag, item, classification, speaker)

    def _select(self, who: Character, classification: Classification) -> TagScore | None:
        """Best tag that this character may speak about.

        Only tags tied with (or within ``margin`` of) the winning distance are
        considered. Without that guard a character could answer a ritual question
        with the one rumour item that happens to rank fifth, which is worse than
        deflecting.
        """
        if not classification.tags:
            return None
        limit = classification.tags[0].distance + self._margin
        for score in classification.tags:
            if score.distance > limit:
                break
            if score.tag not in who.known_tags:
                continue
            if self._max_distance is not None and score.distance > self._max_distance:
                continue
            return score
        return None

    def _answer(
        self,
        who: Character,
        tag: str,
        item: KnowledgeItem,
        classification: Classification,
        speaker: str | None,
    ) -> Reply:
        values = {
            "character": who.name,
            "fact": item.text,
            "topic": item.slots.get("topic") or _humanise(tag),
            **item.slots,
        }
        if speaker:
            values["speaker"] = speaker

        filled = self._fill(
            self._candidates(who, tag),
            f"{self._seed}|{who.id}|{tag}|{normalise(classification.query)}",
            values,
        )
        if filled is None:
            # Nothing for this tag could be filled; do not leak the fact.
            return self._deflect(who, classification, speaker)

        template, text = filled
        return Reply(
            text=_sentence_case(text),
            character=who.id,
            tag=tag,
            knowledge_id=item.id,
            template_id=template.id,
            distance=classification.distance,
            known=True,
        )

    def _deflect(
        self, who: Character, classification: Classification, speaker: str | None
    ) -> Reply:
        """Say "not my field" without handing over the fact."""
        values: dict[str, str] = {
            "character": who.name,
            "topic": _humanise(classification.best_tag or "that"),
        }
        if speaker:
            values["speaker"] = speaker

        filled = self._fill(
            self._candidates(who, who.fallback_tag),
            f"{self._seed}|{who.id}|{who.fallback_tag}|{normalise(classification.query)}",
            values,
        )
        if filled is None:
            raise ReplyUnavailable(
                f"character {who.id!r} has no {who.fallback_tag!r} reply it can fill"
            )
        template, text = filled
        return Reply(
            text=_sentence_case(text),
            character=who.id,
            tag=None,
            knowledge_id=None,
            template_id=template.id,
            distance=classification.distance,
            known=False,
        )

    def _candidates(self, who: Character, tag: str) -> Sequence[ResponseTemplate]:
        return (
            *self._index.get((who.id, tag), ()),
            *self._index.get((WILDCARD, tag), ()),
        )

    def _fill(
        self, candidates: Sequence[ResponseTemplate], key: str, values: Mapping[str, str]
    ) -> tuple[ResponseTemplate, str] | None:
        """Pick a template deterministically, skipping ones this data cannot fill.

        Rotation happens *within* a group, so a character never answers in the
        generic wildcard voice while one of its own lines is available.
        """
        owned = [template for template in candidates if template.character != WILDCARD]
        generic = [template for template in candidates if template.character == WILDCARD]
        if not owned and not generic:
            return None

        digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
        for group in (owned, generic):
            ordered = sorted(group, key=lambda template: template.id)
            if not ordered:
                continue
            start = int.from_bytes(digest, "big") % len(ordered)
            for offset in range(len(ordered)):
                template = ordered[(start + offset) % len(ordered)]
                try:
                    text = madlib.render(template.template, values)
                except (madlib.MissingSlot, ValueError):
                    continue
                if text.strip():
                    return template, text
        return None

