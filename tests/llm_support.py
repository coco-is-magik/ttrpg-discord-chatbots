"""Fakes for the LLM layer: no sockets, no keys, no model.

The suite-wide guard in ``conftest.py`` already refuses connections; these fakes exist
so the tests never get that far.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from ttrpg_chatbots.llm.http import HttpResponse
from ttrpg_chatbots.llm.types import ChatMessage, Completion, ToolCall
from ttrpg_chatbots.respond import Answer


@dataclass(frozen=True)
class Call:
    """One recorded request."""

    url: str
    payload: Mapping[str, Any]
    headers: Mapping[str, str]
    timeout: float


class FakeTransport:
    """Replays queued responses, or raises queued exceptions, recording every call."""

    name = "fake"

    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self._responses = list(responses)
        self.calls: list[Call] = []

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        self.calls.append(Call(url, dict(payload), dict(headers), timeout))
        if not self._responses:
            raise AssertionError("FakeTransport ran out of queued responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def last(self) -> Call:
        assert self.calls, "no request was made"
        return self.calls[-1]


def ok(body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(status=status, body=body)


def chat_body(
    text: str,
    *,
    model: str = "test-model",
    finish_reason: str = "stop",
    wrapped: bool = False,
) -> str:
    """A Chat Completions body; ``wrapped`` reproduces the ClinePass envelope."""
    payload: dict[str, Any] = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    if wrapped:
        return json.dumps({"success": True, "data": payload})
    return json.dumps(payload)


def responses_body(
    text: str,
    *,
    model: str = "gpt-5-codex",
    status: str = "completed",
) -> str:
    """A Responses API body."""
    return json.dumps(
        {
            "id": "resp-test",
            "object": "response",
            "model": model,
            "status": status,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 11, "output_tokens": 7},
        }
    )


def completion(
    text: str = "Aye.",
    *,
    backend: str = "fake",
    model: str = "fake-model",
    truncated: bool = False,
    usage: Mapping[str, Any] | None = None,
    tool_calls: tuple[ToolCall, ...] = (),
) -> Completion:
    return Completion(
        text=text,
        backend=backend,
        model=model,
        truncated=truncated,
        usage=usage if usage is not None else {},
        tool_calls=tool_calls,
    )


class FakeBackend:
    """A backend that answers from a queue, or raises from it."""

    name = "fake"
    model = "fake-model"

    def __init__(self, *results: Completion | Exception) -> None:
        self._results = list(results)
        self.requests: list[tuple[ChatMessage, ...]] = []
        self.offered_tools: list[tuple[Mapping[str, Any], ...]] = []

    def complete(self, messages, *, tools=()):
        self.requests.append(tuple(messages))
        self.offered_tools.append(tuple(tools))
        if not self._results:
            raise AssertionError("FakeBackend ran out of queued results")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    @property
    def last_request(self) -> tuple[ChatMessage, ...]:
        assert self.requests, "no request was made"
        return self.requests[-1]

    @property
    def rounds(self) -> int:
        return len(self.requests)


class StaticResponder:
    """A responder that returns a fixed answer, or always raises."""

    def __init__(
        self,
        name: str,
        *,
        text: str = "Aye.",
        source: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.text = text
        self.source = source or name
        self.error = error
        self.prompts: list[str] = []

    def answer(self, prompt: str) -> Answer:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return Answer(text=self.text, source=self.source)
