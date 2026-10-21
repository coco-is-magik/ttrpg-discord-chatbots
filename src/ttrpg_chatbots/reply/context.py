"""What was said before the message being answered.

The classifier is stateless on purpose -- one query in, one tag out -- but a group chat is
not. "hey" is a different move depending on whether the bot greeted three seconds ago, and
saying the same thing twice is worse than saying nothing.

A :class:`Turn` records one line as the room heard it: who said it, what they said, which
act it turned out to be, and whether a bot said it. :class:`Context` is the tail of those
turns -- the only history anyone needs to answer the next line.

Nothing here decides anything. It is a record of what happened, so the classifier can
consult it and the reviewer can see why. Every decision taken from it lives in
``replier.py`` and is named in the reply's ``detail``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ttrpg_chatbots.reply.intents import normalise

# Eight turns is two greetings, one aside and an answer: enough to know whether the bot
# just spoke, without letting a stale remark from ten minutes ago steer a fresh question.
DEFAULT_WINDOW = 8


@dataclass(frozen=True)
class Turn:
    """One line, as it happened.

    ``text`` may be empty: a message that is only an attachment or an emoji is a turn
    somebody took, even though it says nothing a classifier can read.
    """

    speaker: str
    text: str = ""
    act: str | None = None
    is_bot: bool = False

    def __post_init__(self) -> None:
        if not self.speaker.strip():
            raise ValueError("a turn needs a speaker")

    @property
    def says_nothing(self) -> bool:
        """True for a turn with no readable text."""
        return not self.text.strip()


@dataclass(frozen=True)
class Context:
    """The turns immediately before the message being answered, oldest first."""

    turns: tuple[Turn, ...] = ()

    @classmethod
    def of(cls, turns: Iterable[Turn], *, window: int = DEFAULT_WINDOW) -> Context:
        """Keep only the last ``window`` turns."""
        if window < 1:
            raise ValueError("window must be at least 1")
        return cls(tuple(turns)[-window:])

    def __bool__(self) -> bool:
        return bool(self.turns)

    def __len__(self) -> int:
        return len(self.turns)

    @property
    def latest(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    @property
    def previous_act(self) -> str | None:
        """The act of the most recent turn, if it had one.

        Deliberately not "the most recent act": if the last thing said could not be
        classified, reaching further back describes a conversation that is not the one
        being answered.
        """
        latest = self.latest
        return latest.act if latest is not None else None

    @property
    def last_human(self) -> Turn | None:
        return next((turn for turn in reversed(self.turns) if not turn.is_bot), None)

    @property
    def last_bot(self) -> Turn | None:
        return next((turn for turn in reversed(self.turns) if turn.is_bot), None)

    def bot_spoke_last(self) -> bool:
        """True when the newest turn is a bot's, so anything now is a follow-up."""
        latest = self.latest
        return latest is not None and latest.is_bot

    def act_from_bot(self, act: str) -> bool:
        """True when this bot's own last line was that act, and nothing has followed it."""
        latest = self.latest
        return latest is not None and latest.is_bot and latest.act == act

    def repeated(self, text: str) -> bool:
        """True when a human already said exactly this within the window.

        Compared on the normalised text, because the repeat that matters is the one
        that reads the same to a person, not the one that hashes the same.
        """
        wanted = normalise(text)
        if not wanted:
            return False
        return any(
            not turn.is_bot and normalise(turn.text) == wanted for turn in self.turns
        )

    @property
    def acts(self) -> tuple[str, ...]:
        """The acts seen in the window, oldest first, with unclassified turns dropped."""
        return tuple(turn.act for turn in self.turns if turn.act)

    def sequence(self, *, limit: int = 4) -> str:
        """``greeting>greeting`` -- a compact trail for log lines."""
        seen = self.acts[-limit:]
        return ">".join(act.rsplit(":", 1)[-1] for act in seen)
