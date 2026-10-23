"""Good or bad, and about what?

Separate from tone because they disagree: "great, another inspection" is positive wording, negative
feeling, flat delivery. Polarity comes from a short lexicon; the target comes from the pronoun in
front of it, because "my day" and "your day" are different facts.
"""

from __future__ import annotations

import re

from ttrpg_chatbots.conv.types import Sentiment
from ttrpg_chatbots.reply.text import normalise_typing

_POSITIVE = re.compile(
    r"\b(?:good|great|nice|love|loved|brilliant|happy|glad|fun|excellent|best|bought|getting|new|"
    r"started|found|fixed)\b"
)
#: Words that make a message bad news. Measured: "my plant is dying" read as *neutral*, so nothing
#: could tell it apart from "i am getting a plant" and the sympathy line was picked for both.
_NEGATIVE = re.compile(
    r"\b(?:bad|awful|terrible|hate|hated|sick|tired|wrecked|rough|worst|annoying|dying|died|dead|"
    r"broke|broken|killed|ruined|failed|lost|stuck|missed|late)\b"
)
_SELF = re.compile(r"\b(?:i|i'm|my|me|myself)\b")
_YOU = re.compile(r"\b(?:you|your|you're|yours)\b")


def read(text: str) -> Sentiment:
    """Polarity and target, or neutral about nothing."""
    cleaned = normalise_typing(text)
    positive = bool(_POSITIVE.search(cleaned))
    negative = bool(_NEGATIVE.search(cleaned))
    if positive and negative:
        polarity = "mixed"
    elif positive:
        polarity = "positive"
    elif negative:
        polarity = "negative"
    else:
        polarity = "neutral"
    target = "it"
    if _SELF.search(cleaned):
        target = "self"
    if _YOU.search(cleaned):
        target = "you"
    return Sentiment(polarity=polarity, target=target)
