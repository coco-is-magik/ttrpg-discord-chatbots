"""What shape should the line take?

A word, a clause, a clause plus a question, or two beats. Shape is chosen before wording, from the
job and the budget -- which is how a two-word message gets a three-word reply."""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Budget, Form, Job


def choose(*, job: Job, budget: Budget) -> Form:
    """The shortest shape that can do this job."""
    if budget.max_words <= 2:
        return "word"
    if job in ("greet", "acknowledge", "mirror"):
        return "clause"
    if budget.max_words <= 6:
        return "clause_question"
    return "two_beat"
