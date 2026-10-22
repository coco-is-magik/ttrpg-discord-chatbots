from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.tts import casting
from ttrpg_chatbots.tts.casting import (
    CastingError,
    VoiceCast,
    VoiceDirectory,
    VoiceProfile,
    VoiceRule,
    default_factory,
    from_records,
    load_voice_directory,
)
from ttrpg_chatbots.tts.engines import espeak_engine, piper_engine
from ttrpg_chatbots.tts.spoken import SpokenSynthesizer, unwrap
from ttrpg_chatbots.tts.synthesizer import SynthesizerUnavailable

from reply_support import DEMO_WORLD
from tts_support import FakeSynthesizer, tone


class Someone:
    """A minimal speaker: id, name and tags are all casting needs."""

    def __init__(self, identifier: str, name: str | None = None, tags=()) -> None:
        self.id = identifier
        self.name = name or identifier.title()
        self.tags = frozenset(tags)


SCHOLAR = Someone("brannoc", "Brannoc the Archivist", {"role:scholar", "species:dwarf"})
GUIDE = Someone("sable", "Sable", {"role:guide"})
PLAIN = Someone("orla", "Orla the Tavernkeep")


def test_profile_defaults_are_the_engine_defaults() -> None:
    profile = VoiceProfile()
    assert (profile.engine, profile.voice) == (None, None)
    assert (profile.speed, profile.volume) == (1.0, 1.0)


def test_a_voice_without_an_engine_is_rejected() -> None:
    """Voice names only mean something inside one engine; guessing breaks consistency."""
    with pytest.raises(ValueError, match="must name its engine"):
        VoiceProfile(voice="en_US-lessac-medium")


@pytest.mark.parametrize("kwargs", [{"engine": "  "}, {"engine": "piper", "voice": "  "}])
def test_blank_names_are_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        VoiceProfile(**kwargs)


@pytest.mark.parametrize("speed", [0, -1, 3.5])
def test_speed_bounds(speed: float) -> None:
    with pytest.raises(ValueError, match="speed"):
        VoiceProfile(speed=speed)


@pytest.mark.parametrize("volume", [0, -0.5, 2.5])
def test_volume_bounds(volume: float) -> None:
    with pytest.raises(ValueError, match="volume"):
        VoiceProfile(volume=volume)


def test_profile_describes_itself() -> None:
    profile = VoiceProfile(engine="piper", voice="en_GB-alan-medium", speed=0.95)
    assert profile.describe() == "piper:en_GB-alan-medium speed=0.95 volume=1"


def test_profiles_are_hashable_and_immutable() -> None:
    profile = VoiceProfile(engine="piper", voice="v")
    assert {profile: "cached"}[profile] == "cached"
    with pytest.raises(FrozenInstanceError):
        profile.speed = 2.0


def test_a_rule_must_select_somebody() -> None:
    with pytest.raises(ValueError, match="selects nobody"):
        VoiceRule(id="r", profile=VoiceProfile())


def test_a_rule_cannot_be_both_default_and_selector() -> None:
    with pytest.raises(ValueError, match="both a default"):
        VoiceRule(id="r", profile=VoiceProfile(), default=True, tags=frozenset({"role:scholar"}))


def test_a_rule_needs_an_id() -> None:
    with pytest.raises(ValueError, match="id"):
        VoiceRule(id="  ", profile=VoiceProfile(), default=True)


def test_rules_match_a_character_by_id_or_display_name() -> None:
    by_id = VoiceRule(id="r", profile=VoiceProfile(), characters=frozenset({"BRANNOC"}))
    assert by_id.names_character(SCHOLAR)
    by_name = VoiceRule(
        id="r", profile=VoiceProfile(), characters=frozenset({"brannoc the archivist"})
    )
    assert by_name.names_character(SCHOLAR)
    assert not by_name.names_character(GUIDE)


def test_rule_tags_match_case_insensitively() -> None:
    rule = VoiceRule(
        id="r", profile=VoiceProfile(), tags=frozenset({"ROLE:scholar", "species:halfling"})
    )
    assert rule.matching_tags(SCHOLAR) == frozenset({"role:scholar"})
    assert rule.matching_tags(PLAIN) == frozenset()


SCHOLAR_VOICE = VoiceProfile(engine="piper", voice="scholar")
GUIDE_VOICE = VoiceProfile(engine="piper", voice="guide")
SPECIAL_VOICE = VoiceProfile(engine="piper", voice="special")
DEFAULT_VOICE = VoiceProfile(engine="piper", voice="default")


