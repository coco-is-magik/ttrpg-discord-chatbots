"""The persona harness: the numbers behind "does this sound like him?".

One test asserts the committed material passes every check. The rest pin the helpers, because each of
them encodes a judgement that was wrong on the first attempt -- the blunt cold-word list flagged advice
about hardware, and the beat rule rejected a question at the end of a line.
"""

from __future__ import annotations

from pathlib import Path

from ttrpg_chatbots.bots.persona_harness import (
    COLD_ADJECTIVES,
    _cold_phrases,
    _declaratives,
    measure,
    sample_render,
)
from ttrpg_chatbots.decide import persona_fit

DATA = Path("examples/friends_world")
ROSTER = Path("examples/bots.example.json")


def test_the_committed_material_passes_every_check() -> None:
    report = measure("friend-a", data=DATA, roster=ROSTER)

    failures = "; ".join(finding.describe() for finding in report.failures)
    assert report.ok, f"the material does not match the brief: {failures}"


def test_the_report_carries_the_numbers_a_person_would_want() -> None:
    report = measure("friend-a", data=DATA, roster=ROSTER)

    assert report.stats["subjects"] >= 30, "his interests need more than a question each"
    assert report.stats["median_words"] <= 12, "the old corpus was 7 words median but 51% two sentences"
    assert report.stats["distinct_pct"] >= 90, "lines should not repeat inside the material"


def test_every_check_has_a_question_a_person_could_answer() -> None:
    """The report is read by a person deciding what to edit, so each line has to be legible."""
    report = measure("friend-a", data=DATA, roster=ROSTER)

    assert len(report.findings) >= 10
    for finding in report.findings:
        assert finding.check == finding.check.lower() and " " not in finding.check
        assert finding.question and finding.question[0].islower()
        assert finding.question[-1].isalnum() or finding.question.endswith("?")


class TestSampleRender:
    def test_a_placeholder_becomes_the_shape_of_thing_it_holds(self) -> None:
        assert sample_render("{hook}. {event_phrase}") == (
            "sanding a rifle stock. the season opener is in six days"
        )

    def test_an_unknown_placeholder_is_long_enough_not_to_look_like_a_beat(self) -> None:
        rendered = sample_render("not much. {something_new}")

        assert "{something_new}" not in rendered
        assert not persona_fit.read(rendered).reasons, "a template is judged on its own words"


class TestDeclaratives:
    def test_a_trailing_question_is_not_a_stacked_statement(self) -> None:
        assert _declaratives("morning. how is the fence?") == 1

    def test_two_statements_count_as_two(self) -> None:
        assert _declaratives("it got comfortable. it got lazy") == 2

    def test_a_single_sentence_is_one(self) -> None:
        assert _declaratives("sanding a rifle stock") == 1


class TestColdPhrases:
    def test_contempt_aimed_at_the_person_is_caught(self) -> None:
        assert _cold_phrases("you are boring") == ("you are boring", "boring")

    def test_advice_about_a_thing_is_not(self) -> None:
        """Measured: the blunt list flagged 'something boring and fixable', which is advice."""
        assert _cold_phrases("something boring and fixable") == ()

    def test_a_bare_adjective_is_only_cold_next_to_the_person(self) -> None:
        for adjective in COLD_ADJECTIVES:
            assert _cold_phrases(f"that is {adjective}") in ((), (f"that is {adjective}",))
            assert _cold_phrases(f"you are {adjective}")

    def test_a_directed_phrase_is_caught_without_the_word_you(self) -> None:
        assert _cold_phrases("shut up") == ("shut up",)


class TestTheRegisterRules:
    def test_a_trailing_question_is_a_hand_back_not_a_beat(self) -> None:
        assert persona_fit.read("morning. how is the fence?").ok

    def test_backchannel_is_not_a_punchline(self) -> None:
        assert persona_fit.read("ha. same").ok
        assert persona_fit.read("ugh. yeah").ok

    def test_a_statement_that_lands_and_stops_is_still_a_beat(self) -> None:
        fit = persona_fit.read("the truck failed over a bulb. i replaced it last month")

        assert not fit.ok
        assert "ends on a beat" in fit.reasons

    def test_a_story_is_allowed_to_explain_itself_and_land(self) -> None:
        line = "my grandfather's axe hung in the garage for twenty years. the handle was rotten"

        assert not persona_fit.read(line).ok
        assert persona_fit.read(line, story=True).ok
