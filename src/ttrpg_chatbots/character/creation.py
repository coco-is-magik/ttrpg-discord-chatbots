"""Starting a character: the interview first, then the mechanics, then one structure.

The flow is deliberately linear and dumb: ask every question, refuse blank answers, then
spend the build budgets, then hand back a sealed :class:`Character`. It never reads stdin;
it only talks to a :class:`~ttrpg_chatbots.character.prompting.Prompter`, so the same code
serves a terminal today and a Discord flow later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Mapping

from ttrpg_chatbots.character.prompting import (
    Prompter,
    PrompterError,
    ask_int,
    ask_optional_text,
    ask_text,
)
from ttrpg_chatbots.character.types import Character
from ttrpg_chatbots.sheets.interview import Interview, Question, Questionnaire
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Ability, Gift, Sheet, Trait

GROUP_ATTEMPTS = 5
MAX_TRAITS = 20


def now_utc() -> str:
    """Timestamps are ISO-8601 UTC, injected so tests can pin them."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def blank_sheet(name: str, *, system=houseg) -> Sheet:
    """An empty character: attributes and virtues at 1, abilities at 0, nothing else.

    This is the "empty character sheet" a build starts from. Every attribute and virtue begins
    at 1 per the rules, which is why the budgets are measured against a floor rather than 0.
    """
    return Sheet(
        name=name.strip(),
        system=system.SYSTEM,
        attributes={attribute: 1 for attribute in system.attribute_names()},
        abilities={
            ability: Ability(name=ability, rank=0, category=category)
            for category, names in system.ABILITY_LISTS.items()
            for ability in names
        },
        virtues={virtue: 1 for virtue in system.VIRTUE_NAMES},
        willpower=1,
        willpower_remaining=1,
        morality=2,
        health=system.HEALTH_LEVELS,
        freebies=system.FREEBIE_BASE,
    )


def start_character(
    prompter: Prompter,
    questionnaire: Questionnaire,
    *,
    name: str | None = None,
    seal: bool = True,
    system=houseg,
    clock: Callable[[], str] = now_utc,
) -> Character:
    """Run the whole creation flow and return the character."""
    prompter.say(f"Creating a character for {system.SYSTEM}.")
    character_name = (name or "").strip() or ask_text(prompter, "Character name?")
    interview = ask_interview(prompter, questionnaire, character_name)
    prompter.say("\nNow the mechanics.")
    sheet = ask_mechanics(prompter, character_name, system=system)

    created = clock()
    character = Character(sheet=sheet, interview=interview, created=created)
    character = character.record("created", f"created {character_name}", at=created)
    if seal and interview.complete:
        character = character.seal(at=created)
    return character


def ask_interview(
    prompter: Prompter, questionnaire: Questionnaire, character: str
) -> Interview:
    """Ask every question, in order. A blank answer is rejected, never skipped."""
    questions: list[Question] = []
    section = ""
    for title, prompt in questionnaire.prompts:
        if title != section:
            section = title
            prompter.say(f"\n== {title} ==")
        questions.append(
            Question(prompt=prompt, answer=ask_text(prompter, prompt), section=section)
        )
    return Interview(
        character=character, questions=tuple(questions), sheet=questionnaire.name
    )


