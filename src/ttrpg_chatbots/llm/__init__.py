"""Language-model replies, with the classifier as a safety net.

Three backends, one interface:

``local``
    an OpenAI-compatible server on this machine -- text-generation-webui listens on
    ``http://127.0.0.1:5000/v1`` by default, and ``TTRPG_LLM_PORT`` moves it.
``openai``
    OpenAI's Responses API, which is where Codex models (``gpt-5-codex``) live. Needs
    ``OPENAI_API_KEY``.
``clinepass``
    ClinePass through the Cline API, so the model is chosen with a ClinePass slug such
    as ``cline-pass/qwen3.7-max``. Needs ``CLINE_API_KEY``.

:func:`load_llm_config` decides which; :func:`build_backend` constructs it;
:class:`LlmResponder` puts a persona in front of it; :class:`FallbackResponder` keeps
the conversation alive when it cannot answer.

Nothing here imports ``reply``: the fallback target only has to satisfy
:class:`~ttrpg_chatbots.respond.Responder`, so the two are wired together in the CLI.
"""

from ttrpg_chatbots.llm import wire
from ttrpg_chatbots.llm.backends import (
    BACKENDS,
    ClinePassBackend,
    LocalBackend,
    OpenAiBackend,
    OpenAiCompatibleBackend,
    build_backend,
)
from ttrpg_chatbots.llm.config import LlmConfig, load_llm_config
from ttrpg_chatbots.llm.fallback import FallbackResponder, describe_failure
from ttrpg_chatbots.llm.http import HttpResponse, Transport, UrllibTransport
from ttrpg_chatbots.llm.prompt import build_messages, persona_from, system_prompt
from ttrpg_chatbots.llm.responder import LlmResponder
from ttrpg_chatbots.llm.tools import (
    Tool,
    ToolBox,
    ToolInvocation,
    chat_schemas,
    responses_schemas,
)
from ttrpg_chatbots.llm.types import (
    ChatMessage,
    Completion,
    LlmAuthError,
    LlmConfigError,
    LlmError,
    LlmProtocolError,
    LlmRateLimited,
    LlmRequestError,
    LlmUnavailable,
    Persona,
    ToolCall,
)
from ttrpg_chatbots.respond import Answer, Responder

__all__ = [
    "Answer",
    "BACKENDS",
    "ChatMessage",
    "ClinePassBackend",
    "Completion",
    "FallbackResponder",
    "HttpResponse",
    "LlmAuthError",
    "LlmConfig",
    "LlmConfigError",
    "LlmError",
    "LlmProtocolError",
    "LlmRateLimited",
    "LlmRequestError",
    "LlmResponder",
    "LlmUnavailable",
    "LocalBackend",
    "OpenAiBackend",
    "OpenAiCompatibleBackend",
    "Persona",
    "Responder",
    "Tool",
    "ToolBox",
    "ToolCall",
    "ToolInvocation",
    "Transport",
    "UrllibTransport",
    "build_backend",
    "build_messages",
    "chat_schemas",
    "describe_failure",
    "load_llm_config",
    "persona_from",
    "responses_schemas",
    "system_prompt",
    "wire",
]
