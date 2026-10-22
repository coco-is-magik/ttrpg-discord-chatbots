"""The spoken form: what a voice should read, which is not what a person should read.

The bug that started this: ``$250 watch`` was read as "dollar sign two hundred fifty watch". The fix is
not one regex but five modules and, more importantly, an order -- so the order is tested directly.
"""

from __future__ import annotations

import pytest

from ttrpg_chatbots.tts.spoken import say
from ttrpg_chatbots.tts.spoken import numbers, pipeline, symbols
from ttrpg_chatbots.tts.spoken.wrap import SpokenSynthesizer, unwrap, wrap


class TestMoney:
    def test_the_reported_bug(self) -> None:
        assert say("$250 watch") == "two hundred fifty dollars watch"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("$1", "one dollar"),
            ("$2", "two dollars"),
            ("$1.50", "one dollar and fifty cents"),
            ("$0.50", "fifty cents"),
            ("$1,200", "one thousand two hundred dollars"),
            ("£250", "two hundred fifty pounds"),
            ("€3", "three euros"),
            ("he paid $250 for it", "he paid two hundred fifty dollars for it"),
        ],
    )
    def test_amounts(self, text: str, expected: str) -> None:
        assert say(text) == expected


class TestSymbols:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("10% off", "ten percent off"),
            ("50/50", "fifty fifty"),
            ("#1 pick", "number one pick"),
            ("20°C", "twenty degrees Celsius"),
            ("100°F", "one hundred degrees Fahrenheit"),
            ("AT&T", "A T and T"),
            ("a & b", "a and b"),
        ],
    )
    def test_symbols_become_words(self, text: str, expected: str) -> None:
        assert say(text) == expected

    def test_a_slash_inside_a_word_is_left_alone(self) -> None:
        assert say("and/or") == "and/or"

    def test_a_symbol_glued_to_a_number_still_gets_a_space(self) -> None:
        # Without the space the number pass cannot see the digits, and this was measured as
        # "10percent off". Checked on the symbol pass itself, because `say` has already turned the
        # digits into words by the time it returns -- and its output carries padding spaces on
        # purpose, which the pipeline collapses at the end.
        spoken = " ".join(symbols.expand("10% off").split())
        assert spoken == "10 percent off"


class TestNumbers:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("250", "two hundred fifty"),
            ("1,200", "one thousand two hundred"),
            ("1,000,000", "one million"),
            ("21", "twenty-one"),
            ("100", "one hundred"),
            ("0", "zero"),
            ("1.5", "one point five"),
            ("3.05", "three point zero five"),
            ("21st", "twenty-first"),
            ("2nd", "second"),
            ("3rd", "third"),
            ("11th", "eleventh"),
            ("3:30", "three thirty"),
            ("3:00", "three o'clock"),
            ("4:05", "four oh five"),
            ("3pm", "three p m"),
            ("3:30 pm", "three thirty p m"),
            ("a 3-5 year window", "a three to five year window"),
        ],
    )
    def test_numbers_as_they_are_said(self, text: str, expected: str) -> None:
        assert say(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("1984", "nineteen eighty-four"),
            ("1905", "nineteen oh five"),
            ("2001", "twenty oh one"),
            ("1900", "nineteen hundred"),
            ("1100", "eleven hundred"),
        ],
    )
    def test_a_four_digit_year_is_a_year(self, text: str, expected: str) -> None:
        assert say(text) == expected

    def test_a_clock_time_with_a_meridiem_keeps_them_together(self) -> None:
        # The bare clock pattern used to eat "3:30" and orphan the "pm" (measured: "three thirty pm").
        assert numbers.expand("3:30 pm") == "three thirty p m"

    def test_ordinals_past_a_hundred(self) -> None:
        assert numbers.ordinal(121) == "one hundred twenty-first"
        assert numbers.ordinal(100) == "one hundredth"

    def test_negative_numbers(self) -> None:
        assert numbers.words(-5) == "minus five"


class TestAbbreviations:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Dr. Smith", "Doctor Smith"),
            ("Mr. and Mrs. Jones", "Mister and Missus Jones"),
            ("A vs. B", "A versus B"),
            ("and so on, etc.", "and so on, et cetera"),
            ("e.g. this", "for example this"),
            ("i.e. that", "that is that"),
            ("No. 5", "number five"),  # numbers run before abbreviations, so the 5 is already spoken
        ],
    )
    def test_abbreviations(self, text: str, expected: str) -> None:
        assert say(text) == expected

    def test_st_is_a_saint_before_a_name_and_a_street_otherwise(self) -> None:
        assert "Saint Louis" in say("St. Louis")
        assert "Main Street" in say("Main St.")

    def test_a_multi_word_abbreviation_is_not_half_replaced(self) -> None:
        assert say("et al.") == "et al"


class TestAcronyms:
    def test_capitals_are_spelled_out(self) -> None:
        assert say("NCAA") == "N C A A"
        assert say("TTRPG") == "T T R P G"

    def test_words_that_are_said_as_words_are_left_alone(self) -> None:
        assert say("NASA") == "NASA"

    def test_short_forms_people_say_as_letters_are_left_alone(self) -> None:
        assert say("TV and OK") == "TV and OK"

    def test_a_single_letter_is_a_word(self) -> None:
        assert say("I am") == "I am"


class TestPipeline:
    def test_the_order_is_data(self) -> None:
        assert [name for name, _ in pipeline.STEPS] == [
            "money",
            "symbols",
            "numbers",
            "abbreviations",
            "acronyms",
        ]

    def test_money_runs_before_symbols(self) -> None:
        """The whole point: if symbols ran first, $250 would become "dollars two hundred fifty"."""
        assert say("$250") == "two hundred fifty dollars"

    def test_symbols_run_before_numbers(self) -> None:
        assert say("10%") == "ten percent"

    def test_plain_text_is_unchanged(self) -> None:
        text = "messing with an old computer"
        assert say(text) == text

    def test_whitespace_is_tidied(self) -> None:
        assert say("  $250   watch  ") == "two hundred fifty dollars watch"

    def test_empty_text_is_returned_not_raised(self) -> None:
        assert say("   ") == "   "

    def test_it_is_idempotent_for_already_spoken_text(self) -> None:
        once = say("$250 watch")
        assert say(once) == once


class TestWrapping:
    def test_wrapping_is_idempotent(self) -> None:
        class Engine:
            name = "fake"

            def synthesize(self, text):
                return text

        engine = Engine()
        once = wrap(engine)
        assert wrap(once) is once
        assert unwrap(once) is engine

    def test_an_unwrapped_engine_is_returned_as_is(self) -> None:
        engine = object()
        assert unwrap(engine) is engine

    def test_the_engine_receives_the_spoken_form(self) -> None:
        """What Discord plays is the spoken form, and the engine never sees the symbols."""

        class Engine:
            name = "fake"

            def __init__(self) -> None:
                self.seen: list[str] = []

            def synthesize(self, text):
                self.seen.append(text)
                return text

        engine = Engine()
        SpokenSynthesizer(engine).synthesize("$250 watch")

        assert engine.seen == ["two hundred fifty dollars watch"]

    def test_engine_specific_attributes_still_reach_the_engine(self) -> None:
        class Engine:
            name = "fake"
            words_per_minute = 165

        assert SpokenSynthesizer(Engine()).words_per_minute == 165
