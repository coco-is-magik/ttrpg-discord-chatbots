"""What a friend is like, written down.

A persona is a **spec, not an engine**. The behaviour lives in the reply dataset: which tags a
character knows (``examples/friends_world/characters.jsonl``), the facts and opinions they can
speak (``knowledge.jsonl``), and the lines in their own voice (``responses.jsonl``). This module
holds the brief -- the thing a human wrote and would otherwise have to remember -- and
``tests/test_persona.py`` refuses to let the brief and the data drift apart:

- every ``topic`` must be a tag that exists in the dataset *and* is in that character's
  ``known_tags``, or the friend would claim to care about something they cannot discuss;
- every ``signature`` line must appear in at least one of that character's templates, or the
  catchphrase is a fiction;
- every ``voice`` must be matched by a casting rule in ``voices.jsonl`` with the same engine,
  voice and speed, or the friend would sound like somebody else.

``traits`` and ``values`` are descriptive and cannot be tested; they are here so the next person
writing lines for this character knows what they are aiming at. Everything else is enforced.

Nothing in this module imports the reply engine or the audio stack. It is value types and
validation, so a roster can be read without a dataset and a dataset can be checked without
Discord.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ttrpg_chatbots.reply.style import Style

MAX_SPEED = 3.0
MIN_SPEED = 0.1


class PersonaError(ValueError):
    """Raised when a persona record is malformed or self-contradictory."""


@dataclass(frozen=True)
class VoiceSpec:
    """How a friend should sound, in the terms the casting system uses.

    ``engine`` and ``voice`` are pinned together on purpose: a voice name means nothing outside
    its engine, and guessing one is how a character starts sounding different on another box.
    """

    engine: str
    voice: str
    speed: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if not self.engine.strip():
            raise PersonaError("a voice needs an engine")
        if not self.voice.strip():
            raise PersonaError("a voice needs a voice name")
        if isinstance(self.speed, bool) or not isinstance(self.speed, (int, float)):
            raise PersonaError("a voice speed must be a number")
        if not MIN_SPEED <= float(self.speed) <= MAX_SPEED:
            raise PersonaError(
                f"a voice speed must be between {MIN_SPEED} and {MAX_SPEED}, got {self.speed}"
            )

    def describe(self) -> str:
        return f"{self.engine}:{self.voice} at {self.speed:g}x"


@dataclass(frozen=True)
class Persona:
    """Who a friend is: the brief, in the few fields that shape what they say.

    ``name`` and ``summary`` are for humans and logs. ``traits`` and ``values`` are the brief
    proper, and are *not* enforced -- prose cannot be tested, and pretending otherwise would be
    worse than admitting it. ``topics``, ``signature`` and ``voice`` are enforced against the
    dataset and the casting table.
    """

    name: str
    summary: str = ""
    traits: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    signature: tuple[str, ...] = ()
    voice: VoiceSpec | None = None
    style: Style | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise PersonaError("a persona needs a name")
        for label, items in (
            ("traits", self.traits),
            ("values", self.values),
            ("signature", self.signature),
        ):
            if any(not isinstance(item, str) or not item.strip() for item in items):
                raise PersonaError(f"{label} must be non-blank strings")
        for topic in self.topics:
            if not isinstance(topic, str) or ":" not in topic.strip():
                raise PersonaError(
                    f"topic {topic!r} must be a tag such as 'topic:hockey'; a bare word cannot "
                    "be looked up in the dataset"
                )

    def describe(self) -> str:
        """One line for a startup log: name, what they care about, how they sound."""
        parts = [self.name]
        if self.topics:
            parts.append(f"{len(self.topics)} topics")
        if self.voice is not None:
            parts.append(self.voice.describe())
        return f"{parts[0]} ({', '.join(parts[1:])})" if len(parts) > 1 else parts[0]

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, where: str = "persona") -> Persona:
        """Read and validate one ``persona`` object from a roster record."""
        if not isinstance(record, Mapping):
            raise PersonaError(f"{where}: must be an object")

        name = record.get("name", "")
        if not isinstance(name, str) or not name.strip():
            raise PersonaError(f"{where}: 'name' must be a non-blank string")

        summary = record.get("summary", "")
        if not isinstance(summary, str):
            raise PersonaError(f"{where}: 'summary' must be a string")

        def strings(key: str) -> tuple[str, ...]:
            value = record.get(key) or []
            if isinstance(value, str) or not isinstance(value, Sequence):
                raise PersonaError(f"{where}: {key!r} must be a list of strings")
            return tuple(value)

        voice: VoiceSpec | None = None
        voice_record = record.get("voice")
        if voice_record is not None:
            if not isinstance(voice_record, Mapping):
                raise PersonaError(f"{where}: 'voice' must be an object")
            engine = voice_record.get("engine", "")
            voice_name = voice_record.get("voice", "")
            if not isinstance(engine, str) or not isinstance(voice_name, str):
                raise PersonaError(f"{where}: 'voice.engine' and 'voice.voice' must be strings")
            description = voice_record.get("description", "")
            if not isinstance(description, str):
                raise PersonaError(f"{where}: 'voice.description' must be a string")
            try:
                voice = VoiceSpec(
                    engine=engine,
                    voice=voice_name,
                    speed=voice_record.get("speed", 1.0),
                    description=description,
                )
            except PersonaError as error:
                raise PersonaError(f"{where}: {error}") from error

        style: Style | None = None
        style_record = record.get("style")
        if style_record is not None:
            if not isinstance(style_record, Mapping):
                raise PersonaError(f"{where}: 'style' must be an object")
            try:
                style = Style.from_record(style_record)
            except ValueError as error:
                raise PersonaError(f"{where}: {error}") from error

        try:
            return cls(
                name=name.strip(),
                summary=summary.strip(),
                traits=strings("traits"),
                values=strings("values"),
                topics=strings("topics"),
                signature=strings("signature"),
                voice=voice,
                style=style,
            )
        except PersonaError as error:
            raise PersonaError(f"{where}: {error}") from error
