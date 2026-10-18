"""House Games: the cell map, the pool maths, and the house rules."""

from __future__ import annotations

import pytest

from dice_support import ScriptedRng
from sheets_support import house_workbook
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import (
    KNOWLEDGE,
    SKILL,
    TALENT,
    Ability,
    Sheet,
    SheetError,
    UnknownTrait,
)
from ttrpg_chatbots.sheets.xlsx import read_grid


def loaded(tmp_path, **cells) -> Sheet:
    path = house_workbook(tmp_path / "house.xlsx", **cells)
    return houseg.read_sheet(read_grid(path, "House Games"))


def sheet(**overrides) -> Sheet:
    """A hand-built sheet, for rules tests that do not care about cell references."""
    base = dict(
        name="Brannoc",
        system=houseg.SYSTEM,
        attributes={"Dexterity": 3, "Intelligence": 2, "Stamina": 1},
        abilities={
            "Stealth": Ability("Stealth", 2, SKILL, "alleys"),
            "Occult": Ability("Occult", 1, KNOWLEDGE),
            "Brawl": Ability("Brawl", 2, TALENT),
            "Pyshcology": Ability("Pyshcology", 3, KNOWLEDGE),
        },
        willpower=5,
        willpower_remaining=4,
    )
    base.update(overrides)
    return Sheet(**base)


# -- reading the workbook tab ---------------------------------------------


def test_a_filled_sheet_reads_every_block(tmp_path) -> None:
    character = loaded(
        tmp_path,
        attributes={"Dexterity": 4, "Wits": 3},
        abilities={"Stealth": 2, "Computers": 4},
        specialties={"Stealth": "alleys"},
        virtues={"Courage": 3, "Conscience/Conviction": 4},
        willpower=5,
        willpower_remaining=4,
        morality=7,
        gifts={"Auspex": 2},
        backgrounds={"Mentor": 3},
        merits={"Jaded": 2},
    )
    assert character.name == "Brannoc the Archivist"
    assert character.system == houseg.SYSTEM
    assert character.attributes["Dexterity"] == 4
    assert character.attribute("dex") == 4
    assert character.ability("Stealth").rank == 2
    assert character.ability("Stealth").category == SKILL
    assert character.ability("Stealth").specialty == "alleys"
    assert character.ability("Computers").category == KNOWLEDGE
    assert character.virtues["Courage"] == 3
    assert character.willpower == 5
    assert character.willpower_remaining == 4
    assert character.morality == 7
    assert [gift.name for gift in character.gifts] == ["Auspex"]
    assert [trait.name for trait in character.backgrounds] == ["Mentor"]
    # The workbook's "Player" cell names a person; identity is a seat, so it is not read.
    assert "player" not in character.meta
    assert character.meta["merits"] == [{"name": "Jaded", "points": 2}]
    assert character.source == "House Games"


def test_health_levels_come_in_the_books_order(tmp_path) -> None:
    health = loaded(tmp_path).health
    assert health[0] == "Unharmed"
    assert health[-1] == "Incapacitated"
    assert len(health) == 8
    assert "Crippled (-5)" in health


def test_the_spec_placeholder_is_not_a_specialty(tmp_path) -> None:
    character = loaded(tmp_path, abilities={"Stealth": 2})
    assert all(ability.specialty == "" for ability in character.abilities.values())


def test_all_thirty_abilities_are_present(tmp_path) -> None:
    character = loaded(tmp_path)
    assert len(character.abilities) == 30
    assert {ability.category for ability in character.abilities.values()} == {
        TALENT,
        SKILL,
        KNOWLEDGE,
    }


def test_several_gifts_and_backgrounds_are_read(tmp_path) -> None:
    character = loaded(
        tmp_path,
        gifts={"Auspex": 2, "Celerity": 1},
        backgrounds={"Mentor": 3, "Contacts": 2},
    )
    assert [gift.name for gift in character.gifts] == ["Auspex", "Celerity"]
    assert [trait.name for trait in character.backgrounds] == ["Mentor", "Contacts"]


def test_a_sheet_without_a_name_is_refused(tmp_path) -> None:
    with pytest.raises(SheetError, match="no character name"):
        loaded(tmp_path, name=None)


# -- building a pool -------------------------------------------------------


def test_the_pool_is_attribute_plus_ability() -> None:
    spec = houseg.build_pool(sheet(), "Dexterity", "Stealth")
    assert spec.dice == 5
    assert spec.difficulty == 6
    assert spec.ability == "Stealth"
    assert spec.specialty == "alleys"
    assert any("specialty" in note for note in spec.notes)


def test_a_short_attribute_name_works() -> None:
    assert houseg.build_pool(sheet(), "dex", "stealth").dice == 5


