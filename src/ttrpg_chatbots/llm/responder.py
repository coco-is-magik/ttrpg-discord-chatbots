"""Responders: the seam between "something that answers" and the voice pipeline.

A responder takes a prompt and returns an :class:`Answer`. The LLM is one; the
compression classifier is another; a scripted line or a canned recording could be a
third. Everything downstream -- TTS, casting, playback -- only ever sees
``answer(prompt)``, which is why none of those layers import this module.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from ttrpg_chatbots.llm.backends import OpenAiCompatibleBackend
from ttrpg_chatbots.llm.prompt import DEFAULT_MAX_SENTENCES, build_messages
from ttrpg_chatbots.llm.tools import ToolBox
from ttrpg_chatbots.llm.types import ChatMessage, Completion, Persona, ToolCall
from ttrpg_chatbots.respond import Answer

DEFAULT_MAX_TOOL_ROUNDS = 3


class LlmResponder:
    """Answers with a chat backend, always in the same persona.

    ``connect`` is called on the first question rather than at construction. That way a
    missing key, a retired model or an unreachable host fails *inside* the fallback
    wrapper, so the table still gets an answer; it also means nothing is connected for
    a reply the classifier ends up handling. The built backend is cached.

    With ``tools``, the model may call them: the responder runs each call, feeds the
    result back, and asks again -- so "roll stealth" comes back as an actual roll rather
    than the model pretending. The loop is bounded by ``max_tool_rounds`` and, if the
    budget runs out, the tool output itself becomes the answer: a roll that happened is
    never dropped on the floor.

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
        tools: ToolBox | None = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ) -> None:
        if max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must not be negative")
        self._connect = connect
        self._name = name.strip() or "llm"
        self._persona = persona
        self._context = tuple(context)
        self._context_for = context_for
        self._history = tuple(history)
        self._max_sentences = max_sentences
        self._tools = tools
        self._max_tool_rounds = max_tool_rounds
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
        messages: list[ChatMessage] = list(
            build_messages(
                self._persona,
                prompt,
                context=context,
                history=self._history,
                max_sentences=self._max_sentences,
            )
        )
        schemas = self._tools.schemas() if self._tools is not None else ()
        used: list[dict[str, Any]] = []

        completion = self.backend.complete(messages, tools=schemas)
        rounds = 0
        while completion.tool_calls and self._tools is not None:
            if rounds >= self._max_tool_rounds:
                return self._exhausted(completion, used)
            rounds += 1
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=completion.text,
                    tool_calls=completion.tool_calls,
                )
            )
            for call in completion.tool_calls:
                messages.append(self._run_tool(call, used))
            completion = self.backend.complete(messages, tools=schemas)

        return self._answer_from(completion, used)

    def _run_tool(self, call: ToolCall, used: list[dict[str, Any]]) -> ChatMessage:
        assert self._tools is not None  # guarded by the caller
        invocation = self._tools.invoke(call)
        used.append(
            {
                "name": call.name,
                "arguments": call.arguments,
                "result": invocation.text,
                "failed": invocation.failed,
            }
        )
        return ChatMessage(
            role="tool",
            content=invocation.text,
            tool_call_id=call.id,
            name=call.name,
        )

    def _answer_from(self, completion: Completion, used: list[dict[str, Any]]) -> Answer:
        # A model that ran a tool but said nothing still has something to report.
        text = completion.text.strip() or _tool_text(used) or "I could not put that into words."
        return Answer(
            text=text,
            source=f"llm:{completion.backend}",
            detail=self._detail(completion, used),
        )

    def _exhausted(self, completion: Completion, used: list[dict[str, Any]]) -> Answer:
        """The model kept asking for tools: report what they produced."""
        text = completion.text.strip() or _tool_text(used) or "I could not finish that."
        detail = self._detail(completion, used)
        detail["tool_budget_exhausted"] = True
        return Answer(text=text, source=f"llm:{completion.backend}", detail=detail)

    def _detail(self, completion: Completion, used: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "model": completion.model,
            "truncated": completion.truncated,
            "usage": dict(completion.usage),
            "tools": used,
        }


def _tool_text(used: Sequence[dict[str, Any]]) -> str:
    """The tool results, in order: a roll that happened must still be reported."""
    return "\n".join(entry["result"] for entry in used if entry.get("result"))

