"""Normalised Compression Distance: similarity without training or models.

    ncd(x, y) = 2 * C(xy) / (C(x) + C(y)) - 1

``C`` is a compressed length. There are no parameters, weights or model files: the
tagged corpus *is* the model, so a new world needs new data and no retraining. Two
strings that share phrasing compress better together, so a smaller distance means
"more alike"; identical strings land just above 0 and unrelated ones near 1.

The denominator is the *sum* of both lengths rather than ``max``: with the classic
``(C(xy) - min) / max`` form, a long item wins arguments it should lose, simply
because ``max`` grows with its length. On the demo world's 14 test questions the
sum form scores 13/14 against 9/14 for the ``max`` form. Ranking is per item, not
per tag prototype -- concatenating a whole tag into one long text measured much
worse (2/10) because a short question is overwhelmed by the prototype.
"""

from __future__ import annotations

from typing import Sequence

from ttrpg_chatbots.reply.compression import DEFAULT as DEFAULT_COMPRESSOR
from ttrpg_chatbots.reply.compression import Compressor, get
from ttrpg_chatbots.reply.types import (
    Classification,
    DatasetError,
    KnowledgeItem,
    Match,
    TagScore,
)

DEFAULT_TOP_K = 5


def normalise(text: str) -> str:
    """Case- and whitespace-insensitive comparison, nothing cleverer."""
    return " ".join(text.lower().split())


def ncd(left: bytes, right: bytes, compressor: Compressor) -> float:
    """Distance in roughly [0, 1]: near 0 for identical, near 1 for unrelated."""
    if not left and not right:
        return 0.0
    compressed_left = compressor.compressed_length(left)
    compressed_right = compressor.compressed_length(right)
    total = compressed_left + compressed_right
    if total == 0:  # a compressor that emits nothing for anything
        return 0.0
    # A separator keeps the compressor from inventing a phrase across the joint.
    joint = compressor.compressed_length(left + b"\n" + right)
    return max(0.0, 2.0 * joint / total - 1.0)


def rank(
    query: str,
    items: Sequence[KnowledgeItem],
    compressor: Compressor,
    *,
    top_k: int | None = None,
) -> tuple[Match, ...]:
    """Return knowledge items ordered best-first by distance to ``query``."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if not items:
        raise DatasetError("no knowledge items to classify against")
    query_bytes = normalise(query).encode("utf-8")
    matches = [
        Match(
            ref=item.id,
            distance=ncd(query_bytes, normalise(item.search_text).encode("utf-8"), compressor),
        )
        for item in items
    ]
    matches.sort(key=lambda match: (match.distance, match.ref))
    return tuple(matches[:top_k] if top_k is not None else matches)


def classify(
    query: str,
    items: Sequence[KnowledgeItem],
    compressor: Compressor | None = None,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> Classification:
    """Score every tag, best first.

    Tag scores always consider the whole corpus: a tag's score is the distance of
    the closest item carrying it, so trimming the corpus would make a tag invisible
    just because its item ranked sixth. ``top_k`` only trims the reported matches,
    which exist for provenance.
    """
    if top_k < 1:
        raise ValueError("top_k must be at least 1")
    active = compressor if compressor is not None else get(DEFAULT_COMPRESSOR)
    ranked = rank(query, items, active)
    by_id = {item.id: item for item in items}

    scored: dict[str, TagScore] = {}
    for match in ranked:
        for tag in by_id[match.ref].tags:
            current = scored.get(tag)
            if current is None or match.distance < current.distance:
                scored[tag] = TagScore(tag, match.distance, match.ref)
    tags = tuple(sorted(scored.values(), key=lambda score: (score.distance, score.tag)))

    return Classification(
        query=query,
        compressor=active.name,
        tags=tags,
        matches=ranked[:top_k],
        best_item=by_id[ranked[0].ref],
    )
