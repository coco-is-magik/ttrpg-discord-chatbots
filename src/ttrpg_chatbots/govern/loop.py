"""The only place that knows the order.

Eight rungs, each a module that answers one question: floor, phase, job, who, form, family, variant,
render. This file contains no wording and no rules of its own -- if a decision is being made here, it
is in the wrong module.

Anything the ladder cannot render this turn is an `Abstain`. Silence is a valid answer, and it is
how a half-built pipeline stays usable while the rest of it is written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

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
from ttrpg_chatbots.decide import (
    depth as depth_rung,
    floor,
    form,
    job,
    length,
    phase,
    values,
    variant,
    who,
)
from ttrpg_chatbots.decide.shelf import Shelf
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.govern.trace import Recorder
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.render import audition, fill, line as line_rung, trim, typing
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
    social.SOCIAL_COMFORT: "comfort",
    social.SOCIAL_THANKS: "meta",
    social.SOCIAL_APOLOGY: "meta",
    social.SOCIAL_AGREEMENT: "agree",
    social.SOCIAL_GOODBYE: "decline",
    # "why?" is a question about whatever is under discussion -- and when he has just said something,
    # that thing is him. Mapping it to the world sent it to a hedge instead of the reason.
    social.SOCIAL_WHY: "explain_me",
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
    life: Life | None = None
    name: str = ""
    day: date | str | None = None
    facts: tuple[tuple[str, str], ...] = ()
    named: tuple[str, ...] = ()


# Words that open a question, so a missing question mark does not turn "what is the plot of dune"
# into a statement. Deliberately a short list: a false question is a hedge, a false statement is a
# "yeah", and the first is the cheaper mistake.
QUESTION_OPENERS = frozenset(
    {
        "what", "why", "how", "who", "when", "where", "which", "whose",
        "do", "does", "did", "is", "are", "was", "were", "can", "could",
        "would", "should", "will", "anyone", "anybody", "tell",
    }
)


def looks_like_question(text: str) -> bool:
    """Whether this is a question, with or without a question mark."""
    stripped = text.strip()
    if stripped.endswith("?"):
        return True
    first = stripped.split(" ", 1)[0].lower().strip(",.")
    return first in QUESTION_OPENERS


def intent_of(text: str) -> Intent:
    """Which intent the lexicon hears, mapped into this layer's vocabulary.

    What the lexicon does not recognise splits in two, and the difference matters: a **question** is
    something he cannot answer, so it hedges; a **statement** is somebody talking and there is nothing
    to add, so it is noted. Treating both the same produced "?" in reply to "i have been rebuilding a
    fence myself this month", which reads as a bot that was not listening.
    """
    tag = social.match_intent(text)
    if tag is None:
        return "about_world" if looks_like_question(text) else "remark"
    return _INTENT.get(tag, "remark")


def reply(
    *,
    scene: Scene,
    book: Phrasebook | None = None,
    books: Shelf | None = None,
    style: Style | None = None,
    recent: Recent | None = None,
) -> Line | Abstain:
    """Run the ladder. Returns a line, or the reason there is not one.

    Either one `book` (a single-phase caller such as the greet-only facade) or a `books` shelf. With
    a shelf the job picks its own phrasebook, which is what lets phases be added one file at a time.
    """
    trace = Recorder()
    moment = scene.moment or read_clock()
    intent = intent_of(scene.utterance.text)
    trace.add("intent", intent)

    spoken = scene.named
    depth = depth_rung.read(scene.turns)
    asked_why = social.match_intent(scene.utterance.text) == social.SOCIAL_WHY
    where = phase.read(
        turns_today=len([turn for turn in scene.turns if not turn.is_bot]),
        closing=intent == "decline",
        named_subject=bool(spoken),
        depth=depth,
        asked_why=asked_why,
    )
    trace.add("phase", where)

    budget = length.budget(their_words=len(scene.utterance.text.split()), phase=where)
    trace.add("length", budget)

    allowed = floor.decide(addressed=scene.addressed, asleep=scene.asleep, budget=budget)
    trace.add("floor", allowed)
    if isinstance(allowed, Abstain):
        return allowed

    # "Known" is per intent, not global: having a life makes "what are you up to" answerable, but it
    # says nothing about the Roman republic. Until world knowledge is wired in as a tool, a question
    # about the world hedges -- which is honest, and better than a phrasebook bluffing.
    known = (
        (bool(scene.life) or bool(scene.facts))
        if intent in ("about_me", "explain_me")
        else False
    )
    chosen = job.choose(intent=intent, phase=where, depth=depth, known=known)
    trace.add("job", chosen)

    chosen_book = book if book is not None else (books.for_job(chosen) if books else None)
    if chosen_book is None:
        return Abstain(f"no phrasebook for {chosen}")
    if chosen_book.job != chosen:
        # One phrasebook per job, and no borrowing across them. This is the phase boundary that
        # makes "prove greet before moving on" true instead of aspirational.
        return Abstain(f"the {chosen_book.job} phrasebook does not do {chosen}")


    speaker = who.choose(situation=scene.situation.kind, table_active=scene.table_active)
    trace.add("who", speaker)

    shape = form.choose(job=chosen, budget=budget)
    trace.add("form", shape)

    register = family_rung.choose(
        job=chosen,
        relationship=scene.relationship,
        part_of_day=moment.part_of_day,
        depth=depth,
    )
    trace.add("family", register)

    ledger = recent if recent is not None else Recent()
    template = variant.choose(
        book=chosen_book, family=register, recent=ledger.recent(), budget=budget
    )
    trace.add("variant", template or "none")
    if template is None:
        return Abstain(f"nothing to say for {chosen} in a {register} voice")

    slots = values.build(
        job=chosen,
        life=scene.life,
        day=scene.day,
        name=scene.name,
        subject=spoken[0] if spoken else "",
        facts=dict(scene.facts),
    )
    text = fill.render(template, slots)
    if text is None:
        return Abstain("missing " + ",".join(values.missing(template, slots)))
    trace.add("fill", text)

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
