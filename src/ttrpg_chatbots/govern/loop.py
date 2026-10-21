"""The only place that knows the order.

Eight rungs, each a module that answers one question: floor, phase, job, who, form, family, variant,
render. This file contains no wording and no rules of its own -- if a decision is being made here, it
is in the wrong module.

Anything the ladder cannot render this turn is an `Abstain`. Silence is a valid answer, and it is
how a half-built pipeline stays usable while the rest of it is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ttrpg_chatbots.conv.types import (
    Abstain,
    Addressee,
    Intent,
    Line,
    Relationship,
    Situation,
    Utterance,
)
from ttrpg_chatbots.decide import family as family_rung
from ttrpg_chatbots.decide import floor, form, job, length, phase, variant, who
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.govern.trace import Recorder
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.render import audition, line as line_rung, trim, typing
from ttrpg_chatbots.reply import intents as social
from ttrpg_chatbots.reply.context import Turn
from ttrpg_chatbots.reply.style import Style

# The seam between the lexicon's tags and this layer's intents. A tag it does not know becomes
# "meta", which asks the ladder for an acknowledgement rather than an explanation.
_INTENT: dict[str, Intent] = {
    social.SOCIAL_GREETING: "greet",
    social.SOCIAL_HOWAREYOU: "about_me",
    social.SOCIAL_SMALLTALK: "about_me",
    social.SOCIAL_PRESENCE: "about_me",
    social.SOCIAL_PLANS: "about_me",
    social.SOCIAL_ROUGH: "complain",
    social.SOCIAL_COMFORT: "meta",
    social.SOCIAL_THANKS: "meta",
    social.SOCIAL_APOLOGY: "meta",
    social.SOCIAL_AGREEMENT: "agree",
    social.SOCIAL_GOODBYE: "decline",
    social.SOCIAL_WHY: "about_world",
}


@dataclass(frozen=True)
class Scene:
    """Everything the ladder is allowed to know, gathered by the caller.

    Facts only: what arrived, whether he was addressed, what time it is, how well he knows the
    person. No decisions -- those belong to the rungs.
    """

    utterance: Utterance
    addressed: Addressee = "unaddressed"
    asleep: bool = False
    moment: Moment | None = None
    relationship: Relationship = field(default_factory=Relationship)
    situation: Situation = field(default_factory=Situation)
    turns: tuple[Turn, ...] = ()
    table_active: bool = False


def intent_of(text: str) -> Intent:
    """Which intent the lexicon hears, mapped into this layer's vocabulary."""
    tag = social.match_intent(text)
    return _INTENT.get(tag or "", "meta")


def reply(
    *,
    scene: Scene,
    book: Phrasebook,
    style: Style | None = None,
    recent: Recent | None = None,
) -> Line | Abstain:
    """Run the ladder. Returns a line, or the reason there is not one."""
    trace = Recorder()
    moment = scene.moment or read_clock()
    intent = intent_of(scene.utterance.text)
    trace.add("intent", intent)

    where = phase.read(
        turns_today=len(scene.turns),
        closing=intent == "decline",
        named_subject=False,
        depth=0,
    )
    trace.add("phase", where)

    budget = length.budget(their_words=len(scene.utterance.text.split()), phase=where)
    trace.add("length", budget)

def reply(
    *,
    scene: Scene,
    book: Phrasebook,
    style: Style | None = None,
    recent: Recent | None = None,
) -> Line | Abstain:
    """Run the ladder. Returns a line, or the reason there is not one."""
    trace = Recorder()
    moment = scene.moment or read_clock()
    intent = intent_of(scene.utterance.text)
    trace.add("intent", intent)

    where = phase.read(
        turns_today=len(scene.turns),
        closing=intent == "decline",
        named_subject=False,
        depth=0,
    )
    trace.add("phase", where)

    budget = length.budget(their_words=len(scene.utterance.text.split()), phase=where)
    trace.add("length", budget)

    allowed = floor.decide(addressed=scene.addressed, asleep=scene.asleep, budget=budget)
    trace.add("floor", allowed)
    if isinstance(allowed, Abstain):
        return allowed

    chosen = job.choose(intent=intent, phase=where, depth=0)
    trace.add("job", chosen)
    if chosen != book.job:
        # One phrasebook per job, and no borrowing across them. This is the phase boundary that
        # makes "prove greet before moving on" true instead of aspirational.
        return Abstain(f"the {book.job} phrasebook does not do {chosen}")

    speaker = who.choose(situation=scene.situation.kind, table_active=scene.table_active)
    trace.add("who", speaker)

    shape = form.choose(job=chosen, budget=budget)
    trace.add("form", shape)

    register = family_rung.choose(
        job=chosen, relationship=scene.relationship, part_of_day=moment.part_of_day
    )
    trace.add("family", register)

    ledger = recent if recent is not None else Recent()
    text = variant.choose(book=book, family=register, recent=ledger.recent(), budget=budget)
    trace.add("variant", text or "none")
    if text is None:
        return Abstain(f"nothing to say for {chosen} in a {register} voice")

    trimmed = trim.enforce(text, budget)
    trace.add("trim", trimmed or "over budget")
    if trimmed is None:
        return Abstain("over budget")

    typed = typing.apply(trimmed, style)
    verdict = audition.judge(text=typed, budget=budget, repeated=ledger.seen_last(typed))
    trace.add("audition", verdict.reason or "ok")
    if not verdict.ok:
        return Abstain(verdict.reason)

    ledger.remember(typed)
    return line_rung.assemble(text=typed, trail=trace.trail)
