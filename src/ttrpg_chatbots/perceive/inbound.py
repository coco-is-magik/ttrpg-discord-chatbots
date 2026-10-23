"""What arrived, in a sane shape.

One job: turn the handful of things Discord hands over into an `Utterance` with the mention tokens
stripped out. Every module downstream reads `Utterance` and never has to know that "<@156246… hey"
is how a mention actually looks.
"""

from __future__ import annotations

import re
from datetime import datetime

from ttrpg_chatbots.conv.types import Utterance

_MENTION = re.compile(r"<@!?\d+>")

# Words that open a question, so a missing question mark does not turn "what is the plot of dune"
# into a statement, and "what are you up to" into something he can answer with a story. Deliberately
# short: a false question costs a hedge, a false statement costs a shrug.
QUESTION_OPENERS = frozenset(
    {
        "what", "why", "how", "who", "when", "where", "which", "whose",
        "do", "does", "did", "is", "are", "was", "were", "can", "could",
        "would", "should", "will", "anyone", "anybody", "tell",
    }
)


#: What somebody says *before* the question. Measured: "also do you like trains" was heard as a
#: statement, so a direct question about his own subject got "ah" instead of an answer.
LEAD_INS = frozenset(
    {
        "also", "so", "and", "but", "ok", "okay", "well", "oh", "um", "uh", "hmm", "then",
        "now", "alright", "right", "just", "anyway",
    }
)


def looks_like_question(text: str) -> bool:
    """Whether this is a question, with or without a question mark.

    Only the *first* meaningful word is consulted, not any of the first few: "i was thinking about
    getting a plant" contains "was" and is a statement, while "also do you like trains" opens with a
    filler and is a question.
    """
    stripped = (text or "").strip()
    if stripped.endswith("?"):
        return True
    for word in stripped.lower().replace(",", " ").split():
        if word in LEAD_INS:
            continue
        return word in QUESTION_OPENERS
    return False


def strip_mentions(text: str) -> str:
    """Remove mention tokens but keep the words: "<@1> hey" is "hey"."""
    return " ".join(_MENTION.sub(" ", text or "").split())


def read(
    *,
    text: str,
    speaker: str = "",
    channel: str = "",
    at: datetime | None = None,
    reply_to: str | None = None,
    attachments: int = 0,
    embeds: int = 0,
) -> Utterance:
    """Build the one input type everything else consumes."""
    return Utterance(
        text=strip_mentions(text),
        speaker=speaker,
        channel=channel,
        at=at,
        reply_to=reply_to,
        attachments=int(attachments or 0),
        embeds=int(embeds or 0),
    )
