"""Backend request shapes and the mapping from HTTP status to failure kind."""

from __future__ import annotations

import pytest

from llm_support import FakeTransport, chat_body, ok, responses_body
from ttrpg_chatbots.llm import backends, wire
from ttrpg_chatbots.llm.config import LlmConfig
from ttrpg_chatbots.llm.http import HttpResponse
from ttrpg_chatbots.llm.types import (
    ChatMessage,
    LlmAuthError,
    LlmConfigError,
    LlmProtocolError,
    LlmRateLimited,
    LlmRequestError,
    LlmUnavailable,
)

KEY = "fake-key-not-a-real-credential"
MESSAGES = (
    ChatMessage(role="system", content="You are Brannoc."),
    ChatMessage(role="user", content="Who holds the docks?"),
)


def _local(transport, **kwargs):
    return backends.LocalBackend(
        transport=transport, base_url="http://127.0.0.1:5000/v1", **kwargs
    )


# -- request shape --------------------------------------------------------


def test_chat_wire_posts_to_chat_completions() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    _local(transport).complete(MESSAGES)
    assert transport.last.url == "http://127.0.0.1:5000/v1/chat/completions"


def test_a_trailing_slash_does_not_double_up() -> None:
    backend = backends.LocalBackend(base_url="http://host:1234/v1/", model="m")
    assert backend.url == "http://host:1234/v1/chat/completions"


def test_responses_wire_posts_to_responses() -> None:
    backend = backends.OpenAiBackend(
        api_key=KEY, wire_format=wire.WIRE_RESPONSES, transport=FakeTransport()
    )
    assert backend.url == "https://api.openai.com/v1/responses"


def test_chat_payload_carries_the_messages_and_limits() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    _local(transport, model="local-model", max_tokens=64, temperature=0.2).complete(MESSAGES)
    payload = transport.last.payload
    assert payload["model"] == "local-model"
    assert payload["messages"] == [message.as_dict() for message in MESSAGES]
    assert payload["max_tokens"] == 64
    assert payload["temperature"] == 0.2
    assert payload["stream"] is False


def test_no_temperature_when_it_is_switched_off() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    _local(transport, temperature=None).complete(MESSAGES)
    assert "temperature" not in transport.last.payload


def test_openai_chat_wire_uses_max_completion_tokens() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    backends.OpenAiBackend(api_key=KEY, wire_format=wire.WIRE_CHAT, transport=transport).complete(
        MESSAGES
    )
    payload = transport.last.payload
    assert "max_completion_tokens" in payload
    assert "max_tokens" not in payload


def test_an_api_key_becomes_a_bearer_header() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    backends.ClinePassBackend(api_key=KEY, transport=transport).complete(MESSAGES)
    assert transport.last.headers["Authorization"] == f"Bearer {KEY}"


def test_local_sends_no_authorization_header_by_default() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    _local(transport).complete(MESSAGES)
    assert "Authorization" not in transport.last.headers


def test_extra_headers_are_preserved() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    backend = _local(transport, extra_headers={"X-Guild": "greyfall"})
    backend.complete(MESSAGES)
    assert transport.last.headers["X-Guild"] == "greyfall"


def test_responses_payload_moves_the_system_prompt_to_instructions() -> None:
    transport = FakeTransport(ok(responses_body("hi")))
    backends.OpenAiBackend(api_key=KEY, transport=transport).complete(MESSAGES)
    payload = transport.last.payload
    assert payload["instructions"] == "You are Brannoc."
    assert payload["input"] == [{"role": "user", "content": "Who holds the docks?"}]
    assert payload["max_output_tokens"] == 300
    # Reasoning models reject temperature, so it must not be sent.
    assert "temperature" not in payload
    assert "messages" not in payload


def test_responses_payload_without_a_system_prompt_omits_instructions() -> None:
    transport = FakeTransport(ok(responses_body("hi")))
    message = ChatMessage(role="user", content="hello")
    backends.OpenAiBackend(api_key=KEY, transport=transport).complete((message,))
    assert "instructions" not in transport.last.payload


def test_the_timeout_reaches_the_transport() -> None:
    transport = FakeTransport(ok(chat_body("hi")))
    _local(transport, timeout=2.5).complete(MESSAGES)
    assert transport.last.timeout == 2.5


# -- defaults per provider ------------------------------------------------


def test_openai_defaults_target_the_responses_api() -> None:
    backend = backends.OpenAiBackend(api_key=KEY)
    assert backend.url == "https://api.openai.com/v1/responses"
    assert backend.model == "gpt-5-codex"


