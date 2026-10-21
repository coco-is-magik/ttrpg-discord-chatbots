"""Why did nobody speak?

Several rungs can decline. The reason that matters is the first one, because that is the earliest
point at which the reply was already impossible."""

from __future__ import annotations

from collections.abc import Iterable

from ttrpg_chatbots.conv.types import Abstain


def first(candidates: Iterable[Abstain]) -> Abstain:
    """The first abstention, or a generic one if there were none."""
    for candidate in candidates:
        return candidate
    return Abstain("nothing to say")
