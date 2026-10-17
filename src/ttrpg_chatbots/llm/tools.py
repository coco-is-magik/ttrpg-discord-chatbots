"""Tools a model can call, and the translation to each wire format.

A tool is anything with a ``name``, a ``schema()`` and a ``run(arguments)``. The toolbox
owns the parts that must never kill a conversation: an unknown tool name, arguments that
are not JSON, arguments that are not an object, and a tool that raises. Each becomes a
readable error *for the model*, which can then correct itself.

Schemas are provider-neutral (``name``, ``description``, ``parameters``);
:func:`chat_schemas` and :func:`responses_schemas` wrap them for each wire.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from ttrpg_chatbots.llm.types import ToolCall

LOGGER = logging.getLogger("ttrpg_chatbots.llm.tools")


class Tool(Protocol):
    """What the toolbox needs from a tool."""

    name: str

    def schema(self) -> Mapping[str, Any]: ...

    def run(self, arguments: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ToolInvocation:
    """The result of one tool call: what the model is told, and what came back."""

    text: str
    failed: bool = False
    outcome: Any = None


def chat_schemas(schemas: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Chat Completions shape: ``{"type": "function", "function": {...}}``."""
    return [{"type": "function", "function": dict(schema)} for schema in schemas]


def responses_schemas(schemas: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Responses shape: the function fields sit at the top level."""
    return [{"type": "function", **dict(schema)} for schema in schemas]


class ToolBox:
    """The tools one responder may offer, keyed by name."""

    def __init__(self, *tools: Tool) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            name = (getattr(tool, "name", "") or "").strip()
            if not name:
                raise ValueError("a tool needs a non-empty name")
            if name in self._tools:
                raise ValueError(f"duplicate tool {name!r}")
            self._tools[name] = tool

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(tool.schema()) for tool in self._tools.values())

    def invoke(self, call: ToolCall) -> ToolInvocation:
        """Run one call, turning every failure into text the model can act on."""
        tool = self._tools.get(call.name)
        if tool is None:
            available = ", ".join(self.names) or "none"
            return ToolInvocation(
                f"error: unknown tool {call.name!r}; available tools: {available}", failed=True
            )

        try:
            arguments = json.loads(call.arguments or "{}")
        except ValueError as error:
            return ToolInvocation(
                f"error: arguments for {call.name} were not valid JSON: {error}", failed=True
            )
        if not isinstance(arguments, Mapping):
            return ToolInvocation(
                f"error: arguments for {call.name} must be a JSON object", failed=True
            )

        try:
            outcome = tool.run(arguments)
        except Exception as error:  # noqa: BLE001 - a tool must not end the conversation
            LOGGER.warning("tool %s failed: %s", call.name, error, exc_info=True)
            return ToolInvocation(f"error: {error}", failed=True)

        text = getattr(outcome, "text", None)
        return ToolInvocation(str(text) if text is not None else str(outcome), outcome=outcome)
