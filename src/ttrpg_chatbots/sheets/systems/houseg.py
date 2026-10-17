"""House Games: the community's homebrew World-of-Darkness mash-up.

Two things live here, because they are two halves of one contract:

* the **cell map** for the "House Games" tab of ``OG Character Sheets.xlsx``;
* the **resolution rules** in *My House Games Edits.md* -- a d10 pool of Attribute +
  Ability, success at or above the Difficulty (6 by default), ones cancelling successes,
  difficulties above 10 becoming a success threshold, a specialty rerolling tens, and
  Willpower buying a success.

The numbers and cell references below were read off the shipped workbook; the rules
quotes are from the rules document, section "0. Action Resolution".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import MODE_HITS, RollSpec
from ttrpg_chatbots.sheets.types import (
    KNOWLEDGE,
    SKILL,
    TALENT,
    Ability,
    Sheet,
    SheetError,
    Trait,
    UnknownTrait,
    normalise,
    resolve_name,
)

SYSTEM = "house-games"
TAB = "House Games"

DEFAULT_DIFFICULTY = 6
UNSKILLED_PENALTY = 2
DIE = 10
# "reroll 10's" can cascade; the cap only exists so a broken RNG cannot hang the bot.
MAX_REROLLS = 100

# -- cell map (verified against the workbook) ------------------------------

_INFO = {
    "name": "B2",
    "player": "B3",
    "nature": "E2",
    "demeanor": "E3",
    "age_sex": "H2",
    "ambition": "H3",
    "concept": "H4",
    "experience": "B4",
    "money": "E4",
}

_ATTRIBUTES = {
    "Strength": "B7",
    "Dexterity": "B8",
    "Stamina": "B9",
    "Charisma": "E7",
    "Manipulation": "E8",
    "Appearance": "E9",
    "Perception": "H7",
    "Intelligence": "H8",
    "Wits": "H9",
}

_VIRTUES = {
    "Conscience/Conviction": "E29",
    "Self-Control/Instinct": "E30",
    "Courage": "E31",
}

_WILLPOWER_TOTAL = "E26"
_WILLPOWER_REMAINING = "E27"
_MORALITY = "E24"

_HEALTH_FIRST_ROW = 24
_HEALTH_LAST_ROW = 31
_HEALTH_LABEL_COLUMN = "G"
_HEALTH_MARK_COLUMN = "H"

# (category, label column, specialty column, dots column)
_ABILITY_BLOCKS = (
    (TALENT, "A", "B", "C"),
    (SKILL, "D", "E", "F"),
    (KNOWLEDGE, "G", "H", "I"),
)
_ABILITY_FIRST_ROW = 12
_ABILITY_LAST_ROW = 21

# Lists run downward; the template leaves rows 34-80 merged and empty for more.
_POWER_ROWS = (34, 80)
_BACKGROUND_ROWS = (34, 80)
# The merits block is the one cramped corner of this layout: "Powers/Paths" starts at
# A32, so merits only get rows 24-31. A filled tab puts its first merit in row 24, where
# the template has the "Name" header, so header rows are skipped rather than assumed.
_MERIT_ROWS = (24, 31)
_MERIT_HEADERS = {"name", "merits and flaws"}

# The template ships a placeholder in every specialty cell.
_SPECIALTY_PLACEHOLDER = "spec"

# -- the Standard Build System (rules document, "Character Creation") ------
#
# Attribute and ability points are spent as one of three budgets assigned to one of
# three groups; every attribute starts at 1 and every ability at 0. Virtues start at 1.
ATTRIBUTE_GROUPS = {
    "Physical": ("Strength", "Dexterity", "Stamina"),
    "Social": ("Charisma", "Manipulation", "Appearance"),
    "Mental": ("Perception", "Intelligence", "Wits"),
}
ATTRIBUTE_BUDGETS = (7, 5, 3)
ABILITY_BUDGETS = (13, 9, 5)
VIRTUE_NAMES = ("Conscience/Conviction", "Self-Control/Instinct", "Courage")
VIRTUE_POINTS = 7
BACKGROUND_POINTS = 5
FREEBIE_BASE = 15
MAX_CREATION_TRAIT = 5
MAX_CREATION_TRACKER = 10

# The health track, from the sheet template (G24:G31).
HEALTH_LEVELS = (
    "Unharmed",
    "Bruised",
    "Hurt (-1)",
    "Injured (-1)",
    "Wounded (-2)",
    "Mauled (-2)",
    "Crippled (-5)",
    "Incapacitated",
)

# Backgrounds the book mentions; a character may name anything, these are suggestions.
BACKGROUND_SUGGESTIONS = (
    "Allies",
    "Contacts",
    "Fame",
    "Influence",
    "Library",
    "Mentor",
    "Resources",
    "Retainers",
    "Status",
)


def attribute_names() -> tuple[str, ...]:
    """All nine attributes, in the book's group order."""
    return tuple(name for names in ATTRIBUTE_GROUPS.values() for name in names)


