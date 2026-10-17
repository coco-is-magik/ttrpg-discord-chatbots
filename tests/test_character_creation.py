"""The creation wizard: interview first, then budgets, then a sealed character."""

from __future__ import annotations

import pytest

from character_support import MECHANICS, ScriptedPrompter, prompter, script
from ttrpg_chatbots.character import creation
from ttrpg_chatbots.character.creation import start_character
from ttrpg_chatbots.character.prompting import PrompterError, ask_int, ask_text
from ttrpg_chatbots.sheets.interview import Questionnaire

FORM = Questionnaire(name="test", sections=(("Warmup", ("Where from?", "Why leave?")),))
CLOCK = "2026-10-17T00:00:00+00:00"


def build(**kwargs):
    return start_character(prompter(name="Test Subject"), FORM, clock=lambda: CLOCK, **kwargs)


def test_a_complete_run_produces_a_sealed_character() -> None:
    character = build()
    assert character.name == "Test Subject"
    assert character.created == CLOCK
    assert character.sealed is True
    assert character.ready is True
    assert [event.kind for event in character.history] == ["created", "sealed"]
    assert character.interview.answered == 2


def test_the_interview_answers_are_kept_in_order() -> None:
    character = build()
    assert [question.answer for question in character.interview.questions] == [
        "A vat under New York.",
        "Boredom, mostly.",
    ]
    assert character.interview.questions[0].section == "Warmup"


def test_attribute_and_ability_budgets_are_respected() -> None:
    sheet = build().sheet
    groups = {
        "physical": ("Strength", "Dexterity", "Stamina"),
        "social": ("Charisma", "Manipulation", "Appearance"),
        "mental": ("Perception", "Intelligence", "Wits"),
    }
    # Each attribute starts at 1, so a group's spend is its total minus three.
    spent = sorted(
        sum(sheet.attributes[name] for name in names) - 3 for names in groups.values()
    )
    assert spent == [3, 5, 7]

    totals: dict[str, int] = {}
    for ability in sheet.abilities.values():
        totals[ability.category] = totals.get(ability.category, 0) + ability.rank
    assert sorted(totals.values()) == [5, 9, 13]
    assert all(0 <= ability.rank <= 5 for ability in sheet.abilities.values())


def test_trackers_are_derived_from_virtues() -> None:
    sheet = build().sheet
    virtues = sheet.virtues
    assert sheet.willpower == virtues["Courage"]
    assert sheet.willpower_remaining == virtues["Courage"]
    assert sheet.morality == (
        virtues["Conscience/Conviction"] + virtues["Self-Control/Instinct"]
    )
    assert sum(virtues.values()) - 3 == 7


def test_backgrounds_powers_and_health_are_recorded() -> None:
    sheet = build().sheet
    assert [(trait.name, trait.dots) for trait in sheet.backgrounds] == [
        ("Mentor", 3),
        ("Contacts", 2),
    ]
    assert [(trait.name, trait.dots) for trait in sheet.powers] == [("Auspex", 2)]
    assert sheet.health[0] == "Unharmed"
    assert len(sheet.health) == 8


def test_a_supplied_name_skips_the_name_prompt() -> None:
    speaker = prompter()
    start_character(speaker, FORM, name="Given", clock=lambda: CLOCK)
    assert not any("Character name" in prompt for prompt in speaker.asked)


def test_a_missing_name_is_asked_for() -> None:
    speaker = ScriptedPrompter(*script(name="Test Subject"))
    character = start_character(speaker, FORM, clock=lambda: CLOCK)
    assert character.name == "Test Subject"
    assert speaker.asked[0] == "Character name?"


def test_a_blank_interview_answer_is_asked_again() -> None:
    speaker = ScriptedPrompter("Test Subject", "", "A vat.", "Boredom.", *MECHANICS)
    character = start_character(speaker, FORM, clock=lambda: CLOCK)
    assert character.interview.questions[0].answer == "A vat."
    assert any("blank answer" in line for line in speaker.said)


