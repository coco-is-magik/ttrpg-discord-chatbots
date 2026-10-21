"""The questionnaire text file: export a template, fill it in, import it back."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.character.questionnaire_text import (
    Imported,
    apply_text,
    parse_text,
    render_text,
)
from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import SKIPPED, Interview, Question
from ttrpg_chatbots.sheets.types import Sheet


def interview(*pairs: tuple[str, str], section: str = "Warmup") -> Interview:
    return Interview(
        character="Ailis",
        questions=tuple(
            Question(prompt=prompt, answer=answer, section=section)
            for prompt, answer in pairs
        ),
    )


def character(*pairs: tuple[str, str], sealed: bool = False) -> Character:
    sheet = Sheet(name="Ailis", system="house-games")
    built = Character(sheet=sheet, interview=interview(*pairs))
    return built.seal() if sealed else built


# -- exporting -------------------------------------------------------------


def test_the_export_has_a_prompt_for_every_question() -> None:
    text = render_text(character(("Where from?", "A vat."), ("Why leave?", "")))
    assert "## Where from?" in text
    assert "## Why leave?" in text  # unanswered questions still get a heading
    assert "A vat." in text


def test_the_export_explains_its_own_format() -> None:
    text = render_text(character(("Where from?", "A vat.")))
    assert text.startswith("<!--")
    assert "/fill" in text
    assert "##" in text.splitlines()[0] or "two ##" in text


def test_sections_become_single_hash_headings() -> None:
    first = interview(("Where from?", "A vat."))
    text = render_text(character(("Where from?", "A vat.")))
    assert "# Warmup" in text
    assert first.questions[0].section in text


def test_a_character_without_an_interview_cannot_be_exported() -> None:
    with pytest.raises(CharacterError, match="no interview"):
        render_text(Character(sheet=Sheet(name="X", system="house-games")))


# -- parsing ---------------------------------------------------------------


def test_questions_and_answers_are_read_back() -> None:
    blocks = parse_text("# Warmup\n\n## Where from?\n\nA vat.\n\n## Why leave?\n\nBoredom.\n")
    assert [(b.prompt, b.answer) for b in blocks] == [
        ("Where from?", "A vat."),
        ("Why leave?", "Boredom."),
    ]
    assert {block.section for block in blocks} == {"Warmup"}


def test_a_multi_line_answer_stays_together() -> None:
    blocks = parse_text("## Where from?\n\nLine one\nline two\n\nstill the answer\n")
    assert blocks[0].answer == "Line one\nline two\n\nstill the answer"


def test_crlf_and_a_byte_order_mark_are_tolerated() -> None:
    text = "\ufeff## Where from?\r\n\r\nA vat.\r\n"
    blocks = parse_text(text)
    assert blocks[0].prompt.endswith("Where from?")
    assert blocks[0].answer == "A vat."


def test_the_qa_style_also_parses() -> None:
    blocks = parse_text("Q: Where from?\nA: A vat.\nQ: Why leave?\nA: Boredom.\n")
    assert [(b.prompt, b.answer) for b in blocks] == [
        ("Where from?", "A vat."),
        ("Why leave?", "Boredom."),
    ]


def test_the_hint_comment_is_ignored() -> None:
    text = render_text(character(("Where from?", "A vat.")))
    blocks = parse_text(text)
    # The comment line never becomes an answer to anything.
    assert blocks[0].answer == "A vat."


def test_an_empty_file_has_no_blocks() -> None:
    assert parse_text("") == ()
    assert parse_text("<!-- just a comment -->\n") == ()


# -- applying --------------------------------------------------------------


def test_answers_land_on_the_right_question_by_text_not_position() -> None:
    target = character(("Where from?", ""), ("Why leave?", ""))
    # Deliberately reversed order.
    result = apply_text(target, "## Why leave?\n\nBoredom.\n\n## Where from?\n\nA vat.\n")
    answers = [q.answer for q in result.character.interview.questions]
    assert answers == ["A vat.", "Boredom."]
    assert result.matched == 2


def test_a_partial_file_leaves_the_rest_alone() -> None:
    target = character(("Where from?", "A vat."), ("Why leave?", ""))
    result = apply_text(target, "## Why leave?\n\nBoredom.\n")
    answers = [q.answer for q in result.character.interview.questions]
    assert answers == ["A vat.", "Boredom."]
    assert result.still_missing == ()


def test_prompts_that_are_not_on_the_form_are_reported_not_dropped() -> None:
    target = character(("Where from?", ""))
    result = apply_text(target, "## Favourite colour?\n\nGreen.\n")
    assert result.ignored == ("Favourite colour?",)
    assert result.matched == 0
    assert target.interview.questions[0].answer == ""


def test_an_export_can_be_imported_unchanged() -> None:
    original = character(("Where from?", "A vat."), ("Why leave?", "Boredom."))
    result = apply_text(original, render_text(original))
    assert [q.answer for q in result.character.interview.questions] == [
        q.answer for q in original.interview.questions
    ]


def test_writing_skip_is_recorded_as_the_skip_marker() -> None:
    target = character(("Why leave?", ""))
    for word in ("skip", "SKIPPED", "n/a"):
        result = apply_text(target, f"## Why leave?\n\n{word}\n")
        assert result.character.interview.questions[0].answer == SKIPPED


def test_a_sealed_character_must_be_unlocked_first() -> None:
    sealed = character(("Where from?", "A vat."), sealed=True)
    with pytest.raises(CharacterError, match="sealed"):
        apply_text(sealed, "## Where from?\n\nElsewhere.\n")


def test_a_file_with_no_questions_says_so() -> None:
    with pytest.raises(CharacterError, match="no questions found"):
        apply_text(character(("Where from?", "")), "just some prose\nwith no headings\n")


def test_the_import_is_recorded_in_history() -> None:
    result = apply_text(character(("Where from?", "")), "## Where from?\n\nA vat.\n")
    assert result.character.history[-1].kind == "answer"
    assert "imported 1 answer" in result.character.history[-1].summary
    assert result.character.history[-1].detail["imported"] == 1


def test_the_summary_reads_like_a_sentence() -> None:
    result = apply_text(
        character(("Where from?", ""), ("Why leave?", "")),
        "## Where from?\n\nA vat.\n",
    )
    assert "imported 1 answer" in result.summary()
    assert "1/2 answered" in result.summary()
    assert "1 still unanswered" in result.summary()
    assert isinstance(result, Imported)

