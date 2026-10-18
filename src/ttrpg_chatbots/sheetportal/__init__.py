"""The sheet portal: every accepted change to a character, with a receipt.

The arithmetic lives in one place (``mutations``) so that the Discord surfaces, the CLI and any
future UI cannot disagree about what a point costs or whether a trait is capped.
"""

from ttrpg_chatbots.sheetportal.mutations import (
    KINDS,
    OUTCOMES,
    POOLS,
    MutationError,
    adjust_health,
    Receipt,
    award_gift,
    cap_for,
    cost_of,
    current_rating,
    explain,
    options,
    raise_trait,
    remove_gift,
    set_specialty,
    set_trait,
    record_mission,
    resolve_kind,
)

__all__ = [
    "KINDS",
    "OUTCOMES",
    "POOLS",
    "MutationError",
    "adjust_health",
    "Receipt",
    "award_gift",
    "cap_for",
    "cost_of",
    "current_rating",
    "explain",
    "options",
    "raise_trait",
    "remove_gift",
    "set_specialty",
    "set_trait",
    "record_mission",
    "resolve_kind",
]