def ask_mechanics(prompter: Prompter, name: str, *, system=houseg) -> Sheet:
    """Spend the build budgets, prompting for each trait."""
    prompter.say(
        f"Attributes: budgets {system.ATTRIBUTE_BUDGETS}, each starts at 1, "
        f"max {system.MAX_CREATION_TRAIT}."
    )
    attributes = _ask_groups(
        prompter,
        system.ATTRIBUTE_GROUPS,
        system.ATTRIBUTE_BUDGETS,
        base=1,
        high=system.MAX_CREATION_TRAIT,
    )

    prompter.say(
        f"\nAbilities: budgets {system.ABILITY_BUDGETS}, each starts at 0, "
        f"max {system.MAX_CREATION_TRAIT}. Blank means 0."
    )
    ability_values = _ask_groups(
        prompter,
        system.ABILITY_LISTS,
        system.ABILITY_BUDGETS,
        base=0,
        high=system.MAX_CREATION_TRAIT,
    )
    abilities = _build_abilities(prompter, ability_values, system=system)

    prompter.say(f"\nVirtues: {system.VIRTUE_POINTS} points to spend, each starts at 1.")
    virtues = _ask_groups(
        prompter,
        {"Virtues": system.VIRTUE_NAMES},
        (system.VIRTUE_POINTS,),
        base=1,
        high=system.MAX_CREATION_TRAIT,
    )

    prompter.say(
        f"\nBackgrounds: {system.BACKGROUND_POINTS} points, blank name to finish."
    )
    backgrounds = _ask_traits(prompter, "Background", budget=system.BACKGROUND_POINTS)

    prompter.say("\nGifts (optional): one at a time, blank name to finish.")
    asks = _ask_traits(prompter, "Gift")
    gifts = tuple(Gift(name=asked.name, rating=asked.dots) for asked in asks)

    willpower = virtues["Courage"]
    morality = virtues["Conscience/Conviction"] + virtues["Self-Control/Instinct"]
    return Sheet(
        name=name.strip(),
        system=system.SYSTEM,
        attributes=attributes,
        abilities=abilities,
        virtues=virtues,
        willpower=willpower,
        willpower_remaining=willpower,
        morality=morality,
        health=system.HEALTH_LEVELS,
        gifts=gifts,
        backgrounds=backgrounds,
        # 15 freebies, plus the value of any Flaws taken (rules: "15 + Flaw value").
        freebies=system.FREEBIE_BASE,
    )


def _ask_groups(
    prompter: Prompter,
    groups: Mapping[str, tuple[str, ...]],
    budgets: tuple[int, ...],
    *,
    base: int,
    high: int,
) -> dict[str, int]:
    """Ask each trait, and insist the totals use each budget exactly once."""
    available = list(budgets)
    values: dict[str, int] = {}
    for group, names in groups.items():
        prompter.say(f"  {group}: {base}..{high} each, budgets still available {available}")
        for _ in range(GROUP_ATTEMPTS):
            attempt = {
                name: ask_int(prompter, f"    {name}", default=base, low=base, high=high)
                for name in names
            }
            spent = sum(attempt.values()) - base * len(names)
            if spent in available:
                available.remove(spent)
                values.update(attempt)
                break
            prompter.say(f"  {group} spent {spent}; available budgets: {available}")
        else:
            raise PrompterError(
                f"could not spend a legal budget on {group}; available were {available}"
            )
    if available:
        raise PrompterError(f"budgets left unspent: {available}")
    return values


def _build_abilities(
    prompter: Prompter, values: Mapping[str, int], *, system=houseg
) -> dict[str, Ability]:
    abilities: dict[str, Ability] = {}
    for category, names in system.ABILITY_LISTS.items():
        for name in names:
            rank = values.get(name, 0)
            specialty = ""
            if rank >= 4:
                specialty = ask_optional_text(
                    prompter, f"    specialty for {name} (blank for none)"
                )
            abilities[name] = Ability(
                name=name, rank=rank, category=category, specialty=specialty
            )
    return abilities


def _ask_traits(
    prompter: Prompter, label: str, *, budget: int | None = None, high: int = 5
) -> tuple[Trait, ...]:
    """Free-form traits: a name, then dots, until the name is left blank."""
    traits: list[Trait] = []
    spent = 0
    for _ in range(MAX_TRAITS):
        name = ask_optional_text(prompter, f"  {label} name (blank to finish)")
        if not name:
            return tuple(traits)
        dots = ask_int(prompter, f"    dots for {name}", default=1, low=1, high=high)
        if budget is not None and spent + dots > budget:
            prompter.say(f"    that would exceed the {budget}-point budget ({spent} spent)")
            continue
        traits.append(Trait(name=name, dots=dots))
        spent += dots
    raise PrompterError(f"too many {label.lower()}s; save the rest for play")

