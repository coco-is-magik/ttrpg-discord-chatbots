"""The seat list: reading ``seats.json`` and looking people up.

One file, one list, validated on load. Every lookup failure names the seats that do exist,
because the usual cause is a typo in a Discord id or a character id, and a message that lists
the alternatives is faster than a log dive.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from ttrpg_chatbots.seats.types import Seat, SeatsError

DEFAULT_SEATS_FILE = Path("data") / "seats.json"


class SeatBook:
    """Seats by id, by Discord user and by character."""

    def __init__(self, seats: Iterable[Seat] = ()) -> None:
        self._seats: dict[str, Seat] = {}
        self._by_discord: dict[int, Seat] = {}
        self._by_character: dict[str, Seat] = {}
        for seat in seats:
            key = seat.id.strip().lower()
            if key in self._seats:
                raise SeatsError(f"duplicate seat id {seat.id!r}")
            if seat.discord_id is not None:
                owner = self._by_discord.get(seat.discord_id)
                if owner is not None:
                    raise SeatsError(
                        f"discord id {seat.discord_id} is claimed by both "
                        f"{owner.id!r} and {seat.id!r}"
                    )
            if seat.character.strip().lower() in self._by_character:
                raise SeatsError(f"character {seat.character!r} is seated twice")
            self._seats[key] = seat
            if seat.discord_id is not None:
                self._by_discord[seat.discord_id] = seat
            self._by_character[seat.character.strip().lower()] = seat

    def __len__(self) -> int:
        return len(self._seats)

    def __iter__(self) -> Iterator[Seat]:
        return iter(self._seats.values())

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(seat.id for seat in self._seats.values()))

    @property
    def humans(self) -> tuple[Seat, ...]:
        return tuple(seat for seat in self._seats.values() if seat.is_human)

    @property
    def bots(self) -> tuple[Seat, ...]:
        return tuple(seat for seat in self._seats.values() if seat.is_bot)

    def get(self, identifier: str) -> Seat:
        """A seat by id (case-insensitive), or by character id."""
        wanted = (identifier or "").strip().lower()
        seat = self._seats.get(wanted) or self._by_character.get(wanted)
        if seat is None:
            known = ", ".join(self.ids) or "none"
            raise SeatsError(f"no seat {identifier!r}; known seats: {known}")
        return seat

    def for_discord(self, discord_id: int | None) -> Seat | None:
        """The human seat for a Discord user, if they have one."""
        if discord_id is None:
            return None
        return self._by_discord.get(int(discord_id))

    def with_seat(self, seat: Seat) -> SeatBook:
        """A new book including ``seat``, re-validated (duplicates raise)."""
        return SeatBook((*self._seats.values(), seat))

    def for_character(self, character: str) -> Seat | None:
        return self._by_character.get((character or "").strip().lower())

    def require_for_discord(self, discord_id: int | None) -> Seat:
        """The seat for a Discord user, or an error that says how to get one."""
        seat = self.for_discord(discord_id)
        if seat is None:
            raise SeatsError(
                "no character is bound to you: add a human seat with your Discord id to the "
                f"seat list ({', '.join(seat.id for seat in self.humans) or 'no humans yet'})"
            )
        return seat


def seats_from_records(records: Iterable[object], *, source: str = "seats") -> tuple[Seat, ...]:
    seats = []
    for index, record in enumerate(records, start=1):
        seats.append(Seat.from_dict(record, where=f"{source}: seat {index}"))
    return tuple(seats)


def load_seats(path: Path | str = DEFAULT_SEATS_FILE) -> SeatBook:
    """Read a seat list. A missing file means "nobody is seated", not an error."""
    source = Path(path)
    if not source.is_file():
        return SeatBook()
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise SeatsError(f"cannot read {source}: {error}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise SeatsError(f"{source}: invalid JSON: {error}") from error
    if isinstance(data, dict):
        data = data.get("seats")
    if not isinstance(data, list):
        raise SeatsError(f"{source}: expected a list of seats")
    return SeatBook(seats_from_records(data, source=str(source)))


def save_seats(book: SeatBook, path: Path | str = DEFAULT_SEATS_FILE) -> Path:
    """Write the seat list atomically: a half-written file would lock everyone out."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps([seat.as_dict() for seat in book], indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".seats-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)  # Discord ids are personal data
        os.replace(temporary, target)
    except OSError as error:
        Path(temporary).unlink(missing_ok=True)
        raise SeatsError(f"cannot write {target}: {error}") from error
    return target
