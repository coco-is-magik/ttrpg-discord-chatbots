"""HTTP backends: one class per provider shape.

All of them take OpenAI-shaped messages and return a :class:`Completion`. What differs
is the URL, the auth header, and the wire format:

===========  ========================================  ==================
backend      speaks                                    needs a key
===========  ========================================  ==================
``local``    Chat Completions (text-generation-webui)   no
``openai``   Responses (Codex models live here)         yes
``clinepass`` Chat Completions                          yes
===========  ========================================  ==================

Backends are cheap objects: no connection is opened until ``complete()`` is called, so
constructing one at startup costs nothing if the first reply never needs it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

from ttrpg_chatbots.llm import wire
from ttrpg_chatbots.llm.http import Transport, UrllibTransport, describe_response
from ttrpg_chatbots.llm.tools import chat_schemas, responses_schemas
from ttrpg_chatbots.llm.types import (
    ChatMessage,
    Completion,
    LlmAuthError,
    LlmConfigError,
    LlmError,
    LlmRateLimited,
    LlmRequestError,
    LlmUnavailable,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps config out of the cycle
    from ttrpg_chatbots.llm.config import LlmConfig

MAX_TIMEOUT = 600.0
MAX_TOKENS_LIMIT = 8192

# text-generation-webui's standard port; the host is here so the port can be
# overridden without rewriting the URL.
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 5000
LOCAL_BASE_URL = f"http://{LOCAL_HOST}:{LOCAL_PORT}/v1"


class OpenAiCompatibleBackend:
    """A JSON client for any server that speaks an OpenAI-shaped API."""

    name = "compatible"
    requires_key = False
    key_env: tuple[str, ...] = ()
    default_wire = wire.WIRE_CHAT
    default_base_url = ""
    default_model = ""
    # OpenAI wants ``max_completion_tokens`` on newer models; compatible servers and
    # local runtimes still expect the older ``max_tokens``.
    max_tokens_field = "max_tokens"
    # Reasoning models reject ``temperature``, so it is only sent on the chat wire
    # unless a subclass opts in.
    temperature_on_responses = False

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str = "",
        wire_format: str | None = None,
        timeout: float = 30.0,
        max_tokens: int = 300,
        temperature: float | None = 0.7,
        extra_headers: Mapping[str, str] | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = (base_url or self.default_base_url).strip().rstrip("/")
        self.model = (model or self.default_model).strip()
        self._wire = (wire_format or self.default_wire).strip().lower()
        self._timeout = float(timeout)
        self._max_tokens = int(max_tokens)
        self._temperature = temperature
        self._extra_headers = dict(extra_headers or {})
        self._api_key = api_key.strip()
        self._transport = transport if transport is not None else UrllibTransport()

        if not self.base_url:
            raise LlmConfigError(f"{self.name}: no base URL configured")
        if not self.model:
            raise LlmConfigError(f"{self.name}: no model configured")
        if self._wire not in wire.WIRES:
            raise LlmConfigError(
                f"{self.name}: unknown wire format {self._wire!r}; expected one of {wire.WIRES}"
            )
        if not 0 < self._timeout <= MAX_TIMEOUT:
            raise LlmConfigError(f"{self.name}: timeout must be in (0, {MAX_TIMEOUT}]")
        if not 0 < self._max_tokens <= MAX_TOKENS_LIMIT:
            raise LlmConfigError(f"{self.name}: max tokens must be in (0, {MAX_TOKENS_LIMIT}]")
        if self._temperature is not None and not 0.0 <= self._temperature <= 2.0:
            raise LlmConfigError(f"{self.name}: temperature must be in [0, 2]")
        if self.requires_key and not self._api_key:
            wanted = " or ".join(self.key_env) or "an API key"
            raise LlmAuthError(
                f"{self.name} needs an API key: set {wanted} (or TTRPG_LLM_API_KEY)",
                backend=self.name,
            )

    # -- request shape -----------------------------------------------------

    @property
    def wire_format(self) -> str:
        return self._wire

    @property
    def url(self) -> str:
        endpoint = "responses" if self._wire == wire.WIRE_RESPONSES else "chat/completions"
        return f"{self.base_url}/{endpoint}"

    def headers(self) -> dict[str, str]:
        headers = dict(self._extra_headers)
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def payload(
        self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]] = ()
    ) -> dict[str, Any]:
        if self._wire == wire.WIRE_RESPONSES:
            return self._responses_payload(messages, tools)
        return self._chat_payload(messages, tools)

    def _chat_payload(
        self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [_chat_message(message) for message in messages],
            self.max_tokens_field: self._max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = chat_schemas(tools)
            body["tool_choice"] = "auto"
        if self._temperature is not None:
            body["temperature"] = self._temperature
        return body

    def _responses_payload(
        self, messages: Sequence[ChatMessage], tools: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        # The system prompt belongs in ``instructions``; the rest becomes ``input``.
        instructions = "\n\n".join(
            message.content for message in messages if message.role == "system"
        )
        items: list[dict[str, Any]] = []
        for message in messages:
            if message.role != "system":
                items.extend(_responses_items(message))
        body: dict[str, Any] = {
            "model": self.model,
            "input": items,
            "max_output_tokens": self._max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = responses_schemas(tools)
        if instructions:
            body["instructions"] = instructions
        if self._temperature is not None and self.temperature_on_responses:
            body["temperature"] = self._temperature
        return body

    # -- the call ----------------------------------------------------------

    def complete(
        self, messages: Sequence[ChatMessage], *, tools: Sequence[Mapping[str, Any]] = ()
    ) -> Completion:
        """Send one turn to the model and return its answer."""
        if not messages:
            raise LlmRequestError(f"{self.name}: no messages to send", backend=self.name)
        try:
            response = self._transport.post_json(
                self.url, self.payload(messages, tools), self.headers(), self._timeout
            )
        except LlmError as error:
            # Transport failures happen below this layer; stamp them with the backend
            # name so a log line says *which* server refused to answer.
            error.backend = error.backend or self.name
            raise
        self._raise_for_status(response)
        payload = wire.decode_json(response.body, backend=self.name)
        return wire.parse_completion(payload, wire=self._wire, backend=self.name)

    def _raise_for_status(self, response: Any) -> None:
        status = response.status
        if status < 400:
            return
        detail = describe_response(response, self._api_key)
        if status in (401, 403):
            raise LlmAuthError(
                f"{self.name} rejected the credentials ({detail})",
                backend=self.name,
                status=status,
            )
        if status == 429:
            raise LlmRateLimited(
                f"{self.name} is rate limiting ({detail})", backend=self.name, status=status
            )
        if status >= 500:
            raise LlmUnavailable(
                f"{self.name} is failing ({detail})", backend=self.name, status=status
            )
        raise LlmRequestError(
            f"{self.name} rejected the request ({detail})", backend=self.name, status=status
        )



def _chat_message(message: ChatMessage) -> dict[str, Any]:
    """A neutral message in Chat Completions shape."""
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.tool_calls:
        return {
            "role": "assistant",
            # Tool-calling turns carry no prose; ``null`` is what the API expects.
            "content": message.content or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in message.tool_calls
            ],
        }
    return message.as_dict()


def _responses_items(message: ChatMessage) -> list[dict[str, Any]]:
    """A neutral message as one or more Responses input items."""
    if message.role == "tool":
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": message.content,
            }
        ]
    items: list[dict[str, Any]] = []
    if message.content.strip():
        items.append({"role": message.role, "content": message.content})
    items.extend(
        {
            "type": "function_call",
            "call_id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }
        for call in message.tool_calls
    )
    return items


class LocalBackend(OpenAiCompatibleBackend):
    """A model server on this machine: text-generation-webui, Ollama, llama.cpp.

    text-generation-webui serves its OpenAI-compatible API on ``/v1`` at port 5000 by
    default. No key is required, but one is sent if configured, because some
    deployments put a reverse proxy in front.
    """

    name = "local"
    requires_key = False
    default_base_url = LOCAL_BASE_URL
    default_model = "local-model"


class OpenAiBackend(OpenAiCompatibleBackend):
    """OpenAI itself. Defaults to the Responses API, which is where Codex models are.

    Codex models (``gpt-5-codex``) are *not* served by ``/chat/completions`` -- that
    path answers 404 -- so ``wire="responses"`` is the working default here. Set
    ``TTRPG_LLM_WIRE=chat`` for a proxy or a chat-only model.
    """

    name = "openai"
    requires_key = True
    key_env = ("OPENAI_API_KEY",)
    default_wire = wire.WIRE_RESPONSES
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-5-codex"
    max_tokens_field = "max_completion_tokens"


class ClinePassBackend(OpenAiCompatibleBackend):
    """ClinePass via the Cline API: a subscription in front of open-weight models.

    Model ids are ClinePass slugs such as ``cline-pass/qwen3.7-max``. Non-streaming
    responses are wrapped in ``data`` today; :mod:`ttrpg_chatbots.llm.wire` accepts
    both shapes, so this keeps working if that changes.
    """

    name = "clinepass"
    requires_key = True
    key_env = ("CLINE_API_KEY",)
    default_wire = wire.WIRE_CHAT
    default_base_url = "https://api.cline.bot/api/v1"
    default_model = "cline-pass/qwen3.7-max"


BACKENDS: Mapping[str, type[OpenAiCompatibleBackend]] = {
    backend_class.name: backend_class
    for backend_class in (LocalBackend, OpenAiBackend, ClinePassBackend)
}


def build_backend(
    config: LlmConfig, *, transport: Transport | None = None
) -> OpenAiCompatibleBackend:
    """Build the backend a :class:`LlmConfig` describes."""
    backend_class = BACKENDS.get(config.backend)
    if backend_class is None:
        known = ", ".join(sorted(BACKENDS))
        raise LlmConfigError(f"unknown LLM backend {config.backend!r}; known backends: {known}")
    return backend_class(
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        wire_format=config.wire,
        timeout=config.timeout,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        transport=transport,
    )

