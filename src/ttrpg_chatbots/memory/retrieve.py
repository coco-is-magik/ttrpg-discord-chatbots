"""What is relevant to right now?

Word overlap, which is crude and sufficient: if the cue mentions a dog, the fact whose value is a
dog's name comes back first. No embeddings, no similarity model, and the ranking is explainable in
one sentence."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ttrpg_chatbots.memory.long import Fact

_WORD = re.compile(r"[a-z']+")


def read(*, cue: str, facts: Iterable[Fact], limit: int = 3) -> tuple[Fact, ...]:
    """The facts that share the most words with the cue."""
    words = {word for word in _WORD.findall((cue or "").lower()) if len(word) > 3}
    scored: list[tuple[int, int, Fact]] = []
    for fact in facts:
        value_words = set(_WORD.findall(f"{fact.key.replace('.', ' ')} {fact.value}".lower()))
        overlap = len(words & value_words)
        if overlap:
            scored.append((overlap, fact.count, fact))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].key))
    return tuple(fact for _, _, fact in scored[:limit])
