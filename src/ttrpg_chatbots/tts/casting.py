"""Casting: which voice speaks for which character.

Consistency is the point. A character must sound the same on every turn, every
session, and -- when a rule pins an engine and a voice -- on every machine. Rules
are data (``voices.jsonl`` beside the world), resolved in a fixed order:

1. a rule naming the character (id or display name);
2. a rule naming one of the character's tags, most matching tags first;
3. the rule marked ``default``;
4. the built-in profile: whatever engine this box resolves, at normal speed.

Nothing here imports the reply engine. A character only has to look like
``Speaker`` -- id, name, tags -- and that match is structural, so the classifier's
``Character`` fits without either module knowing about the other.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ttrpg_chatbots import jsonl
from ttrpg_chatbots.audio.pcm import PcmAudio, shift_pitch
from ttrpg_chatbots.tts import engines
from ttrpg_chatbots.tts.engines import espeak_engine, piper_engine
from ttrpg_chatbots.tts.synthesizer import SpeechSynthesizer, SynthesizerUnavailable

VOICES_FILE = "voices.jsonl"
DEFAULT_MAX_LOADED = 4
ESPEAK_WPM = 165

MAX_SPEED = 3.0
MIN_PITCH = 0.5
MAX_PITCH = 2.0
MAX_VOLUME = 2.0


class CastingError(ValueError):
    """Raised when voice rules are malformed or contradictory."""


@runtime_checkable
class Speaker(Protocol):
    """The minimum a character needs to be cast a voice."""

    id: str
    name: str
    tags: frozenset[str]


@dataclass(frozen=True)
class VoiceProfile:
    """One voice: an engine, a voice name inside it, and its delivery.

    ``speed`` is the engine's length scale (1.0 normal, lower is faster). It is
    meaningful for piper and mapped to words-per-minute for espeak.

    ``pitch`` is applied *after* the engine, by resampling, so it works for every engine and needs no
    extra dependency: 1.0 is unchanged and lower is deeper. See
    :func:`ttrpg_chatbots.audio.pcm.shift_pitch` for the trade it makes.
    """

    engine: str | None = None
    voice: str | None = None
    speed: float = 1.0
    volume: float = 1.0
    pitch: float = 1.0

    def __post_init__(self) -> None:
        if self.engine is not None and not self.engine.strip():
            raise ValueError("engine must be a name or None")
        if self.voice is not None and not self.voice.strip():
            raise ValueError("voice must be a name or None")
        if self.voice is not None and self.engine is None:
            raise ValueError(
                "a profile with a voice must name its engine: voice names are "
                "engine-specific, and guessing would break consistency"
            )
        if not 0.0 < self.speed <= MAX_SPEED:
            raise ValueError(f"speed must be in (0, {MAX_SPEED}], got {self.speed}")
        if not 0.0 < self.volume <= MAX_VOLUME:
            raise ValueError(f"volume must be in (0, {MAX_VOLUME}], got {self.volume}")
        if not MIN_PITCH <= self.pitch <= MAX_PITCH:
            raise ValueError(
                f"pitch must be between {MIN_PITCH} and {MAX_PITCH} (1.0 is unchanged, "
                f"lower is deeper), got {self.pitch}"
            )

    def describe(self) -> str:
        engine = self.engine or "auto"
        voice = self.voice or "engine default"
        pitch = "" if self.pitch == 1.0 else f" pitch={self.pitch:g}"
        return f"{engine}:{voice} speed={self.speed:g} volume={self.volume:g}{pitch}"


@dataclass(frozen=True)
class VoiceRule:
    """A selector and the voice it assigns to whoever it selects."""

    id: str
    profile: VoiceProfile
    characters: frozenset[str] = frozenset()
    tags: frozenset[str] = frozenset()
    default: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("voice rule id must not be empty")
        if self.default and (self.characters or self.tags):
            raise ValueError(f"voice rule {self.id!r} is both a default and a selector")
        if not (self.default or self.characters or self.tags):
            raise ValueError(
                f"voice rule {self.id!r} selects nobody: give characters, tags or default"
            )

    def names_character(self, speaker: Speaker) -> bool:
        wanted = {name.strip().lower() for name in self.characters}
        return bool(wanted & {speaker.id.strip().lower(), speaker.name.strip().lower()})

    def matching_tags(self, speaker: Speaker) -> frozenset[str]:
        owned = {tag.strip().lower() for tag in speaker.tags}
        return frozenset(tag.lower() for tag in self.tags if tag.lower() in owned)


@dataclass(frozen=True)
class VoiceDirectory:
    """The voice rules, and the profile used when nothing matches."""

    rules: tuple[VoiceRule, ...] = ()
    default_profile: VoiceProfile = VoiceProfile()

    def __post_init__(self) -> None:
        identifiers = [rule.id for rule in self.rules]
        duplicates = {value for value in identifiers if identifiers.count(value) > 1}
        if duplicates:
            raise ValueError(f"duplicate voice rule id(s): {', '.join(sorted(duplicates))}")

    def resolve(self, speaker: Speaker) -> VoiceProfile:
        """A character's voice. Deterministic: same character, same answer, always."""
        by_character = sorted(
            (rule for rule in self.rules if rule.names_character(speaker)),
            key=lambda rule: rule.id,
        )
        if by_character:
            return by_character[0].profile

        tagged = [(len(rule.matching_tags(speaker)), rule) for rule in self.rules]
        tagged = [pair for pair in tagged if pair[0]]
        if tagged:
            _, rule = sorted(tagged, key=lambda pair: (-pair[0], pair[1].id))[0]
            return rule.profile

        defaults = sorted((rule for rule in self.rules if rule.default), key=lambda rule: rule.id)
        if defaults:
            return defaults[0].profile
        return self.default_profile

    def cast(self, speakers: Iterable[Speaker]) -> dict[str, VoiceProfile]:
        """Every speaker's voice, for a `--list-voices` style overview."""
        return {speaker.id: self.resolve(speaker) for speaker in speakers}


