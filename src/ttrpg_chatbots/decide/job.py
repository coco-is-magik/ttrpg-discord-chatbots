"""Which job owns this turn?

Exactly one. A greeting does not also offer a hook; a hook does not also tell the story. This is the
module that stops a reply from trying to be three things at once.

The one piece of knowledge it needs from outside is whether there is anything to say at all:
`about_me` with no life is not a hook, and `about_world` with nothing to draw on is not an
explanation. Both become `hedge` -- a short, honest, *useful* reply rather than a refusal.
"""

from __future__ import annotations

from ttrpg_chatbots.conv.types import Intent, Job, Phase


def choose(
    *,
    intent: Intent,
    phase: Phase,
    depth: int = 0,
    known: str = "",
    story: str = "",
    point: bool = False,
    theirs: bool = False,
) -> Job:
    """The one job this turn does.

    `known` says *what kind* of thing he can draw on, because they are not interchangeable:
    `"self"` is his own life (which answers "what are you up to" and "why?"), `"world"` is a subject
    he has something to say about, and `"fact"` is something the other person told him -- which is
    never an answer about the world, only a reason to ask after it.

    Depth deliberately does **not** turn a hook into an explanation. Measured live: "what are you up
    to" arrived after a long message, the conversation was already deep, and the answer was a reason
    instead of the thing he is doing. Depth belongs to the *follow-up* ("why?"), not to a fresh
    question about his day.
    """
    if point:
        # The point of a story he just told is an explanation, not another story. Getting this
        # wrong told the same story twice when asked what it meant.
        return "explain"
    if story in ("asked", "follow_up"):
        # They asked about something that happened, or asked a question about the thing he just
        # offered. That is stronger evidence than the lexicon, which does not know the difference
        # between "how did the fence go" and "what is the plot of dune" -- both are unmatched
        # questions to it, and only one of them is a story.
        return "tell_story"
    if story == "leaned_in" and intent in ("about_me", "explain_me", "remark"):
        # Unprompted, so the ordinary job keeps a say: two long turns is not a licence to answer a
        # question about the world with the deer.
        return "tell_story"
    if intent == "greet":
        return "greet"
    if intent == "complain":
        return "mirror"
    if intent == "comfort":
        return "reassure"
    if intent == "decline":
        return "close"
    if intent == "remark":
        # A statement about *their own* thing that he knows about gets his answer about it: measured
        # live, "my plant is dying" was acknowledged with "oh" while his plant line ("oh no, i am
        # sorry. tell me what the leaves look like") sat unused. The possessive is what separates it
        # from news about the world -- "the train was late again" is their complaint, not their plant,
        # and answering it with his own train line was a non-sequitur ("i go when i can").
        return "explain" if known == "world" and theirs else "noted"
    if intent == "agree":
        # "yeah it is pretty good" is somebody agreeing with themselves out loud, and the answer is a
        # note ("nice"), not a thank-you reply. Measured: mapping both here produced "no worries" in
        # reply to an agreement, which reads as a bot that mistook what it was being told.
        return "noted"
    if intent == "meta":
        # Thanks and apologies: the two moves that have a stock reply.
        return "acknowledge"
    if intent in ("about_me", "plans"):
        return "offer_hook" if known == "self" else "hedge"
    if intent == "explain_me":
        return "explain" if known == "self" else "hedge"
    if intent == "about_world":
        return "explain" if known == "world" else "hedge"
    if intent == "joke":
        return "mirror"
    return "acknowledge"
