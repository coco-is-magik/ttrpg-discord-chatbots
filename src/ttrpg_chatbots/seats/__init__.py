"""Who is at the table: seats, and the seat list.

A seat binds a Discord user (or a bot) to a character, a set of voices and a set of
permissions. Everything that needs to know "who is this and what may they do" asks here,
instead of assuming the first character in the world.
"""

from ttrpg_chatbots.seats.registry import (
    SeatBook,
    load_seats,
    save_seats,
    seats_from_records,
)
from ttrpg_chatbots.seats.types import (
    KIND_BOT,
    KIND_HUMAN,
    KINDS,
    PERMISSION_EDIT_OWN_SHEET,
    PERMISSION_ROLL_FOR_ANY,
    PERMISSION_VIEW_ANY_SHEET,
    PERMISSIONS,
    VOICE_MODES,
    Seat,
    SeatsError,
)

__all__ = [
    "KINDS",
    "KIND_BOT",
    "KIND_HUMAN",
    "PERMISSIONS",
    "PERMISSION_EDIT_OWN_SHEET",
    "PERMISSION_ROLL_FOR_ANY",
    "PERMISSION_VIEW_ANY_SHEET",
    "VOICE_MODES",
    "Seat",
    "SeatBook",
    "SeatsError",
    "load_seats",
    "save_seats",
    "seats_from_records",
]