def _directory(*rules: VoiceRule) -> VoiceDirectory:
    return VoiceDirectory(rules)


class TestVoiceDirectory:
    def test_a_character_rule_beats_a_tag_rule(self) -> None:
        directory = _directory(
            VoiceRule(id="by-tag", profile=GUIDE_VOICE, tags=frozenset({"role:guide"})),
            VoiceRule(id="by-name", profile=SPECIAL_VOICE, characters=frozenset({"sable"})),
        )
        assert directory.resolve(GUIDE) == SPECIAL_VOICE

    def test_the_tag_rule_with_the_most_matches_wins(self) -> None:
        directory = _directory(
            VoiceRule(id="one", profile=GUIDE_VOICE, tags=frozenset({"role:scholar"})),
            VoiceRule(
                id="two", profile=SPECIAL_VOICE, tags=frozenset({"role:scholar", "species:dwarf"})
            ),
        )
        assert directory.resolve(SCHOLAR) == SPECIAL_VOICE

    def test_a_tag_rule_beats_the_default(self) -> None:
        directory = _directory(
            VoiceRule(id="fallback", profile=DEFAULT_VOICE, default=True),
            VoiceRule(id="scholar", profile=SCHOLAR_VOICE, tags=frozenset({"role:scholar"})),
        )
        assert directory.resolve(SCHOLAR) == SCHOLAR_VOICE
        assert directory.resolve(PLAIN) == DEFAULT_VOICE

    def test_the_built_in_profile_is_the_last_resort(self) -> None:
        assert _directory().resolve(PLAIN) == VoiceProfile()

    def test_ties_break_on_rule_id_not_on_insertion_order(self) -> None:
        directory = _directory(
            VoiceRule(id="b", profile=GUIDE_VOICE, tags=frozenset({"role:guide"})),
            VoiceRule(id="a", profile=SPECIAL_VOICE, tags=frozenset({"role:guide"})),
        )
        answers = {directory.resolve(GUIDE) for _ in range(5)}
        assert answers == {SPECIAL_VOICE}

    def test_duplicate_rule_ids_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            _directory(
                VoiceRule(id="same", profile=GUIDE_VOICE, default=True),
                VoiceRule(id="same", profile=SPECIAL_VOICE, tags=frozenset({"x"})),
            )

    def test_cast_covers_every_speaker(self) -> None:
        directory = _directory(VoiceRule(id="d", profile=DEFAULT_VOICE, default=True))
        assert set(directory.cast([SCHOLAR, GUIDE, PLAIN])) == {"brannoc", "sable", "orla"}


