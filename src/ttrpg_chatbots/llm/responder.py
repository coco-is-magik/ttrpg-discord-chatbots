"""Responders: the seam between "something that answers" and the voice pipeline.

A responder takes a prompt and returns an :class:`Answer`. The LLM is one; the
compression classifier is another; a scripted line or a canned recording could be a
third. Everything downstream -- TTS, casting, playback -- only ever sees
``answer(prompt)``, which is why none of those layers import this module.
"""

from __future__ import annotations

from typing import Callable, Sequence

from ttrpg_chatbots.llm.backends import OpenAiCompatibleBackend
from ttrpg_chatbots.llm.prompt import DEFAULT_MAX_SENTENCES, build_messages
from ttrpg_chatbots.llm.types import ChatMessage, Persona
from ttrpg_chatbots.respond import Answer


class LlmResponder:
    """Answers with a chat backend, always in the same persona.

    ``connect`` is called on the first question rather than at construction. That way a
    missing key, a retired model or an unreachable host fails *inside* the fallback
    wrapper, so the table still gets an answer; it also means nothing is connected for
    a reply the classifier ends up handling. The built backend is cached.

    ``context_for`` exists so knowledge can be looked up per question instead of being
    frozen at construction: the CLI passes the character's known facts that the
    classifier matched best, which keeps a model from inventing a town's geography.
    """

    def __init__(
        self,
        connect: Callable[[], OpenAiCompatibleBackend],
        persona: Persona,
        *,
        name: str = "llm",
        context: Sequence[str] = (),
        context_for: Callable[[str], Sequence[str]] | None = None,
        history: Sequence[ChatMessage] = (),
        max_sentences: int = DEFAULT_MAX_SENTENCES,
    ) -> None:
        self._connect = connect
        self._name = name.strip() or "llm"
        self._persona = persona
        self._context = tuple(context)
        self._context_for = context_for
        self._history = tuple(history)
        self._max_sentences = max_sentences
        self._backend: OpenAiCompatibleBackend | None = None

    @property
    def name(self) -> str:
        """Stable even before connecting, so a log line can name the intended backend."""
        return self._name

    @property
    def backend(self) -> OpenAiCompatibleBackend:
        if self._backend is None:
            self._backend = self._connect()
        return self._backend

    def answer(self, prompt: str) -> Answer:
        context = self._context
        if self._context_for is not None:
            context = tuple(self._context_for(prompt))
        messages = build_messages(
            self._persona,
            prompt,
            context=context,
            history=self._history,
            max_sentences=self._max_sentences,
        )
        completion = self.backend.complete(messages)
        return Answer(
            text=completion.text,
            source=f"llm:{completion.backend}",
            detail={
                "model": completion.model,
                "truncated": completion.truncated,
                "usage": dict(completion.usage),
            },
        )