def test_clinepass_defaults_target_the_cline_api() -> None:
    backend = backends.ClinePassBackend(api_key=KEY)
    assert backend.url == "https://api.cline.bot/api/v1/chat/completions"
    assert backend.model.startswith("cline-pass/")


def test_local_needs_no_key_and_points_at_the_standard_port() -> None:
    backend = backends.LocalBackend()
    assert backend.url == "http://127.0.0.1:5000/v1/chat/completions"
    assert backend.headers() == {}


def test_a_missing_key_is_an_auth_failure_that_names_the_variable() -> None:
    with pytest.raises(LlmAuthError) as caught:
        backends.OpenAiBackend()
    assert "OPENAI_API_KEY" in str(caught.value)
    assert caught.value.backend == "openai"


def test_an_unknown_backend_cannot_be_built() -> None:
    with pytest.raises(LlmConfigError, match="known backends"):
        backends.build_backend(LlmConfig(backend="telepathy"))


def test_build_backend_carries_the_whole_configuration() -> None:
    config = LlmConfig(
        backend="local",
        base_url="http://10.0.0.2:8080/v1",
        model="mistral",
        timeout=12.0,
        max_tokens=99,
        temperature=None,
    )
    transport = FakeTransport(ok(chat_body("hi")))
    backend = backends.build_backend(config, transport=transport)
    assert isinstance(backend, backends.LocalBackend)
    assert backend.url == "http://10.0.0.2:8080/v1/chat/completions"
    assert backend.model == "mistral"
    backend.complete(MESSAGES)
    assert transport.last.timeout == 12.0
    assert transport.last.payload["max_tokens"] == 99


# -- failure mapping ------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, LlmAuthError),
        (403, LlmAuthError),
        (429, LlmRateLimited),
        (400, LlmRequestError),
        (422, LlmRequestError),
        (500, LlmUnavailable),
        (503, LlmUnavailable),
    ],
)
def test_http_status_maps_to_a_failure_kind(status: int, expected: type[Exception]) -> None:
    transport = FakeTransport(HttpResponse(status=status, body='{"error": "nope"}'))
    with pytest.raises(expected) as caught:
        _local(transport).complete(MESSAGES)
    assert caught.value.backend == "local"  # type: ignore[attr-defined]
    assert caught.value.status == status  # type: ignore[attr-defined]


def test_an_error_body_never_repeats_the_key() -> None:
    # Servers sometimes echo the rejected credential back in the error message.
    transport = FakeTransport(
        HttpResponse(status=401, body='{"error": "bad key ' + KEY + '"}')
    )
    with pytest.raises(LlmAuthError) as caught:
        backends.OpenAiBackend(api_key=KEY, transport=transport).complete(MESSAGES)
    message = str(caught.value)
    assert KEY not in message
    assert "***" in message


def test_a_transport_failure_is_stamped_with_the_backend_name() -> None:
    transport = FakeTransport(LlmUnavailable("cannot reach the host"))
    with pytest.raises(LlmUnavailable) as caught:
        backends.ClinePassBackend(api_key=KEY, transport=transport).complete(MESSAGES)
    assert caught.value.backend == "clinepass"


def test_a_protocol_failure_from_the_body_cap_is_stamped_too() -> None:
    transport = FakeTransport(LlmProtocolError("response body exceeds 4 bytes"))
    with pytest.raises(LlmProtocolError) as caught:
        _local(transport).complete(MESSAGES)
    assert caught.value.backend == "local"


def test_sending_nothing_is_a_request_error() -> None:
    with pytest.raises(LlmRequestError, match="no messages"):
        _local(FakeTransport()).complete(())


def test_a_successful_response_is_parsed_for_both_wires() -> None:
    chat = _local(FakeTransport(ok(chat_body("from chat"))))
    assert chat.complete(MESSAGES).text == "from chat"

    responses = backends.OpenAiBackend(
        api_key=KEY, transport=FakeTransport(ok(responses_body("from responses")))
    )
    assert responses.complete(MESSAGES).text == "from responses"


# -- constructor validation -----------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"base_url": "   "}, "no base URL"),
        ({"model": "  "}, "no model"),
        ({"wire_format": "grpc"}, "unknown wire format"),
        ({"timeout": 0}, "timeout"),
        ({"timeout": 10_000}, "timeout"),
        ({"max_tokens": 0}, "max tokens"),
        ({"max_tokens": 99_999}, "max tokens"),
        ({"temperature": 3.0}, "temperature"),
    ],
)
def test_invalid_settings_are_rejected_early(kwargs: dict, fragment: str) -> None:
    settings = {"base_url": "http://127.0.0.1:5000/v1", "model": "m", **kwargs}
    with pytest.raises(LlmConfigError, match=fragment):
        backends.LocalBackend(**settings)