def ability_names(category: str) -> tuple[str, ...]:
    return ABILITY_LISTS[category]


# -- vocabulary ------------------------------------------------------------


# The template's own ability names, by category. Kept here so an ability the character
# has never bought still resolves to a category, which is what decides the untrained
# penalty. "Pyshcology" is spelled that way in the workbook on purpose.
ABILITY_LISTS = {
    TALENT: (
        "Alertness",
        "Athletics",
        "Brawl",
        "Dodge",
        "Endurance",
        "Intimidation",
        "Intuition",
        "Legerdemain",
        "Persuasion",
        "Subterfuge",
    ),
    SKILL: (
        "Animal Ken",
        "Crafts",
        "Engineering",
        "Firearms",
        "Meditation",
        "Melee",
        "Performance",
        "Pilot",
        "Stealth",
        "Survival",
    ),
    KNOWLEDGE: (
        "Academics",
        "Computers",
        "Culture",
        "Investigation",
        "Linguistics",
        "Management",
        "Medicine",
        "Occult",
        "Pyshcology",
        "Science",
    ),
}

_CATEGORY_OF = {name: category for category, names in ABILITY_LISTS.items() for name in names}
_ALL_ABILITIES = tuple(_CATEGORY_OF)

# Spellings players actually type, mapped onto the workbook's vocabulary.
ALIASES = {
    "psychology": "Pyshcology",
    "psyche": "Pyshcology",
    "animal handling": "Animal Ken",
    "animals": "Animal Ken",
    "computers": "Computers",
    "computer": "Computers",
    "first aid": "Medicine",
    "science: biology": "Science",
}


# -- reading a sheet -------------------------------------------------------


def read_sheet(grid, *, source: str = "", name: str | None = None) -> Sheet:
    """Turn a ``House Games`` worksheet into a :class:`Sheet`.

    ``name`` overrides the name cell, which matters when importing: the tab name is
    authoritative and the ``Name`` cell is sometimes left blank.
    """
    character_name = (name or grid.text(_INFO["name"])).strip()
    if not character_name:
        raise SheetError(f"{grid.name}: no character name in {_INFO['name']}")

    meta = {
        key: value
        for key, ref in _INFO.items()
        if key != "name" and (value := grid.text(ref))
    }
    merits = _read_merits(grid)
    if merits:
        meta["merits"] = merits

    # Read everything before collecting notes: a note is only created while these run.
    attributes = {label: grid.integer(ref) for label, ref in _ATTRIBUTES.items()}
    abilities = _read_abilities(grid)
    virtues = {label: grid.integer(ref) for label, ref in _VIRTUES.items()}
    willpower = grid.integer(_WILLPOWER_TOTAL)
    willpower_remaining = (
        grid.integer(_WILLPOWER_REMAINING) if grid.filled(_WILLPOWER_REMAINING) else None
    )
    morality = grid.integer(_MORALITY) if grid.filled(_MORALITY) else None
    health = _read_health(grid)
    powers = _read_traits(grid, _POWER_ROWS, "A", "B")
    backgrounds = _read_traits(grid, _BACKGROUND_ROWS, "D", "E")

    if grid.notes:
        meta["notes"] = list(grid.notes)

    return Sheet(
        name=character_name,
        system=SYSTEM,
        attributes=attributes,
        abilities=abilities,
        virtues=virtues,
        willpower=willpower,
        willpower_remaining=willpower_remaining,
        morality=morality,
        health=health,
        powers=powers,
        backgrounds=backgrounds,
        meta=meta,
        source=source or grid.name,
    )


