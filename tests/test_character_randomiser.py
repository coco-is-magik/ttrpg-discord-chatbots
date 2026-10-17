"""Random characters by legal budgets, and assignment of finished ones."""

from __future__ import annotations

import random

import pytest

from ttrpg_chatbots.character.randomiser import (
    assign_premade,
    pool_by_system,
    random_character,
    random_mechanics,
)
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import Interview, Question, Questionnaire
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Ability, Sheet

CLOCK = "2026-10-17T00:00:00+00:00"
FORM = Questionnaire(name="test", sections=(("Warmup", ("Where from?",)),))


def groups(sheet: Sheet) -> list[int]:
    spent = sorted(
        sum(sheet.attributes[name] for name in names) - 3
        for names in houseg.ATTRIBUTE_GROUPS.values()
    )
    return spent


def test_random_mechanics_always_spend_the_budgets() -> None:
    for seed in range(50):
        sheet = random_mechanics(random.Random(seed), name="Rolled")
        assert groups(sheet) == [3, 5, 7]
        totals: dict[str, int] = {}
        for ability in sheet.abilities.values():
            totals[ability.category] = totals.get(ability.category, 0) + ability.rank
        assert sorted(totals.values()) == [5, 9, 13]
        assert sum(sheet.virtues.values()) - 3 == houseg.VIRTUE_POINTS
        assert sum(trait.dots for trait in sheet.backgrounds) == houseg.BACKGROUND_POINTS


def test_random_mechanics_respect_the_trait_cap() -> None:
    for seed in range(30):
        sheet = random_mechanics(random.Random(seed))
        assert max(sheet.attributes.values()) <= houseg.MAX_CREATION_TRAIT
        assert max(a.rank for a in sheet.abilities.values()) <= houseg.MAX_CREATION_TRAIT
        assert max(sheet.virtues.values()) <= houseg.MAX_CREATION_TRAIT


def test_random_mechanics_derive_trackers_from_virtues() -> None:
    sheet = random_mechanics(random.Random(7))
    assert sheet.willpower == sheet.virtues["Courage"]
    assert sheet.willpower_remaining == sheet.virtues["Courage"]
    assert sheet.morality == (
        sheet.virtues["Conscience/Conviction"] + sheet.virtues["Self-Control/Instinct"]
    )


def test_random_mechanics_are_reproducible_and_varied() -> None:
    first = random_mechanics(random.Random(3)).attributes
    same = random_mechanics(random.Random(3)).attributes
    other = random_mechanics(random.Random(4)).attributes
    assert first == same
    assert first != other


def test_random_mechanics_use_the_whole_trait_list() -> None:
    abilities = set()
    for seed in range(20):
        abilities.update(random_mechanics(random.Random(seed)).abilities)
    assert abilities == set(houseg.attribute_names() + ("Alertness",)) or len(abilities) > 20


def test_random_character_has_mechanics_but_no_prose() -> None:
    character = random_character(random.Random(1), name="Rand", questionnaire=FORM)
    assert character.sheet.name == "Rand"
    assert character.interview is not None
    assert character.interview.answered == 0
    assert character.interview_complete is False
    assert character.ready is False
    assert [event.kind for event in character.history] == ["created"]


def test_random_character_without_a_form_has_no_interview() -> None:
    character = random_character(random.Random(1), name="Rand")
    assert character.interview is None
    assert character.ready is False


def test_a_biased_rng_still_cannot_exceed_the_cap() -> None:
    """A random source that always picks the first option must still respect the cap."""

    class Stuck(random.Random):
        def choice(self, seq):
            return seq[0]

    sheet = random_mechanics(Stuck(0), name="Stuck")
    assert max(sheet.attributes.values()) <= houseg.MAX_CREATION_TRAIT
    assert groups(sheet) == [3, 5, 7]
    # Always picking the first legal trait fills it to the cap (4 spent), then moves on.
    physical = sorted(sheet.attributes[name] for name in houseg.ATTRIBUTE_GROUPS["Physical"])
    assert physical == [1, 4, 5]


def test_an_impossible_budget_is_reported_not_hidden() -> None:
    class TooSmall(random.Random):
        def choice(self, seq):
            return seq[0]

    from ttrpg_chatbots.character.randomiser import _spread

    with pytest.raises(CharacterError, match="cannot spend"):
        _spread(TooSmall(0), ("a", "b"), 9, cap=2)


def test_assignment_picks_from_the_pool_and_logs_it() -> None:
    pool = [_ready("Ann"), _ready("Bob"), _ready("Cat")]
    chosen = assign_premade(random.Random(1), pool, clock=lambda: CLOCK)
    assert chosen.name in {"Ann", "Bob", "Cat"}
    assert chosen.ready is True
    assert chosen.history[-1].kind == "assigned"
    assert chosen.created == CLOCK


def test_assignment_is_reproducible() -> None:
    pool = [_ready(name) for name in ("Ann", "Bob", "Cat", "Dee")]
    first = assign_premade(random.Random(9), pool)
    again = assign_premade(random.Random(9), pool)
    assert first.name == again.name


def test_an_empty_pool_is_an_error() -> None:
    with pytest.raises(CharacterError, match="no characters"):
        assign_premade(random.Random(1), [])


def test_renaming_keeps_the_answers() -> None:
    original = _ready("Ann")
    renamed = assign_premade(random.Random(1), [original], rename="Zed")
    assert renamed.name == "Zed"
    assert renamed.interview.character == "Zed"
    assert renamed.digest == original.digest  # answers unchanged
    assert renamed.ready is True
    assert renamed.id == "zed"


def test_the_pool_only_offers_usable_characters() -> None:
    ready = _ready("Ready")
    unfinished = Character(sheet=ready.sheet, interview=_interview("Ready", ""))
    other_system = Character(sheet=Sheet(name="Elsewhere", system="shadowrun"), interview=None)
    assert pool_by_system([ready, unfinished, other_system]) == (ready,)


# -- helpers ---------------------------------------------------------------


def _interview(name: str, answer: str = "A vat.") -> Interview:
    return Interview(
        character=name, questions=(Question(prompt="Where from?", answer=answer),)
    )


def _ready(name: str) -> Character:
    sheet = Sheet(
        name=name,
        system=houseg.SYSTEM,
        attributes={"Dexterity": 2},
        abilities={"Stealth": Ability("Stealth", rank=1)},
    )
    return Character(sheet=sheet, interview=_interview(name)).seal()
