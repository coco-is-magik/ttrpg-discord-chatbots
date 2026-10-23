"""Dataset loading.

The runtime types are independent of the file format: ``read_jsonl`` yields plain
records and the ``*_from_records`` functions build value types. A future CSV,
SQLite or HTTP source only has to produce records, so nothing downstream changes.

Unknown fields are preserved in ``meta`` so the schema can grow -- provenance,
timestamps, embeddings -- without editing this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from ttrpg_chatbots import jsonl
from ttrpg_chatbots.reply.types import (
    Character,
    DatasetError,
    KnowledgeItem,
    ResponseTemplate,
    World,
)

KNOWLEDGE_FILE = "knowledge.jsonl"
RESPONSES_FILE = "responses.jsonl"
CHARACTERS_FILE = "characters.jsonl"
MANIFEST_FILE = "world.json"

_KNOWLEDGE_FIELDS = frozenset({"id", "text", "tags", "slots", "reply", "character"})
_RESPONSE_FIELDS = frozenset({"id", "character", "tags", "template"})
_CHARACTER_FIELDS = frozenset({"id", "name", "known_tags", "tags", "fallback_tag"})


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield one record per line, reporting problems as ``DatasetError``."""
    try:
        yield from jsonl.read_jsonl(path)
    except jsonl.JsonlError as error:
        raise DatasetError(str(error)) from error


def _identifier(record: Mapping[str, Any], where: str) -> str:
    value = record.get("id")
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{where}: 'id' must be a non-empty string")
    return value.strip()


def _tags(
    record: Mapping[str, Any], key: str, where: str, *, required: bool = True
) -> frozenset[str]:
    value = record.get(key)
    if value is None:
        if required:
            raise DatasetError(f"{where}: missing required list {key!r}")
        return frozenset()
    if not isinstance(value, list) or any(
        not isinstance(tag, str) or not tag.strip() for tag in value
    ):
        raise DatasetError(f"{where}: {key!r} must be a list of non-blank strings")
    tags = frozenset(tag.strip() for tag in value)
    if required and not tags:
        raise DatasetError(f"{where}: {key!r} must not be empty")
    return tags


def _slots(record: Mapping[str, Any], where: str) -> dict[str, str]:
    value = record.get("slots") or {}
    if not isinstance(value, dict):
        raise DatasetError(f"{where}: 'slots' must be an object of strings")
    return {str(key): str(item) for key, item in value.items()}


def _meta(record: Mapping[str, Any], known: frozenset[str]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in known}


def _build(where: str, factory):
    """Turn the value types' ValueError into a located DatasetError."""
    try:
        return factory()
    except ValueError as error:
        raise DatasetError(f"{where}: {error}") from error


def knowledge_from_records(
    records: Iterable[Mapping[str, Any]], *, source: str = "knowledge"
) -> tuple[KnowledgeItem, ...]:
    items: list[KnowledgeItem] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        identifier = _identifier(record, f"{source} record {index}")
        where = f"{source} record {index} ({identifier})"
        if identifier in seen:
            raise DatasetError(f"{where}: duplicate id")
        seen.add(identifier)

        text = record.get("text")
        if not isinstance(text, str) or not text.strip():
            raise DatasetError(f"{where}: 'text' must be a non-empty string")

        reply = record.get("reply")
        if reply is not None and (not isinstance(reply, str) or not reply.strip()):
            raise DatasetError(f"{where}: 'reply' must be a non-empty string when given")

        # Optional: who owns this line. Absent means anybody who knows the tag.
        character = record.get("character", "*")
        if not isinstance(character, str) or not character.strip():
            raise DatasetError(f"{where}: 'character' must be a non-empty string when given")

        items.append(
            _build(
                where,
                lambda record=record, where=where, identifier=identifier, text=text, reply=reply: KnowledgeItem(
                    id=identifier,
                    text=text.strip(),
                    tags=_tags(record, "tags", where),
                    slots=_slots(record, where),
                    meta=_meta(record, _KNOWLEDGE_FIELDS),
                    reply=reply.strip() if isinstance(reply, str) else None,
                    character=character.strip(),
                ),
            )
        )
    if not items:
        raise DatasetError(f"{source}: no records")
    return tuple(items)


