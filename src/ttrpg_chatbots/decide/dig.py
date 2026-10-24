"""Taking a hook.

The log said it plainly: every line was an offer nobody took.

    Otto:   i have been rearranging my shelf
    Terry:  nice
    Otto:   re- rearranging my shelf
    Crusty: Oh, that is lovely
    Terry:  ah right

Five turns, and the conversation never left the entry point. `"what do you put on it?"` never happened. That
is not a wording problem -- the words are fine -- it is that nothing in the ladder can *reach* the thing that
was offered. `ask_back` hands the turn back ("what about you?"), `follow_up` asks a follow-up about *them*
("how long have you been at that?"), and neither can ask about the shelf, because a question about a shelf
needs material about shelves.

So this module does one thing: given a hook that was offered and the domains the friend knows, produce the
question that takes it. The answering half (`answer_for`) says which aspect he was asked about, so he can
answer from his own material for that aspect rather than changing the subject.

The rules are the ones a person follows. He only digs at an *offer* (`offered_hook`), never twice in a row
(that is an interrogation), at his own `question_rate`, and never a question he has just asked.
"""

from __future__ import annotations

from dataclasses import dataclass

from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.reply.domains import Aspect, Domain, DomainBook

#: Asking about somebody's own thing is easier than asking cold, so the rate is nudged up -- the same bonus
#: `follow_up` uses, for the same reason: they have just handed you something to ask about.
OFFER_BONUS = 1.5


@dataclass(frozen=True)
class Dig:
    """A question worth asking, and what it is about."""

    question: str
    domain: Domain
    aspect: Aspect

    @property
    def about(self) -> str:
        """How the turn records what it was about: ``<domain>:<aspect>``.

        Written onto the turn's act so the *answering* side knows what it was asked, which is the whole
        mechanism -- a question like "what is on it?" names nothing, so the text cannot carry it.
        """
        return f"{self.domain.id}:{self.aspect.name}"


def _last_bot_turn(turns: tuple[Turn, ...]) -> Turn | None:
    for turn in reversed(turns):
        if turn.is_bot:
            return turn
        return None
    return None


def _act(turn: Turn | None) -> list[str]:
    if turn is None:
        return []
    return (turn.act or "").split("|")


def answer_for(*, turns: tuple[Turn, ...], domains: DomainBook | None) -> tuple[Domain, Aspect] | None:
    """If the last thing said was a dig at him, which aspect of which domain was it about."""
    if not domains:
        return None
    parts = _act(_last_bot_turn(turns))
    if len(parts) < 3 or parts[0] != "ladder" or parts[1] != "dig":
        return None
    identifier, _, aspect_name = parts[2].partition(":")
    domain = domains.domains.get(identifier)
    if domain is None:
        return None
    aspect = domain.aspects.get(aspect_name)
    if aspect is None:
        return None
    return domain, aspect


def question_for(
    *,
    turns: tuple[Turn, ...],
    domains: DomainBook | None,
    offered_hook: bool,
    question_rate: float,
    asked_recently: tuple[str, ...] = (),
    roll: float | None = None,
) -> Dig | None:
    """The question that takes the hook they just offered, or ``None``.

    ``roll`` is the dice, passed in rather than drawn, so a test can force either side of the threshold.
    """
    if not domains or not offered_hook:
        return None
    if question_rate <= 0:
        return None

    last = _last_bot_turn(turns)
    parts = _act(last)
    if len(parts) >= 2 and parts[1] == "dig":
        # He asked the last question himself. Two in a row is an interview.
        return None

    offered = (last.text if last is not None else "").strip()
    if not offered:
        return None
    found = domains.find(offered)
    if found is None:
        return None
    domain, aspect = found
    if not domain.answers.get(aspect.name) and not aspect.questions:
        return None

    chance = min(1.0, question_rate * OFFER_BONUS)
    if roll is not None and roll > chance:
        return None

    choices = domains.questions(aspect, avoid=asked_recently)
    if not choices:
        # Every question for this aspect has been asked recently: better to say nothing than to repeat.
        return None
    index = 0 if roll is None else int(roll * 10_000) % len(choices)
    return Dig(question=choices[index], domain=domain, aspect=aspect)