class TestFromRecords:
    def test_a_record_becomes_a_rule(self) -> None:
        directory = from_records(
            [
                {
                    "id": "cast-scholar",
                    "tags": ["role:scholar"],
                    "engine": "piper",
                    "voice": "en_GB-alan-medium",
                    "speed": 0.95,
                }
            ]
        )
        rule = directory.rules[0]
        assert rule.id == "cast-scholar"
        assert rule.tags == frozenset({"role:scholar"})
        assert rule.profile == VoiceProfile(
            engine="piper", voice="en_GB-alan-medium", speed=0.95
        )

    def test_unknown_record_fields_are_ignored(self) -> None:
        """Future-proofing: extra keys must not break the loader."""
        directory = from_records([{"id": "d", "default": True, "notes": "added later"}])
        assert directory.rules[0].default is True

    def test_a_missing_id_is_reported_with_its_position(self) -> None:
        with pytest.raises(CastingError, match=r"record 1: missing required field 'id'"):
            from_records([{"default": True}])

    def test_a_duplicate_id_is_reported(self) -> None:
        with pytest.raises(CastingError, match="duplicate"):
            from_records([{"id": "d", "default": True}, {"id": "d", "tags": ["x"]}])

    @pytest.mark.parametrize(
        "record,message",
        [
            ({"id": "r", "default": True, "speed": "fast"}, "must be a number"),
            ({"id": "r", "default": "yes"}, "true or false"),
            ({"id": "r", "tags": "role:scholar"}, "list of non-blank strings"),
            ({"id": "r", "voice": "v"}, "must name its engine"),
            ({"id": "r", "default": True, "speed": 9}, "speed"),
        ],
    )
    def test_bad_values_are_reported(self, record, message: str) -> None:
        with pytest.raises(CastingError, match=message):
            from_records([record])

    def test_two_rules_for_one_character_are_ambiguous(self) -> None:
        with pytest.raises(CastingError, match="cast by both"):
            from_records(
                [
                    {"id": "a", "characters": ["sable"], "engine": "piper", "voice": "x"},
                    {"id": "b", "characters": ["Sable"], "engine": "piper", "voice": "y"},
                ]
            )

    def test_two_rules_for_the_same_tags_are_ambiguous(self) -> None:
        with pytest.raises(CastingError, match="cast by both"):
            from_records(
                [
                    {"id": "a", "tags": ["role:guide"], "engine": "piper", "voice": "x"},
                    {"id": "b", "tags": ["ROLE:guide"], "engine": "piper", "voice": "y"},
                ]
            )

    def test_two_defaults_are_ambiguous(self) -> None:
        with pytest.raises(CastingError, match="more than one default"):
            from_records([{"id": "a", "default": True}, {"id": "b", "default": True}])

    def test_a_tag_no_character_carries_is_rejected(self) -> None:
        """A typo here would silently change a voice, so it is an error."""
        with pytest.raises(CastingError, match="no character carries"):
            from_records(
                [{"id": "a", "tags": ["role:wizard"], "engine": "piper", "voice": "x"}],
                known_tags={"role:scholar"},
            )

    def test_an_unknown_character_is_rejected(self) -> None:
        with pytest.raises(CastingError, match="unknown character"):
            from_records(
                [{"id": "a", "characters": ["branno"], "engine": "piper", "voice": "x"}],
                known_characters={"brannoc"},
            )


class TestLoading:
    def test_a_missing_file_means_no_cast(self, tmp_path) -> None:
        assert load_voice_directory(tmp_path).rules == ()

    def test_a_directory_is_searched_for_the_voices_file(self, tmp_path) -> None:
        (tmp_path / "voices.jsonl").write_text(
            '{"id": "d", "default": true, "engine": "piper", "voice": "v"}\n', encoding="utf-8"
        )
        assert load_voice_directory(tmp_path).rules[0].id == "d"

    def test_broken_json_carries_the_path_and_line(self, tmp_path) -> None:
        (tmp_path / "voices.jsonl").write_text("{nope\n", encoding="utf-8")
        with pytest.raises(CastingError, match=r"voices\.jsonl:1"):
            load_voice_directory(tmp_path)

    def test_the_demo_world_casts_three_distinct_voices(self) -> None:
        world = load_world(DEMO_WORLD)
        directory = load_voice_directory(
            DEMO_WORLD,
            known_tags={tag for character in world.characters for tag in character.tags},
            known_characters={
                alias
                for character in world.characters
                for alias in (character.id, character.name)
            },
        )

        assert directory.resolve(world.character("brannoc")).voice == "en_GB-alan-medium"
        assert directory.resolve(world.character("sable")).voice == "en_US-amy-medium"
        orla = directory.resolve(world.character("orla"))
        assert orla.voice == "en_US-lessac-medium"
        assert orla.volume == pytest.approx(0.9)