def test_an_untrained_skill_raises_the_difficulty() -> None:
    spec = houseg.build_pool(sheet(), "Dexterity", "Firearms")
    assert spec.dice == 3
    assert spec.difficulty == 8
    assert any("untrained skill" in note for note in spec.notes)


def test_an_untrained_talent_is_rolled_without_penalty() -> None:
    spec = houseg.build_pool(sheet(), "Dexterity", "Alertness")
    assert (spec.dice, spec.difficulty) == (3, 6)
    assert not any("untrained" in note for note in spec.notes)


def test_an_untrained_knowledge_cannot_be_rolled() -> None:
    with pytest.raises(SheetError, match="untrained knowledges"):
        houseg.build_pool(sheet(), "Intelligence", "Academics")


def test_an_unknown_ability_lists_the_vocabulary() -> None:
    with pytest.raises(UnknownTrait) as caught:
        houseg.build_pool(sheet(), "Dexterity", "flying")
    assert "Alertness" in str(caught.value)


def test_the_workbook_typo_is_forgiven() -> None:
    spec = houseg.build_pool(sheet(), "Intelligence", "psychology")
    assert spec.ability == "Pyshcology"
    assert spec.dice == 5


def test_a_difficulty_can_be_set_and_must_be_sane() -> None:
    assert houseg.build_pool(sheet(), "Dexterity", difficulty=8).difficulty == 8
    with pytest.raises(SheetError, match="difficulty"):
        houseg.build_pool(sheet(), "Dexterity", difficulty=0)


def test_difficulty_above_ten_becomes_a_threshold() -> None:
    spec = houseg.build_pool(sheet(), "Intelligence", "Occult", difficulty=12)
    assert spec.target == 10
    assert spec.threshold == 2


def test_willpower_is_optional_and_costs_a_point() -> None:
    spec = houseg.build_pool(sheet(), "Dexterity", "Stealth", willpower=True)
    assert spec.willpower is True
    assert any("Willpower" in note for note in spec.notes)
    with pytest.raises(SheetError, match="no Willpower"):
        houseg.build_pool(
            sheet(willpower_remaining=0), "Dexterity", "Stealth", willpower=True
        )


def test_a_sheet_with_no_dice_cannot_roll() -> None:
    with pytest.raises(SheetError, match="no dice"):
        houseg.build_pool(sheet(attributes={"Dexterity": 0}), "Dexterity")


# -- resolving a pool ------------------------------------------------------


def resolve(dice: int, script: list[int], **spec_kwargs):
    spec = houseg.PoolSpec(attribute="Dexterity", dice=dice, **spec_kwargs)
    return houseg.resolve_pool(spec, Roller(ScriptedRng(*script)), character="Brannoc")


def test_successes_at_or_above_the_difficulty() -> None:
    result = resolve(3, [6, 3, 9])
    assert (result.successes, result.ones, result.net) == (2, 0, 2)
    assert result.ok is True


def test_ones_subtract_from_successes() -> None:
    result = resolve(3, [6, 1, 9])
    assert (result.successes, result.ones, result.net) == (2, 1, 1)


def test_more_ones_than_successes_is_a_botch() -> None:
    result = resolve(3, [1, 1, 2])
    assert result.botch is True
    assert result.ok is False
    assert "BOTCH" in result.render()


def test_a_difficulty_above_ten_needs_extras() -> None:
    # Difficulty 12: only tens count, and two successes are spent before anything lands.
    result = resolve(3, [10, 10, 10], difficulty=12)
    assert (result.successes, result.net) == (3, 1)
    two = resolve(2, [10, 10], difficulty=12)
    assert (two.successes, two.net, two.ok) == (2, 0, False)


def test_a_specialty_rerolls_tens() -> None:
    result = resolve(2, [10, 2, 7], specialty="alleys")
    assert result.rerolls == (7,)
    assert (result.successes, result.ones, result.net) == (2, 0, 2)


def test_a_rerolled_one_does_not_subtract() -> None:
    result = resolve(1, [10, 1], specialty="alleys")
    assert result.rerolls == (1,)
    assert (result.successes, result.ones, result.net) == (1, 0, 1)


def test_willpower_adds_a_success() -> None:
    result = resolve(2, [3, 2], willpower=True)
    assert (result.successes, result.net, result.ok) == (0, 1, True)


def test_the_rendering_reads_like_a_table_result() -> None:
    text = resolve(3, [6, 9, 1]).render()
    assert text.startswith("Brannoc rolls Dexterity at difficulty 6:")
    assert "2 successes" in text
    assert "1 one" in text
    assert "= 1 (success)" in text


def test_an_empty_pool_is_refused() -> None:
    with pytest.raises(SheetError, match="at least one die"):
        houseg.resolve_pool(
            houseg.PoolSpec(attribute="Dexterity", dice=0),
            Roller(ScriptedRng()),
            character="Brannoc",
        )


