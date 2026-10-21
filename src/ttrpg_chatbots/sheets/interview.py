"""The character questionnaire: the "Autism Questionaire of Doom".

Every character is built twice -- once mechanically on the sheet, and once in prose here.
The rules document makes the second one mandatory: *answer all the questions about your
character as you build it*. So this module reads the answers **and** reports which
questions are still blank.

One tab per character, named ``AQ <Name>``, laid out in column A::

    row 1   section header   "Warmup Questions"
    row 2   question
    row 3   answer           <- the only rows carrying a wrap-text style
    ...
    row 16  section header   "Autism Questionaire of Doom"
    row 17  question
    row 18  answer

Answers are recognised by that wrap-text style, not by punctuation. A question here can
end with a full stop or a bracket ("... (1)baby, (2)child, (3)teenager"), so guessing from
the text would silently attach an answer to the wrong question -- the one mistake this
module must never make.

**Limitations.** The grammar is positional: a question always owns the row beneath it. That
survives the messy case in the real workbook (Cormac's answer at row 26 lost its wrap style
in a paste and is still paired correctly), and it refuses an answer that has no question or
a section title that reads like prose. What it cannot detect is a *deleted row*: the sheet
shifts and every later answer lands one row early, with no structural trace. If a tab looks
wrong, re-export it rather than deleting rows in place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from ttrpg_chatbots.sheets.types import SheetError, normalise, resolve_name

# Tab-name prefixes used in the workbook: "AQ Molly MacIntosh" is Molly's questionnaire.
TAB_PREFIXES = ("AQ", "HG", "VDA", "VM2", "VMR")


@dataclass(frozen=True)
class Question:
    """One prompt and the answer (possibly empty) that belongs to it."""

    prompt: str
    answer: str = ""
    section: str = ""
    row: int = 0

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise ValueError("a question needs a prompt")

    @property
    def answered(self) -> bool:
        return bool(self.answer.strip())

    def as_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "prompt": self.prompt,
            "answer": self.answer,
            "row": self.row,
            "answered": self.answered,
        }


@dataclass(frozen=True)
class Interview:
    """A character's answers, and whether the questionnaire is finished."""

    character: str
    questions: tuple[Question, ...] = ()
    sheet: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if not self.character.strip():
            raise ValueError("an interview needs a character name")

    @property
    def total(self) -> int:
        return len(self.questions)

    @property
    def answered(self) -> int:
        return sum(1 for question in self.questions if question.answered)

    @property
    def missing(self) -> tuple[Question, ...]:
        return tuple(question for question in self.questions if not question.answered)

    @property
    def complete(self) -> bool:
        return bool(self.questions) and not self.missing

    @property
    def next_unanswered(self) -> int | None:
        """The number of the first unanswered question, or ``None`` when complete.

        Position is derived, never stored, which is what makes resuming a build free: kill the
        bot for a week and this still points at the right question.
        """
        for number, question in enumerate(self.questions, start=1):
            if not question.answered:
                return number
        return None

    @property
    def sections(self) -> tuple[str, ...]:
        seen: list[str] = []
        for question in self.questions:
            if question.section not in seen:
                seen.append(question.section)
        return tuple(seen)

    def question(self, prompt: str) -> Question:
        """Look a question up by prompt, exactly or by unique prefix."""
        resolved = resolve_name(prompt, [item.prompt for item in self.questions])
        return next(item for item in self.questions if item.prompt == resolved)

    def in_section(self, section: str) -> tuple[Question, ...]:
        wanted = normalise(section)
        return tuple(
            question
            for question in self.questions
            if normalise(question.section) == wanted
        )

    def number_of(self, prompt: str) -> int:
        """The 1-based position of a question, so people can refer to "answer 12"."""
        resolved = self.question(prompt).prompt
        for index, question in enumerate(self.questions, start=1):
            if question.prompt == resolved:
                return index
        raise ValueError(f"no question {prompt!r}")

    def at(self, number: int) -> Question:
        """The question at a 1-based position, with the reason attached when it is out of range."""
        if not 1 <= number <= self.total:
            raise IndexError(
                f"{self.character}: no question {number}; there are {self.total}, "
                f"numbered 1..{self.total}"
            )
        return self.questions[number - 1]

    def with_answer(self, number: int, answer: str) -> Interview:
        """A copy with one answer replaced. Draft editing, not history."""
        if not answer.strip():
            raise ValueError("an answer cannot be blank")
        target = self.at(number)
        questions = tuple(
            replace(question, answer=answer.strip())
            if question.prompt == target.prompt and question.section == target.section
            else question
            for question in self.questions
        )
        return replace(self, questions=questions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "character": self.character,
            "sheet": self.sheet,
            "source": self.source,
            "complete": self.complete,
            "answered": self.answered,
            "total": self.total,
            "missing": [question.prompt for question in self.missing],
            "sections": list(self.sections),
            "questions": [question.as_dict() for question in self.questions],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Interview:
        """Rebuild an interview from :meth:`as_dict` output."""
        if not isinstance(data, Mapping):
            raise SheetError("an interview must be a JSON object")
        character = data.get("character")
        if not isinstance(character, str) or not character.strip():
            raise SheetError("an interview needs a 'character'")
        raw = data.get("questions")
        if not isinstance(raw, list) or not raw:
            raise SheetError(f"interview for {character!r} has no questions")
        questions: list[Question] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                raise SheetError(f"interview for {character!r} has a malformed question")
            questions.append(
                Question(
                    prompt=str(entry.get("prompt", "")),
                    answer=str(entry.get("answer", "") or ""),
                    section=str(entry.get("section", "") or ""),
                    row=int(entry.get("row", 0) or 0),
                )
            )
        return cls(
            character=character.strip(),
            questions=tuple(questions),
            sheet=str(data.get("sheet", "") or ""),
            source=str(data.get("source", "") or ""),
        )


@dataclass(frozen=True)
class Questionnaire:
    """The blank form: the questions a character must answer, in order.

    Separate from :class:`Interview` on purpose. The questionnaire is the *rules of the
    form* -- it can be shipped, versioned and edited without touching anyone's answers --
    while an interview is one character's responses and never changes once sealed.
    """

    name: str = "house-games"
    sections: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a questionnaire needs a name")
        if not self.sections:
            raise ValueError("a questionnaire needs at least one section")
        for title, prompts in self.sections:
            if not isinstance(title, str):
                raise ValueError("a section needs a title")
            if not prompts:
                raise ValueError(f"section {title!r} has no questions")

    @property
    def prompts(self) -> tuple[tuple[str, str], ...]:
        """``(section, prompt)`` for every question, in order."""
        return tuple(
            (title, prompt) for title, prompts in self.sections for prompt in prompts
        )

    @property
    def total(self) -> int:
        return len(self.prompts)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sections": [
                {"title": title, "questions": list(prompts)}
                for title, prompts in self.sections
            ],
        }

    @classmethod
    def from_dict(cls, data: Any) -> Questionnaire:
        if not isinstance(data, Mapping):
            raise SheetError("a questionnaire file must be a JSON object")
        raw_sections = data.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise SheetError("a questionnaire needs a non-empty 'sections' list")
        sections: list[tuple[str, tuple[str, ...]]] = []
        for index, section in enumerate(raw_sections, start=1):
            if not isinstance(section, Mapping):
                raise SheetError(f"questionnaire section {index} must be an object")
            title = section.get("title")
            questions = section.get("questions")
            if not isinstance(title, str) or not title.strip():
                raise SheetError(f"questionnaire section {index} needs a 'title'")
            if not isinstance(questions, list) or not questions:
                raise SheetError(f"questionnaire section {index} needs 'questions'")
            if any(not isinstance(prompt, str) or not prompt.strip() for prompt in questions):
                raise SheetError(f"questionnaire section {index} has a blank question")
            sections.append((title.strip(), tuple(p.strip() for p in questions)))
        name = data.get("name")
        return cls(
            name=name.strip() if isinstance(name, str) and name.strip() else "house-games",
            sections=tuple(sections),
        )


