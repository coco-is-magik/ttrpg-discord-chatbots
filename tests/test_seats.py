"""Seats: who is at the table, what they play, and what they may do."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots.seats import Seat, SeatBook, SeatsError, load_seats, seats_from_records

HUMAN = {
    "id": "truman",
    "kind": "human",
    "character": "molly-macintosh",
    "world_character": "brannoc",
    "discord_id": 123456789012345678,
    "permissions": ["edit_own_sheet"],
}
BOT = {
    "id": "dennis",
    "kind": "bot",
    "character": "dennis-the-dragon-slayer",
    "voices": {"ic": "en_GB-alan-medium", "ooc": "en_US-lessac-medium"},
}


def seat(**overrides) -> Seat:
    return Seat.from_dict({**HUMAN, **overrides})


def book() -> SeatBook:
    return SeatBook([Seat.from_dict(HUMAN), Seat.from_dict(BOT)])


# -- parsing ---------------------------------------------------------------


def test_a_human_seat_parses() -> None:
    parsed = seat()
    assert parsed.id == "truman"
    assert parsed.is_human and not parsed.is_bot
    assert parsed.character == "molly-macintosh"
    assert parsed.reply_character == "brannoc"
    assert parsed.discord_id == 123456789012345678
    assert parsed.may("edit_own_sheet")


def test_a_bot_seat_needs_no_discord_id() -> None:
    parsed = Seat.from_dict(BOT)
    assert parsed.is_bot
    assert parsed.discord_id is None
    assert parsed.voices["ooc"] == "en_US-lessac-medium"
    assert parsed.reply_character == parsed.character


def test_a_human_without_a_discord_id_is_refused() -> None:
    with pytest.raises(SeatsError, match="needs a discord_id"):
        Seat.from_dict({**HUMAN, "discord_id": None})


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(SeatsError, match="must be one of"):
        seat(kind="dm")


def test_an_unknown_permission_is_refused_and_lists_the_known_ones() -> None:
    with pytest.raises(SeatsError, match="unknown permissions"):
        seat(permissions=["edit_own_sheet", "summon_demons"])


def test_only_ic_and_ooc_voices_are_allowed() -> None:
    with pytest.raises(SeatsError, match="voices may only name"):
        seat(voices={"narration": "en_US-lessac-medium"})


def test_a_discord_id_may_arrive_as_a_string() -> None:
    assert seat(discord_id="123456789012345678").discord_id == 123456789012345678


def test_unknown_keys_are_kept_in_meta() -> None:
    parsed = seat(favourite_drink="tea", meta={"name": "Truman"})
    assert parsed.meta["favourite_drink"] == "tea"
    assert parsed.name == "Truman"


def test_a_seat_round_trips_through_its_own_dict() -> None:
    original = Seat.from_dict(BOT)
    assert Seat.from_dict(original.as_dict()).as_dict() == original.as_dict()


def test_seats_from_records_numbers_the_bad_one() -> None:
    with pytest.raises(SeatsError, match="seat 2"):
        seats_from_records([HUMAN, {"id": "x", "kind": "human"}])


# -- the seat list ---------------------------------------------------------


def test_lookups_by_id_character_and_discord() -> None:
    seats = book()
    assert seats.get("truman").id == "truman"
    assert seats.get("TRUMAN").id == "truman"  # case-insensitive
    assert seats.get("molly-macintosh").id == "truman"  # by character
    assert seats.for_discord(123456789012345678).id == "truman"
    assert seats.for_discord(999) is None
    assert seats.for_character("Dennis-The-Dragon-Slayer").id == "dennis"
    assert [seat.id for seat in seats.humans] == ["truman"]
    assert [seat.id for seat in seats.bots] == ["dennis"]
    assert len(seats) == 2


def test_an_unknown_seat_lists_the_known_ones() -> None:
    with pytest.raises(SeatsError, match="known seats: dennis, truman"):
        book().get("charlie")


def test_requiring_a_seat_explains_how_to_get_one() -> None:
    with pytest.raises(SeatsError, match="no character is bound to you"):
        book().require_for_discord(999)
    assert book().require_for_discord(123456789012345678).id == "truman"


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(SeatsError, match="duplicate seat id"):
        SeatBook([Seat.from_dict(HUMAN), Seat.from_dict({**BOT, "id": "truman"})])


def test_one_discord_user_cannot_hold_two_seats() -> None:
    twin = {**BOT, "id": "dennis-two", "discord_id": HUMAN["discord_id"]}
    with pytest.raises(SeatsError, match="claimed by both"):
        SeatBook([Seat.from_dict(HUMAN), Seat.from_dict(twin)])


def test_one_character_cannot_be_seated_twice() -> None:
    twin = {**BOT, "id": "dennis-two", "character": HUMAN["character"]}
    with pytest.raises(SeatsError, match="seated twice"):
        SeatBook([Seat.from_dict(HUMAN), Seat.from_dict(twin)])


# -- loading ---------------------------------------------------------------


def test_a_missing_file_means_nobody_is_seated(tmp_path: Path) -> None:
    seats = load_seats(tmp_path / "absent.json")
    assert len(seats) == 0
    assert seats.for_discord(123) is None


def test_a_list_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "seats.json"
    path.write_text(json.dumps([HUMAN, BOT]), encoding="utf-8")
    assert load_seats(path).get("dennis").is_bot


def test_a_wrapped_file_loads(tmp_path: Path) -> None:
    path = tmp_path / "seats.json"
    path.write_text(json.dumps({"seats": [HUMAN]}), encoding="utf-8")
    assert len(load_seats(path)) == 1


def test_broken_json_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "seats.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SeatsError, match="invalid JSON"):
        load_seats(path)


def test_a_non_list_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "seats.json"
    path.write_text(json.dumps({"seats": {"truman": HUMAN}}), encoding="utf-8")
    with pytest.raises(SeatsError, match="expected a list of seats"):
        load_seats(path)


def test_the_example_file_is_valid() -> None:
    """The committed example must always parse, or it teaches the wrong shape."""
    example = Path("examples/seats.example.json")
    if not example.is_file():
        pytest.skip("no example seat list")
    seats = load_seats(example)
    assert len(seats) >= 2
    assert seats.humans and seats.bots

