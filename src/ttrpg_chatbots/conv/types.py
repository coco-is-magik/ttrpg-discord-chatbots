"""The contracts every conversation module shares.

Nothing here decides anything. These are the shapes that travel between the single-purpose modules
in `docs/CONVERSATION.md`, so that each module can be tested alone: one type in, one type out.

Two rules encoded here:

* **Decisions are data, not sentences.** A stage returns a `Draft` (what to say, by reference) or
  an `Abstain` (why not). Words appear only in `Line`.
* **Every step is recorded.** A `Trail` names the module and the answer at each rung, so a reply
  can be explained without re-running it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Phase = Literal["opening", "pleasantries", "hook", "substance", "closing"]
Job = Literal[
    "greet",
    "acknowledge",
    "mirror",
    "reassure",
    "offer_hook",
    "explain",
    "tell_story",
    "hedge",
    "noted",
    "decline",
    "close",
    "ask_back",
]
Form = Literal["word", "clause", "clause_question", "two_beat"]
Family = Literal[
    "warm",
    "casual",
    "time_morning",
    "time_evening",
    "name_based",
    "dry",
    "reaction",
    "detail",
    "reassure",
    "story",
    "point",
    "closing",
    "noted",
    "recall",
    "hedge",
]
Intent = Literal[
    "greet",
    "about_me",
    "plans",
    "explain_me",
    "about_world",
    "complain",
    "comfort",
    "agree",
    "decline",
    "joke",
    "remark",
    "meta",
]
Tone = Literal["neutral", "warm", "terse", "teasing", "flat"]
Who = Literal["friend", "character"]
Addressee = Literal["named", "reply", "unaddressed"]
Modality = Literal["text", "voice", "image", "embed", "system"]


@dataclass(frozen=True)
class Utterance:
    """One inbound message, in a shape nothing downstream has to re-parse."""

    text: str
    speaker: str = ""
    channel: str = ""
    at: datetime | None = None
    reply_to: str | None = None
    modality: Modality = "text"
    attachments: int = 0
    embeds: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("utterance text must be a string")


@dataclass(frozen=True)
class Budget:
    """How much to say, derived from what they said and where we are.

    The single most useful number in the system: our old corpus ran 7 words against the human's 2,
    which is what "written" sounds like. A budget makes brevity a constraint instead of a taste.
    """

    max_words: int = 6
    max_sentences: int = 1

    def __post_init__(self) -> None:
        if self.max_words < 1:
            raise ValueError("a budget needs at least one word")
        if self.max_sentences < 1:
            raise ValueError("a budget needs at least one sentence")

    def fits(self, text: str) -> bool:
        """Does this line fit? A trailing question tag does not count as a second sentence."""
        words = len([part for part in text.split() if part])
        parts = [p.strip() for p in text.replace("!", ".").split(".") if p.strip()]
        questions = [p for p in parts if p.endswith("?")]
        trailing_tag = bool(questions) and len(questions[-1].split()) <= 3
        counted = len(parts) - (1 if trailing_tag and len(parts) > 1 else 0)
        return words <= self.max_words and counted <= self.max_sentences


@dataclass(frozen=True)
class Draft:
    """What to say, before any words are chosen."""

    stage: str
    tag: str | None = None
    reference: str | None = None  # a phrase id, an activity id, a fact id
    depth: int = 0


@dataclass(frozen=True)
class Abstain:
    """A stage declining to act, with the reason that made it decline."""

    reason: str


@dataclass(frozen=True)
class Trail:
    """Every rung of the ladder, in order: (module, answer)."""

    steps: tuple[tuple[str, str], ...] = ()

    def add(self, module: str, answer: object) -> Trail:
        return Trail(steps=self.steps + ((module, str(answer)),))

    def describe(self) -> str:
        return " > ".join(f"{module}={answer}" for module, answer in self.steps)


@dataclass(frozen=True)
class Line:
    """The only object in the system that contains words to send."""

    text: str
    trail: Trail = field(default_factory=Trail)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a line must say something")


@dataclass(frozen=True)
class Attachment:
    """A file or picture, and whether he can actually see it."""

    kind: str
    count: int = 1
    visible: bool = False


@dataclass(frozen=True)
class Situation:
    """What kind of conversation this is, and what gave it away."""

    kind: str = "chatting"
    evidence: str = ""


@dataclass(frozen=True)
class Gap:
    """How long since this person last spoke."""

    seconds: float = 0.0
    bucket: str = "new"


@dataclass(frozen=True)
class Relationship:
    """How well he knows this person, from counts rather than feelings."""

    stage: str = "new"
    warmth: int = 0


@dataclass(frozen=True)
class Thread:
    """What the current stretch of conversation is about."""

    id: str = ""
    subject: str = ""


@dataclass(frozen=True)
class Event:
    """Something happening in his world, and how far away it is."""

    label: str
    days_away: int = 0
    topics: tuple[str, ...] = ()
    short: str = ""  # what a person would call it out loud


@dataclass(frozen=True)
class Speak:
    """The floor says yes."""

    reason: str = "addressed"


@dataclass(frozen=True)
class Reciprocate:
    """Whether he hands the turn back, and how."""

    kind: str = "none"


@dataclass(frozen=True)
class Fit:
    """Whether a candidate line sounds like him, and what is wrong if not."""

    ok: bool = True
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Sentiment:
    """Good, bad or mixed -- and about whom."""

    polarity: str = "neutral"
    target: str = "it"
