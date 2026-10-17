"""The character questionnaire: pairing answers, and insisting on completeness."""

from __future__ import annotations

from pathlib import Path

import pytest

from sheets_support import questionnaire, questionnaire_workbook, write_workbook
from ttrpg_chatbots.sheets.interview import Interview, character_from_tab, read_interview
from ttrpg_chatbots.sheets.types import SheetError, UnknownTrait
from ttrpg_chatbots.sheets.xlsx import read_grid

REAL = Path(__file__).resolve().parents[1] / "custom_assets" / "My Character Sheets.xlsx"

SECTIONS = (
    (
        "Warmup Questions",
        [
            ("Where was the Character Born?", "In a vat under New York."),
            ("Who are their parents?", "Two donors, records expunged."),
        ],
    ),
    (
        "Autism Questionaire of Doom",
        [
            ("What are your worst fears? Why?", "Turning into goop."),
            ("If you had theme music, what would it sound like?", "Synthwave."),
        ],
    ),
)


def load(tmp_path, *sections, tab: str = "AQ Test Subject") -> Interview:
    path = questionnaire_workbook(tmp_path / "book.xlsx", *sections, tab=tab)
    return read_interview(read_grid(path, tab))


def test_questions_and_answers_pair_up(tmp_path) -> None:
    interview = load(tmp_path, *SECTIONS)
    assert interview.character == "Test Subject"
    assert interview.total == 4
    assert interview.answered == 4
    assert interview.complete is True
    assert interview.missing == ()
    assert interview.sections == ("Warmup Questions", "Autism Questionaire of Doom")
    assert interview.questions[0].prompt == "Where was the Character Born?"
    assert interview.questions[0].answer == "In a vat under New York."
    assert interview.questions[0].section == "Warmup Questions"
    assert interview.questions[0].row == 2


def test_a_section_can_be_selected(tmp_path) -> None:
    interview = load(tmp_path, *SECTIONS)
    second = interview.in_section("Autism Questionaire of Doom")
    assert [question.prompt for question in second] == [
        "What are your worst fears? Why?",
        "If you had theme music, what would it sound like?",
    ]
    assert interview.in_section("warmup questions")[0].prompt.startswith("Where")


def test_a_question_can_be_found_by_prefix(tmp_path) -> None:
    interview = load(tmp_path, *SECTIONS)
    assert interview.question("Where was the").answer.startswith("In a vat")
    with pytest.raises(UnknownTrait):
        interview.question("What is your favourite colour")


def test_an_empty_answer_counts_as_unanswered(tmp_path) -> None:
    sections = (
        (
            "Warmup Questions",
            [("Where was the Character Born?", "In a vat."), ("Who are their parents?", "")],
        ),
    )
    interview = load(tmp_path, *sections)
    assert interview.total == 2
    assert interview.answered == 1
    assert interview.complete is False
    assert [question.prompt for question in interview.missing] == ["Who are their parents?"]


def test_an_answer_that_repeats_a_prompt_is_refused(tmp_path) -> None:
    """A question pasted into an answer slot would look like prose otherwise."""
    cells = {
        "A1": "Warmup Questions",
        "A2": "Where was the Character Born?",
        "A3": "In a vat.",
        "A4": "Who are their parents?",
        "A5": "Where was the Character Born?",
    }
    path = write_workbook(
        tmp_path / "book.xlsx", {"AQ X": cells}, wrapped={"AQ X": ("A3", "A5")}
    )
    with pytest.raises(SheetError, match="is itself a question"):
        read_interview(read_grid(path, "AQ X"))


def test_a_deleted_row_is_a_documented_blind_spot(tmp_path) -> None:
    """Pinned on purpose: a shifted sheet cannot be detected, so it is documented.

    If this ever starts raising, the parser got smarter -- good -- but the docstring's
    Limitations section must change with it.
    """
    cells = {"A1": "Section", "A2": "First question?", "A3": "Second question?", "A4": "An answer"}
    path = write_workbook(tmp_path / "book.xlsx", {"AQ X": cells}, wrapped={"AQ X": ("A4",)})
    interview = read_interview(read_grid(path, "AQ X"))
    assert interview.total == 2
    assert interview.questions[0].answer == "First question?"


