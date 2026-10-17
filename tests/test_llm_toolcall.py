"""Tool calls: schema shapes, message serialisation, and the bounded loop."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from llm_support import FakeBackend, FakeTransport, completion, ok
from ttrpg_chatbots.llm import backends
from ttrpg_chatbots.llm.responder import LlmResponder
from ttrpg_chatbots.llm.tools import ToolBox, chat_schemas, responses_schemas
from ttrpg_chatbots.llm.types import (
    ChatMessage,
    LlmProtocolError,
    Persona,
    ToolCall,
)

PERSONA = Persona(name="Brannoc")


@dataclass
class FakeOutcome:
    text: str
    payload: dict


class EchoTool:
    """A tool that echoes one argument, so the loop is visible in assertions."""

    name = "echo"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def schema(self) -> dict:
        return {
            "name": "echo",
            "description": "echo text back",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }

    def run(self, arguments: dict) -> FakeOutcome:
        self.calls.append(dict(arguments))
        return FakeOutcome(text=f"echo: {arguments.get('text', '')}", payload=dict(arguments))


class BrokenTool:
    name = "broken"

    def schema(self) -> dict:
        return {"name": "broken", "description": "always fails", "parameters": {}}

    def run(self, arguments: dict) -> FakeOutcome:
        raise RuntimeError("the tool fell over")


def chat_tool_body(name: str = "echo", arguments: str = '{"text": "hi"}', call_id: str = "c1"):
    return json.dumps(
        {
            "model": "local-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": name, "arguments": arguments},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )


def responses_tool_body(name: str = "echo", arguments: str = '{"text": "hi"}'):
    return json.dumps(
        {
            "model": "gpt-5-codex",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "c1",
                    "name": name,
                    "arguments": arguments,
                }
            ],
        }
    )


# -- schema translation ---------------------------------------------------


def test_chat_schemas_are_wrapped_in_a_function_object() -> None:
    schemas = chat_schemas((EchoTool().schema(),))
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "echo"


def test_responses_schemas_are_flattened() -> None:
    schemas = responses_schemas((EchoTool().schema(),))
    assert schemas[0]["type"] == "function"
    assert schemas[0]["name"] == "echo"
    assert "function" not in schemas[0]


# -- message serialisation ------------------------------------------------


def _tool_turns() -> tuple[ChatMessage, ...]:
    call = ToolCall(id="c1", name="roll_dice", arguments='{"count": 3}')
    return (
        ChatMessage(role="user", content="roll 3d6"),
        ChatMessage(role="assistant", content="", tool_calls=(call,)),
        ChatMessage(role="tool", content="rolled 9", tool_call_id="c1", name="roll_dice"),
    )


def test_chat_payload_carries_tool_turns() -> None:
    backend = backends.LocalBackend(base_url="http://127.0.0.1:5000/v1", model="m")
    messages = backend.payload(_tool_turns())["messages"]
    assert messages[1]["content"] is None
    assert messages[1]["tool_calls"][0] == {
        "id": "c1",
        "type": "function",
        "function": {"name": "roll_dice", "arguments": '{"count": 3}'},
    }
    assert messages[2] == {"role": "tool", "tool_call_id": "c1", "content": "rolled 9"}


def test_responses_payload_carries_tool_turns() -> None:
    backend = backends.OpenAiBackend(api_key="k", wire_format="responses")
    items = backend.payload(_tool_turns())["input"]
    assert items[1] == {
        "type": "function_call",
        "call_id": "c1",
        "name": "roll_dice",
        "arguments": '{"count": 3}',
    }
    assert items[2] == {
        "type": "function_call_output",
        "call_id": "c1",
        "output": "rolled 9",
    }


def test_tools_are_offered_in_each_wire_format() -> None:
    schema = EchoTool().schema()
    chat = backends.LocalBackend(base_url="http://x/v1", model="m")
    body = chat.payload((ChatMessage(role="user", content="hi"),), (schema,))
    assert body["tools"][0]["function"]["name"] == "echo"
    assert body["tool_choice"] == "auto"

    responses = backends.OpenAiBackend(api_key="k", wire_format="responses")
    body = responses.payload((ChatMessage(role="user", content="hi"),), (schema,))
    assert body["tools"][0]["name"] == "echo"


def test_no_tools_means_no_tools_key() -> None:
    backend = backends.LocalBackend(base_url="http://x/v1", model="m")
    payload = backend.payload((ChatMessage(role="user", content="hi"),))
    assert "tools" not in payload


# -- parsing tool calls out of responses ----------------------------------


def test_a_chat_tool_call_is_parsed() -> None:
    transport = FakeTransport(ok(chat_tool_body()))
    backend = backends.LocalBackend(base_url="http://x/v1", model="m", transport=transport)
    completion_ = backend.complete((ChatMessage(role="user", content="hi"),))
    assert completion_.text == ""
    assert completion_.tool_calls[0].name == "echo"
    assert completion_.tool_calls[0].arguments == '{"text": "hi"}'


def test_a_responses_tool_call_is_parsed() -> None:
    transport = FakeTransport(ok(responses_tool_body()))
    backend = backends.OpenAiBackend(api_key="k", transport=transport)
    completion_ = backend.complete((ChatMessage(role="user", content="hi"),))
    assert completion_.text == ""
    assert completion_.tool_calls[0].id == "c1"
    assert completion_.tool_calls[0].name == "echo"


def test_arguments_sent_as_an_object_are_normalised() -> None:
    body = json.loads(chat_tool_body())
    body["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = {"text": "hi"}
    transport = FakeTransport(ok(json.dumps(body)))
    backend = backends.LocalBackend(base_url="http://x/v1", model="m", transport=transport)
    parsed = backend.complete((ChatMessage(role="user", content="hi"),)).tool_calls[0]
    assert json.loads(parsed.arguments) == {"text": "hi"}


@pytest.mark.parametrize(
    "message",
    [
        {"tool_calls": "nope"},
        {"tool_calls": [1]},
        {"tool_calls": [{"id": "c1"}]},
        {"tool_calls": [{"id": "c1", "function": {"arguments": "{}"}}]},
    ],
)
def test_malformed_tool_calls_are_protocol_errors(message: dict) -> None:
    body = {"choices": [{"message": {"role": "assistant", "content": "", **message}}]}
    backend = backends.LocalBackend(
        base_url="http://x/v1", model="m", transport=FakeTransport(ok(json.dumps(body)))
    )
    with pytest.raises(LlmProtocolError):
        backend.complete((ChatMessage(role="user", content="hi"),))


def test_a_message_may_omit_its_text_only_when_it_calls_a_tool() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        ChatMessage(role="assistant", content="")
    with pytest.raises(ValueError, match="tool_call_id"):
        ChatMessage(role="tool", content="result")
    with pytest.raises(ValueError, match="only an assistant"):
        ChatMessage(
            role="user", content="hi", tool_calls=(ToolCall(id="c", name="n"),)
        )


# -- the toolbox ----------------------------------------------------------


def test_the_toolbox_reports_what_it_offers() -> None:
    box = ToolBox(EchoTool())
    assert box.names == ("echo",)
    assert "echo" in box
    assert bin(len(box)) == "0b1"
    assert box.schemas()[0]["name"] == "echo"


def test_duplicate_tool_names_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate tool"):
        ToolBox(EchoTool(), EchoTool())


def test_an_unknown_tool_tells_the_model_what_exists() -> None:
    invocation = ToolBox(EchoTool()).invoke(ToolCall(id="c1", name="summon_dragon"))
    assert invocation.failed is True
    assert "unknown tool" in invocation.text
    assert "echo" in invocation.text


@pytest.mark.parametrize(
    ("arguments", "fragment"),
    [
        ("not json", "not valid JSON"),
        ("[1, 2]", "must be a JSON object"),
        ('"text"', "must be a JSON object"),
    ],
)
def test_bad_arguments_are_reported_not_raised(arguments: str, fragment: str) -> None:
    invocation = ToolBox(EchoTool()).invoke(
        ToolCall(id="c1", name="echo", arguments=arguments)
    )
    assert invocation.failed is True
    assert fragment in invocation.text


def test_a_tool_that_raises_is_reported_not_raised(caplog) -> None:
    invocation = ToolBox(BrokenTool()).invoke(ToolCall(id="c1", name="broken"))
    assert invocation.failed is True
    assert "the tool fell over" in invocation.text
    assert any(record.levelno >= 30 for record in caplog.records)


def test_a_successful_call_keeps_the_outcome() -> None:
    echo = EchoTool()
    invocation = ToolBox(echo).invoke(
        ToolCall(id="c1", name="echo", arguments='{"text": "hello"}')
    )
    assert invocation.failed is False
    assert invocation.text == "echo: hello"
    assert invocation.outcome.payload == {"text": "hello"}
    assert echo.calls == [{"text": "hello"}]



# -- the responder loop ---------------------------------------------------


def _responder(backend: FakeBackend, box: ToolBox | None, **kwargs) -> LlmResponder:
    return LlmResponder(lambda: backend, PERSONA, name="llm:fake", tools=box, **kwargs)


def test_the_model_may_call_a_tool_and_then_answer() -> None:
    call = ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')
    backend = FakeBackend(
        completion("", tool_calls=(call,)),
        completion("The echo came back."),
    )
    echo = EchoTool()
    answer = _responder(backend, ToolBox(echo)).answer("say hi")

    assert answer.text == "The echo came back."
    assert answer.source == "llm:fake"
    assert backend.rounds == 2
    assert echo.calls == [{"text": "hi"}]
    assert answer.detail["tools"] == [
        {
            "name": "echo",
            "arguments": '{"text": "hi"}',
            "result": "echo: hi",
            "failed": False,
        }
    ]


def test_the_second_turn_carries_the_call_and_its_result() -> None:
    call = ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')
    backend = FakeBackend(completion("", tool_calls=(call,)), completion("done"))
    _responder(backend, ToolBox(EchoTool())).answer("say hi")

    second = backend.requests[1]
    assistant = second[-2]
    assert assistant.role == "assistant"
    assert assistant.tool_calls == (call,)
    assert second[-1].role == "tool"
    assert second[-1].tool_call_id == "c1"
    assert second[-1].content == "echo: hi"


def test_the_tools_are_offered_on_every_turn() -> None:
    call = ToolCall(id="c1", name="echo", arguments="{}")
    backend = FakeBackend(completion("", tool_calls=(call,)), completion("done"))
    _responder(backend, ToolBox(EchoTool())).answer("say hi")
    assert all(len(offered) == 1 for offered in backend.offered_tools)
    assert backend.offered_tools[0][0]["name"] == "echo"


def test_no_toolbox_means_no_tools_are_offered() -> None:
    backend = FakeBackend(completion("just words"))
    answer = _responder(backend, None).answer("hello")
    assert backend.offered_tools == [()]
    assert answer.detail["tools"] == []


def test_a_hallucinated_tool_call_without_tools_is_survivable() -> None:
    call = ToolCall(id="c1", name="echo", arguments="{}")
    backend = FakeBackend(completion("", tool_calls=(call,)))
    answer = _responder(backend, None).answer("hello")
    assert answer.text == "I could not put that into words."


def test_an_unknown_tool_is_reported_back_to_the_model() -> None:
    call = ToolCall(id="c1", name="summon_dragon", arguments="{}")
    backend = FakeBackend(completion("", tool_calls=(call,)), completion("Sorry, no dragons."))
    answer = _responder(backend, ToolBox(EchoTool())).answer("summon a dragon")

    assert answer.detail["tools"][0]["failed"] is True
    fed_back = backend.requests[1][-1].content
    assert "unknown tool" in fed_back
    assert answer.text == "Sorry, no dragons."


def test_the_tool_budget_bounds_the_loop() -> None:
    call = ToolCall(id="c1", name="echo", arguments='{"text": "again"}')
    backend = FakeBackend(*[completion("", tool_calls=(call,)) for _ in range(5)])
    answer = _responder(backend, ToolBox(EchoTool()), max_tool_rounds=1).answer("loop")

    assert backend.rounds == 2  # one tool round, then the budget stops the loop
    assert answer.detail["tool_budget_exhausted"] is True
    # The roll happened, so it is reported rather than dropped.
    assert answer.text == "echo: again"


def test_a_zero_budget_reports_the_tool_text_immediately() -> None:
    call = ToolCall(id="c1", name="echo", arguments='{"text": "hi"}')
    backend = FakeBackend(completion("", tool_calls=(call,)))
    answer = _responder(backend, ToolBox(EchoTool()), max_tool_rounds=0).answer("loop")
    assert backend.rounds == 1
    assert answer.detail["tool_budget_exhausted"] is True
    assert answer.text == "I could not finish that."


def test_a_negative_budget_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="max_tool_rounds"):
        _responder(FakeBackend(), None, max_tool_rounds=-1)

