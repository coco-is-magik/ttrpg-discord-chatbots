"""What parts does this line already have?

**Derived before authored.** Every phrasebook variant today is one string, and a good number of them are
already two parts in a trench coat: `Messing with the tank. how is otis doing?` is a `content` plus a
`question`. Reading the parts out of the existing text means the packaging layer can be built, measured and
tuned before a single phrasebook is rewritten -- and it means the 25-line register we already have starts
arriving in more than one shape.

The rules are deliberately conservative. A wrong split is worse than no split, because it produces a message
that reads as two half-thoughts, so anything ambiguous stays one `content`.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.conv.parts import Part

#: A sentence ends at terminal punctuation, keeping the punctuation with the sentence.
SENTENCE = re.compile(r"(?<=[.!?…])\s+")

#: The beat words that mean a short fragment is a reaction rather than the substance. Small on purpose: a
#: reaction is the *first* thing said and carries no information, so a list of the things people actually say
#: as one is the honest way to find one.
REACTIONS = frozenset(
    {
        "ah",
        "aha",
        "anyway",
        "aw",
        "aww",
        "eh",
        "ha",
        "haha",
        "heh",
        "hey",
        "hmm",
        "hm",
        "mm",
        "mmm",
        "mmhm",
        "mhm",
        "nah",
        "nice",
        "nope",
        "oh",
        "ooh",
        "oof",
        "ouch",
        "right",
        "sure",
        "true",
        "ugh",
        "well",
        "yeah",
        "yep",
        "yikes",
        "yup",
    }
)

#: Openers that make a fragment an aside -- a thought about the conversation rather than part of it.
ASIDES = frozenset({"anyway", "wait", "oh wait", "also", "hang on", "right so"})

#: Emoji, kaomoji, and the emoticon punctuation they are made of. A fragment made only of these is `emoji`.
EMOTICON_CHARS = frozenset("^_-.o0O()<>;:3=vV'`~\\|/@*")

#: A correction is something a person types to fix what they already sent.
CORRECTION = re.compile(r"^\*")


def _is_emoji(fragment: str) -> bool:
    """Whether a fragment is only non-verbal marks."""
    if not fragment:
        return False
    for character in fragment:
        if character.isalnum() and character not in EMOTICON_CHARS:
            return False
        if character.isspace():
            continue
        if character.isascii() and character not in EMOTICON_CHARS:
            # Punctuation is fine; a letter would not have reached here.
            continue
    # Something with no letters at all and at least one mark is an emoji or a kaomoji.
    return not any(character.isalnum() for character in fragment)


def _classify(fragment: str, *, first: bool, last: bool) -> str:
    """What kind of part is this fragment?"""
    stripped = fragment.strip()
    if CORRECTION.match(stripped):
        return "correction"
    if _is_emoji(stripped):
        return "emoji"
    if stripped.endswith("?"):
        return "question"
    words = [word.strip("?!.,…").lower() for word in stripped.split()]
    if words and " ".join(words[:2]) in ASIDES:
        return "aside"
    # A short fragment that is all beat words, or a short fragment before a longer one, is a reaction.
    if words and all(word in REACTIONS for word in words) and len(words) <= 3:
        return "reaction"
    if first and not last and len(words) <= 3 and words and words[0] in REACTIONS:
        return "reaction"
    return "content"


def read(text: str) -> tuple[Part, ...]:
    """The parts this text already has. One `content` when nothing suggests otherwise."""
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("nothing to read parts from")

    fragments = [fragment.strip() for fragment in SENTENCE.split(cleaned) if fragment.strip()]
    if len(fragments) <= 1:
        return (Part(kind=_classify(cleaned, first=True, last=True), text=cleaned),)

    parts: list[Part] = []
    for index, fragment in enumerate(fragments):
        kind = _classify(
            fragment,
            first=index == 0,
            last=index == len(fragments) - 1,
        )
        parts.append(Part(kind=kind, text=fragment))
    return tuple(parts)
