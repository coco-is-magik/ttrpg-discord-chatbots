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
