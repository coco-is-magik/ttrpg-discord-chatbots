"""Compression-classified, in-character replies.

No LLM involved: knowledge is ranked with Normalised Compression Distance and
rendered through madlib templates, gated by the tags each character may know. Context
(the last few turns, and which act plausibly follows which) is an optional third input.
"""

from ttrpg_chatbots.reply.context import Context, Turn
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.ncd import classify, ncd, rank
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.transitions import TransitionError, TransitionModel
from ttrpg_chatbots.reply.types import (
    Character,
    Classification,
    DatasetError,
    KnowledgeItem,
    Match,
    Reply,
    ReplyError,
    ReplyUnavailable,
    ResponseTemplate,
    TagScore,
    UnknownCharacter,
    World,
)

__all__ = [
    "Character",
    "Classification",
    "Context",
    "DatasetError",
    "KnowledgeItem",
    "Match",
    "Reply",
    "ReplyError",
    "ReplyUnavailable",
    "Replier",
    "ResponseTemplate",
    "TagScore",
    "TransitionError",
    "TransitionModel",
    "Turn",
    "UnknownCharacter",
    "World",
    "classify",
    "load_world",
    "ncd",
    "rank",
]
