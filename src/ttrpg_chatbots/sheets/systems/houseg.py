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

import re
from dataclasses import dataclass, field

from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import MODE_HITS, RollSpec
from ttrpg_chatbots.sheets.types import (
    KNOWLEDGE,
    SKILL,
    TALENT,
    Ability,
    Gift,
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
    # "Player" (B3) is deliberately not read: who plays a character is a **seat**, and that
    # cell has been used for numbers as often as for names. Importing it would copy a real
    # person's name into the character file for no gain.
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
_POWER_ROWS = (33, 80)
# Row 32 is the "Backgrounds" header, so the first entry is row 33. Getting this wrong
# silently drops a player's first background.
_BACKGROUND_ROWS = (33, 80)
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
MAX_FLAW_POINTS = 7  # "maximum of 7 points of Flaws, or two Flaws totaling any amount"
# A single flaw's value is not capped at 5: the index has Blind at 6, and a custom flaw is
# allowed "any amount" the group accepts. The *total* rule above is what balances it.
MAX_FLAW_RATING = 10


# -- Gifts -------------------------------------------------------------------
#
# House Games does not price Gifts: the rules award **one Gift per won Game** ("Characters
# receive 10 XP and a Gift if they win. They get 5 XP but no Gift if they lose but survive")
# and measure power level by how many a character holds. So a character's gift count *is*
# their number of wins, and the portal counts rather than costs.
#
# The ladder is the rules document's own, and it has a wrinkle worth preserving: **Veteran is
# not a count**. "Any non-Veteran with at least thirty Gifts is Very High Seasoned"; a Veteran
# is a character who has taken the **Veteran Template** (earned by a solo Veteran Game with no
# assistance) and may hold fewer than thirty.
GIFT_TIERS = (
    (30, "Very High Seasoned"),
    (20, "High Seasoned"),
    (10, "Seasoned"),
    (0, "Novice"),
)
VETERAN = "Veteran"
# The rules write Seasoned as "10 to 20" and High Seasoned as "at least 20", so 20 sits in
# both. Taking the higher band is the only reading that keeps the ladder disjoint.
GIFT_BALANCE_SPREAD = 5


def gift_tier(count: int, *, veteran: bool = False) -> str:
    """The rules' power level: Novice, Seasoned, High Seasoned, Very High Seasoned, Veteran.

    ``veteran`` comes from the Veteran Template, not from the count: 30+ Gifts without the
    template is Very High Seasoned.
    """
    if veteran:
        return VETERAN
    for threshold, name in GIFT_TIERS:
        if count >= threshold:
            return name
    return GIFT_TIERS[-1][1]


# -- the economy, straight from the rules ------------------------------------
#
# Creation and advancement costs are *rating dependent*, so they are encoded once here rather
# than re-derived by guesswork in the mutation layer. Each advancement entry is
# (cost of the first rank, or 0, multiplier of the current rating).
FREEBIE_COSTS = {
    "attribute": 5,
    "ability": 2,
    "virtue": 2,
    "morality": 2,
    "background": 1,
    "willpower": 1,
}
ADVANCEMENT_COSTS = {
    "attribute": (0, 4),    # Current Rating x4
    "ability": (3, 2),      # 3 for the first rank, then Current Rating x2
    "background": (7, 3),   # 7 for the first rank, then Current Rating x3
    "virtue": (0, 2),       # Current Rating x2
    "willpower": (0, 1),    # Current Rating x1
    "pool": (0, 2),         # Current Rating x2
    "merit": (0, 3),        # Rating x3 to acquire, two GMs' approval
    "flaw": (0, 3),         # Rating x3 to buy off, two GMs' approval
    "maneuver": (2, 0),     # 2 each
    "ritual": (2, 0),       # 2 each
    "power": (0, 6),        # Current Rating x6, x5 when dramatically flawed; max 5
    "magic": (0, 7),        # Current Rating x7
}
# A Game's reward: "10 XP and a Gift if they win. 5 XP but no Gift if they lose but survive."
XP_WIN = 10
XP_LOSS = 5
GIFTS_PER_WIN = 1
GM_XP_PER_GAME = 10
# Caps: 5 for traits (Morality and Willpower to 10); backgrounds 5, 8 as a Veteran, 8 with a
# Gift (Seasoned) or 10 with a Gift (Veteran).
TRAIT_CAP = 5
TRACKER_CAP = 10
# Creation uses the same ceilings as advancement; these aliases exist so the wizard reads in
# the rules' language without a second, drift-prone copy of the numbers.
MAX_CREATION_TRAIT = TRAIT_CAP
MAX_CREATION_TRACKER = TRACKER_CAP
BACKGROUND_CAP = 5
BACKGROUND_CAP_VETERAN = 8
BACKGROUND_CAP_GIFT = 10


def advancement_cost(
    kind: str, current: int = 0, *, flawed: bool = False, rating: int | None = None
) -> int:
    """Experience cost to raise one trait of ``kind`` by a point.

    ``current`` is the rating before the raise (abilities and backgrounds also have a flat
    first-rank cost). ``rating`` prices merits and flaws, which are costed by their own rating
    rather than by a current value. Unknown kinds raise instead of guessing a number.
    """
    if kind not in ADVANCEMENT_COSTS:
        known = ", ".join(sorted(ADVANCEMENT_COSTS))
        raise ValueError(f"unknown advancement kind {kind!r}; known: {known}")
    if kind in {"merit", "flaw"}:
        points = rating if rating is not None else current
        return points * ADVANCEMENT_COSTS[kind][1]
    first, multiplier = ADVANCEMENT_COSTS[kind]
    if current <= 0 and first:
        return first
    if kind == "power" and flawed:
        return current * 5
    return current * multiplier


def freebie_cost(kind: str) -> int:
    """Freebie points for one point of ``kind`` at creation."""
    try:
        return FREEBIE_COSTS[kind]
    except KeyError:
        known = ", ".join(sorted(FREEBIE_COSTS))
        raise ValueError(f"unknown freebie kind {kind!r}; known: {known}") from None



def balance_warnings(counts: Mapping[str, int]) -> tuple[str, ...]:
    """Pairs more than five Gifts apart.

    The rules say the spread "should be enforced" so that carries and the weight do not mix;
    enforcement belongs to table composition (who sits down together), while a build-time
    check should only report it. Hence: a function that names the problem, not one that edits
    a character.
    """
    warnings = []
    characters = sorted(counts)
    for index, first in enumerate(characters):
        for second in characters[index + 1 :]:
            spread = abs(counts[first] - counts[second])
            if spread > GIFT_BALANCE_SPREAD:
                warnings.append(
                    f"{first} ({counts[first]} gifts) and {second} ({counts[second]} gifts) "
                    f"are {spread} apart; the house rule keeps a table within "
                    f"{GIFT_BALANCE_SPREAD}"
                )
    return tuple(warnings)

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


# -- which attribute an ability is rolled with -------------------------------
#
# House Games rolls "Attribute + Ability" (see *Action Resolution*), but a player says "roll
# Stealth", not "roll Dexterity + Stealth". These are the World of Darkness defaults, keyed by
# the ability vocabulary on the sheet. A player can always override the attribute explicitly,
# and an ability nobody has mapped falls back to its category's usual pairings rather than
# refusing to roll.
ABILITY_ATTRIBUTE = {
    # Talents
    "Alertness": "Perception",
    "Athletics": "Dexterity",
    "Brawl": "Strength",
    "Dodge": "Dexterity",
    "Empathy": "Perception",
    "Expression": "Charisma",
    "Intimidation": "Charisma",
    "Intuition": "Perception",
    "Leadership": "Charisma",
    "Legerdemain": "Dexterity",
    "Streetwise": "Manipulation",
    "Subterfuge": "Manipulation",
    "Endurance": "Stamina",
    # Skills
    "Animal Ken": "Charisma",
    "Crafts": "Dexterity",
    "Engineering": "Intelligence",
    "Etiquette": "Charisma",
    "Firearms": "Dexterity",
    "Melee": "Dexterity",
    "Meditation": "Wits",
    "Performance": "Charisma",
    "Pilot": "Dexterity",
    "Stealth": "Dexterity",
    "Survival": "Wits",
    # Knowledges
    "Academics": "Intelligence",
    "Computers": "Intelligence",
    "Culture": "Intelligence",
    "Investigation": "Perception",
    "Linguistics": "Intelligence",
    "Management": "Manipulation",
    "Medicine": "Intelligence",
    "Occult": "Intelligence",
    "Pyschology": "Perception",
    "Psychology": "Perception",
    "Science": "Intelligence",
    "Thanatology": "Intelligence",
}
# When an ability is not in the table: the attribute its category is usually rolled with.
CATEGORY_ATTRIBUTE = {TALENT: "Perception", SKILL: "Dexterity", KNOWLEDGE: "Intelligence"}


def attribute_for(sheet: Sheet, ability: str) -> tuple[str, bool]:
    """The attribute an ability rolls with, and whether that pairing was a guess.

    ``(attribute, guessed)`` — the caller can tell the player when it fell back, so an unusual
    homebrew ability does not silently roll the wrong stat.
    """
    name, category = _kind(sheet, ability)
    for known, attribute in ABILITY_ATTRIBUTE.items():
        if normalise(known) == normalise(name):
            return resolve_name(attribute, sheet.attributes), False
    return CATEGORY_ATTRIBUTE.get(category, "Intelligence"), True


def wound_penalty(sheet: Sheet) -> int:
    """The health penalty currently in force, as a positive number (0 when unhurt).

    Levels name their own penalty (``Hurt (-1)``), and the deeper of the levels reached is the
    one that applies, so walking the track from the top is what produces the right number.
    """
    levels = sheet.health or HEALTH_LEVELS
    raw = sheet.meta.get("health_current")
    try:
        current = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        current = 0
    current = max(0, min(current, len(levels) - 1))
    worst = 0
    for level in levels[: current + 1]:
        match = re.search(r"\(-(\d+)\)", str(level))
        if match:
            worst = max(worst, int(match.group(1)))
    return worst


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
    gifts, planned_gifts = _read_gifts(grid)
    backgrounds, planned_backgrounds = _read_backgrounds(grid)
    planned_wishlist = _read_wishlist(grid)

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
        gifts=gifts,
        planned=planned_gifts + planned_backgrounds + planned_wishlist,
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


# Sub-header cells that appear inside a trait block. The template has a second header row
# ("background" / "# dots"); filled sheets usually overwrite it with a real entry, so a reader
# has to tolerate both shapes.
_TRAIT_HEADER_VALUES = frozenset({"# dots", "#dot", "#dots", "dots", "point cost/bonus"})
# The planning block that sits below the mission log on a filled tab.
_WISHLIST_HEADER = "things to get"
# Players group their plans, so a single blank row does not end the list.
_WISHLIST_GAP_TOLERANCE = 3


def _is_trait_header(label: str, raw: str) -> bool:
    """A row that labels the block rather than belonging to it."""
    lowered = raw.strip().lower()
    if lowered in _TRAIT_HEADER_VALUES:
        return True
    # Section titles repeat themselves across the two columns ("Missions" / "Missions",
    # "Backgrounds" / "Backgrounds"), which is how a new block announces itself.
    return lowered == label.strip().lower()


# A mission log row is (mission name, player list). Player lists are terse ("Me, Cowboy,
# Hikou"); a gift's description is a sentence. That length gap is the only reliable signal in
# a freeform tab, so it is used explicitly -- and anything skipped is reported, never guessed.
_MISSION_HEADERS = frozenset({"name", "mission", "missions"})
_PLAYER_LIST_VALUES = frozenset({"players", "player", "me"})
_MIN_GIFT_DESCRIPTION = 35


def _is_mission_header(label: str, raw: str) -> bool:
    """The row that starts the mission log: "name" beside "players"."""
    return label.strip().lower() in _MISSION_HEADERS and raw.strip().lower() in _PLAYER_LIST_VALUES


def _looks_like_player_list(raw: str) -> bool:
    text = raw.strip()
    if text.lower() in _PLAYER_LIST_VALUES:
        return True
    return "," in text and len(text) < _MIN_GIFT_DESCRIPTION


def _read_gifts(grid) -> tuple[tuple[Gift, ...], tuple[Gift, ...]]:
    """The Gifts column, in both of its legitimate shapes, with the mission log removed.

    A Gift is whatever the GM offered, so this block holds levelled powers (a number beside
    the name) *and* flat techniques (a sentence beside the name). Both are owned; only a
    rating of zero means "planned".

    Filled tabs also interleave a **mission log** into these columns: a "name | players"
    header followed by mission names beside the people who played them. That is personal
    data and it is not a Gift, so it is skipped and counted, and a note records how much was
    passed over. A prose cell with a number in the third column is a labelled value rather
    than a power -- "Vampire Gen | Caitiff | 13" is generation 13, not a Gift called Caitiff.
    """
    owned: list[Gift] = []
    planned: list[Gift] = []
    skipping_missions = False
    skipped = 0
    mission_row = 0

    for row in range(_POWER_ROWS[0], _POWER_ROWS[1] + 1):
        name = grid.text(f"A{row}")
        raw = grid.text(f"B{row}")
        note = grid.text(f"C{row}")
        if not name:
            continue
        if not raw and not note:
            continue
        if _is_mission_header(name, raw):
            skipping_missions = True
            mission_row = row
            continue
        if skipping_missions:
            if _looks_like_player_list(raw):
                skipped += 1
                continue
            skipping_missions = False

        if raw and _is_trait_header(name, raw):
            continue
        if _numeric(raw):
            rating = int(round(float(raw)))
            # The third column often just repeats the rating; that is not a description.
            description = "" if _numeric(note) or note == raw else note
            if rating > 0:
                owned.append(Gift(name=name, rating=rating, description=description))
            else:
                planned.append(Gift(name=name, rating=0, description=description))
            continue
        if not raw:
            continue
        if _numeric(note):
            # "Vampire Gen: Caitiff, 13" -- a labelled scalar, not a Gift.
            continue
        owned.append(Gift(name=name, description=note or raw))

    if skipped:
        grid.notes.append(
            f"A{mission_row}: skipped a mission log ({skipped} rows); "
            "missions and player names are not imported"
        )
    return tuple(owned), tuple(planned)


def _read_backgrounds(grid) -> tuple[tuple[Trait, ...], tuple[Gift, ...]]:
    """Backgrounds, plus the zero-rated ones the player is planning to buy.

    Filled tabs grow past the template: below the backgrounds sits a **Missions** section,
    below that a wishlist, below that merits with their full text in the same columns. So the
    block skips its own header rows and stops at the first row that is neither a header nor a
    rating.
    """
    owned: list[Trait] = []
    planned: list[Gift] = []
    for row in range(_BACKGROUND_ROWS[0], _BACKGROUND_ROWS[1] + 1):
        label = grid.text(f"D{row}")
        if not label:
            continue
        raw = grid.text(f"E{row}")
        if not raw:
            continue
        if not _numeric(raw):
            if _is_trait_header(label, raw):
                continue
            break
        dots = int(round(float(raw)))
        if dots > 0:
            owned.append(Trait(name=label, dots=dots))
        else:
            planned.append(Gift(name=label, rating=0, description="background, planned"))
    return tuple(owned), tuple(planned)


def _read_wishlist(grid) -> tuple[Gift, ...]:
    """The "Things to get" block: purchases and advances the player intends to make.

    It is a *plan*, not a possession, so it never counts toward the Gift total. Reading it
    keeps the player's intentions instead of discarding them with the mission log that
    precedes it. Short gaps are allowed (players group their plans); a run of blanks or a
    section header ends the block.
    """
    start = None
    for row in range(_BACKGROUND_ROWS[0], grid.max_row + 1):
        if grid.text(f"D{row}").strip().lower().startswith(_WISHLIST_HEADER):
            start = row + 1
            break
    if start is None:
        return ()

    planned: list[Gift] = []
    blanks = 0
    for row in range(start, grid.max_row + 1):
        name = grid.text(f"D{row}")
        if not name:
            blanks += 1
            if blanks >= _WISHLIST_GAP_TOLERANCE:
                break
            continue
        blanks = 0
        note = grid.text(f"E{row}")
        if _is_trait_header(name, note):
            break
        planned.append(Gift(name=name, description=note))
    return tuple(planned)


def _numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


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