def blank_interview(questionnaire: Questionnaire, character: str) -> Interview:
    """An interview for ``character`` with every question unanswered."""
    return Interview(
        character=character,
        questions=tuple(
            Question(prompt=prompt, answer="", section=section)
            for section, prompt in questionnaire.prompts
        ),
        sheet=questionnaire.name,
    )


def questionnaire_from_interview(interview: Interview) -> Questionnaire:
    """Recover the blank form from a filled one (how the shipped default was made)."""
    sections: list[tuple[str, list[str]]] = []
    for question in interview.questions:
        if not sections or sections[-1][0] != question.section:
            sections.append((question.section, []))
        sections[-1][1].append(question.prompt)
    return Questionnaire(
        name=interview.sheet or "house-games",
        sections=tuple((title, tuple(prompts)) for title, prompts in sections),
    )


def load_questionnaire(path: Path) -> Questionnaire:
    """Read a questionnaire definition from JSON."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise SheetError(f"cannot read questionnaire {path}: {error}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise SheetError(f"{path}: invalid JSON: {error}") from error
    return Questionnaire.from_dict(data)


# An answer a player chose not to give. Distinct from blank, which means "not yet".
SKIPPED = "(skipped)"


def character_from_tab(tab: str) -> str:
    """``"AQ Molly MacIntosh"`` -> ``"Molly MacIntosh"``; unknown prefixes stay whole."""
    name = " ".join((tab or "").split())
    head, _, rest = name.partition(" ")
    if rest and head.upper() in TAB_PREFIXES:
        return rest.strip()
    return name


def read_interview(grid, *, character: str | None = None, source: str = "") -> Interview:
    """Parse a questionnaire tab into an :class:`Interview`.

    The document's grammar is simple and strictly positional: a question always owns the
    very next row, blank or not. That is what makes the parser survive hand-editing -- one
    of these sheets has an answer whose wrap style was lost in a paste, and a parser that
    trusted the styling alone shifted every later answer by a row.

    A section header is therefore only recognised when no question is waiting for its
    answer, and it is recognised by shape: the row after it is a question whose own answer
    *is* styled. Ambiguity is reported rather than guessed at.
    """
    rows = grid.max_row
    if rows == 0:
        raise SheetError(f"{grid.name}: the questionnaire tab is empty")

    section = ""
    pending: tuple[int, str] | None = None
    questions: list[Question] = []

    for row in range(1, rows + 1):
        text = grid.text(f"A{row}")

        if pending is not None:
            # Whatever is here belongs to the waiting question: the answer, or nothing.
            questions.append(
                Question(prompt=pending[1], answer=text, section=section, row=pending[0])
            )
            pending = None
            continue

        if not text:
            continue
        if grid.wrapped(f"A{row}"):
            raise SheetError(
                f"{grid.name} A{row}: an answer with no question above it "
                "(has a row been deleted?)"
            )
        if _looks_like_header(grid, row, rows):
            section = text
        else:
            pending = (row, text)

    if pending is not None:
        # The last question owns no answer row at all: still record it as unanswered.
        questions.append(
            Question(prompt=pending[1], answer="", section=section, row=pending[0])
        )

    if not questions:
        raise SheetError(f"{grid.name}: no questions found; is this a questionnaire tab?")

    interview = Interview(
        character=character or character_from_tab(grid.name),
        questions=tuple(questions),
        sheet=grid.name,
        source=source,
    )
    _check_sections(interview)
    _check_no_prompt_answered_itself(interview)
    return interview


def _looks_like_header(grid, row: int, last_row: int) -> bool:
    """A header is followed by a question, and that question's answer is styled."""
    following = row + 1
    if following > last_row:
        return False
    next_text = grid.text(f"A{following}")
    if not next_text or grid.wrapped(f"A{following}"):
        return False
    after = following + 1
    return after <= last_row and grid.wrapped(f"A{after}")


