"""Measure the greet stage instead of admiring it.

Runs a matrix through the ladder -- several relationships, several times of day, several messages,
repeated -- and reports the numbers that separate a person from a caption: how many words, how many
distinct lines, whether any line ends on a beat, and why anything stayed quiet.

This is the acceptance test for the module approach on one phase: if the numbers are not better than
the old corpus (7 words median, 29% beats, 100% novelty), the phase has not proved anything.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from ttrpg_chatbots.conv.types import Abstain, Line, Relationship, Utterance
from ttrpg_chatbots.decide.persona_fit import read as fit
from ttrpg_chatbots.decide.shelf import Shelf
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.loop import Scene, reply
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.reply.style import Style


def words(text: str) -> int:
    return len([part for part in text.split() if part])


@dataclass
class Report:
    """What the harness measured."""

    attempts: int = 0
    lines: tuple[str, ...] = ()
    abstains: Counter[str] = field(default_factory=Counter)
    # Lines the trimmer shortened. Not an error in itself, but a high rate means the phrasebook and
    # the budget disagree -- measured live: a comiseration was trimmed from twelve words to "yeah".
    trimmed: int = 0

    @property
    def trim_rate(self) -> float:
        return self.trimmed / self.attempts if self.attempts else 0.0

    @property
    def said(self) -> int:
        return len(self.lines)

    @property
    def median_words(self) -> float:
        return statistics.median([words(line) for line in self.lines]) if self.lines else 0.0

    @property
    def max_words(self) -> int:
        return max((words(line) for line in self.lines), default=0)

    @property
    def distinct_ratio(self) -> float:
        return len(set(self.lines)) / self.said if self.said else 0.0

    @property
    def beat_rate(self) -> float:
        """Share of lines that end on a beat -- the single worst written tell."""
        if not self.lines:
            return 0.0
        beatty = [line for line in self.lines if not fit(line).ok]
        return len(beatty) / len(self.lines)

    def summary(self) -> str:
        reasons = ", ".join(f"{reason} x{count}" for reason, count in self.abstains.most_common())
        return (
            f"attempts {self.attempts}  said {self.said}  "
            f"abstained {self.attempts - self.said}" + (f" ({reasons})" if reasons else "") + "\n"
            f"words: median {self.median_words:g}, max {self.max_words}\n"
            f"distinct: {self.distinct_ratio:.0%} ({len(set(self.lines))} of {self.said})\n"
            f"ends on a beat: {self.beat_rate:.0%}\n"
            f"trimmed: {self.trim_rate:.0%}"
        )


def run(
    *,
    book: Phrasebook | None = None,
    books: Shelf | None = None,
    life: Life | None = None,
    messages: tuple[str, ...] = ("hey", "hey", "morning", "yo"),
    relationships: tuple[Relationship, ...] = (),
    moments: tuple[Moment, ...] = (),
    repeats: int = 3,
    style: Style | None = None,
    question_rate: float = 1.0,
    he_asked: bool = False,
) -> Report:
    """Push the matrix through the ladder and count what came out."""
    people = relationships or (
        Relationship(stage="new", warmth=0),
        Relationship(stage="acquainted", warmth=1),
        Relationship(stage="friend", warmth=3),
    )
    times = moments or (
        read_clock(datetime(2026, 10, 21, 8, 10)),
        read_clock(datetime(2026, 10, 21, 13, 0)),
        read_clock(datetime(2026, 10, 21, 19, 20)),
        read_clock(datetime(2026, 10, 22, 0, 40)),
    )
    report = Report()
    said: list[str] = []
    ledger = Recent()
    for moment in times:
        for person in people:
            for message in messages:
                for _ in range(repeats):
                    report.attempts += 1
                    out = reply(
                        scene=Scene(
                            utterance=Utterance(text=message, speaker="tav"),
                            addressed="named",
                            moment=moment,
                            relationship=person,
                            life=life,
                            name="tav",
                            turns=_after_his_question() if he_asked else (),
                            # The harness measures what a phase *can* say, so it asks as often as it
                            # can: `ask_back` is unreachable at question_rate 0, and a phase the
                            # harness cannot reach is a phase nothing proves.
                            question_rate=question_rate,
                        ),
                        book=book,
                        books=books,
                        style=style,
                        recent=ledger,
                    )
                    if isinstance(out, Abstain):
                        report.abstains[out.reason] += 1
                    else:
                        said.append(out.text)
                        steps = dict(out.trail.steps)
                        if steps.get("fill") and steps.get("trim") != steps.get("fill"):
                            report.trimmed += 1
    report.lines = tuple(said)
    return report


# The messages each phase is for. Not the ones a phrasebook would like to receive: a two-word
# question, a one-word "why?", a complaint with no detail in it.
PHASE_MESSAGES: dict[str, tuple[str, ...]] = {
    "greet": ("hey", "hey", "morning", "yo"),
    "acknowledge": ("thanks", "thanks", "yeah", "sounds good"),
    "close": ("good night", "night", "good night"),
    "reassure": ("i am nervous about tomorrow", "i am stuck on this", "i am dreading it"),
    "mirror": ("rough day at work", "today was a mess", "ugh"),
    "offer_hook": ("what are you up to", "what are you doing", "whats up", "you around"),
    "explain": ("why?", "why though", "why is that"),
    "hedge": ("what is the plot of dune", "tell me about the guild", "who is agrippa"),
    "tell_story": ("how did the fence go?", "what happened with the truck?", "how was the weekend"),
    "noted": ("i have been rebuilding a fence myself", "the truck is in the shop", "my dog is called otis"),
    # Statements with nothing to add to: the job with the least to say, and therefore the one worth
    # spending on a question when the persona asks often enough.
    "ask_back": (
        "i have been rebuilding a fence myself this month",
        "i finally finished the thing i was working on",
        "i spent the weekend sorting the garage out",
    ),
    # The answers to a question he asked. Unreachable without `he_asked`, which is the point: the phase
    # exists to prove he was listening, so it may only follow a question of his own.
    "follow_up": (
        "playing video games",
        "i sorted the garage out",
        "reading a book about trains",
    ),
    # Somebody saying no to something. The one job in the vocabulary with no book behind it until the
    # refusal move was wired, so this phase had never been measured.
    "decline": ("no thanks", "i would rather not", "not today", "i do not want to talk about it"),
}


def _after_his_question() -> tuple[Turn, ...]:
    """A turn of his own that asked a question, so the follow-up phase is reachable."""
    return (Turn(speaker="friend", text="what about you?", act="ladder|ask_back||", is_bot=True),)


def run_phases(
    *,
    books: Shelf,
    life: Life | None = None,
    style: Style | None = None,
) -> dict[str, Report]:
    """One report per phase a shelf can actually answer."""
    reports: dict[str, Report] = {}
    for job in books.jobs():
        messages = PHASE_MESSAGES.get(job)
        if messages is None:
            continue
        reports[job] = run(
            books=books,
            messages=messages,
            repeats=3,
            style=style,
            life=life,
            he_asked=job == "follow_up",
        )
    return reports
