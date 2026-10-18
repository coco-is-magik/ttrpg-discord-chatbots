"""The native character: sealing, history, serialisation and the store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.character.store import CharacterStore, slug_for
from ttrpg_chatbots.character.types import (
    EVENT_KINDS,
    Character,
    CharacterConflict,
    CharacterError,
    Event,
    interview_digest,
)
from ttrpg_chatbots.sheets.interview import Interview, Question
from ttrpg_chatbots.sheets.types import Ability, Sheet

AT = "2026-10-17T12:00:00+00:00"


def sheet(name: str = "Molly MacIntosh") -> Sheet:
    return Sheet(
        name=name,
        system="house-games",
        attributes={"Dexterity": 2, "Wits": 4},
        abilities={"Stealth": Ability("Stealth", rank=1)},
        virtues={"Courage": 2},
        willpower=2,
        morality=6,
        health=("Unharmed", "Bruised"),
    )


def interview(character: str = "Molly MacIntosh", *, answered: bool = True) -> Interview:
    answer = "In a vat." if answered else ""
    return Interview(
        character=character,
        questions=(
            Question(prompt="Where from?", answer=answer, section="Warmup"),
            Question(prompt="Why leave?", answer=answer, section="Warmup"),
        ),
    )


def sealed(**kwargs) -> Character:
    character = Character(sheet=sheet(), interview=interview(), created=AT, **kwargs)
    return character.seal(at=AT)


# -- events ---------------------------------------------------------------


def test_events_must_have_a_known_kind_and_a_summary() -> None:
    with pytest.raises(ValueError, match="unknown event kind"):
        Event(kind="teleported", summary="somewhere")
    with pytest.raises(ValueError, match="needs a summary"):
        Event(kind="note", summary="   ")
    assert Event(kind="note", summary="ok").as_dict()["kind"] == "note"


def test_every_advertised_kind_is_accepted() -> None:
    for kind in EVENT_KINDS:
        assert Event(kind=kind, summary="x").kind == kind


def test_history_only_ever_grows() -> None:
    character = Character(sheet=sheet(), interview=interview(), created=AT)
    updated = character.record("session", "session one", at=AT)
    assert character.history == ()
    assert [event.kind for event in updated.history] == ["session"]
    assert updated.history[0].summary == "session one"


# -- sealing --------------------------------------------------------------


def test_a_character_without_an_interview_cannot_be_sealed() -> None:
    with pytest.raises(CharacterError, match="no interview"):
        Character(sheet=sheet()).seal()


def test_an_incomplete_interview_cannot_be_sealed() -> None:
    character = Character(sheet=sheet(), interview=interview(answered=False))
    with pytest.raises(CharacterError, match="2 unanswered questions"):
        character.seal()


def test_sealing_locks_the_answers_and_records_it() -> None:
    character = sealed()
    assert character.sealed is True
    assert character.ready is True
    assert character.digest == interview_digest(character.interview)
    assert [event.kind for event in character.history] == ["sealed"]
    assert character.seal() is character  # idempotent


def test_a_sealed_interview_cannot_be_replaced() -> None:
    with pytest.raises(CharacterError, match="sealed"):
        sealed().with_interview(interview())


def test_tampering_with_answers_is_detected() -> None:
    character = sealed()
    original = interview()
    edited = Interview(
        character=original.character,
        questions=(
            Question("Where from?", "Somewhere else.", "Warmup"),
            *original.questions[1:],
        ),
    )
    with pytest.raises(CharacterError, match="digest"):
        Character(
            sheet=character.sheet,
            interview=edited,
            sealed=True,
            digest=character.digest,
        )


def test_updating_the_sheet_is_recorded() -> None:
    updated = sealed().with_sheet(sheet(), summary="willpower spent", at=AT)
    assert updated.history[-1].kind == "sheet"
    assert updated.history[-1].summary == "willpower spent"


# -- serialisation --------------------------------------------------------


def test_a_character_round_trips_through_json() -> None:
    character = sealed().record("note", "a note", at=AT)
    again = Character.from_json(character.to_json())
    assert again.as_dict() == character.as_dict()
    assert again.ready is True
    assert again.interview.questions[0].answer == "In a vat."


def test_json_carries_its_schema_version() -> None:
    assert json.loads(sealed().to_json())["schema_version"] == 1


def test_an_unknown_schema_is_refused() -> None:
    payload = json.loads(sealed().to_json())
    payload["schema_version"] = 99
    with pytest.raises(CharacterError, match="unsupported character schema"):
        Character.from_dict(payload)


def test_broken_json_says_so() -> None:
    with pytest.raises(CharacterError, match="invalid character JSON"):
        Character.from_json("{not json")


def test_an_unanswered_character_round_trips_too() -> None:
    character = Character(sheet=sheet(), interview=interview(answered=False))
    again = Character.from_json(character.to_json())
    assert again.sealed is False
    assert again.interview_complete is False
    assert again.ready is False


# -- the store ------------------------------------------------------------


def test_slugs_are_filename_safe() -> None:
    assert slug_for("Molly MacIntosh") == "molly-macintosh"
    assert slug_for("  Ann O'Neil!! ") == "ann-o-neil"
    with pytest.raises(CharacterError, match="filename"):
        slug_for("///")


def test_saving_and_loading_a_character(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path / "chars")
    character = sealed().record("note", "hello", at=AT)
    path = store.save(character)
    assert path.is_file()
    assert store.exists("molly macintosh") is True
    assert store.load("Molly MacIntosh").as_dict() == character.as_dict()
    assert store.ids() == ("molly-macintosh",)


def test_a_missing_character_lists_what_exists(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    store.save(sealed())
    with pytest.raises(CharacterError) as caught:
        store.load("Nobody")
    assert "Nobody" in str(caught.value)
    assert "molly-macintosh" in str(caught.value)


def test_saving_leaves_no_temporary_files(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    store.save(sealed())
    assert [path.name for path in tmp_path.iterdir()] == ["molly-macintosh.json"]


def test_a_slug_collision_is_refused_rather_than_overwritten(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    store.save(sealed())
    other_name = "Molly  MacIntosh!"
    other = Character(sheet=sheet(other_name), interview=interview(other_name))
    with pytest.raises(CharacterError, match="refusing to overwrite"):
        store.save(other.seal())


def test_a_new_character_starts_at_revision_zero() -> None:
    assert Character(sheet=sheet()).revision == 0


def test_every_accepted_change_bumps_the_revision() -> None:
    character = Character(sheet=sheet(), interview=interview())
    assert character.revision == 0

    noted = character.record("note", "a note", at=AT)
    assert noted.revision == 1

    resheeted = noted.with_sheet(sheet(), summary="raised Stealth", at=AT)
    assert resheeted.revision == 2

    sealed = resheeted.seal(at=AT)
    assert sealed.revision == 3
    # Sealing is one action, so it bumps once, not once for the flag and once for the event.
    assert [event.kind for event in sealed.history] == ["note", "sheet", "sealed"]


def test_sealing_twice_does_not_bump_again() -> None:
    sealed = sealed_character()
    assert sealed.seal().revision == sealed.revision


def test_a_negative_revision_is_refused() -> None:
    with pytest.raises(CharacterError, match="must not be negative"):
        Character(sheet=sheet(), revision=-1)


def test_the_revision_survives_a_round_trip() -> None:
    character = sealed_character()
    assert Character.from_json(character.to_json()).revision == character.revision


def test_a_file_without_a_revision_reads_as_zero() -> None:
    payload = json.loads(sealed_character().to_json())
    payload.pop("revision")
    assert Character.from_dict(payload).revision == 0


def sealed_character() -> Character:
    return Character(sheet=sheet(), interview=interview(), created=AT).seal(at=AT)


# -- compare-and-swap ------------------------------------------------------


def test_a_write_based_on_a_stale_revision_is_refused(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    saved = sealed_character()
    store.save(saved)

    stale = saved
    first = saved.record("session", "session one", at=AT)
    store.save(first, expect_revision=saved.revision)

    with pytest.raises(CharacterConflict, match="changed while this view was open"):
        other_device = stale.record("note", "from the other device", at=AT)
        store.save(other_device, expect_revision=stale.revision)

    # Nothing was written: the file still holds the first write.
    assert store.load(saved.id).history[-1].summary == "session one"


def test_a_write_at_the_current_revision_succeeds(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    saved = sealed_character()
    store.save(saved)

    updated = saved.record("session", "session one", at=AT)
    store.save(updated, expect_revision=saved.revision)
    assert store.load(saved.id).revision == updated.revision


def test_compare_and_swap_reports_a_deleted_character(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    character = sealed_character()
    with pytest.raises(CharacterConflict, match="no longer at"):
        store.save(character, expect_revision=0)


def test_an_unconditional_save_still_overwrites(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    saved = sealed_character()
    store.save(saved)
    store.save(saved.record("note", "overwrite", at=AT))
    assert store.load(saved.id).history[-1].summary == "overwrite"


def test_listing_and_deleting(tmp_path: Path) -> None:
    store = CharacterStore(tmp_path)
    assert store.all() == ()
    store.save(sealed())
    assert len(store.all()) == 1
    store.delete("molly macintosh")
    assert store.all() == ()
    store.delete("molly macintosh")  # deleting twice is harmless

