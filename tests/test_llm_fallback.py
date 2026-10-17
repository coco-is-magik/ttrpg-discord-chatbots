"""Fallback policy: name the cause, keep talking, never swallow our own bugs."""

from __future__ import annotations

import logging

import pytest

from llm_support import StaticResponder
from ttrpg_chatbots.llm.fallback import FallbackResponder, describe_failure
from ttrpg_chatbots.llm.types import (
    LlmAuthError,
    LlmConfigError,
    LlmProtocolError,
    LlmRateLimited,
    LlmRequestError,
    LlmUnavailable,
)


def test_a_healthy_primary_is_used_and_nothing_is_logged(caplog) -> None:
    primary = StaticResponder("llm:local", text="from the model")
    fallback = StaticResponder("reply:sable", text="from the classifier")
    with caplog.at_level(logging.WARNING):
        answer = FallbackResponder(primary, fallback).answer("hello")
    assert answer.text == "from the model"
    assert answer.degraded is False
    assert answer.fallback_reason is None
    assert caplog.records == []
    assert fallback.prompts == []


def test_an_auth_failure_warns_with_the_cause_and_falls_back(caplog) -> None:
    error = LlmAuthError(
        "openai rejected the credentials (HTTP 401: Incorrect API key)",
        backend="openai",
        status=401,
    )
    primary = StaticResponder("llm:openai", error=error)
    fallback = StaticResponder("reply:sable", text="Aye, I will answer instead.")
    with caplog.at_level(logging.WARNING):
        answer = FallbackResponder(primary, fallback).answer("who holds the docks?")

    assert answer.text == "Aye, I will answer instead."
    assert answer.source == "reply:sable"
    assert answer.degraded is True
    assert answer.fallback_reason == "openai (HTTP 401): authentication failed"

    (record,) = caplog.records
    assert record.levelno == logging.WARNING
    assert record.name == "ttrpg_chatbots.llm"
    message = record.getMessage()
    assert "llm:openai" in message
    assert "reply:sable" in message
    assert "authentication failed" in message
    # The original exception is attached, not just flattened into the text.
    assert record.exc_info is not None
    assert record.exc_info[1] is error


@pytest.mark.parametrize(
    ("error", "phrase"),
    [
        (LlmAuthError("x", backend="openai", status=401), "authentication failed"),
        (LlmUnavailable("x", backend="local"), "backend unreachable"),
        (LlmRateLimited("x", backend="clinepass", status=429), "rate limited"),
        (LlmRequestError("x", backend="openai", status=400), "request rejected"),
        (LlmProtocolError("x", backend="openai"), "unusable response"),
        (LlmConfigError("x"), "not configured"),
    ],
)
def test_each_failure_kind_is_named(error: Exception, phrase: str) -> None:
    assert phrase in describe_failure(error)


def test_the_subject_names_the_backend_and_status() -> None:
    assert (
        describe_failure(LlmRateLimited("slow down", backend="clinepass", status=429))
        == "clinepass (HTTP 429): rate limited"
    )


def test_a_failure_without_a_backend_says_so() -> None:
    assert describe_failure(LlmUnavailable("nothing to say")) == "llm: backend unreachable"


def test_a_bug_in_the_primary_is_not_hidden() -> None:
    # Only LlmError falls back; anything else must surface.
    primary = StaticResponder("llm:local", error=ZeroDivisionError("oops"))
    fallback = StaticResponder("reply:sable")
    with pytest.raises(ZeroDivisionError):
        FallbackResponder(primary, fallback).answer("hi")
    assert fallback.prompts == []


def test_a_failing_fallback_keeps_a_note_about_the_primary() -> None:
    primary = StaticResponder("llm:local", error=LlmUnavailable("down", backend="local"))
    fallback = StaticResponder("reply:sable", error=RuntimeError("no template fits"))
    with pytest.raises(RuntimeError) as caught:
        FallbackResponder(primary, fallback).answer("hi")
    assert any("llm:local" in note for note in caught.value.__notes__)


def test_a_custom_logger_can_be_supplied(caplog) -> None:
    logger = logging.getLogger("custom.llm")
    primary = StaticResponder("llm:local", error=LlmUnavailable("down", backend="local"))
    with caplog.at_level(logging.WARNING, logger="custom.llm"):
        FallbackResponder(primary, StaticResponder("reply:sable"), logger=logger).answer("hi")
    assert caplog.records[0].name == "custom.llm"


def test_the_traceback_is_logged_once_per_cause(caplog) -> None:
    # A live game keeps talking after the model dies; one traceback is enough.
    error = LlmUnavailable("cannot reach the host", backend="local")
    primary = StaticResponder("llm:local", error=error)
    responder = FallbackResponder(primary, StaticResponder("reply:sable"))
    with caplog.at_level(logging.WARNING):
        responder.answer("first")
        responder.answer("second")
    first, second = caplog.records
    assert first.exc_info is not None
    assert second.exc_info is None
    assert "backend unreachable" in second.getMessage()


def test_a_different_cause_gets_its_own_traceback(caplog) -> None:
    primary = StaticResponder("llm:local", error=LlmUnavailable("down", backend="local"))
    other = StaticResponder("llm:local", error=LlmAuthError("bad key", backend="local", status=401))
    with caplog.at_level(logging.WARNING):
        FallbackResponder(primary, StaticResponder("reply:sable")).answer("one")
        FallbackResponder(other, StaticResponder("reply:sable")).answer("two")
    assert caplog.records[0].exc_info is not None
    assert caplog.records[1].exc_info is not None


def test_both_sides_are_named() -> None:
    responder = FallbackResponder(StaticResponder("llm:local"), StaticResponder("reply:sable"))
    assert responder.name == "llm:local"
    assert responder.fallback_name == "reply:sable"


def test_the_prompt_is_passed_through_unchanged(caplog) -> None:
    primary = StaticResponder("llm:local", error=LlmUnavailable("down", backend="local"))
    fallback = StaticResponder("reply:sable")
    with caplog.at_level(logging.WARNING):
        FallbackResponder(primary, fallback).answer("the tide is out")
    assert primary.prompts == ["the tide is out"]
    assert fallback.prompts == ["the tide is out"]
