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

from ttrpg_chatbots.conv.types import Abstain, Line, Relationship, Utterance
from ttrpg_chatbots.decide.persona_fit import read as fit
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.loop import Scene, reply
from ttrpg_chatbots.govern.repeat import Recent
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
            f"ends on a beat: {self.beat_rate:.0%}"
        )


def run(
    *,
    book: Phrasebook,
    messages: tuple[str, ...] = ("hey", "hey", "morning", "yo"),
    relationships: tuple[Relationship, ...] = (),
    moments: tuple[Moment, ...] = (),
    repeats: int = 3,
    style: Style | None = None,
) -> Report:
    """Push the matrix through the ladder and count what came out."""
    people = relationships or (
        Relationship(stage="new", warmth=0),
        Relationship(stage="acquainted", warmth=1),
        Relationship(stage="friend", warmth=3),
    )
    times = moments or (
        read_clock(__import__("datetime").datetime(2026, 10, 21, 8, 10)),
        read_clock(__import__("datetime").datetime(2026, 10, 21, 13, 0)),
        read_clock(__import__("datetime").datetime(2026, 10, 21, 19, 20)),
        read_clock(__import__("datetime").datetime(2026, 10, 22, 0, 40)),
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
                        ),
                        book=book,
                        style=style,
                        recent=ledger,
                    )
                    if isinstance(out, Abstain):
                        report.abstains[out.reason] += 1
                    else:
                        said.append(out.text)
    report.lines = tuple(said)
    return report
