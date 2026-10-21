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
from dataclasses import replace
from typing import Any, Mapping, Sequence

from ttrpg_chatbots.reply import compression, madlib
from ttrpg_chatbots.reply import intents as social
from ttrpg_chatbots.reply.context import Context
from ttrpg_chatbots.reply.ncd import DEFAULT_TOP_K, Classification, classify, normalise
from ttrpg_chatbots.reply.transitions import TransitionModel
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
        rotate: bool = False,
        transitions: TransitionModel | None = None,
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
        # Without a table, context changes nothing: `plausible` is true for every act and
        # the priority order below decides alone. A table only ever *vetoes* an act that
        # is rarer after the previous one than chance would predict.
        self._transitions = transitions
        # Rotation is opt-in: a replay or a test wants the same query to give the same line,
        # but a conversation wants "hey" twice not to sound like a broken record. The last
        # template per (character, tag) is skipped while another candidate remains.
        self._rotate = rotate
        self._last: dict[tuple[str, str], str] = {}
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

    def reply(
        self,
        query: str,
        character: str,
        *,
        speaker: str | None = None,
        context: Context | None = None,
        addressed: bool = True,
    ) -> Reply | None:
        """Answer ``query`` as ``character``, deflect in character, or stay quiet.

        The tag is chosen *within the character's knowledge*. When one fact carries
        several tags (a battle that is both history and geography), a historian and
        a guide can both answer it, each from their own tag.

        Social moves are matched before compression runs: "hey" and "thanks" are not
        facts, and measuring them against lore is how a greeting ends up answered
        with a rumour. If no social intent matches, the knowledge classifier decides.

        ``context`` is what the room said just before this. It is used for two things
        only: to prefer a reading of an ambiguous move that makes sense where it landed,
        and -- when the bot is *not* being addressed -- to stay quiet rather than repeat
        itself. ``None`` returns exactly the context-free answer.

        Returns ``None`` for silence. That is a real outcome in a group chat, not an
        error: see ``friend`` etiquette in the module docstring of ``bots/chat.py``.
        """
        who = self._world.character(character)
        matches = social.match_all(query)
        tag = self._choose_act(matches, context)
        answer = self._compose(
            who, tag, query, speaker, context=context, addressed=addressed
        )
        if answer is None:
            return None
        return self._annotate(answer, context, matches)

    def _compose(
        self,
        who: Character,
        tag: str | None,
        query: str,
        speaker: str | None,
        *,
        context: Context | None,
        addressed: bool,
    ) -> Reply | None:
        """Render the chosen move, or fall through to the knowledge classifier."""
        if tag is not None and tag in who.known_tags:
            if self._declines(query, tag, context, addressed):
                return None
            rendered = self._answer_intent(who, tag, query, speaker)
            if rendered is not None:
                return rendered

        classification = self.classify(query)
        chosen = self._select(who, classification)
        if chosen is None:
            return self._deflect(who, classification, speaker)
        item = self._items[chosen.ref]
        return self._answer(who, chosen.tag, item, classification, speaker)

    def _choose_act(
        self, matches: tuple[str, ...], context: Context | None
    ) -> str | None:
        """The first matching move that could plausibly land where this one did.

        Priority order alone answers "hey, anyone around tonight?" as a presence
        question, which is right. Context only overrules it when the priority answer is
        implausible after the previous turn -- for instance a greeting in reply to a
        goodbye -- and another reading is not.
        """
        if not matches:
            return None
        if context is None or self._transitions is None:
            return matches[0]
        previous = context.previous_act
        for tag in matches:
            if self._transitions.plausible(tag, previous):
                return tag
        return matches[0]

    def _declines(
        self,
        query: str,
        tag: str,
        context: Context | None,
        addressed: bool,
    ) -> bool:
        """Whether silence beats speaking.

        Only for an unprompted remark. Somebody who used the bot's name expects an
        answer, even a second one; somebody who merely repeated themselves in the room
        does not need to be told twice.
        """
        if addressed or context is None:
            return False
        if context.repeated(query):
            return True
        return context.act_from_bot(tag)

    def _annotate(
        self, reply: Reply, context: Context | None, matches: tuple[str, ...]
    ) -> Reply:
        """Attach the trail: what else this could have been, and what came before."""
        detail: dict[str, Any] = {}
        if len(matches) > 1:
            detail["candidates"] = list(matches)
        if context is not None and context.acts:
            detail["after"] = context.previous_act
            detail["sequence"] = context.sequence()
        return replace(reply, detail={**detail, **reply.detail}) if detail else reply

    def _answer_intent(
        self, who: Character, tag: str, query: str, speaker: str | None
    ) -> Reply | None:
        """Render a social reply, with no fact behind it -- the move is the message."""
        values: dict[str, str] = {"character": who.name, "topic": _humanise(tag)}
        if speaker:
            values["speaker"] = speaker

        filled = self._fill(
            self._candidates(who, tag),
            f"{self._seed}|{who.id}|{tag}|{normalise(query)}",
            values,
            rotate_key=(who.id, tag),
        )
        if filled is None:
            return None
        template, text = filled
        return Reply(
            text=_sentence_case(text),
            character=who.id,
            tag=tag,
            knowledge_id=None,
            template_id=template.id,
            distance=None,
            known=True,
        )

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
            rotate_key=(who.id, tag),
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
        self,
        who: Character,
        classification: Classification | None,
        speaker: str | None,
    ) -> Reply:
        """Say "not my field" without handing over the fact."""
        best = classification.best_tag if classification is not None else None
        distance = classification.distance if classification is not None else None
        values: dict[str, str] = {
            "character": who.name,
            "topic": _humanise(best or "that"),
        }
        if speaker:
            values["speaker"] = speaker

        filled = self._fill(
            self._candidates(who, who.fallback_tag),
            f"{self._seed}|{who.id}|{who.fallback_tag}|{normalise(classification.query if classification else '')}",
            values,
            rotate_key=(who.id, who.fallback_tag),
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
            distance=distance,
            known=False,
        )

    def _candidates(self, who: Character, tag: str) -> Sequence[ResponseTemplate]:
        return (
            *self._index.get((who.id, tag), ()),
            *self._index.get((WILDCARD, tag), ()),
        )

    def _fill(
        self,
        candidates: Sequence[ResponseTemplate],
        key: str,
        values: Mapping[str, str],
        *,
        rotate_key: tuple[str, str] | None = None,
    ) -> tuple[ResponseTemplate, str] | None:
        """Pick a template deterministically, skipping ones this data cannot fill.

        Rotation happens *within* a group, so a character never answers in the
        generic wildcard voice while one of its own lines is available. With
        ``rotate`` on, the template used last for this (character, tag) is skipped
        while another candidate remains, so a repeated question is not a repeated
        sentence.
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
            if rotate_key is not None and self._rotate:
                last = self._last.get(rotate_key)
                if last is not None and len(ordered) > 1:
                    fresh = [template for template in ordered if template.id != last]
                    if fresh:
                        ordered = fresh
            start = int.from_bytes(digest, "big") % len(ordered)
            for offset in range(len(ordered)):
                template = ordered[(start + offset) % len(ordered)]
                try:
                    text = madlib.render(template.template, values)
                except (madlib.MissingSlot, ValueError):
                    continue
                if text.strip():
                    if rotate_key is not None:
                        self._last[rotate_key] = template.id
                    return template, text
        return None

