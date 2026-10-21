"""Rolling a check from a character sheet, rather than from a static table.

"Roll stealth" should use *your* Stealth and *your* Dexterity, and a wounded character should
suffer for it. This module is where those three things meet:

* the pool is ``attribute + ability`` from the sheet (the house rules' own formula);
* the difficulty starts at the house default (6) and a wound penalty raises it;
* spending Willpower buys an automatic success, and the point is actually taken.

It owns no randomness of its own: the dice come from :class:`dice.roller.Roller`, which the
caller can seed. That keeps "roll from a sheet" testable to the die.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Sheet, SheetError


class CheckError(SheetError):
    """A check that cannot be rolled: no such ability, no dice, or no Willpower."""


@dataclass(frozen=True)
class CheckOutcome:
    """One rolled check, with the sheet it happened to."""

    sheet: Sheet
    spec: houseg.PoolSpec
    result: houseg.PoolResult
    wound: int = 0
    guessed_attribute: bool = False

    @property
    def willpower_spent(self) -> int:
        return self.result.willpower

    def render(self) -> str:
        line = self.result.render()
        # The pool's own notes already name the wound penalty; only the guess needs flagging.
        if self.guessed_attribute:
            line += "\n-# attribute guessed from the ability's category"
        return line


def roll_check(
    sheet: Sheet,
    ability: str,
    *,
    attribute: str | None = None,
    difficulty: int | None = None,
    willpower: bool = False,
    roller: Roller | None = None,
) -> CheckOutcome:
    """Roll ``attribute + ability`` from the sheet.

    ``attribute`` overrides the usual pairing (useful for "Strength + Brawl" when Brawl normally
    rolls off a different stat). ``willpower`` spends a point for an automatic success and is
    reflected on the returned sheet, so the caller can save it.
    """
    if not sheet.find_ability(ability) and not any(
        ability.lower() in houseg.normalise(name) or houseg.normalise(name) in ability.lower()
        for name in (sheet.abilities or {})
    ):
        known = ", ".join(sorted(sheet.abilities)) or "none"
        raise CheckError(f"{sheet.name} has no ability called {ability!r}; known: {known}")

    if attribute:
        chosen, guessed = attribute, False
    else:
        chosen, guessed = houseg.attribute_for(sheet, ability)

    penalty = houseg.wound_penalty(sheet)
    base = houseg.DEFAULT_DIFFICULTY if difficulty is None else int(difficulty)
    spec = houseg.build_pool(
        sheet,
        chosen,
        ability,
        difficulty=base + penalty,
        willpower=willpower,
    )
    if penalty:
        spec = replace(spec, notes=spec.notes + (f"wound penalty +{penalty} difficulty",))

    result = houseg.resolve_pool(spec, roller or Roller(), character=sheet.name)

    updated = sheet
    if willpower and result.willpower:
        remaining = sheet.willpower_remaining
        if remaining is None:
            remaining = sheet.willpower
        updated = replace(sheet, willpower_remaining=max(0, remaining - 1))

    return CheckOutcome(
        sheet=updated, spec=spec, result=result, wound=penalty, guessed_attribute=guessed
    )


def spend_willpower(sheet: Sheet, points: int = 1) -> Sheet:
    """Spend Willpower without rolling, for the things that cost but do not test."""
    if points < 1:
        raise CheckError(f"spending Willpower takes at least one point, got {points}")
    remaining = sheet.willpower_remaining
    if remaining is None:
        remaining = sheet.willpower
    if remaining < points:
        raise CheckError(f"{sheet.name} has {remaining} Willpower left, not {points}")
    return replace(sheet, willpower_remaining=remaining - points)
