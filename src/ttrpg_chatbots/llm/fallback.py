"""Fall back to the classifier when the LLM cannot answer.

The failure that matters in a live game is "the model is unreachable or the key
expired": the table keeps talking, so the bot has to say *something*. The policy is
deliberately narrow -- only :class:`LlmError` triggers a fallback. A ``TypeError`` in
our own code must surface instead of being hidden behind a template.

Every fallback is logged at WARNING with the original exception attached, so the cause
is preserved for whoever reads the log later, and the returned :class:`Answer` carries
``fallback_reason`` so a degraded reply is never mistaken for a healthy one.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Mapping

from ttrpg_chatbots.llm.types import (
    LlmAuthError,
    LlmConfigError,
    LlmError,
    LlmProtocolError,
    LlmRateLimited,
    LlmRequestError,
    LlmUnavailable,
)
from ttrpg_chatbots.respond import Answer, Responder

LOGGER = logging.getLogger("ttrpg_chatbots.llm")

# Ordered most specific first; the exact type is checked before the isinstance walk.
FAILURE_KINDS: Mapping[type[LlmError], str] = {
    LlmAuthError: "authentication failed",
    LlmUnavailable: "backend unreachable",
    LlmRateLimited: "rate limited",
    LlmRequestError: "request rejected",
    LlmProtocolError: "unusable response",
    LlmConfigError: "not configured",
}


def describe_failure(error: LlmError) -> str:
    """``openai (HTTP 401): authentication failed`` -- specific enough to act on."""
    kind = FAILURE_KINDS.get(type(error), "LLM failure")
    if kind == "LLM failure":
        kind = next(
            (label for error_type, label in FAILURE_KINDS.items() if isinstance(error, error_type)),
            kind,
        )
    subject = error.backend or "llm"
    if error.status is not None:
        subject = f"{subject} (HTTP {error.status})"
    return f"{subject}: {kind}"


class FallbackResponder:
    """Answer with ``primary``; if it fails with an :class:`LlmError`, use ``fallback``.

    The traceback is logged with the first failure of a given kind but not on repeats:
    in a live game an unreachable model fails on every question, and a fifty-line
    traceback per reply buries everything else. The one-line warning always carries the
    cause, so the reason is never lost.
    """

    def __init__(
        self,
        primary: Responder,
        fallback: Responder,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._logger = logger if logger is not None else LOGGER
        self._explained: set[str] = set()

    @property
    def name(self) -> str:
        return self._primary.name

    @property
    def fallback_name(self) -> str:
        return self._fallback.name

    def answer(self, prompt: str) -> Answer:
        try:
            return self._primary.answer(prompt)
        except LlmError as error:
            reason = describe_failure(error)
            first_of_its_kind = reason not in self._explained
            self._explained.add(reason)
            self._logger.warning(
                "%s is unavailable (%s); falling back to %s. Cause: %s",
                self._primary.name,
                reason,
                self._fallback.name,
                error,
                exc_info=True if first_of_its_kind else None,
            )
            try:
                answer = self._fallback.answer(prompt)
            except Exception as fallback_error:
                fallback_error.add_note(
                    f"the primary responder {self._primary.name} also failed: {reason}"
                )
                raise
            return replace(answer, fallback_reason=reason)
