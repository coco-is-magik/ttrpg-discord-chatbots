"""The rolling group conversation.

Not a chat log -- a *room*: who said what, when, and who has been quiet longest. Everything the friends
need in order to talk to each other rather than at the human, and nothing else. The transcript is kept
because it is the data a later tuning pass needs; the decisions read only the tail.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: How much of the conversation is kept in memory for decisions. Long enough to see a rhythm, short
#: enough that a friend is not answering something from an hour ago.
WINDOW = 12

#: Below the cadence floor, so a repeat inside this window cannot be a second real utterance -- it can
#: only be the same one arriving by another route. See ``Room.add``.
DEDUPE_SECONDS = 30.0


@dataclass(frozen=True)
class Said:
    """One message in the room."""

    speaker: str
    text: str
    at: datetime
    kind: str = "chat"  # chat | greeting | human
    #: Which turn this message belongs to. A turn arrives as one or more messages, and without this a
    #: transcript cannot tell "he sent two short things" from "he sent two thoughts" -- measured: the
    #: first dataset could only count messages, never turns.
    turn: str = ""
    #: The ladder's own record of how this line was chosen. Empty for a human turn, and empty for a
    #: line that arrived by being heard rather than by being decided. Measured: the first dataset had no
    #: trails, so the job mix could only be inferred from the words -- and "ah, oh" twenty-two times does
    #: not say whether that was `noted` or `acknowledge`.
    trail: str = ""

    @property
    def is_human(self) -> bool:
        return self.kind == "human"


@dataclass
class Room:
    """A group conversation: the tail of it, plus what the last human turn was."""

    window: int = WINDOW
    #: Called for every line that enters the room, whoever said it. One hook rather than a writer per
    #: caller: the room is the only place that knows the whole conversation, which is what a dataset is.
    on_say: Callable[[Said], None] | None = None
    said: list[Said] = field(default_factory=list)
    #: When each friend last spoke, for the rotation and for "who has been quiet longest".
    last_spoke: dict[str, datetime] = field(default_factory=dict)
    #: When the human last said anything, and when they said goodnight. These two drive bedtime.
    human_last_at: datetime | None = None
    human_goodnight_at: datetime | None = None

    def add(self, entry: Said) -> None:
        """Put a line in the room, once.

        The same utterance arrives by two routes: the director records what it said (in local time) and
        each listening friend records what it heard (Discord's timestamp, UTC). Both are the same words
        at the same instant, so they are compared as *instants*, not as strings -- measured: every line
        was being written to the transcript twice, and the room's own window held each line twice, which
        is what the ladder reads when it decides what the last thing said was.

        The threshold is below the cadence floor on purpose: two genuine utterances are at least
        ``MIN_GAP_SECONDS`` apart, so a repeat inside this window cannot be real speech.
        """
        for earlier in reversed(self.said[-10:]):
            if earlier.speaker != entry.speaker or earlier.text != entry.text:
                continue
            if abs((earlier.at - entry.at).total_seconds()) < DEDUPE_SECONDS:
                return
        self.said.append(entry)
        if self.on_say is not None:
            self.on_say(entry)
        if len(self.said) > self.window * 4:
            self.said = self.said[-self.window :]
        if entry.is_human:
            self.human_last_at = entry.at
        else:
            self.last_spoke[entry.speaker] = entry.at

    def say(
        self,
        speaker: str,
        text: str,
        at: datetime,
        kind: str = "chat",
        trail: str = "",
        turn: str = "",
    ) -> Said:
        entry = Said(speaker=speaker, text=text, at=at, kind=kind, trail=trail, turn=turn)
        self.add(entry)
        return entry
    def tail(self, count: int | None = None) -> tuple[Said, ...]:
        """The last few messages, oldest first -- what a friend is responding to."""
        return tuple(self.said[-(count or self.window) :])

    @property
    def last(self) -> Said | None:
        return self.said[-1] if self.said else None

    def quiet_for(self, speaker: str, now: datetime) -> timedelta:
        """How long since this friend spoke. A friend who has never spoken is infinitely overdue."""
        last = self.last_spoke.get(speaker)
        if last is None:
            return timedelta(days=365)
        return now - last

    def spoke_recently(self, speaker: str, now: datetime, within: timedelta) -> bool:
        return self.quiet_for(speaker, now) < within

    def said_by_others(self, speaker: str, count: int = 3) -> tuple[Said, ...]:
        """The last few things somebody *else* said -- the material a reply can be built from."""
        others = [entry for entry in self.said if entry.speaker != speaker]
        return tuple(others[-count:])
