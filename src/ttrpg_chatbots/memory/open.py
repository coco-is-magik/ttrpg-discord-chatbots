"""What is still unresolved.

An invitation offered and not answered, a question he asked and did not get an answer to. These
are the only things that should survive a restart *as obligations* rather than as facts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Open:
    """Things left hanging, newest concern first."""

    pending_plan: bool = False
    unanswered: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.pending_plan or bool(self.unanswered)

    @property
    def first(self) -> str:
        if self.pending_plan:
            return "an invitation he offered is unanswered"
        return self.unanswered[0] if self.unanswered else ""


def read(*, pending_plan: bool = False, unanswered: tuple[str, ...] = ()) -> Open:
    return Open(pending_plan=pending_plan, unanswered=tuple(unanswered))