# -- trait blocks ----------------------------------------------------------


class _Cells:
    """A grid stand-in: ``text(ref)``, ``max_row`` and a ``notes`` list."""

    def __init__(self, cells: dict[str, str]) -> None:
        self.cells = cells
        self.notes: list[str] = []

    def text(self, ref: str) -> str:
        return self.cells.get(ref, "")

    @property
    def max_row(self) -> int:
        return max((int(ref[1:]) for ref in self.cells), default=0)


def test_a_background_block_stops_when_the_prose_starts() -> None:
    """Filled tabs continue below the template with Missions, wishlists and merit text."""
    grid = _Cells(
        {
            "D33": "Arsenal",
            "E33": "4.0",
            "D34": "Cipher",
            "E34": "3.0",
            "D36": "",
            "D40": "Missions",
            "E40": "Missions",
            "D41": "gm",
            "E41": "win/lost and gift",
            "D42": "Cowboy",
            "E42": "win and rage pool gifted",
        }
    )
    owned, planned = houseg._read_backgrounds(grid)
    assert [(trait.name, trait.dots) for trait in owned] == [("Arsenal", 4), ("Cipher", 3)]
    assert planned == ()


def test_a_flat_gift_keeps_its_description() -> None:
    """Some tabs put a rating beside a Gift; others put a sentence. Neither invents a value."""
    grid = _Cells(
        {
            "A33": "Mentor Skills",
            "B33": "Meditation, Melee, Stealth, Investigation, Occult",
            "A34": "Walking Fire",
            "B34": "Moving x5, Charging, Exposing x2",
            "A36": "Thanatosis",
            "B36": "1.0",
            "A37": "Alchemy",
            "B37": "1.0",
        }
    )
    owned, _ = houseg._read_gifts(grid)
    assert [(gift.name, gift.rating) for gift in owned] == [
        ("Mentor Skills", None),
        ("Walking Fire", None),
        ("Thanatosis", 1),
        ("Alchemy", 1),
    ]
    assert owned[0].description.startswith("Meditation, Melee")


def test_a_zero_rated_background_is_a_plan_not_a_trait() -> None:
    grid = _Cells({"D33": "Blood Bank", "E33": "0.0", "D34": "Cipher", "E34": "4.0"})
    owned, planned = houseg._read_backgrounds(grid)
    assert [trait.name for trait in owned] == ["Cipher"]
    assert [(gift.name, gift.rating) for gift in planned] == [("Blood Bank", 0)]


def test_a_zero_rated_gift_is_a_plan_not_a_gift() -> None:
    grid = _Cells({"A33": "Auspex", "B33": "0.0", "A34": "Thanatosis", "B34": "1.0"})
    owned, planned = houseg._read_gifts(grid)
    assert [gift.name for gift in owned] == ["Thanatosis"]
    assert [(gift.name, gift.rating) for gift in planned] == [("Auspex", 0)]


def test_a_blank_rating_is_skipped_rather_than_ending_the_block() -> None:
    grid = _Cells({"D33": "Cipher", "D34": "", "D35": "Mentor", "E35": "2.0"})
    owned, _ = houseg._read_backgrounds(grid)
    assert [(trait.name, trait.dots) for trait in owned] == [("Mentor", 2)]


def test_a_duplicate_rating_cell_is_not_a_description() -> None:
    grid = _Cells({"A33": "Thanatosis", "B33": "1.0", "C33": "1.0"})
    owned, _ = houseg._read_gifts(grid)
    assert owned[0].description == ""


def test_a_labelled_scalar_is_not_a_gift() -> None:
    """``Vampire Gen | Caitiff | 13`` is generation 13, not a Gift called Caitiff."""
    grid = _Cells({"A33": "Vampire Gen", "B33": "Caitiff", "C33": "13.0"})
    owned, _ = houseg._read_gifts(grid)
    assert owned == ()


def test_the_mission_log_is_skipped_and_reported() -> None:
    """Missions and player names sit in the gifts column; they are not Gifts."""
    grid = _Cells(
        {
            "A33": "Walking Fire",
            "B33": "Moving x5, Charging, Exposing x2",
            "A40": "name",
            "B40": "players",
            "A41": "the vat under the city",
            "B41": "Me, Driver",
            "A42": "Sabbat Party House",
            "B42": "Me, Cowboy, Hikou",
            "A43": "Unstoppable Warrior",
            "B43": "The Garou becomes permanently capable of healing all aggravated damage",
        }
    )
    owned, _ = houseg._read_gifts(grid)
    assert [gift.name for gift in owned] == ["Walking Fire", "Unstoppable Warrior"]
    assert any("mission log" in note for note in grid.notes)
    assert all("Cowboy" not in gift.name for gift in owned)


