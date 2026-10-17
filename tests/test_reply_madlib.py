import pytest

from ttrpg_chatbots.reply import madlib

VALUES = {"subject": "the Sunken Crown", "speaker": "Tav", "fact": "It is tide-iron."}


def test_fills_every_slot() -> None:
    assert madlib.render("{subject}! {fact}", VALUES) == "the Sunken Crown! It is tide-iron."


def test_leaves_text_without_slots_alone() -> None:
    assert madlib.render("Nothing to fill here.", VALUES) == "Nothing to fill here."


def test_double_braces_are_literal() -> None:
    assert madlib.render("{{subject}} is not a slot", VALUES) == "{subject} is not a slot"


def test_missing_slot_raises_rather_than_leaking_a_placeholder() -> None:
    with pytest.raises(madlib.MissingSlot, match="place"):
        madlib.render("You mean {place}?", VALUES)


def test_non_strict_mode_drops_the_placeholder() -> None:
    assert madlib.render("You mean {place}?", VALUES, strict=False) == "You mean ?"


def test_empty_value_counts_as_missing() -> None:
    with pytest.raises(madlib.MissingSlot):
        madlib.render("{subject}", {"subject": "   "})


def test_values_with_braces_are_rejected() -> None:
    """Dataset content must not be able to inject a placeholder."""
    with pytest.raises(ValueError, match="braces"):
        madlib.render("{subject}", {"subject": "{fact}"})


def test_whitespace_is_normalised() -> None:
    assert madlib.render("a  {subject}\n\tb", VALUES) == "a the Sunken Crown b"


def test_slots_in_reports_unique_names_in_order() -> None:
    assert madlib.slots_in("{subject} and {fact} and {subject}") == ("subject", "fact")


def test_slots_in_ignores_escapes() -> None:
    assert madlib.slots_in("{{literal}} then {subject}") == ("subject",)


def test_lowercase_and_snake_case_slots_are_recognised() -> None:
    assert madlib.render("{tide_gates_2}", {"tide_gates_2": "south"}) == "south"


@pytest.mark.parametrize("template", ["{1nvalid}", "{with space}", "{unclosed"])
def test_malformed_placeholders_are_left_alone(template: str) -> None:
    assert madlib.render(template, {}) == template
