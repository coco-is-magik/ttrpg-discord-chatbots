"""Adapt the compression classifier to the :class:`~ttrpg_chatbots.respond.Responder` seam.

This is the only module that knows both ``reply`` and that seam, which is what lets a
classifier reply and an LLM answer be swapped for one another without either engine
importing the other.
"""

from __future__ import annotations

from ttrpg_chatbots.reply.context import Context
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.types import Reply, ReplyUnavailable
from ttrpg_chatbots.respond import Answer


def answer_from_reply(reply: Reply) -> Answer:
    """The one place a ``Reply`` becomes an ``Answer``.

    Kept here rather than in the caller so the ``reply`` engine and the bots share one
    mapping: a provenance key added to the classifier appears in every log line at once.
    """
    return Answer(
        text=reply.text,
        source=f"reply:{reply.character}",
        detail={
            **dict(reply.detail),
            "character": reply.character,
            "tag": reply.tag,
            "knowledge_id": reply.knowledge_id,
            "template_id": reply.template_id,
            "distance": reply.distance,
            "known": reply.known,
        },
    )


class ClassifierResponder:
    """Answers in character with tagged knowledge and madlib templates. No model."""

    def __init__(self, replier: Replier, character: str, *, speaker: str | None = None) -> None:
        self._replier = replier
        # Resolve now, so a mistyped character fails at startup rather than mid-call.
        self._character = replier.world.character(character)
        self._speaker = speaker

    @property
    def name(self) -> str:
        return f"reply:{self._character.id}"

    @property
    def character(self) -> str:
        return self._character.id

    def answer(self, prompt: str) -> Answer:
        reply = self._replier.reply(prompt, self._character.id, speaker=self._speaker)
        if reply is None:
            # This seam promises a line, so an unwelcome silence is a failure here. Callers
            # that can legitimately say nothing use ``FriendChat``, which returns None.
            raise ReplyUnavailable(f"{self._character.id} declined to answer")
        return answer_from_reply(reply)
