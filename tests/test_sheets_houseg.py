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
        powers={"Auspex": 2},
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
    assert [trait.name for trait in character.powers] == ["Auspex"]
    assert [trait.name for trait in character.backgrounds] == ["Mentor"]
    assert character.meta["player"] == "Dan"
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


def test_several_powers_and_backgrounds_are_read(tmp_path) -> None:
    character = loaded(
        tmp_path,
        powers={"Auspex": 2, "Celerity": 1},
        backgrounds={"Mentor": 3, "Contacts": 2},
    )
    assert [trait.name for trait in character.powers] == ["Auspex", "Celerity"]
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