def responses_from_records(
    records: Iterable[Mapping[str, Any]], *, source: str = "responses"
) -> tuple[ResponseTemplate, ...]:
    templates: list[ResponseTemplate] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        identifier = _identifier(record, f"{source} record {index}")
        where = f"{source} record {index} ({identifier})"
        if identifier in seen:
            raise DatasetError(f"{where}: duplicate id")
        seen.add(identifier)

        character = record.get("character")
        if not isinstance(character, str) or not character.strip():
            raise DatasetError(f"{where}: 'character' must be a non-empty string")
        template = record.get("template")
        if not isinstance(template, str) or not template.strip():
            raise DatasetError(f"{where}: 'template' must be a non-empty string")

        templates.append(
            _build(
                where,
                lambda record=record, where=where, identifier=identifier,
                character=character, template=template: ResponseTemplate(
                    id=identifier,
                    character=character.strip(),
                    tags=_tags(record, "tags", where),
                    template=template.strip(),
                    meta=_meta(record, _RESPONSE_FIELDS),
                ),
            )
        )
    if not templates:
        raise DatasetError(f"{source}: no records")
    return tuple(templates)


def characters_from_records(
    records: Iterable[Mapping[str, Any]], *, source: str = "characters"
) -> tuple[Character, ...]:
    characters: list[Character] = []
    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        identifier = _identifier(record, f"{source} record {index}")
        where = f"{source} record {index} ({identifier})"
        if identifier in seen:
            raise DatasetError(f"{where}: duplicate id")
        seen.add(identifier)

        name = record.get("name") or identifier
        if not isinstance(name, str) or not name.strip():
            raise DatasetError(f"{where}: 'name' must be a non-empty string")
        fallback = record.get("fallback_tag") or "fallback"
        if not isinstance(fallback, str) or not fallback.strip():
            raise DatasetError(f"{where}: 'fallback_tag' must be a non-empty string")

        characters.append(
            _build(
                where,
                lambda record=record, where=where, identifier=identifier,
                name=name, fallback=fallback: Character(
                    id=identifier,
                    name=name.strip(),
                    known_tags=_tags(record, "known_tags", where, required=False),
                    tags=_tags(record, "tags", where, required=False),
                    fallback_tag=fallback.strip(),
                    meta=_meta(record, _CHARACTER_FIELDS),
                ),
            )
        )
    if not characters:
        raise DatasetError(f"{source}: no records")

    aliases: dict[str, str] = {}
    for character in characters:
        # A character's id and display name may coincide case-insensitively
        # ("sable" / "Sable"); what must not collide is two *different* characters.
        for key in {alias.lower() for alias in character.aliases}:
            if key in aliases:
                raise DatasetError(
                    f"{source}: alias {key!r} is used by both "
                    f"{aliases[key]!r} and {character.id!r}"
                )
            aliases[key] = character.id
    return tuple(characters)


def load_world(root: Path | str) -> World:
    """Load a dataset directory: characters, knowledge, responses, manifest."""
    base = Path(root)
    if not base.is_dir():
        raise DatasetError(f"dataset directory does not exist: {base}")
    manifest = _read_manifest(base)

    characters_path = _require(base, CHARACTERS_FILE)
    knowledge_path = _require(base, KNOWLEDGE_FILE)
    responses_path = _require(base, RESPONSES_FILE)

    characters = characters_from_records(read_jsonl(characters_path), source=str(characters_path))
    knowledge = knowledge_from_records(read_jsonl(knowledge_path), source=str(knowledge_path))
    responses = responses_from_records(read_jsonl(responses_path), source=str(responses_path))
    _check_response_characters(characters, responses, responses_path)

    name = manifest.get("name")
    return World(
        name=name if isinstance(name, str) and name.strip() else base.name,
        knowledge=knowledge,
        responses=responses,
        characters=characters,
    )


def _require(base: Path, filename: str) -> Path:
    path = base / filename
    if not path.is_file():
        raise DatasetError(f"missing dataset file: {path}")
    return path


def _read_manifest(base: Path) -> dict[str, Any]:
    path = base / MANIFEST_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DatasetError(f"cannot read {path}: {error}") from error
    if not isinstance(data, dict):
        raise DatasetError(f"{path}: expected a JSON object")
    return data


def _check_response_characters(
    characters: tuple[Character, ...], responses: tuple[ResponseTemplate, ...], path: Path
) -> None:
    aliases = {alias.lower() for character in characters for alias in character.aliases}
    for template in responses:
        if template.character == "*":
            continue
        if template.character.lower() not in aliases:
            raise DatasetError(
                f"{path}: response {template.id!r} refers to unknown character "
                f"{template.character!r}"
            )

