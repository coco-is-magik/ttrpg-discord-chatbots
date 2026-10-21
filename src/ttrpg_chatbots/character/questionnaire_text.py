"""The questionnaire as a text file: export a template, import the answers back.

Answering 55 questions through `/answer 12 text:…` is fine for a line and miserable for a
paragraph. So the canonical form is a **plain markdown-ish file** that any editor handles:

    # Warmup Questions

    ## Where was the Character Born?

    Cormac Moon was born Cormac Mac Niall, near Dublin in 780AD.

    ## Why did they leave?

One `#` starts a section, `##` starts a question, and everything between two questions is that
question's answer. Nothing else needs to be remembered, which is the point: `/export
format:questionnaire` hands you a file with every prompt already in place and every existing
answer filled in.

Answers are matched to the form **by prompt text**, not by position, so a file can be reordered,
partly answered, or written months ago against an older form without silently landing on the
wrong question. Anything the parser cannot place is reported rather than dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ttrpg_chatbots.character.types import Character, CharacterError
from ttrpg_chatbots.sheets.interview import SKIPPED, Interview, Question
from ttrpg_chatbots.sheets.types import normalise

HINT = (
    "<!-- Answer under each question. Lines starting with '#' are structure: one # is a "
    "section, two ## is a question. Save as UTF-8 and upload with /fill. -->"
)
SECTION = re.compile(r"^#(?!#)\s*(?P<title>.*\S)\s*$")
QUESTION = re.compile(r"^#{2,}\s*(?P<prompt>.*\S)\s*$")
Q_LINE = re.compile(r"^Q:\s*(?P<prompt>.*\S)\s*$", re.IGNORECASE)
A_LINE = re.compile(r"^A:\s*(?P<answer>.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class QuestionBlock:
    """One question and its answer, as read from a file."""

    prompt: str
    answer: str
    section: str = ""


@dataclass(frozen=True)
class Imported:
    """What happened when a text file was applied."""

    character: Character
    matched: int = 0
    ignored: tuple[str, ...] = ()
    still_missing: tuple[str, ...] = ()

    def summary(self) -> str:
        interview = self.character.interview
        total = interview.total if interview else 0
        parts = [f"imported {self.matched} answer{'s' if self.matched != 1 else ''}"]
        if interview is not None:
            parts.append(f"{interview.answered}/{total} answered")
        if self.ignored:
            parts.append(f"{len(self.ignored)} not on this form")
        if self.still_missing:
            parts.append(f"{len(self.still_missing)} still unanswered")
        return " · ".join(parts)


def is_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def render_text(character: Character) -> str:
    """The questionnaire as an editable file, with the answers it already has."""
    interview = character.interview
    if interview is None:
        raise CharacterError(f"{character.name} has no interview to export")
    lines = [HINT, "", f"# {character.name} — questionnaire", ""]
    section = None
    for question in interview.questions:
        if question.section != section:
            section = question.section
            lines.extend([f"# {section}", ""])
        lines.extend([f"## {question.prompt}", ""])
        if question.answer:
            lines.extend([*question.answer.splitlines(), ""])
    return "\n".join(lines).rstrip() + "\n"


def parse_text(text: str) -> tuple[QuestionBlock, ...]:
    """Read blocks back. Tolerant of `Q:`/`A:` style, CRLF, and a leading byte-order mark."""
    # A BOM is invisible and would stop the first `## ` from matching, silently losing the
    # first question — exactly what a file saved by Notepad or Excel carries.
    text = text.lstrip("\ufeff")
    blocks: list[QuestionBlock] = []
    section = ""
    prompt: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal prompt, body
        if prompt is not None:
            blocks.append(
                QuestionBlock(prompt=prompt, answer="\n".join(body).strip(), section=section)
            )
        prompt, body = None, []

    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if is_comment(line):
            continue
        answered = A_LINE.match(line)
        if answered is not None and prompt is not None:
            body.append(answered.group("answer").strip())
            continue
        question = QUESTION.match(line) or Q_LINE.match(line)
        if question is not None:
            flush()
            prompt = question.group("prompt")
            continue
        as_section = SECTION.match(line)
        if as_section is not None:
            # The "# name — questionnaire" title lands here too; it just matches no question,
            # which is what lets an exported file round-trip through this parser.
            flush()
            section = as_section.group("title")
            continue
        if prompt is not None:
            body.append(line)
    flush()
    return tuple(blocks)


def apply_text(character: Character, text: str) -> Imported:
    """Fill in a character's answers from a text file."""
    interview = character.interview
    if interview is None:
        raise CharacterError(f"{character.name} has no interview to import into")
    if character.sealed:
        raise CharacterError(
            f"{character.name} is sealed; run /unlock first, then import answers"
        )
    blocks = parse_text(text)
    if not blocks:
        raise CharacterError(
            "no questions found in that file; each prompt needs a '## ' line above its answer"
        )

    index_by_prompt = {
        normalise(question.prompt): position
        for position, question in enumerate(interview.questions)
    }
    questions = list(interview.questions)
    matched = 0
    ignored: list[str] = []
    for block in blocks:
        position = index_by_prompt.get(normalise(block.prompt))
        if position is None:
            ignored.append(block.prompt)
            continue
        answer = block.answer.strip()
        if not answer:
            continue
        if normalise(answer) in {normalise(SKIPPED), "skipped", "skip", "n/a"}:
            answer = SKIPPED
        current = questions[position]
        questions[position] = Question(
            prompt=current.prompt, answer=answer, section=current.section, row=current.row
        )
        matched += 1

    updated_interview = Interview(
        character=interview.character,
        questions=tuple(questions),
        sheet=interview.sheet,
        source=interview.source,
    )
    updated = character.with_interview(updated_interview)
    updated = updated.record(
        "answer",
        f"imported {matched} answer(s) from a file",
        detail={"imported": matched, "ignored": ignored},
    )
    return Imported(
        character=updated,
        matched=matched,
        ignored=tuple(ignored),
        still_missing=tuple(question.prompt for question in updated_interview.missing),
    )