def from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    known_tags: Iterable[str] | None = None,
    known_characters: Iterable[str] | None = None,
    source: str = "voices",
) -> VoiceDirectory:
    """Build a directory from plain records, whatever file produced them."""
    rules: list[VoiceRule] = []
    for index, record in enumerate(records, start=1):
        identifier = _text(record, "id", f"{source} record {index}", required=True)
        where = f"{source} record {index} ({identifier})"
        rules.append(_rule(record, str(identifier), where))

    directory = _guard(source, lambda: VoiceDirectory(tuple(rules)))
    _check_ambiguity(directory.rules, source)
    if known_tags is not None:
        _check_known_tags(directory.rules, known_tags, source)
    if known_characters is not None:
        _check_known_characters(directory.rules, known_characters, source)
    return directory


def load_voice_directory(
    path: str | Path,
    *,
    known_tags: Iterable[str] | None = None,
    known_characters: Iterable[str] | None = None,
) -> VoiceDirectory:
    """Load ``voices.jsonl`` from a file or a dataset directory.

    A missing file is not an error: it means "no cast", and every character gets the
    built-in default profile.
    """
    target = Path(path)
    if target.is_dir():
        target = target / VOICES_FILE
    if not target.is_file():
        return VoiceDirectory()
    try:
        records = list(jsonl.read_jsonl(target))
    except jsonl.JsonlError as error:
        raise CastingError(str(error)) from error
    return from_records(
        records,
        known_tags=known_tags,
        known_characters=known_characters,
        source=str(target),
    )


def _guard(where: str, factory):
    try:
        return factory()
    except CastingError:
        raise
    except ValueError as error:
        raise CastingError(f"{where}: {error}") from error


def _rule(record: Mapping[str, Any], identifier: str, where: str) -> VoiceRule:
    def build() -> VoiceRule:
        return VoiceRule(
            id=identifier,
            profile=VoiceProfile(
                engine=_text(record, "engine", where),
                voice=_text(record, "voice", where),
                speed=_number(record, "speed", where, 1.0),
                volume=_number(record, "volume", where, 1.0),
                pitch=_number(record, "pitch", where, 1.0),
            ),
            characters=frozenset(_texts(record, "characters", where)),
            tags=frozenset(_texts(record, "tags", where)),
            default=_flag(record, "default", where),
        )

    return _guard(where, build)


def _text(
    record: Mapping[str, Any], key: str, where: str, *, required: bool = False
) -> str | None:
    value = record.get(key)
    if value is None:
        if required:
            raise CastingError(f"{where}: missing required field {key!r}")
        return None
    if not isinstance(value, str) or not value.strip():
        raise CastingError(f"{where}: {key!r} must be a non-empty string")
    return value.strip()


def _texts(record: Mapping[str, Any], key: str, where: str) -> list[str]:
    value = record.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise CastingError(f"{where}: {key!r} must be a list of non-blank strings")
    return [item.strip() for item in value]


def _number(record: Mapping[str, Any], key: str, where: str, default: float) -> float:
    value = record.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CastingError(f"{where}: {key!r} must be a number")
    return float(value)


def _flag(record: Mapping[str, Any], key: str, where: str) -> bool:
    value = record.get(key)
    if value is None:
        return False
    if not isinstance(value, bool):
        raise CastingError(f"{where}: {key!r} must be true or false")
    return value


