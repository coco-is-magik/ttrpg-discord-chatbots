"""Is there a picture, and can he see it?

No. There is no vision model in this project, and pretending otherwise would produce a bot that
describes photographs it has never seen. The value of this module is that the *fact* of an
attachment is available to the reply, so he can say "can't see it from here" instead of answering
the text as though the picture were not there.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Attachment, Utterance


def describe(utterance: Utterance) -> Attachment | None:
    """The attachment, if there is one. ``visible`` is always False: he has no eyes."""
    if not utterance.attachments:
        return None
    return Attachment(kind="file", count=utterance.attachments, visible=False)
