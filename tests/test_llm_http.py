"""The HTTP boundary: redaction, status mapping, and body limits.

Every case drives ``urlopen`` through a fake, so nothing here opens a socket.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from ttrpg_chatbots.llm import http
from ttrpg_chatbots.llm.http import (
    HttpResponse,
    UrllibTransport,
    describe_response,
    host_of,
    redact,
    summarise,
)
from ttrpg_chatbots.llm.types import LlmProtocolError, LlmUnavailable

SECRET = "fake-key-not-a-real-credential"


class _FakeResponse:
    """Enough of ``http.client.HTTPResponse`` for the transport."""

    def __init__(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def close(self) -> None:
        """``HTTPError`` wraps its file in a temporary-file closer that calls close()."""


def test_redact_removes_a_known_secret() -> None:
    text = f"invalid key {SECRET} for project"
    assert SECRET not in redact(text, SECRET)
    assert "***" in redact(text, SECRET)


def test_redact_leaves_very_short_strings_alone() -> None:
    # Blanket replacement of 1-3 character values would mangle ordinary words.
    assert redact("the ab key", "ab", "") == "the ab key"


def test_summarise_collapses_whitespace_and_truncates() -> None:
    assert summarise("a\n\n  b\tc") == "a b c"
    shortened = summarise("x" * 500)
    assert len(shortened) == http.MAX_DETAIL_CHARS
    assert shortened.endswith("\u2026")


def test_host_of_hides_the_path_and_query() -> None:
    assert host_of("https://api.example.com/v1/chat?key=" + SECRET) == "https://api.example.com"
    assert host_of("not-a-url") == "not-a-url"


def test_describe_response_includes_the_status_and_redacts() -> None:
    response = HttpResponse(status=401, body='{"error": "bad key ' + SECRET + '"}')
    described = describe_response(response, SECRET)
    assert described.startswith("HTTP 401: ")
    assert SECRET not in described


def test_describe_response_with_no_body_has_no_trailing_colon() -> None:
    assert describe_response(HttpResponse(status=403, body="  ")) == "HTTP 403"


def test_a_connection_failure_becomes_llm_unavailable(monkeypatch) -> None:
    def refuse(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    with pytest.raises(LlmUnavailable) as caught:
        UrllibTransport().post_json(
            "https://api.example.com/v1/chat?key=" + SECRET, {}, {}, 5.0
        )
    message = str(caught.value)
    assert "https://api.example.com" in message
    assert SECRET not in message


def test_a_timeout_becomes_llm_unavailable(monkeypatch) -> None:
    def time_out(request, timeout=None):
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", time_out)
    with pytest.raises(LlmUnavailable):
        UrllibTransport().post_json("http://127.0.0.1:5000/v1/chat/completions", {}, {}, 1.0)


def test_an_http_error_is_returned_not_raised(monkeypatch) -> None:
    def reject(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},  # type: ignore[arg-type]
            _FakeResponse(401, b'{"error": "no"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", reject)
    response = UrllibTransport().post_json("http://127.0.0.1:5000/v1/chat", {}, {}, 5.0)
    assert response.status == 401
    assert response.body == '{"error": "no"}'


def test_the_request_is_a_json_post_with_the_given_headers(monkeypatch) -> None:
    captured = {}

    def capture(request, timeout=None):
        captured["request"] = request
        captured["timeout"] = timeout
        return _FakeResponse(200, b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    UrllibTransport().post_json(
        "http://127.0.0.1:5000/v1/chat/completions",
        {"model": "m", "messages": []},
        {"Authorization": "Bearer " + SECRET},
        7.5,
    )
    request = captured["request"]
    assert request.get_method() == "POST"
    assert json.loads(request.data.decode("utf-8")) == {"model": "m", "messages": []}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") == "Bearer " + SECRET
    assert captured["timeout"] == 7.5


def test_an_oversized_body_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(http, "MAX_BODY_BYTES", 4)

    def flood(request, timeout=None):
        return _FakeResponse(200, b"0123456789")

    monkeypatch.setattr(urllib.request, "urlopen", flood)
    with pytest.raises(LlmProtocolError, match="exceeds 4 bytes"):
        UrllibTransport().post_json("http://127.0.0.1:5000/v1/chat", {}, {}, 5.0)


def test_invalid_utf8_is_replaced_rather_than_raised(monkeypatch) -> None:
    def garbage(request, timeout=None):
        return _FakeResponse(200, b"\xff\xfe{}")

    monkeypatch.setattr(urllib.request, "urlopen", garbage)
    response = UrllibTransport().post_json("http://127.0.0.1:5000/v1/chat", {}, {}, 5.0)
    assert "\ufffd" in response.body


def test_a_read_failure_becomes_llm_unavailable(monkeypatch) -> None:
    class Broken(_FakeResponse):
        def read(self, size: int = -1) -> bytes:
            raise OSError("connection reset")

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=None: Broken(200, b""))
    with pytest.raises(LlmUnavailable, match="reading the response"):
        UrllibTransport().post_json("http://127.0.0.1:5000/v1/chat", {}, {}, 5.0)
