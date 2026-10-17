"""Random characters, by the book's build budgets.

Two jobs, because they solve different problems:

* :func:`random_mechanics` spends the Standard Build System budgets at random, so the
  result is a *legal* character even though nobody chose anything.
* :func:`random_character` pairs those mechanics with a **blank** interview. Prose cannot
  be invented without a language model, so the interview stays pending until a person (or
  an LLM) fills it in. :func:`assign_premade` is the alternative the rules allow: hand the
  player an existing, finished character instead of making a new one.
"""

from __future__ import annotations

import random
from dataclasses import replace
from typing import Callable, Mapping, Sequence

from ttrpg_chatbots.character.creation import now_utc
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import Questionnaire, blank_interview
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Ability, Sheet, Trait


def _spread(
    rng: random.Random, names: Sequence[str], points: int, *, cap: int
) -> dict[str, int]:
    """Hand out ``points`` one at a time, never exceeding ``cap`` on any trait."""
    values = {name: 0 for name in names}
    for _ in range(points):
        choices = [name for name in names if values[name] < cap]
        if not choices:
            raise CharacterError(
                f"cannot spend {points} points across {len(names)} traits capped at {cap}"
            )
        values[rng.choice(choices)] += 1
    return values


def _random_traits(
    rng: random.Random, names: Sequence[str], points: int, *, cap: int = 5
) -> tuple[Trait, ...]:
    """Spend ``points`` over a random subset of ``names``, dropping empty ones."""
    if points <= 0:
        return ()
    chosen = list(names)
    rng.shuffle(chosen)
    spread = _spread(rng, chosen, points, cap=cap)
    return tuple(
        Trait(name=name, dots=dots) for name, dots in spread.items() if dots > 0
    )


def random_mechanics(
    rng: random.Random,
    *,
    name: str | None = None,
    system=houseg,
) -> Sheet:
    """A mechanically legal house-games character, chosen at random."""
    attribute_budgets = list(system.ATTRIBUTE_BUDGETS)
    rng.shuffle(attribute_budgets)
    attributes: dict[str, int] = {}
    for (group, names), budget in zip(system.ATTRIBUTE_GROUPS.items(), attribute_budgets):
        spread = _spread(
            rng, names, budget, cap=system.MAX_CREATION_TRAIT - 1  # +1 for the base dot
        )
        attributes.update({trait: 1 + dots for trait, dots in spread.items()})

    ability_budgets = list(system.ABILITY_BUDGETS)
    rng.shuffle(ability_budgets)
    abilities: dict[str, Ability] = {}
    for (category, names), budget in zip(system.ABILITY_LISTS.items(), ability_budgets):
        spread = _spread(rng, names, budget, cap=system.MAX_CREATION_TRAIT)
        abilities.update(
            {
                trait: Ability(name=trait, rank=dots, category=category)
                for trait, dots in spread.items()
            }
        )

    virtues = {
        trait: 1 + dots
        for trait, dots in _spread(
            rng, system.VIRTUE_NAMES, system.VIRTUE_POINTS, cap=system.MAX_CREATION_TRAIT - 1
        ).items()
    }

    return Sheet(
        name=(name or "Random Character").strip(),
        system=system.SYSTEM,
        attributes=attributes,
        abilities=abilities,
        virtues=virtues,
        willpower=virtues["Courage"],
        willpower_remaining=virtues["Courage"],
        morality=virtues["Conscience/Conviction"] + virtues["Self-Control/Instinct"],
        health=system.HEALTH_LEVELS,
        powers=(),
        backgrounds=_random_traits(rng, system.BACKGROUND_SUGGESTIONS, system.BACKGROUND_POINTS),
    )


def random_character(
    rng: random.Random,
    *,
    name: str | None = None,
    questionnaire: Questionnaire | None = None,
    clock: Callable[[], str] = now_utc,
) -> Character:
    """Random mechanics plus a blank interview: playable once someone writes the prose."""
    sheet = random_mechanics(rng, name=name)
    interview = blank_interview(questionnaire, sheet.name) if questionnaire else None
    created = clock()
    character = Character(sheet=sheet, interview=interview, created=created)
    return character.record(
        "created", f"rolled {sheet.name} at random", at=created, detail={"source": "random"}
    )


def assign_premade(
    rng: random.Random,
    pool: Sequence[Character],
    *,
    rename: str | None = None,
    clock: Callable[[], str] = now_utc,
) -> Character:
    """Hand out one finished character from a pool.

    Renaming keeps the answers (the seal's digest covers answers, not names), so the
    prose still says whatever it said -- a renamed character is the same person with a
    different label, which is usually not what you want. It is allowed, not encouraged.
    """
    if not pool:
        raise CharacterError("no characters to pick from")
    chosen = rng.choice(list(pool))
    created = clock()

    if rename:
        new_name = rename.strip()
        sheet: Sheet = replace(chosen.sheet, name=new_name, id="")
        interview = (
            replace(chosen.interview, character=new_name)
            if chosen.interview is not None
            else None
        )
        chosen = replace(chosen, sheet=sheet, interview=interview)

    assigned = replace(chosen, created=created)
    return assigned.record(
        "assigned",
        f"assigned premade {chosen.name!r}" + (f" as {rename.strip()!r}" if rename else ""),
        at=created,
        detail={"source": "premade", "of": chosen.id},
    )


def pool_by_system(
    characters: Sequence[Character], system: str = houseg.SYSTEM
) -> tuple[Character, ...]:
    """Only the characters a caller can actually use."""
    return tuple(
        character
        for character in characters
        if character.system == system and character.ready
    )
