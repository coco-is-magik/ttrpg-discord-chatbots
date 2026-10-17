"""Compression-classified, in-character replies.

No LLM involved: knowledge is ranked with Normalised Compression Distance and
rendered through madlib templates, gated by the tags each character may know.
"""

from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.ncd import classify, ncd, rank
from ttrpg_chatbots.reply.replier import Replier
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
    "DatasetError",
    "KnowledgeItem",
    "Match",
    "Reply",
    "ReplyError",
    "ReplyUnavailable",
    "Replier",
    "ResponseTemplate",
    "TagScore",
    "UnknownCharacter",
    "World",
    "classify",
    "load_world",
    "ncd",
    "rank",
]
