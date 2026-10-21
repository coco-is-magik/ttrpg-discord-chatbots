"""Rolling a check from a sheet: the pool, the wound penalty, and Willpower."""

from __future__ import annotations

import random

import pytest

from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Ability, Sheet, Trait
from ttrpg_chatbots.sheetportal.checks import CheckError, roll_check, spend_willpower


def sheet(**kwargs) -> Sheet:
    base = dict(
        name="Ailis",
        system="house-games",
        attributes={
            "Strength": 1,
            "Dexterity": 4,
            "Stamina": 2,
            "Charisma": 2,
            "Manipulation": 2,
            "Appearance": 2,
            "Perception": 3,
            "Intelligence": 5,
            "Wits": 2,
        },
        abilities={
            "Stealth": Ability("Stealth", rank=3, category="skill"),
            "Brawl": Ability("Brawl", rank=2, category="talent"),
            "Occult": Ability("Occult", rank=4, category="knowledge", specialty="rituals"),
        },
        virtues={"Courage": 3},
        willpower=3,
        willpower_remaining=3,
        health=houseg.HEALTH_LEVELS,
    )
    base.update(kwargs)
    return Sheet(**base)


def seeded(seed: int = 7) -> Roller:
    return Roller(random.Random(seed))


# -- the pool --------------------------------------------------------------


def test_a_check_is_attribute_plus_ability() -> None:
    outcome = roll_check(sheet(), "Stealth", roller=seeded())
    assert outcome.spec.attribute == "Dexterity"
    assert outcome.spec.ability == "Stealth"
    assert outcome.spec.dice == 7  # Dexterity 4 + Stealth 3
    assert outcome.spec.difficulty == houseg.DEFAULT_DIFFICULTY


def test_the_pairing_comes_from_the_ability_not_the_caller() -> None:
    assert roll_check(sheet(), "Brawl", roller=seeded()).spec.attribute == "Strength"
    assert roll_check(sheet(), "Occult", roller=seeded()).spec.attribute == "Intelligence"


def test_an_explicit_attribute_overrides_the_pairing() -> None:
    outcome = roll_check(sheet(), "Brawl", attribute="Stamina", roller=seeded())
    assert outcome.spec.attribute == "Stamina"
    assert outcome.spec.dice == 4  # Stamina 2 + Brawl 2
    assert outcome.guessed_attribute is False


def test_an_unmapped_ability_falls_back_and_says_so() -> None:
    strange = sheet(abilities={"Fishing": Ability("Fishing", rank=1, category="skill")})
    outcome = roll_check(strange, "Fishing", roller=seeded())
    assert outcome.guessed_attribute is True
    assert "attribute guessed" in outcome.render()


def test_a_missing_ability_is_refused_with_the_known_list() -> None:
    with pytest.raises(CheckError, match="no ability called 'Sailing'"):
        roll_check(sheet(), "Sailing")


# -- wound penalties -------------------------------------------------------


def test_being_hurt_raises_the_difficulty() -> None:
    hurt = sheet(meta={"health_current": 4})  # Wounded (-2)
    outcome = roll_check(hurt, "Stealth", roller=seeded())
    assert outcome.wound == 2
    assert outcome.spec.difficulty == houseg.DEFAULT_DIFFICULTY + 2
    assert "wound penalty" in outcome.render()  # named in the pool notes)


def test_the_deepest_penalty_reached_is_the_one_that_applies() -> None:
    # Mauled (-2) is deeper than Wounded (-2)? No: the worst numbered penalty on the way down.
    deeper = sheet(meta={"health_current": 6})  # Crippled (-5)
    assert roll_check(deeper, "Stealth", roller=seeded()).wound == 5


def test_an_unhurt_character_has_no_penalty() -> None:
    assert roll_check(sheet(), "Stealth", roller=seeded()).wound == 0
    assert roll_check(sheet(meta={"health_current": 1}), "Stealth", roller=seeded()).wound == 0


# -- willpower -------------------------------------------------------------


def test_willpower_adds_a_success_and_is_spent() -> None:
    plain = roll_check(sheet(), "Stealth", roller=seeded(11))
    boosted = roll_check(sheet(), "Stealth", willpower=True, roller=seeded(11))
    assert boosted.result.net == plain.result.net + 1
    assert boosted.sheet.willpower_remaining == 2
    assert boosted.willpower_spent == 1


def test_willpower_cannot_be_spent_when_none_is_left() -> None:
    spent = sheet(willpower_remaining=0)
    with pytest.raises(Exception, match="no Willpower"):
        roll_check(spent, "Stealth", willpower=True, roller=seeded())


def test_spending_willpower_bare_leaves_the_roll_alone() -> None:
    after = spend_willpower(sheet(), 2)
    assert after.willpower_remaining == 1
    assert after.willpower == 3
    with pytest.raises(CheckError, match="not 5"):
        spend_willpower(sheet(), 5)


def test_a_rank_zero_knowledge_cannot_be_rolled() -> None:
    untrained = sheet(abilities={"Occult": Ability("Occult", rank=0, category="knowledge")})
    with pytest.raises(Exception, match="untrained knowledges"):
        roll_check(untrained, "Occult", roller=seeded())


def test_an_untrained_skill_raises_the_difficulty_and_says_why() -> None:
    green = sheet(abilities={"Stealth": Ability("Stealth", rank=0, category="skill")})
    outcome = roll_check(green, "Stealth", roller=seeded())
    assert outcome.spec.difficulty == houseg.DEFAULT_DIFFICULTY + houseg.UNSKILLED_PENALTY
    assert "untrained skill" in outcome.render()


def test_a_specialty_rerolls_ten(monkeypatch) -> None:
    outcome = roll_check(sheet(), "Occult", roller=seeded(3))
    assert outcome.spec.specialty == "rituals"
    assert "specialty" in outcome.render()
