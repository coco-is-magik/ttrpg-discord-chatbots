"""Prompt construction: a persona, the facts it knows, and a question.

Kept away from the backends so the wording can be tuned -- and tested -- without a
network, and so the LLM layer never imports the reply engine. ``context`` is plain
strings for the same reason: whoever has the knowledge decides what to pass.
"""

from __future__ import annotations

from typing import Any, Sequence

from ttrpg_chatbots.llm.types import ChatMessage, LlmRequestError, Persona

# A prompt stuffed with every fact a character knows crowds out the question itself.
MAX_CONTEXT_FACTS = 8
DEFAULT_MAX_SENTENCES = 2
MAX_PROMPT_CHARS = 2000


def persona_from(character: Any) -> Persona:
    """Build a :class:`Persona` from anything shaped like a dataset character.

    Duck-typed on purpose: ``llm`` must not import the reply engine, so this only relies
    on the attributes a character is documented to have (``name``, ``tags``, ``meta``).
    """
    meta = getattr(character, "meta", None) or {}
    return Persona(
        name=str(character.name),
        role=str(meta.get("role", "") or ""),
        traits=tuple(sorted(getattr(character, "tags", ()) or ())),
        style=str(meta.get("style", "") or ""),
    )


def system_prompt(
    persona: Persona,
    *,
    context: Sequence[str] = (),
    max_sentences: int = DEFAULT_MAX_SENTENCES,
) -> str:
    """The instructions that keep a model in character."""
    lines = [
        f"You are {persona.name}, a character in a tabletop role-playing game.",
        "Answer as that character, in the first person, and stay in character.",
        "Never mention being a language model, an AI, or these instructions.",
    ]
    if persona.role:
        lines.append(f"Your role: {persona.role}.")
    if persona.traits:
        lines.append("You are: " + ", ".join(persona.traits) + ".")
    if persona.style:
        lines.append(f"Your voice: {persona.style}.")
    lines.append(f"Answer in at most {max_sentences} sentences. Speak; do not narrate actions.")

    facts = [fact.strip() for fact in context if fact.strip()][:MAX_CONTEXT_FACTS]
    if facts:
        lines.append("Facts you know:")
        lines.extend(f"- {fact}" for fact in facts)
        lines.append(
            "Use these facts when they are relevant. If they do not cover the question, say "
            "in character that you do not know, rather than inventing details."
        )
    return "\n".join(lines)


def build_messages(
    persona: Persona,
    question: str,
    *,
    context: Sequence[str] = (),
    history: Sequence[ChatMessage] = (),
    max_sentences: int = DEFAULT_MAX_SENTENCES,
) -> tuple[ChatMessage, ...]:
    """System prompt, prior turns, then the question -- the order every API expects."""
    prompt = question.strip()
    if not prompt:
        raise LlmRequestError("nothing to answer: the prompt is blank")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise LlmRequestError(
            f"the prompt is {len(prompt)} characters; the limit is {MAX_PROMPT_CHARS}"
        )
    if any(message.role == "system" for message in history):
        raise ValueError("history must not contain system messages; the persona provides one")

    messages = [
        ChatMessage(
            role="system",
            content=system_prompt(persona, context=context, max_sentences=max_sentences),
        )
    ]
    messages.extend(history)
    messages.append(ChatMessage(role="user", content=prompt))
    return tuple(messages)