def _read_abilities(grid) -> dict[str, Ability]:
    found: dict[str, Ability] = {}
    for category, label_col, spec_col, dots_col in _ABILITY_BLOCKS:
        for row in range(_ABILITY_FIRST_ROW, _ABILITY_LAST_ROW + 1):
            label = grid.text(f"{label_col}{row}")
            if not label:
                continue
            found[label] = Ability(
                name=label,
                rank=grid.integer(f"{dots_col}{row}"),
                category=category,
                specialty=_specialty(grid.text(f"{spec_col}{row}")),
            )
    return found


def _specialty(text: str) -> str:
    cleaned = " ".join(text.split())
    # Every specialty cell in the template literally says "Spec"; that is not a specialty.
    return "" if cleaned.lower() == _SPECIALTY_PLACEHOLDER else cleaned


def _read_health(grid) -> tuple[str, ...]:
    levels: list[str] = []
    for row in range(_HEALTH_FIRST_ROW, _HEALTH_LAST_ROW + 1):
        label = grid.text(f"{_HEALTH_LABEL_COLUMN}{row}")
        if label:
            levels.append(label)
    return tuple(levels)


def _read_traits(grid, rows: tuple[int, int], label_col: str, dots_col: str) -> tuple[Trait, ...]:
    found: list[Trait] = []
    for row in range(rows[0], rows[1] + 1):
        label = grid.text(f"{label_col}{row}")
        if not label:
            continue
        found.append(Trait(name=label, dots=grid.integer(f"{dots_col}{row}")))
    return tuple(found)


def _read_merits(grid) -> list[dict[str, object]]:
    merits: list[dict[str, object]] = []
    for row in range(_MERIT_ROWS[0], _MERIT_ROWS[1] + 1):
        label = grid.text(f"A{row}")
        if not label or label.lower() in _MERIT_HEADERS:
            continue
        if grid.text(f"B{row}").lower() == "point cost/bonus":
            continue
        merits.append({"name": label, "points": grid.integer(f"B{row}")})
    return merits


# -- resolution ------------------------------------------------------------

@dataclass(frozen=True)
class PoolSpec:
    """What to roll: a pool size, a difficulty, and the reasons for both."""

    attribute: str
    ability: str | None = None
    dice: int = 0
    difficulty: int = DEFAULT_DIFFICULTY
    specialty: str = ""
    willpower: bool = False
    notes: tuple[str, ...] = ()

    @property
    def target(self) -> int:
        """A die this high or higher is a success; above 10 nothing can reach it."""
        return min(self.difficulty, DIE)

    @property
    def threshold(self) -> int:
        """"Successes required" for a difficulty over 10."""
        return max(0, self.difficulty - 10)

    @property
    def label(self) -> str:
        return self.attribute if self.ability is None else f"{self.attribute} + {self.ability}"


@dataclass(frozen=True)
class PoolResult:
    """What came up, with the house rules applied."""

    spec: PoolSpec
    character: str
    rolls: tuple[int, ...]
    rerolls: tuple[int, ...] = ()
    successes: int = 0
    ones: int = 0
    willpower: int = 0

    @property
    def net(self) -> int:
        return self.successes - self.ones - self.spec.threshold + self.willpower

    @property
    def botch(self) -> bool:
        return self.net < 0

    @property
    def ok(self) -> bool:
        return self.net > 0

    def render(self) -> str:
        spec = self.spec
        detail = "[" + ", ".join(str(die) for die in self.rolls) + "]"
        if self.rerolls:
            detail += " rerolled [" + ", ".join(str(die) for die in self.rerolls) + "]"

        count = f"{self.successes} success{'' if self.successes == 1 else 'es'}"
        if self.ones:
            count += f" - {self.ones} one{'' if self.ones == 1 else 's'}"
        if spec.threshold:
            count += f" - {spec.threshold} threshold"
        if self.willpower:
            count += " + 1 Willpower"
        if self.botch:
            count += f" = {self.net} BOTCH"
        else:
            count += f" = {self.net} ({'success' if self.ok else 'failure'})"

        line = f"{self.character} rolls {spec.label} at difficulty {spec.difficulty}: "
        line += f"{detail} -> {count}"
        if spec.notes:
            line += " [" + "; ".join(spec.notes) + "]"
        return line



