"""The only module in the project that opens an outbound HTTP connection.

Everything above this line takes a :class:`Transport`, so the entire LLM stack is
testable without a socket -- which matters, because the test suite refuses network
access outright and because a misconfigured base URL must never be able to hang a
test run.

``urllib`` is used on purpose: it is stdlib, so the LLM layer adds no dependency, and
the calls are synchronous, matching the STT and TTS engines (the bot runs both in a
worker thread).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ttrpg_chatbots.llm.types import LlmProtocolError, LlmUnavailable

USER_AGENT = "ttrpg-chatbots"

# A local model server that starts streaming an error, or a proxy that answers with a
# huge HTML page, must not be able to exhaust memory.
MAX_BODY_BYTES = 1_000_000

# Error messages are logged; keep them short and free of a whole HTML error page.
MAX_DETAIL_CHARS = 400


@dataclass(frozen=True)
class HttpResponse:
    """A completed HTTP exchange, including 4xx and 5xx responses."""

    status: int
    body: str
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    """A JSON-over-HTTP POST. Implemented by :class:`UrllibTransport` and by fakes."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    """Synchronous JSON POSTs via the standard library."""

    name = "urllib"

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout: float,
    ) -> HttpResponse:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                **headers,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    status=int(response.status),
                    body=_read_capped(response),
                    headers=dict(response.headers),
                )
        except urllib.error.HTTPError as error:
            # HTTPError is a URLError subclass, so it must be caught first: an HTTP
            # error still carries a body, and the body is what says *why*.
            return HttpResponse(
                status=int(error.code),
                body=_read_capped(error),
                headers=dict(error.headers or {}),
            )
        except (urllib.error.URLError, OSError) as error:
            raise LlmUnavailable(f"cannot reach {host_of(url)}: {error}") from error


def _read_capped(stream: Any) -> str:
    try:
        raw = stream.read(MAX_BODY_BYTES + 1)
    except OSError as error:
        raise LlmUnavailable(f"connection failed while reading the response: {error}") from error
    if len(raw) > MAX_BODY_BYTES:
        raise LlmProtocolError(f"response body exceeds {MAX_BODY_BYTES} bytes")
    return raw.decode("utf-8", errors="replace")


def host_of(url: str) -> str:
    """``scheme://host:port`` only -- a path or query could carry a token."""
    parts = urllib.parse.urlsplit(url)
    if not parts.netloc:
        return url
    return f"{parts.scheme}://{parts.netloc}"


def redact(text: str, *secrets: str) -> str:
    """Remove any known secret from ``text`` before it reaches a log or an exception."""
    cleaned = text
    for secret in secrets:
        secret = (secret or "").strip()
        if len(secret) >= 4:
            cleaned = cleaned.replace(secret, "***")
    return cleaned


def summarise(text: str, *, limit: int = MAX_DETAIL_CHARS) -> str:
    """Collapse whitespace and truncate, so a log line stays a log line."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "\u2026"


def describe_response(response: HttpResponse, *secrets: str) -> str:
    """A log-safe one-liner for an unsuccessful response."""
    body = summarise(redact(response.body, *secrets))
    return f"HTTP {response.status}: {body}" if body else f"HTTP {response.status}"
