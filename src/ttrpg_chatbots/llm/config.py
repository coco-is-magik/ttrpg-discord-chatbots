"""LLM configuration: which backend, and how to authenticate to it.

Deliberately a pure function of a mapping: no file I/O, no ``dotenv``. The bot reads
it at startup and the CLI reads it per invocation, so neither has to wonder which
directory a ``.env`` came from. Callers that want ``.env`` support load it first
(``ttrpg_chatbots.config`` already does that for Discord).

Secrets follow the same rule as the Discord token: a ``*_FILE`` variable wins over a
plain variable, and the resolved key never appears in ``repr``, a log line or an error.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from ttrpg_chatbots.llm import backends, wire
from ttrpg_chatbots.llm.types import LlmConfigError

ENV_BACKEND = "TTRPG_LLM_BACKEND"
ENV_BASE_URL = "TTRPG_LLM_BASE_URL"
ENV_PORT = "TTRPG_LLM_PORT"
ENV_MODEL = "TTRPG_LLM_MODEL"
ENV_WIRE = "TTRPG_LLM_WIRE"
ENV_API_KEY = "TTRPG_LLM_API_KEY"
ENV_TIMEOUT = "TTRPG_LLM_TIMEOUT"
ENV_MAX_TOKENS = "TTRPG_LLM_MAX_TOKENS"
ENV_TEMPERATURE = "TTRPG_LLM_TEMPERATURE"

OFF = "off"
AUTO = "auto"
OFF_ALIASES = frozenset({"off", "none", "disabled", "no"})
# ``auto`` prefers a backend that has a key; the local server needs none.
AUTO_ORDER = ("openai", "clinepass")

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_TOKENS = 300
DEFAULT_TEMPERATURE = 0.7
MAX_TEMPERATURE = 2.0


@dataclass(frozen=True)
class LlmConfig:
    """Everything needed to build a backend. Safe to log."""

    backend: str
    wire: str = wire.WIRE_CHAT
    base_url: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    timeout: float = DEFAULT_TIMEOUT
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float | None = DEFAULT_TEMPERATURE

    @property
    def enabled(self) -> bool:
        """False when the LLM is switched off and the classifier is the only answerer."""
        return self.backend != OFF

    def describe(self) -> dict[str, object]:
        """A log-safe summary: says whether a key exists, never what it is."""
        return {
            "backend": self.backend,
            "enabled": self.enabled,
            "wire": self.wire,
            "base_url": self.base_url,
            "model": self.model,
            "api_key": "set" if self.api_key else "unset",
            "timeout_s": self.timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }


def load_llm_config(env: Mapping[str, str] | None = None) -> LlmConfig:
    """Resolve the backend, endpoint and credentials from the environment."""
    values = os.environ if env is None else env
    backend = _resolve_backend(values)
    if backend == OFF:
        # Switched off: do not complain about settings that will never be used.
        return LlmConfig(backend=OFF)

    backend_class = backends.BACKENDS[backend]
    explicit_base = values.get(ENV_BASE_URL, "").strip()
    if explicit_base:
        base_url = _check_url(explicit_base)
    else:
        base_url = _default_base_url(backend, backend_class, values)
    return LlmConfig(
        backend=backend,
        wire=_wire_format(values.get(ENV_WIRE, "").strip() or backend_class.default_wire),
        base_url=base_url,
        model=values.get(ENV_MODEL, "").strip() or backend_class.default_model,
        api_key=_read_key(values, backend_class),
        timeout=_timeout(values),
        max_tokens=_max_tokens(values),
        temperature=_temperature(values),
    )


def _resolve_backend(values: Mapping[str, str]) -> str:
    raw = values.get(ENV_BACKEND, "").strip().lower()
    if raw in OFF_ALIASES:
        return OFF
    if raw and raw != AUTO:
        if raw not in backends.BACKENDS:
            known = ", ".join([*sorted(backends.BACKENDS), AUTO, OFF])
            raise LlmConfigError(f"unknown {ENV_BACKEND} {raw!r}; expected one of {known}")
        return raw
    for name in AUTO_ORDER:
        backend_class = backends.BACKENDS[name]
        if backend_class.requires_key and _key_present(values, backend_class):
            return name
    return "local"


def _default_base_url(
    backend: str, backend_class: type[backends.OpenAiCompatibleBackend], values: Mapping[str, str]
) -> str:
    if backend != "local":
        return backend_class.default_base_url
    port = _port(values.get(ENV_PORT, "").strip())
    return f"http://{backends.LOCAL_HOST}:{port}/v1"


def _key_present(values: Mapping[str, str], backend_class: type) -> bool:
    """Whether a key is configured, without reading any file."""
    for name in (ENV_API_KEY, *backend_class.key_env):
        if values.get(name, "").strip() or values.get(f"{name}_FILE", "").strip():
            return True
    return False


def _read_key(values: Mapping[str, str], backend_class: type) -> str:
    """The API key, most specific source first: ``*_FILE`` beats a plain variable.

    File-backed secrets matter for the same reason as ``DISCORD_TOKEN_FILE``: Docker
    secrets and systemd credentials are files, and a key in ``ps`` output or a shell
    history is a leaked key.
    """
    names = (ENV_API_KEY, *backend_class.key_env)
    for name in names:
        path = values.get(f"{name}_FILE", "").strip()
        if path:
            return _read_secret_file(path, f"{name}_FILE")
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return _check_key(value, name)
    return ""


def _read_secret_file(raw_path: str, variable: str) -> str:
    path = Path(raw_path).expanduser()
    try:
        secret = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as error:
        raise LlmConfigError(f"{variable} is not a readable text file: {path}") from error
    if not secret:
        raise LlmConfigError(f"{variable} file is empty: {path}")
    return _check_key(secret, variable)


def _check_key(value: str, variable: str) -> str:
    if any(character.isspace() for character in value):
        raise LlmConfigError(
            f"the API key from {variable} contains whitespace, so it is not a single key; "
            "check the secret file or environment value"
        )
    return value


def _check_url(raw: str) -> str:
    url = raw.rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise LlmConfigError(
            f"{ENV_BASE_URL} must be an http(s) URL including the host, "
            f"for example http://127.0.0.1:5000/v1, got {raw!r}"
        )
    return url


def _wire_format(raw: str) -> str:
    value = raw.strip().lower()
    if value not in wire.WIRES:
        raise LlmConfigError(
            f"{ENV_WIRE} must be one of {wire.WIRES} ({wire.WIRE_CHAT} is Chat "
            f"Completions, {wire.WIRE_RESPONSES} is the OpenAI Responses API), got {raw!r}"
        )
    return value


def _port(raw: str) -> int:
    if not raw:
        return backends.LOCAL_PORT
    try:
        port = int(raw)
    except ValueError as error:
        raise LlmConfigError(f"{ENV_PORT} must be a TCP port number, got {raw!r}") from error
    if not 0 < port <= 65535:
        raise LlmConfigError(f"{ENV_PORT} is out of range for a TCP port: {raw!r}")
    return port


def _timeout(values: Mapping[str, str]) -> float:
    return _number(
        values,
        ENV_TIMEOUT,
        DEFAULT_TIMEOUT,
        low=0.0,
        high=backends.MAX_TIMEOUT,
        inclusive_low=False,
    )


def _max_tokens(values: Mapping[str, str]) -> int:
    # Whole numbers only: ``int(1.5)`` would quietly turn a typo into one token.
    raw = values.get(ENV_MAX_TOKENS, "").strip()
    if not raw:
        return DEFAULT_MAX_TOKENS
    try:
        value = int(raw)
    except ValueError as error:
        raise LlmConfigError(f"{ENV_MAX_TOKENS} must be a whole number, got {raw!r}") from error
    if not 0 < value <= backends.MAX_TOKENS_LIMIT:
        raise LlmConfigError(
            f"{ENV_MAX_TOKENS} must be in (0, {backends.MAX_TOKENS_LIMIT}], got {raw!r}"
        )
    return value


def _temperature(values: Mapping[str, str]) -> float:
    # 0 is legitimate (greedy decoding), so the lower bound is inclusive here.
    return _number(
        values,
        ENV_TEMPERATURE,
        DEFAULT_TEMPERATURE,
        low=0.0,
        high=MAX_TEMPERATURE,
        inclusive_low=True,
    )


def _number(
    values: Mapping[str, str],
    name: str,
    default: float,
    *,
    low: float,
    high: float,
    inclusive_low: bool,
) -> float:
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise LlmConfigError(f"{name} must be a number, got {raw!r}") from error
    too_low = value < low if inclusive_low else value <= low
    if too_low or value > high:
        bracket = f"[{low}, {high}]" if inclusive_low else f"({low}, {high}]"
        raise LlmConfigError(f"{name} must be in {bracket}, got {raw!r}")
    return value

