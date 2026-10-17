"""Response decoding: both wire formats, and every way a body can be unusable."""

from __future__ import annotations

import json

import pytest

from ttrpg_chatbots.llm import wire
from ttrpg_chatbots.llm.types import LlmConfigError, LlmProtocolError


def _chat(payload: dict):
    return wire.parse_completion(payload, wire=wire.WIRE_CHAT, backend="test")


def _responses(payload: dict):
    return wire.parse_completion(payload, wire=wire.WIRE_RESPONSES, backend="test")


def _message(content) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


# -- Chat Completions -----------------------------------------------------


def test_chat_text_model_and_usage_are_read() -> None:
    completion = _chat(
        {
            "model": "local-model",
            "choices": [{"message": {"content": "Aye, that I do."}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 12},
        }
    )
    assert completion.text == "Aye, that I do."
    assert completion.model == "local-model"
    assert completion.usage["total_tokens"] == 12
    assert completion.truncated is False


def test_the_clinepass_data_envelope_is_accepted() -> None:
    payload = {"success": True, "data": _message("The docks are ours.")}
    assert _chat(payload).text == "The docks are ours."


def test_a_plain_body_wins_over_a_data_key() -> None:
    payload = _message("plain")
    payload["data"] = {"choices": [{"message": {"content": "envelope"}}]}
    assert _chat(payload).text == "plain"


def test_content_may_be_a_list_of_parts() -> None:
    parts = [{"type": "text", "text": "Part one. "}, {"type": "text", "text": "Part two."}]
    assert _chat(_message(parts)).text == "Part one. Part two."


def test_a_content_part_without_text_is_skipped() -> None:
    parts = [{"type": "image_url", "image_url": {"url": "x"}}, {"text": "still here"}]
    assert _chat(_message(parts)).text == "still here"


def test_legacy_completion_text_is_accepted() -> None:
    assert _chat({"choices": [{"text": "old style"}]}).text == "old style"


def test_a_truncated_answer_is_flagged() -> None:
    payload = {"choices": [{"message": {"content": "half a sen"}, "finish_reason": "length"}]}
    assert _chat(payload).truncated is True


def test_missing_choices_names_the_keys_it_did_get() -> None:
    with pytest.raises(LlmProtocolError) as caught:
        _chat({"id": "x", "object": "chat.completion"})
    assert "no choices" in str(caught.value)
    assert "keys: id, object" in str(caught.value)


def test_an_error_body_explains_itself() -> None:
    with pytest.raises(LlmProtocolError, match="error: invalid model"):
        _chat({"error": {"message": "invalid model", "type": "invalid_request_error"}})


def test_an_empty_answer_is_refused() -> None:
    with pytest.raises(LlmProtocolError, match="empty answer"):
        _chat(_message("   "))


def test_choices_must_be_a_non_empty_list() -> None:
    with pytest.raises(LlmProtocolError, match="no choices"):
        _chat({"choices": []})
    with pytest.raises(LlmProtocolError, match="no choices"):
        _chat({"choices": "nope"})


def test_a_malformed_choice_is_reported() -> None:
    with pytest.raises(LlmProtocolError, match="malformed choice"):
        _chat({"choices": ["nope"]})



# -- Responses ------------------------------------------------------------


def test_responses_output_text_is_read() -> None:
    completion = _responses(
        {
            "model": "gpt-5-codex",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "The crown is gone."}],
                }
            ],
            "usage": {"output_tokens": 9},
        }
    )
    assert completion.text == "The crown is gone."
    assert completion.model == "gpt-5-codex"
    assert completion.usage["output_tokens"] == 9


def test_several_message_items_are_joined() -> None:
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": "One."}]},
            {"type": "message", "content": [{"type": "output_text", "text": "Two."}]},
        ]
    }
    assert _responses(payload).text == "One.\nTwo."


def test_an_incomplete_response_is_flagged_but_usable() -> None:
    payload = {
        "status": "incomplete",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": "cut"}]}],
    }
    completion = _responses(payload)
    assert completion.truncated is True
    assert completion.text == "cut"


def test_a_refusal_is_an_error_not_an_answer() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "refusal", "refusal": "I cannot help with that."}],
            }
        ]
    }
    with pytest.raises(LlmProtocolError, match="refused to answer: I cannot help"):
        _responses(payload)


def test_a_failed_response_is_an_error() -> None:
    payload = {"status": "failed", "error": {"message": "server blew up"}}
    with pytest.raises(LlmProtocolError, match="failed response"):
        _responses(payload)


def test_the_output_text_convenience_field_is_accepted() -> None:
    assert _responses({"output": [], "output_text": "  shortcut  "}).text == "shortcut"


def test_missing_output_is_reported() -> None:
    with pytest.raises(LlmProtocolError, match="no output text"):
        _responses({"status": "completed", "output": []})


# -- decoding and dispatch ------------------------------------------------


def test_a_non_json_body_is_a_protocol_error() -> None:
    with pytest.raises(LlmProtocolError, match="non-JSON body"):
        wire.decode_json("<html>502</html>", backend="test")


def test_json_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(LlmProtocolError, match="not an object"):
        wire.decode_json("[1, 2]", backend="test")
    assert wire.decode_json('{"a": 1}', backend="test") == {"a": 1}


def test_an_unknown_wire_format_is_a_config_error() -> None:
    with pytest.raises(LlmConfigError, match="unknown wire format"):
        wire.parse_completion({}, wire="grpc", backend="test")


def test_the_body_helpers_decode() -> None:
    from llm_support import chat_body, responses_body

    assert _chat(json.loads(chat_body("hello"))).text == "hello"
    assert _chat(json.loads(chat_body("hello", wrapped=True))).text == "hello"
    assert _responses(json.loads(responses_body("hello"))).text == "hello"
