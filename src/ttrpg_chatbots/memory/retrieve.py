"""What is relevant to right now?

Word overlap, which is crude and sufficient: if the cue mentions a dog, the fact whose value is a
dog's name comes back first. No embeddings, no similarity model, and the ranking is explainable in
one sentence."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ttrpg_chatbots.memory.long import Fact

_WORD = re.compile(r"[a-z']+")
# Three-letter words matter here: "dog", "cat", "car", "job" are exactly the words a person uses
# about the things they told you. So the filter is a small stoplist rather than a length rule --
# measured: a length filter of four silently made "how is the dog?" match nothing.
_STOP = frozenset(
    {
        "the", "and", "you", "your", "yours", "was", "were", "for", "with", "that", "this",
        "have", "has", "had", "but", "not", "are", "how", "who", "what", "when", "why",
        "its", "it's", "our", "his", "her", "them", "they", "she", "him", "any", "all",
    }
)


def _words(text: str) -> set[str]:
    return {
        word for word in _WORD.findall((text or "").lower()) if len(word) >= 3 and word not in _STOP
    }


def read(*, cue: str, facts: Iterable[Fact], limit: int = 3) -> tuple[Fact, ...]:
    """The facts that share the most words with the cue.

    A fact's own words are its key, its value, and the word the person would use for it -- "pet.name
    Otis" is matched by "how is the dog", because `encode` records that the pet is a dog. Without
    that, retrieval only worked when the person repeated the key's vocabulary back at us.
    """
    words = _words(cue)
    scored: list[tuple[int, int, Fact]] = []
    for fact in facts:
        described = f"{fact.key.replace('.', ' ')} {fact.value} {fact.meta.get('word', '')}"
        overlap = len(words & _words(described))
        if overlap:
            scored.append((overlap, fact.count, fact))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].key))
    return tuple(fact for _, _, fact in scored[:limit])