def test_an_answer_whose_styling_was_lost_still_belongs_to_its_question(tmp_path) -> None:
    """The real workbook has this: a pasted answer with no wrap style."""
    cells, wrapped = questionnaire(*SECTIONS)
    # Row 5 is the second answer; strip its wrap style, as a paste would.
    kept = [ref for ref in wrapped if ref != "A5"]
    path = write_workbook(
        tmp_path / "book.xlsx",
        {"AQ Test Subject": cells},
        wrapped={"AQ Test Subject": tuple(kept)},
    )
    interview = read_interview(read_grid(path, "AQ Test Subject"))
    assert interview.total == 4
    assert interview.answered == 4
    assert interview.questions[1].answer == "Two donors, records expunged."


def test_an_answer_with_no_question_is_refused(tmp_path) -> None:
    cells = {"A1": "Section", "A2": "Q one?", "A3": "A one", "A4": "An orphan answer"}
    path = write_workbook(
        tmp_path / "book.xlsx", {"AQ X": cells}, wrapped={"AQ X": ("A3", "A4")}
    )
    with pytest.raises(SheetError, match="no question above it"):
        read_interview(read_grid(path, "AQ X"))


@pytest.mark.parametrize("title", ["What was your childhood like?", "x" * 130])
def test_a_section_that_reads_like_prose_is_refused(tmp_path, title: str) -> None:
    with pytest.raises(SheetError, match="looks like an answer or a question"):
        load(tmp_path, (title, [("A question?", "An answer.")]))


def test_an_empty_tab_is_refused(tmp_path) -> None:
    path = write_workbook(tmp_path / "book.xlsx", {"AQ X": {"B1": "wrong column"}})
    with pytest.raises(SheetError, match="no questions found"):
        read_interview(read_grid(path, "AQ X"))


def test_the_character_comes_from_the_tab_name() -> None:
    assert character_from_tab("AQ Molly MacIntosh") == "Molly MacIntosh"
    assert character_from_tab("HG Robert Ross") == "Robert Ross"
    assert character_from_tab("VDA Aoife Moon") == "Aoife Moon"
    assert character_from_tab("Interview Notes") == "Interview Notes"
    assert character_from_tab("AQ") == "AQ"


def test_the_dictionary_shape_is_stable(tmp_path) -> None:
    payload = load(tmp_path, *SECTIONS).as_dict()
    assert payload["character"] == "Test Subject"
    assert payload["complete"] is True
    assert payload["answered"] == 4
    assert payload["total"] == 4
    assert payload["missing"] == []
    assert payload["sections"] == ["Warmup Questions", "Autism Questionaire of Doom"]
    assert payload["questions"][0] == {
        "section": "Warmup Questions",
        "prompt": "Where was the Character Born?",
        "answer": "In a vat under New York.",
        "row": 2,
        "answered": True,
    }


# -- the real workbook, when it is present --------------------------------

real_only = pytest.mark.skipif(
    not REAL.is_file(), reason="custom_assets/My Character Sheets.xlsx is not checked in"
)


@real_only
def test_every_real_questionnaire_is_complete() -> None:
    from ttrpg_chatbots.sheets.xlsx import sheet_names

    tabs = [name for name in sheet_names(REAL) if name.startswith("AQ ")]
    assert len(tabs) == 5
    for tab in tabs:
        interview = read_interview(read_grid(REAL, tab))
        assert interview.total == 55, tab
        assert interview.complete, (tab, [q.prompt for q in interview.missing])
        assert interview.sections[0] == "Warmup Questions"
        assert len(interview.sections) == 2


@real_only
def test_the_real_questionnaires_are_edited_per_character() -> None:
    """They are not a fixed form: Connor's tab asks a different question at #41."""
    molly = read_interview(read_grid(REAL, "AQ Molly MacIntosh"))
    connor = read_interview(read_grid(REAL, "AQ Connor McCoy"))
    assert [q.prompt for q in molly.questions] != [q.prompt for q in connor.questions]
    assert len(molly.questions) == len(connor.questions) == 55


@real_only
def test_a_real_answer_with_lost_styling_stays_with_its_question() -> None:
    """Cormac's row 26 answer is not wrap-styled; it still belongs to row 25's question."""
    interview = read_interview(read_grid(REAL, "AQ Cormac Moon"))
    question = interview.question("Have you ever been in love")
    assert question.answer.startswith("In the romantic sense")

