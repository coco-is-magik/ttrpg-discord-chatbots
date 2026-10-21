"""Is this text, voice, an image, an embed, or a system notice?

He cannot see pictures (there is no vision anywhere in this project), so the honest answer for an
image is "image, not visible" -- which the floor can turn into "can't see it, tell me".
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Modality, Utterance


def classify(utterance: Utterance) -> Modality:
    """What kind of message is this, most specific first."""
    if utterance.speaker == "system":
        return "system"
    if utterance.modality == "voice":
        return "voice"
    if utterance.attachments:
        return "image"
    if utterance.embeds:
        return "embed"
    return "text"