def test_an_illegal_budget_is_reported_and_retried() -> None:
    speaker = ScriptedPrompter(
        "Test Subject", "A.", "B.", "5", "5", "5", *MECHANICS
    )
    character = start_character(speaker, FORM, clock=lambda: CLOCK)
    assert sum(character.sheet.attributes.values()) == 24
    assert any("spent" in line and "available" in line for line in speaker.said)


def test_repeated_illegal_budgets_give_up(monkeypatch) -> None:
    monkeypatch.setattr(creation, "GROUP_ATTEMPTS", 1)
    speaker = ScriptedPrompter("Test Subject", "A.", "B.", "5", "5", "5")
    with pytest.raises(PrompterError, match="legal budget"):
        start_character(speaker, FORM, clock=lambda: CLOCK)


def test_sealing_can_be_deferred() -> None:
    character = build(seal=False)
    assert character.sealed is False
    assert character.ready is False
    assert [event.kind for event in character.history] == ["created"]
    assert character.interview.complete is True


def test_specialties_reach_the_sheet() -> None:
    answers = ["Test Subject", "A.", "B."]
    answers += ["4", "4", "2", "3", "3", "2", "2", "2", "2"]  # attributes 7/5/3
    # Every ability value is asked before any specialty, group by group.
    answers += ["4", "4", "4", "1", "0", "0", "0", "0", "0", "0"]  # Talents: 13
    answers += ["4", "3", "2", "0", "0", "0", "0", "0", "0", "0"]  # Skills: 9
    answers += ["3", "2", "0", "0", "0", "0", "0", "0", "0", "0"]  # Knowledges: 5
    answers += ["sharp eyes", "reading people", "hanging on"]  # talent specialties
    answers += ["clean kills"]  # Animal Ken is rank 4
    answers += ["4", "2", "4"]  # Virtues: 7
    answers += ["Mentor", "5", "", "Auspex", "1", ""]
    character = start_character(ScriptedPrompter(*answers), FORM, clock=lambda: CLOCK)
    specialties = {
        ability.name: ability.specialty
        for ability in character.sheet.abilities.values()
        if ability.specialty
    }
    assert specialties == {
        "Alertness": "sharp eyes",
        "Athletics": "reading people",
        "Brawl": "hanging on",
        "Animal Ken": "clean kills",
    }


def test_a_specialty_may_be_left_blank() -> None:
    answers = ["Test Subject", "A.", "B."]
    answers += ["4", "4", "2", "3", "3", "2", "2", "2", "2"]
    answers += ["4", "4", "4", "1", "0", "0", "0", "0", "0", "0"]
    answers += ["4", "3", "2", "0", "0", "0", "0", "0", "0", "0"]
    answers += ["3", "2", "0", "0", "0", "0", "0", "0", "0", "0"]
    answers += ["", "", "", ""]  # four blank specialties
    answers += ["4", "2", "4"]
    answers += ["Mentor", "5", "", "Auspex", "1", ""]
    character = start_character(ScriptedPrompter(*answers), FORM, clock=lambda: CLOCK)
    assert all(not ability.specialty for ability in character.sheet.abilities.values())


# -- prompting helpers -----------------------------------------------------


def test_ask_int_takes_a_default_on_a_blank_line() -> None:
    assert ask_int(ScriptedPrompter(""), "n?", default=3) == 3


def test_ask_int_rejects_nonsense_and_out_of_range() -> None:
    speaker = ScriptedPrompter("banana", "99", "4")
    assert ask_int(speaker, "n?", low=1, high=5) == 4
    assert any("not a whole number" in line for line in speaker.said)
    assert any("out of range" in line for line in speaker.said)


def test_ask_int_gives_up_eventually() -> None:
    with pytest.raises(PrompterError, match="unusable answers"):
        ask_int(ScriptedPrompter("x", "y", "z"), "n?")


def test_ask_text_needs_something() -> None:
    speaker = ScriptedPrompter("  ", "  a real answer  ")
    assert ask_text(speaker, "q?") == "a real answer"
    with pytest.raises(PrompterError, match="no answer"):
        ask_text(ScriptedPrompter("", "", ""), "q?")


def test_an_empty_form_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one section"):
        Questionnaire(name="empty")

