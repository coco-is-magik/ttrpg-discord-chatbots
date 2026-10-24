"""The unit below the message.

A reply is not one string. It is a set of **parts** -- a reaction, the substance, a hand-back, an emoji --
and the parts are what a reader notices arriving. This module is the vocabulary for that, and nothing else:
no decisions, no words, no imports from the rest of the conversation layer.

Why it exists: measured from the first dataset (`docs/DATASET.md`), a room running a 25-line register for a
day produced 260 messages in which the same situation always produced the same *sentence*. The unit of
decision was a whole message, so a bigger corpus could only make the canned line rarer, never absent. Parts
let the same words arrive differently, which is the texture a person actually reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: The kinds of part. Six, and each is a job in its own right -- see `docs/TEXTURE.md` §1.1.
#:
#: ``reaction``   the beat before the substance ("oh nice", "hmm")
#: ``content``    the substance ("Messing with the tank")
#: ``question``   the hand-back ("how is otis doing?")
#: ``emoji``      a non-verbal fragment ("🐠", "(＾▽＾)")
#: ``aside``      a self-interruption or trailing thought ("anyway", "wait")
#: ``correction`` a revision of something already sent ("*the garage, not the shed")
PartKind = Literal["reaction", "content", "question", "emoji", "aside", "correction"]

#: The kinds that can stand as a whole message on their own. A reaction or an emoji alone is a message a
#: person sends; a `content` alone is the ordinary case; an `aside` alone would be strange, and a
#: `correction` alone is not a thing.
STANDALONE: frozenset[str] = frozenset({"reaction", "content", "question", "emoji"})


@dataclass(frozen=True)
class Part:
    """One piece of a reply."""

    kind: PartKind
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError(f"a {self.kind} part must say something")
        if self.kind not in STANDALONE and self.kind not in ("aside", "correction"):
            raise ValueError(f"unknown part kind: {self.kind!r}")


@dataclass(frozen=True)
class Turn:
    """What somebody is about to say, as parts."""

    parts: tuple[Part, ...] = ()

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("a turn needs at least one part")
        for part in self.parts:
            if not isinstance(part, Part):
                raise TypeError(f"a turn holds Parts, not {type(part).__name__}")

    @property
    def text(self) -> str:
        """The whole turn as one string -- what it would be if it arrived in one message."""
        return " ".join(part.text for part in self.parts)

    @property
    def words(self) -> int:
        return len([word for word in self.text.split() if word.strip("?!.,")])

    def kinds(self) -> tuple[str, ...]:
        return tuple(part.kind for part in self.parts)


@dataclass(frozen=True)
class Delivery:
    """How a turn should arrive: one message, several, and how far apart.

    The knobs are explicit rather than derived from context here, so the packaging can be built and measured
    before the context modules exist (`docs/TEXTURE.md` §6, slice D wires a Condition into this).
    """

    #: Whether to break the turn into more than one message at all. False is exactly today's behaviour.
    split: bool = True
    #: A reaction or an aside is the natural thing to send on its own line.
    separate_reaction: bool = True
    #: An emoji on its own is a legitimate message -- two of the three briefs ask for it.
    emoji_alone: bool = True
    #: A hand-back is its own message: "Messing with the tank" then "how is otis doing?".
    separate_question: bool = True
    #: Never more than this many messages for one turn. Three is a person mid-thought; five is a bot.
    max_messages: int = 3
    #: Seconds of pause between two messages of the same turn.
    pause: float = 1.6
    #: Whether the person types the message out (Discord shows a typing indicator) or it appears at once.
    show_typing: bool = True
    #: A trailing aside ("anyway", "wait") reads as a thought after the fact, so it goes last and alone.
    aside_last: bool = True
    trail: dict = field(default_factory=dict)