# -- building and rolling a pool ------------------------------------------


def _kind(sheet: Sheet, name: str) -> tuple[str, str]:
    """``(canonical name, category)`` for an ability.

    The sheet wins, so a player's homebrew ability keeps its own category; the template's
    vocabulary is the fallback, which is what gives an unbought ability a category and so
    the right untrained penalty.
    """
    wanted = ALIASES.get(normalise(name), name)
    on_sheet = sheet.find_ability(wanted)
    if on_sheet is not None:
        return on_sheet.name, on_sheet.category
    resolved = resolve_name(wanted, _ALL_ABILITIES)
    return resolved, _CATEGORY_OF[resolved]


def build_pool(
    sheet: Sheet,
    attribute: str,
    ability: str | None = None,
    *,
    difficulty: int | None = None,
    willpower: bool = False,
) -> PoolSpec:
    """Work out the dice pool and difficulty for one action."""
    attribute_name = resolve_name(attribute, sheet.attributes)
    dice = sheet.attribute(attribute_name)
    resolved_difficulty = DEFAULT_DIFFICULTY if difficulty is None else int(difficulty)
    if resolved_difficulty < 1:
        raise SheetError(f"difficulty must be at least 1, got {resolved_difficulty}")

    notes: list[str] = []
    ability_name = None
    specialty = ""
    if ability:
        ability_name, category = _kind(sheet, ability)
        on_sheet = sheet.find_ability(ability_name)
        rank = on_sheet.rank if on_sheet is not None else 0
        specialty = on_sheet.specialty if on_sheet is not None else ""
        dice += rank
        if rank == 0:
            if category == KNOWLEDGE:
                raise SheetError(
                    f"{sheet.name} has no ranks in {ability_name}: untrained knowledges "
                    "cannot be rolled"
                )
            if category == SKILL:
                resolved_difficulty += UNSKILLED_PENALTY
                notes.append(f"untrained skill (+{UNSKILLED_PENALTY} difficulty)")

    if dice < 1:
        raise SheetError(f"{sheet.name} has no dice to roll for {attribute_name}")

    if willpower:
        remaining = sheet.willpower_remaining
        if remaining is not None and remaining < 1:
            raise SheetError(f"{sheet.name} has no Willpower left to spend")
        notes.append("spends 1 Willpower for an automatic success")
    if specialty:
        notes.append(f"specialty: {specialty} (rerolls 10s)")

    return PoolSpec(
        attribute=attribute_name,
        ability=ability_name,
        dice=dice,
        difficulty=resolved_difficulty,
        specialty=specialty,
        willpower=willpower,
        notes=tuple(notes),
    )


def resolve_pool(spec: PoolSpec, roller: Roller, *, character: str) -> PoolResult:
    """Roll the pool and apply the house rules.

    The dice themselves come from :class:`ttrpg_chatbots.dice.roller.Roller`, so the
    neutral roller keeps owning randomness and range checks while this module owns the
    rules that only this game uses.
    """
    if spec.dice < 1:
        raise SheetError("a dice pool needs at least one die")

    rolled = roller.roll(
        RollSpec(
            count=spec.dice,
            sides=DIE,
            mode=MODE_HITS,
            target=spec.target,
            label=spec.label,
        ),
        character=character,
    )
    rolls = rolled.dice
    successes = rolled.hits
    ones = sum(1 for die in rolls if die == 1)

    rerolls: list[int] = []
    if spec.specialty:
        pending = [die for die in rolls if die == DIE]
        while pending and len(rerolls) < MAX_REROLLS:
            pending.pop(0)
            again = roller.roll(RollSpec(count=1, sides=DIE), character=character).dice[0]
            rerolls.append(again)
            if again >= spec.target:
                successes += 1
            if again == DIE:
                pending.append(again)

    return PoolResult(
        spec=spec,
        character=character,
        rolls=rolls,
        rerolls=tuple(rerolls),
        successes=successes,
        ones=ones,
        willpower=1 if spec.willpower else 0,
    )

