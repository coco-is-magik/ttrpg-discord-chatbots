"""Which candidates graduate to long-term?

The rule that keeps memory from filling with noise: a fact is kept when it is important by kind
(pets and jobs are), or when it has been said twice. Everything else stays in the short window and
is forgotten, which is what a person does too.
"""

from __future__ import annotations

IMPORTANT = ("pet.", "job")


def decide(*, kind: str, count: int = 1, said_by: str = "them", importance: bool | None = None) -> bool:
    """Keep it, or let it fade."""
    if importance is not None:
        return importance
    if count >= 2:
        return True
    return any(kind.startswith(prefix) for prefix in IMPORTANT) and said_by == "them"