class TestVoiceCast:
    def _cast(self, directory, *, factory=None, max_loaded: int = 4) -> VoiceCast:
        return VoiceCast(directory, factory=factory, max_loaded=max_loaded)

    def test_it_synthesizes_with_the_directory_profile(self) -> None:
        built = []

        def factory(profile):
            built.append(profile)
            return FakeSynthesizer()

        directory = _directory(
            VoiceRule(id="s", profile=SCHOLAR_VOICE, tags=frozenset({"role:scholar"}))
        )
        clip = self._cast(directory, factory=factory).synthesize("hello", SCHOLAR)

        assert built == [SCHOLAR_VOICE]
        assert clip.duration_s > 0

    def test_one_engine_per_voice_not_per_call(self) -> None:
        built = []

        def factory(profile):
            engine = FakeSynthesizer()
            built.append(engine)
            return engine

        directory = _directory(VoiceRule(id="d", profile=DEFAULT_VOICE, default=True))
        cast = self._cast(directory, factory=factory)

        cast.synthesize("one", SCHOLAR)
        cast.synthesize("two", SCHOLAR)

        assert len(built) == 1
        assert built[0].loads == 1
        assert built[0].spoken == ["one", "two"]

    def test_different_voices_get_their_own_engine(self) -> None:
        built = []

        def factory(profile):
            engine = FakeSynthesizer()
            built.append(engine)
            return engine

        directory = _directory(
            VoiceRule(id="s", profile=SCHOLAR_VOICE, tags=frozenset({"role:scholar"})),
            VoiceRule(id="g", profile=GUIDE_VOICE, tags=frozenset({"role:guide"})),
        )
        cast = self._cast(directory, factory=factory)
        cast.synthesize("a", SCHOLAR)
        cast.synthesize("b", GUIDE)

        assert len(built) == 2
        assert len(cast.loaded_profiles()) == 2

    def test_the_cache_evicts_and_closes_the_oldest_engine(self) -> None:
        built = {}

        def factory(profile):
            engine = FakeSynthesizer()
            built[profile.voice] = engine
            return engine

        directory = _directory(
            VoiceRule(id="s", profile=SCHOLAR_VOICE, tags=frozenset({"role:scholar"})),
            VoiceRule(id="g", profile=GUIDE_VOICE, tags=frozenset({"role:guide"})),
        )
        cast = self._cast(directory, factory=factory, max_loaded=1)
        cast.synthesize("a", SCHOLAR)
        cast.synthesize("b", GUIDE)

        assert built["scholar"].closes == 1
        assert built["guide"].closes == 0
        assert cast.loaded_profiles() == (GUIDE_VOICE,)

    def test_a_missing_engine_is_never_swallowed(self) -> None:
        def factory(profile):
            raise SynthesizerUnavailable("engine gone")

        with pytest.raises(SynthesizerUnavailable, match="engine gone"):
            self._cast(_directory(), factory=factory).synthesize("hi", PLAIN)

    def test_close_releases_every_engine(self) -> None:
        built = []

        def factory(profile):
            engine = FakeSynthesizer()
            built.append(engine)
            return engine

        directory = _directory(VoiceRule(id="d", profile=DEFAULT_VOICE, default=True))
        cast = self._cast(directory, factory=factory)
        cast.synthesize("a", PLAIN)
        cast.close()

        assert built[0].closes == 1
        assert cast.loaded_profiles() == ()

    def test_max_loaded_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_loaded"):
            VoiceCast(max_loaded=0)

    def test_profile_for_matches_the_directory(self) -> None:
        directory = _directory(VoiceRule(id="s", profile=SCHOLAR_VOICE, default=True))
        assert VoiceCast(directory).profile_for(PLAIN) == SCHOLAR_VOICE


class TestDefaultFactory:
    """The factory builds the engine a profile asks for, wrapped so it speaks the spoken form."""

    def test_a_piper_profile_builds_piper(self) -> None:
        engine = default_factory(
            VoiceProfile(engine="piper", voice="en_US-lessac-medium", speed=0.9)
        )
        assert isinstance(unwrap(engine), piper_engine.PiperSynthesizer)
        assert engine.name == "piper"

    def test_every_built_engine_is_wrapped_for_speech(self) -> None:
        """Wrapping at the build site is what makes it unforgettable: no caller has to remember."""
        assert isinstance(default_factory(VoiceProfile(engine="piper", voice="x")), SpokenSynthesizer)

    @pytest.mark.parametrize("speed,expected", [(1.0, 165), (0.2, 300), (3.0, 80)])
    def test_espeak_speed_maps_to_words_per_minute(self, speed: float, expected: int) -> None:
        engine = default_factory(VoiceProfile(engine="espeak-ng", voice="en", speed=speed))
        assert isinstance(unwrap(engine), espeak_engine.EspeakSynthesizer)
        assert engine.words_per_minute == expected

    def test_an_unknown_engine_is_refused(self) -> None:
        with pytest.raises(SynthesizerUnavailable, match="known engines"):
            default_factory(VoiceProfile(engine="festival", voice="kal"))

    def test_an_unpinned_profile_uses_the_first_available_engine(self, monkeypatch) -> None:
        monkeypatch.setattr(casting, "_first_available_engine", lambda: piper_engine.NAME)
        assert isinstance(unwrap(default_factory(VoiceProfile())), piper_engine.PiperSynthesizer)


def test_pitch_outside_its_range_is_refused() -> None:
    with pytest.raises(ValueError, match="pitch must be between"):
        VoiceProfile(engine="piper", voice="en_US-ryan-high", pitch=0.2)