def test_the_wishlist_is_read_as_plans() -> None:
    grid = _Cells(
        {
            "D49": "Things to get (exp)",
            "E49": "Things to get (exp)",
            "D50": "Tough as nails",
            "E50": "You have an extra Bruised health level.",
            "D51": "Lucky",
            "E51": "Three times per session you can re-roll.",
            "D53": "Stamina 7",
            "E53": "Increase in stamina",
        }
    )
    planned = houseg._read_wishlist(grid)
    assert [gift.name for gift in planned] == ["Tough as nails", "Lucky", "Stamina 7"]
    assert planned[0].description.startswith("You have an extra")


# -- gifts are counted, not priced -----------------------------------------


def test_tiers_follow_the_rules_document() -> None:
    assert [houseg.gift_tier(n) for n in (0, 9)] == ["Novice", "Novice"]
    assert [houseg.gift_tier(n) for n in (10, 19)] == ["Seasoned", "Seasoned"]
    assert [houseg.gift_tier(n) for n in (20, 29)] == ["High Seasoned", "High Seasoned"]
    # 30+ without the Template is Very High Seasoned; Veteran is a status, not a count.
    assert [houseg.gift_tier(n) for n in (30, 99)] == [
        "Very High Seasoned",
        "Very High Seasoned",
    ]
    assert houseg.gift_tier(0, veteran=True) == "Veteran"
    assert houseg.gift_tier(45, veteran=True) == "Veteran"


def test_the_balance_rule_warns_past_five_gifts() -> None:
    assert houseg.balance_warnings({"Molly": 2, "Robert": 7}) == ()
    warnings = houseg.balance_warnings({"Molly": 2, "Robert": 9})
    assert len(warnings) == 1
    assert "Molly" in warnings[0] and "Robert" in warnings[0]
    assert "7 apart" in warnings[0]


def test_the_balance_rule_compares_every_pair() -> None:
    warnings = houseg.balance_warnings({"A": 0, "B": 6, "C": 12})
    assert len(warnings) == 3

    with pytest.raises(ValueError, match="character name"):
        Sheet(name="  ", system="house-games")
    with pytest.raises(ValueError, match="system"):
        Sheet(name="Brannoc", system="")



# -- the economy, as written in the rules ----------------------------------


def test_advancement_costs_match_the_document() -> None:
    cost = houseg.advancement_cost
    assert cost("attribute", 4) == 16  # Current Rating x4
    assert cost("ability", 0) == 3  # 3 for the first rank
    assert cost("ability", 1) == 2  # then Current Rating x2
    assert cost("ability", 4) == 8
    assert cost("background", 0) == 7  # 7 for the first rank
    assert cost("background", 5) == 15  # then Current Rating x3
    assert cost("virtue", 3) == 6
    assert cost("willpower", 9) == 9  # Current Rating x1
    assert cost("pool", 4) == 8
    assert cost("power", 2) == 12  # Current Rating x6
    assert cost("power", 2, flawed=True) == 10  # x5 when dramatically flawed
    assert cost("magic", 1) == 7  # Current Rating x7
    assert cost("merit", rating=4) == 12  # Rating x3
    assert cost("flaw", rating=3) == 9  # Rating x3 to buy off
    assert cost("maneuver") == 2
    assert cost("ritual") == 2


def test_an_unknown_cost_kind_is_refused_rather_than_guessed() -> None:
    with pytest.raises(ValueError, match="unknown advancement kind"):
        houseg.advancement_cost("spaceship", 1)
    with pytest.raises(ValueError, match="unknown freebie kind"):
        houseg.freebie_cost("spaceship")


def test_freebie_costs_match_the_creation_table() -> None:
    assert houseg.freebie_cost("attribute") == 5
    assert houseg.freebie_cost("ability") == 2
    assert houseg.freebie_cost("virtue") == 2
    assert houseg.freebie_cost("morality") == 2
    assert houseg.freebie_cost("background") == 1
    assert houseg.freebie_cost("willpower") == 1


def test_the_reward_for_a_game_is_one_gift_and_ten_xp() -> None:
    # "10 XP and a Gift if they win. 5 XP but no Gift if they lose but survive."
    assert (houseg.XP_WIN, houseg.XP_LOSS) == (10, 5)
    assert houseg.GIFTS_PER_WIN == 1
    assert houseg.GM_XP_PER_GAME == 10


def test_the_caps_match_the_trait_maximums_section() -> None:
    assert houseg.TRAIT_CAP == 5
    assert houseg.TRACKER_CAP == 10  # Morality and Willpower
    assert houseg.BACKGROUND_CAP == 5
    assert houseg.BACKGROUND_CAP_VETERAN == 8
    assert houseg.BACKGROUND_CAP_GIFT == 10

