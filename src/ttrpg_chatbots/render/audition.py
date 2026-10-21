"""Accept this candidate, or ask for the next.

The governor of quality: a line has to fit the budget, sound like him, and not be a verbatim repeat.
On a reject the ladder asks `decide.variant` for another candidate rather than starting over."""

from __future__ import annotations

from dataclasses import dataclass

from ttrpg_chatbots.conv.types import Budget, Fit


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str = ""


def judge(*, text: str, budget: Budget, fit: Fit | None = None, repeated: bool = False) -> Verdict:
    """Accept or reject, with the first reason that applies."""
    if not text.strip():
        return Verdict(False, "nothing to say")
    # Repeating a two-word line is what people do; repeating a whole sentence straight after
    # itself is what a broken machine does.
    if repeated and len(text.split()) >= 4:
        return Verdict(False, "he just said that")
    if not budget.fits(text):
        return Verdict(False, "over budget")
    if fit is not None and not fit.ok:
        return Verdict(False, ", ".join(fit.reasons) or "does not sound like him")
    return Verdict(True)
