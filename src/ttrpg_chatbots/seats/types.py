"""Who is at the table.

A **seat** is one participant: the human, or one of the bots. It bridges three id spaces that
were separate before this module existed:

* the *sheet* character, which the portal owns (``data/characters/<id>.json``)
* the *reply* character, which the classifier and the voices know (``characters.jsonl``)
* the Discord user, which is how a human is recognised in an interaction

Seats exist so that every surface — a panel, a roll, a line of dialogue — can answer "who is
this and what may they do" without guessing. The two character id spaces are not unified yet;
a seat names both, and each surface picks the one it needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

KIND_HUMAN = "human"
KIND_BOT = "bot"
KINDS = (KIND_HUMAN, KIND_BOT)

# What a seat may do. Unknown names are refused, so a typo in seats.json is loud.
PERMISSION_EDIT_OWN_SHEET = "edit_own_sheet"
PERMISSION_VIEW_ANY_SHEET = "view_any_sheet"
PERMISSION_ROLL_FOR_ANY = "roll_for_any"
PERMISSION_AWARD_GIFTS = "award_gifts"
PERMISSION_EDIT_ANY_SHEET = "edit_any_sheet"
PERMISSIONS = (
    PERMISSION_EDIT_OWN_SHEET,
    PERMISSION_VIEW_ANY_SHEET,
    PERMISSION_ROLL_FOR_ANY,
    PERMISSION_AWARD_GIFTS,
    PERMISSION_EDIT_ANY_SHEET,
)

VOICE_MODES = ("ic", "ooc")

MAX_SNOWFLAKE = 2**64 - 1


class SeatsError(RuntimeError):
    """Raised when a seat list cannot be read, or a lookup cannot be satisfied."""


@dataclass(frozen=True)
class Seat:
    """One participant: who they are, what they play, and what they may do."""

    id: str
    kind: str
    character: str
    discord_id: int | None = None
    world_character: str = ""
    voices: Mapping[str, str] = field(default_factory=dict)
    permissions: frozenset[str] = frozenset()
    # One character is active at a time: a player may own several seats and switch
    # which one /sheet, /spend and /roll act on.
    active: bool = True
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise SeatsError("a seat needs an id")
        if self.kind not in KINDS:
            raise SeatsError(f"seat {self.id!r}: kind must be one of {KINDS}, got {self.kind!r}")
        if not isinstance(self.character, str) or not self.character.strip():
            raise SeatsError(f"seat {self.id!r}: needs a character")
        if self.discord_id is not None:
            if isinstance(self.discord_id, bool) or not isinstance(self.discord_id, int):
                raise SeatsError(f"seat {self.id!r}: discord_id must be a whole number")
            if not 0 < self.discord_id <= MAX_SNOWFLAKE:
                raise SeatsError(f"seat {self.id!r}: discord_id is out of range")
        if self.kind == KIND_HUMAN and self.discord_id is None:
            raise SeatsError(f"seat {self.id!r}: a human seat needs a discord_id")
        unknown = set(self.voices) - set(VOICE_MODES)
        if unknown:
            raise SeatsError(
                f"seat {self.id!r}: voices may only name {VOICE_MODES}, got {sorted(unknown)}"
            )
        bad = set(self.permissions) - set(PERMISSIONS)
        if bad:
            raise SeatsError(
                f"seat {self.id!r}: unknown permissions {sorted(bad)}; known: {list(PERMISSIONS)}"
            )

    @property
    def name(self) -> str:
        """Display name: a label from meta if present, otherwise the seat id."""
        label = self.meta.get("name")
        return label.strip() if isinstance(label, str) and label.strip() else self.id

    @property
    def is_human(self) -> bool:
        return self.kind == KIND_HUMAN

    @property
    def is_bot(self) -> bool:
        return self.kind == KIND_BOT

    @property
    def reply_character(self) -> str:
        """The id the classifier and voices know, defaulting to the sheet character."""
        return self.world_character or self.character

    def may(self, permission: str) -> bool:
        return permission in self.permissions

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "character": self.character,
        }
        if self.discord_id is not None:
            data["discord_id"] = self.discord_id
        if self.world_character:
            data["world_character"] = self.world_character
        if self.voices:
            data["voices"] = dict(self.voices)
        if self.permissions:
            data["permissions"] = sorted(self.permissions)
        if not self.active:
            data["active"] = False
        if self.meta:
            data["meta"] = dict(self.meta)
        return data

    @classmethod
    def from_dict(cls, data: Any, *, where: str = "seat") -> Seat:
        if not isinstance(data, Mapping):
            raise SeatsError(f"{where}: must be an object")
        seat_id = data.get("id")
        if not isinstance(seat_id, str) or not seat_id.strip():
            raise SeatsError(f"{where}: needs a string 'id'")
        kind = data.get("kind")
        if not isinstance(kind, str) or kind.strip().lower() not in KINDS:
            raise SeatsError(f"{where} {seat_id!r}: 'kind' must be one of {KINDS}")
        character = data.get("character")
        if not isinstance(character, str) or not character.strip():
            raise SeatsError(f"{where} {seat_id!r}: needs a string 'character'")

        discord_id = data.get("discord_id")
        if isinstance(discord_id, str) and discord_id.strip().isdigit():
            discord_id = int(discord_id.strip())

        world_character = data.get("world_character", "")
        if not isinstance(world_character, str):
            raise SeatsError(f"{where} {seat_id!r}: 'world_character' must be a string")

        voices = data.get("voices") or {}
        if not isinstance(voices, Mapping):
            raise SeatsError(f"{where} {seat_id!r}: 'voices' must be an object")
        for mode, voice in voices.items():
            if not isinstance(voice, str) or not voice.strip():
                raise SeatsError(f"{where} {seat_id!r}: voice {mode!r} must be a non-empty string")

        permissions = data.get("permissions") or []
        if not isinstance(permissions, list):
            raise SeatsError(f"{where} {seat_id!r}: 'permissions' must be a list")

        known = {
            "id",
            "kind",
            "character",
            "discord_id",
            "world_character",
            "voices",
            "permissions",
            "active",
            "meta",
        }
        # Unknown keys are kept, so a seats file can grow ahead of the code that reads it.
        meta = data.get("meta") if isinstance(data.get("meta"), Mapping) else {}
        meta = {**{key: value for key, value in data.items() if key not in known}, **dict(meta)}

        try:
            return cls(
                id=seat_id.strip(),
                kind=kind.strip().lower(),
                character=character.strip(),
                discord_id=discord_id,
                world_character=world_character.strip(),
                voices={str(mode): voice.strip() for mode, voice in voices.items()},
                permissions=frozenset(str(permission) for permission in permissions),
                active=bool(data.get("active", True)),
                meta=meta,
            )
        except TypeError as error:  # a non-int discord_id reaches validation as a wrong type
            raise SeatsError(f"{where} {seat_id!r}: {error}") from error