def _check_sections(interview: Interview) -> None:
    """Refuse to hand back an interview whose sections look like prose.

    A section title that reads like a question means an answer was mistaken for a header,
    which would mislabel prose as structure. Loud failure beats a shifted questionnaire.
    """
    for section in interview.sections:
        if not section:
            continue
        if section.rstrip().endswith("?") or len(section) > 120:
            raise SheetError(
                f"{interview.sheet}: {section[:60]!r} looks like an answer or a question, "
                "not a section heading; the questionnaire layout has changed"
            )


def _check_no_prompt_answered_itself(interview: Interview) -> None:
    """An answer that is verbatim another question means the rows have shifted.

    This is the one structural failure the styling cannot reveal: when a row is deleted,
    every later answer lands one row early, and the displaced question text becomes the
    previous question's "answer". Prompts are long and distinctive, so an exact match is
    an extremely strong signal -- and a real answer is never an exact copy of a prompt.
    """
    prompts = {normalise(question.prompt): question for question in interview.questions}
    for question in interview.questions:
        if not question.answered:
            continue
        matched = prompts.get(normalise(question.answer))
        if matched is not None:
            raise SheetError(
                f"{interview.sheet} A{question.row + 1}: the answer to "
                f"{question.prompt[:40]!r} is itself a question; a row has probably been "
                "deleted, which would shift every answer below it"
            )

