"""Response decoding, one function per wire format.

Two formats are supported because they are the two that exist in the wild:

``chat``
    ``POST /chat/completions`` -- the Chat Completions shape, spoken by
    text-generation-webui, Ollama, llama.cpp, LM Studio, vLLM and ClinePass.
``responses``
    ``POST /responses`` -- the OpenAI Responses API, which is where Codex models
    (``gpt-5-codex``) are served. They return 404 on ``/chat/completions``.

ClinePass currently answers a non-streaming request by wrapping the whole OpenAI
object in ``data``; :func:`_unwrap` accepts the wrapped *and* the plain shape, so this
backend keeps working whichever way that inconsistency is resolved.

Nothing here performs I/O, so every branch is reachable from a test.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from ttrpg_chatbots.llm.http import summarise
from ttrpg_chatbots.llm.types import Completion, LlmConfigError, LlmProtocolError, ToolCall

WIRE_CHAT = "chat"
WIRE_RESPONSES = "responses"
WIRES = (WIRE_CHAT, WIRE_RESPONSES)

DEFAULT_WIRE = WIRE_CHAT


def decode_json(body: str, *, backend: str) -> Mapping[str, Any]:
    """Parse a response body that is supposed to be a JSON object."""
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise LlmProtocolError(
            f"{backend} returned a non-JSON body: {summarise(body)!r}", backend=backend
        ) from error
    if not isinstance(payload, Mapping):
        raise LlmProtocolError(f"{backend} returned JSON that is not an object", backend=backend)
    return payload


def parse_completion(payload: Mapping[str, Any], *, wire: str, backend: str) -> Completion:
    """Turn a successful response body into a :class:`Completion`."""
    if wire == WIRE_CHAT:
        return _chat_completion(payload, backend)
    if wire == WIRE_RESPONSES:
        return _responses_completion(payload, backend)
    raise LlmConfigError(f"unknown wire format {wire!r}; expected one of {WIRES}")


def _unwrap(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Accept both a plain OpenAI body and the ClinePass ``data`` envelope."""
    if "choices" in payload:
        return payload
    inner = payload.get("data")
    if isinstance(inner, Mapping) and "choices" in inner:
        return inner
    return payload


def _chat_completion(payload: Mapping[str, Any], backend: str) -> Completion:
    body = _unwrap(payload)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmProtocolError(f"{backend} returned no choices ({_why(payload)})", backend=backend)
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise LlmProtocolError(f"{backend} returned a malformed choice", backend=backend)

    message = choice.get("message")
    calls = _chat_tool_calls(message, backend)
    text = _message_text(message) or _legacy_text(choice)
    if not text.strip() and not calls:
        raise LlmProtocolError(
            f"{backend} returned an empty answer ({_why(payload)})", backend=backend
        )
    return Completion(
        text=text.strip(),
        backend=backend,
        model=_model(body),
        truncated=choice.get("finish_reason") == "length",
        usage=_usage(body),
        tool_calls=calls,
    )


def _chat_tool_calls(message: Any, backend: str) -> tuple[ToolCall, ...]:
    if not isinstance(message, Mapping):
        return ()
    raw = message.get("tool_calls")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LlmProtocolError(f"{backend} returned malformed tool calls", backend=backend)

    calls: list[ToolCall] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise LlmProtocolError(f"{backend} returned a malformed tool call", backend=backend)
        function = item.get("function")
        if not isinstance(function, Mapping):
            raise LlmProtocolError(
                f"{backend} returned a tool call without a function", backend=backend
            )
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            raise LlmProtocolError(
                f"{backend} returned a tool call without a name", backend=backend
            )
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call-{index}"),
                name=name.strip(),
                arguments=_arguments_as_text(function.get("arguments")),
            )
        )
    return tuple(calls)


def _arguments_as_text(raw: Any) -> str:
    """Arguments arrive as a JSON string; some proxies send an object instead."""
    if raw is None:
        return "{}"
    if isinstance(raw, str):
        return raw
    return json.dumps(raw)

def _responses_completion(payload: Mapping[str, Any], backend: str) -> Completion:
    status = payload.get("status")
    if status == "failed":
        raise LlmProtocolError(
            f"{backend} reported a failed response ({_why(payload)})", backend=backend
        )

    texts: list[str] = []
    refusals: list[str] = []
    calls: list[ToolCall] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "function_call":
                calls.append(_responses_tool_call(item, len(calls), backend))
                continue
            if item.get("type") != "message":
                continue
            for part in _parts(item.get("content")):
                kind = part.get("type")
                if kind == "output_text" and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif kind == "refusal":
                    refusal = part.get("refusal") or part.get("text")
                    if isinstance(refusal, str) and refusal.strip():
                        refusals.append(refusal)

    text = "\n".join(texts).strip()
    if not text:
        # Some proxies mirror the SDK's convenience field into the body.
        convenience = payload.get("output_text")
        if isinstance(convenience, str):
            text = convenience.strip()
    if not text and not calls:
        if refusals:
            raise LlmProtocolError(
                f"{backend} refused to answer: {summarise(refusals[0])}", backend=backend
            )
        raise LlmProtocolError(
            f"{backend} returned no output text ({_why(payload)})", backend=backend
        )

    return Completion(
        text=text,
        backend=backend,
        model=_model(payload),
        # A truncated answer is still usable, but the caller should know.
        truncated=status == "incomplete",
        usage=_usage(payload),
        tool_calls=tuple(calls),
    )


def _responses_tool_call(item: Mapping[str, Any], index: int, backend: str) -> ToolCall:
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LlmProtocolError(f"{backend} returned a tool call without a name", backend=backend)
    return ToolCall(
        id=str(item.get("call_id") or item.get("id") or f"call-{index}"),
        name=name.strip(),
        arguments=_arguments_as_text(item.get("arguments")),
    )


def _parts(content: Any) -> list[Mapping[str, Any]]:
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, Mapping)]


def _message_text(message: Any) -> str:
    """Text from a chat ``message``: a string, or a list of content parts."""
    if not isinstance(message, Mapping):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if isinstance(part, str):
            chunks.append(part)
        elif isinstance(part, Mapping) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "".join(chunks)


def _legacy_text(choice: Mapping[str, Any]) -> str:
    """Old-style completions put the text at ``choice["text"]``."""
    text = choice.get("text")
    return text if isinstance(text, str) else ""


def _model(payload: Mapping[str, Any]) -> str:
    model = payload.get("model")
    return model if isinstance(model, str) else ""


def _usage(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    usage = payload.get("usage")
    return usage if isinstance(usage, Mapping) else {}


def _why(payload: Mapping[str, Any]) -> str:
    """A short, log-safe hint about why a body was unusable."""
    error = payload.get("error")
    if isinstance(error, Mapping):
        for key in ("message", "type", "code"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                return f"error: {summarise(value)}"
    if isinstance(error, str) and error.strip():
        return f"error: {summarise(error)}"
    keys = ", ".join(sorted(str(key) for key in payload))
    return f"keys: {keys}" if keys else "empty object"