def _check_ambiguity(rules: tuple[VoiceRule, ...], source: str) -> None:
    by_character: dict[str, str] = {}
    by_tags: dict[frozenset[str], str] = {}
    defaults: list[str] = []
    for rule in rules:
        if rule.default:
            defaults.append(rule.id)
            continue
        for name in sorted(rule.characters):
            key = name.strip().lower()
            if key in by_character:
                raise CastingError(
                    f"{source}: {name!r} is cast by both {by_character[key]!r} and {rule.id!r}"
                )
            by_character[key] = rule.id
        if rule.tags:
            key_tags = frozenset(tag.strip().lower() for tag in rule.tags)
            if key_tags in by_tags:
                raise CastingError(
                    f"{source}: tags {sorted(key_tags)} are cast by both "
                    f"{by_tags[key_tags]!r} and {rule.id!r}"
                )
            by_tags[key_tags] = rule.id
    if len(defaults) > 1:
        raise CastingError(
            f"{source}: more than one default voice rule: {', '.join(sorted(defaults))}"
        )


def _check_known_tags(
    rules: tuple[VoiceRule, ...], known_tags: Iterable[str], source: str
) -> None:
    available = {tag.strip().lower() for tag in known_tags}
    for rule in rules:
        unknown = sorted(tag for tag in rule.tags if tag.strip().lower() not in available)
        if unknown:
            raise CastingError(
                f"{source}: voice rule {rule.id!r} uses tags no character carries: "
                f"{', '.join(unknown)}; a typo here would silently change a voice"
            )


def _check_known_characters(
    rules: tuple[VoiceRule, ...], known_characters: Iterable[str], source: str
) -> None:
    available = {name.strip().lower() for name in known_characters}
    for rule in rules:
        unknown = sorted(
            name for name in rule.characters if name.strip().lower() not in available
        )
        if unknown:
            raise CastingError(
                f"{source}: voice rule {rule.id!r} names unknown character(s): "
                f"{', '.join(unknown)}"
            )


SynthesizerFactory = Callable[[VoiceProfile], SpeechSynthesizer]


def default_factory(profile: VoiceProfile) -> SpeechSynthesizer:
    """Build the engine a profile asks for, never a substitute, always speaking the spoken form."""
    from ttrpg_chatbots.tts.spoken import wrap

    return wrap(_engine_for(profile))


def _engine_for(profile: VoiceProfile) -> SpeechSynthesizer:
    engine_name = profile.engine or _first_available_engine()
    if engine_name == piper_engine.NAME:
        return piper_engine.PiperSynthesizer(
            voice=profile.voice, length_scale=profile.speed, volume=profile.volume
        )
    if engine_name == espeak_engine.NAME:
        return espeak_engine.EspeakSynthesizer(
            voice=profile.voice or "en",
            words_per_minute=_words_per_minute(profile.speed),
        )
    raise SynthesizerUnavailable(
        f"a voice profile asks for engine {engine_name!r}; "
        f"known engines: {', '.join(engines.names())}"
    )


def _first_available_engine() -> str:
    for spec in engines.specs():
        if engines.availability(spec).available:
            return spec.name
    raise SynthesizerUnavailable(
        "no TTS engine is available for an unpinned voice profile"
    )


def _words_per_minute(speed: float) -> int:
    return max(80, min(300, int(round(ESPEAK_WPM / speed))))


class VoiceCast:
    """Resolves characters to voices and keeps those engines loaded and warm."""

    def __init__(
        self,
        directory: VoiceDirectory | None = None,
        *,
        factory: SynthesizerFactory | None = None,
        max_loaded: int = DEFAULT_MAX_LOADED,
    ) -> None:
        if max_loaded < 1:
            raise ValueError("max_loaded must be at least 1")
        self._directory = directory if directory is not None else VoiceDirectory()
        self._factory = factory if factory is not None else default_factory
        self._max_loaded = max_loaded
        self._loaded: OrderedDict[VoiceProfile, SpeechSynthesizer] = OrderedDict()

    @property
    def directory(self) -> VoiceDirectory:
        return self._directory

    def profile_for(self, speaker: Speaker) -> VoiceProfile:
        return self._directory.resolve(speaker)

    def synthesize(self, text: str, speaker: Speaker) -> PcmAudio:
        profile = self.profile_for(speaker)
        clip = self._engine(profile).synthesize(text)
        if profile.pitch == 1.0:
            return clip
        # Applied here rather than in the engines: a voice is defined by the casting rule, so every
        # consumer (a command, a reply, a rendered sample) hears the same person.
        return shift_pitch(clip, profile.pitch)

    def loaded_profiles(self) -> tuple[VoiceProfile, ...]:
        return tuple(self._loaded)

    def close(self) -> None:
        for engine in self._loaded.values():
            engine.close()
        self._loaded.clear()

    def _engine(self, profile: VoiceProfile) -> SpeechSynthesizer:
        existing = self._loaded.get(profile)
        if existing is not None:
            self._loaded.move_to_end(profile)
            return existing
        engine = self._factory(profile)
        try:
            engine.load()
        except Exception:
            engine.close()
            raise
        self._loaded[profile] = engine
        while len(self._loaded) > self._max_loaded:
            _, evicted = self._loaded.popitem(last=False)
            evicted.close()
        return engine

