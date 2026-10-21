"""Seat ids and the creation sequence: no collisions, no orphans.

The bug this file exists for: a second `/create` reused the seat id
``name-discordid`` and failed *after* writing the character file, leaving a character nobody
could reach.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ttrpg_chatbots.bot as bot
from ttrpg_chatbots.character.store import CharacterStore
from ttrpg_chatbots.seats import Seat, SeatBook


class _User:
    def __init__(self, name: str = "noodle", ident: int = 4242) -> None:
        self.display_name = name
        self.id = ident
        self.voice = None
        self.bot = False


class _Interaction:
    def __init__(self, user: _User | None = None) -> None:
        self.user = user or _User()
        self.guild = None
        self.channel = None


def _seat(
    ident: str, *, character: str = "someone", discord: int = 99, active: bool = False
) -> Seat:
    return Seat(
        id=ident,
        kind="human",
        character=character,
        discord_id=discord,
        permissions=frozenset({"edit_own_sheet"}),
        active=active,
    )


def test_a_first_character_gets_the_plain_name() -> None:
    assert bot._seat_id(_Interaction(), SeatBook()) == "noodle"


def test_a_second_character_gets_the_discord_id_suffix() -> None:
    book = SeatBook((_seat("noodle", character="first"),))
    assert bot._seat_id(_Interaction(), book) == "noodle-4242"


def test_a_third_character_does_not_collide() -> None:
    """The reported failure: 'duplicate seat id' on the second build for one player."""
    book = SeatBook(
        (_seat("noodle", character="first"), _seat("noodle-4242", character="second"))
    )
    assert bot._seat_id(_Interaction(), book) == "noodle-4242-2"


def test_further_characters_keep_counting() -> None:
    book = SeatBook(
        (
            _seat("noodle", character="a"),
            _seat("noodle-4242", character="b"),
            _seat("noodle-4242-2", character="c"),
        )
    )
    assert bot._seat_id(_Interaction(), book) == "noodle-4242-3"


def test_an_unnamed_player_still_gets_a_seat() -> None:
    assert bot._seat_id(_Interaction(_User(name="")), SeatBook()) == "player"


def test_a_failed_seat_leaves_no_orphan_character(tmp_path: Path, monkeypatch) -> None:
    """If the seat cannot be written, the character file must not survive."""
    monkeypatch.setenv(bot.CHARACTERS_ENV, str(tmp_path / "characters"))
    monkeypatch.setenv(bot.SEATS_ENV, str(tmp_path / "seats.json"))

    def explode(book, path) -> None:
        raise bot.SeatsError("deliberately broken")

    monkeypatch.setattr(bot, "save_seats", explode)
    with pytest.raises(bot.SeatsError):
        bot._begin_creation(_Interaction(), "Testcharacter3")

    store = CharacterStore(tmp_path / "characters")
    assert store.ids() == ()
    assert not (tmp_path / "seats.json").exists()


def test_a_successful_build_writes_both(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(bot.CHARACTERS_ENV, str(tmp_path / "characters"))
    monkeypatch.setenv(bot.SEATS_ENV, str(tmp_path / "seats.json"))

    character = bot._begin_creation(_Interaction(), "Testcharacter3")

    assert CharacterStore(tmp_path / "characters").ids() == (character.id,)
    seats = bot._seatbook()
    assert [seat.character for seat in seats] == [character.id]
    assert character.build is not None, "a new character must be a draft"
