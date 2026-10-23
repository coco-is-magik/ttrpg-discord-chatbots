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
    Event,
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
    recall as recall_rung,
    story as story_rung,
    values,
    variant,
    who,
)
from ttrpg_chatbots.decide import persona_fit
from ttrpg_chatbots.decide.shelf import Shelf
from ttrpg_chatbots.decide.subject import Subject
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.govern.trace import Recorder
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.perceive.clock import Moment, read_clock
from ttrpg_chatbots.perceive.inbound import looks_like_question
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
    # A separate move from "what are you up to": this one is an opening for a plan, and it is the
    # only place an invitation belongs.
    social.SOCIAL_PLANS: "plans",
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
    facts: tuple[Fact, ...] = ()
    subject: Subject | None = None
    events: tuple[Event, ...] = ()
    told: tuple[tuple[str, int], ...] = ()
    offered_hook: bool = False
    about: str = ""
    just_told: str = ""
    gap_bucket: str = "fresh"
    named: tuple[str, ...] = ()


def _has_plan(scene: Scene) -> bool:
    """Whether he has something in mind to invite them to.

    Only when the conversation is about his day: a plan is an invitation, and an invitation
    nobody asked for is a pitch.
    """
    return bool(scene.life and scene.life.plan(scene.day))


def _about(*, scene: Scene, telling) -> str:
    """What this turn was about, carried to the next one as ``topic|story_id``.

    The conversation is the only place this lives: a story told two turns ago is remembered because it
    is written on the act of his own turn, which is why a follow-up can reach the point and a question
    about the fence reaches the fence.
    """
    topic = ""
    story_id = ""
    if telling is not None:
        topic = telling.story.topic
        if telling.mode != "point":
            story_id = telling.story.id
    elif scene.subject is not None:
        topic = scene.subject.tag
    elif scene.life is not None and scene.life.current(scene.day) is not None:
        topic = scene.life.current(scene.day).topic
    return f"{topic}|{story_id}"


def _day_key(day: date | str | None) -> str:
    """The day a fact was last raised, in the same shape the memory file stores it."""
    if day is None:
        return date.today().isoformat()
    return day.isoformat() if isinstance(day, date) else str(day)


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


@dataclass(frozen=True)
class Plan:
    """What the ladder intends to do, before any words exist.

    Split out of `reply` so the *routing* question -- "does the ladder have anything for this
    message?" -- is answered by the same code that answers the message. Measured: a question about a
    dog he remembers was routed to the old classifier by a hardcoded list of intents, and came back
    as the old corpus's reply.
    """

    job: str
    book: Phrasebook
    where: str
    budget: object
    depth: int
    remembered: object = None
    telling: object = None


def plan(
    *,
    scene: Scene,
    book: Phrasebook | None = None,
    books: Shelf | None = None,
) -> Plan | Abstain:
    """Which job owns this turn, with its phrasebook -- or why there is none."""
    intent = intent_of(scene.utterance.text)
    spoken = scene.named
    depth = depth_rung.read(scene.turns)
    asked_why = social.match_intent(scene.utterance.text) == social.SOCIAL_WHY
    telling = story_rung.choose(
        text=scene.utterance.text,
        life=scene.life,
        depth=depth,
        told=dict(scene.told),
        offered_hook=scene.offered_hook,
        topic=scene.about,
        just_told=scene.just_told,
    )
    where = phase.read(
        turns_today=len([turn for turn in scene.turns if not turn.is_bot]),
        closing=intent == "decline",
        named_subject=bool(spoken),
        depth=depth,
        asked_why=asked_why,
        known_subject=scene.subject is not None,
        story=telling is not None,
    )
    budget = length.budget(
        their_words=len(scene.utterance.text.split()), phase=where, story=telling is not None
    )

    allowed = floor.decide(addressed=scene.addressed, asleep=scene.asleep, budget=budget)
    if isinstance(allowed, Abstain):
        return allowed

    # What he remembers, and whether now is the moment to show it. Gated in `decide.recall`: they
    # raised it, or it is the start of a session and it is a kind worth asking about.
    remembered = recall_rung.choose(
        text=scene.utterance.text,
        facts=scene.facts,
        bucket=scene.gap_bucket,
        today=_day_key(scene.day),
    )

    # What kind of thing he can draw on, per intent -- because they are not interchangeable. His own
    # life answers "what are you up to"; a fact the other person told him never answers a question
    # about the world, it only gives him a reason to ask after it.
    if intent in ("about_me", "explain_me", "plans"):
        known = "self" if scene.life else ""
    elif intent in ("about_world", "remark"):
        # A remark that names a subject has something to draw on, and `decide/job` decides whether to
        # use it -- it also wants to know whether the subject is *theirs*, which is the difference
        # between "my plant is dying" and "the train was late again".
        known = "world" if scene.subject is not None else ""
    else:
        known = ""

    # The story gate: three ways in, and none of them is "he felt like it". When it says yes the
    # story owns the turn, which is why it is decided here rather than inside a phrasebook.
    words = {word.strip(".,!?;:'").lower() for word in scene.utterance.text.split()}
    theirs = bool(words & {"my", "our", "mine", "ours"})
    chosen = job.choose(
        intent=intent,
        phase=where,
        depth=depth,
        known=known,
        theirs=theirs,
        story="" if telling is None or telling.mode == "point" else telling.mode,
        point=telling is not None and telling.mode == "point",
    )

    chosen_book = book if book is not None else (books.for_job(chosen) if books else None)
    if chosen_book is None:
        return Abstain(f"no phrasebook for {chosen}")
    if chosen_book.job != chosen:
        # One phrasebook per job, and no borrowing across them. This is the phase boundary that
        # makes "prove greet before moving on" true instead of aspirational.
        return Abstain(f"the {chosen_book.job} phrasebook does not do {chosen}")
    return Plan(
        job=chosen,
        book=chosen_book,
        where=where,
        budget=budget,
        depth=depth,
        remembered=remembered,
        telling=telling,
    )


def would_answer(*, scene: Scene, books: Shelf | None = None) -> bool:
    """Whether the ladder has a job for this message. The bot asks before it picks a path."""
    return isinstance(plan(scene=scene, books=books), Plan)


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

    decided = plan(scene=scene, book=book, books=books)
    if isinstance(decided, Abstain):
        trace.add("plan", decided.reason)
        return decided
    chosen, chosen_book = decided.job, decided.book
    where, budget, depth = decided.where, decided.budget, decided.depth
    remembered = decided.remembered
    telling = decided.telling
    trace.add("phase", where)
    trace.add("length", budget)
    trace.add("floor", "Speak(reason='addressed')")
    trace.add("job", chosen)
    trace.add("subject", f"{scene.subject.tag} ({scene.subject.distance:.2f})" if scene.subject else "nothing")
    trace.add("events", ", ".join(event.label for event in scene.events) or "nothing")
    trace.add("recall", f"{remembered.fact.key} ({remembered.mode})" if remembered else "nothing")
    trace.add("story", f"{telling.story.id} ({telling.mode})" if telling else "nothing")
    trace.add("about", _about(scene=scene, telling=telling))

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
        recall=remembered.mode if remembered else "",
        subject=scene.subject is not None,
        event=bool(scene.events),
        plan=_has_plan(scene) and intent == "plans",
        story=telling is not None,
        point=telling is not None and telling.mode == "point",
    )

    ledger = recent if recent is not None else Recent()
    template = variant.choose(
        book=chosen_book, family=register, recent=ledger.recent(), budget=budget
    )
    if template is None and register in ("recall", "event", "story"):
        # A special phrasing that does not fit the budget -- "hey" is a three-word opening and a
        # recall line is five; "what are you up to" is seven and an event clause is nine. Fall
        # back to the ordinary phrasing rather than going silent: measured, this was the difference
        # between greeting him and hearing nothing.
        register = family_rung.choose(
            job=chosen,
            relationship=scene.relationship,
            part_of_day=moment.part_of_day,
            depth=depth,
            subject=scene.subject is not None,
        )
        template = variant.choose(
            book=chosen_book, family=register, recent=ledger.recent(), budget=budget
        )
        if remembered is not None:
            trace.add("recall", f"{remembered.fact.key} (no room)")
    trace.add("family", register)
    trace.add("variant", template or "none")
    if template is None:
        return Abstain(f"nothing to say for {chosen} in a {register} voice")

    slots = values.build(
        job=chosen,
        life=scene.life,
        day=scene.day,
        name=scene.name,
        subject=scene.named[0] if scene.named else "",
        facts=scene.facts,
        remembered=remembered.fact if remembered else None,
        subject_text=scene.subject.text if scene.subject else "",
        events=scene.events,
        story=telling.story if telling else None,
        point=telling is not None and telling.mode == "point",
        plan=scene.life.plan(scene.day) if scene.life else None,
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
    verdict = audition.judge(
        text=typed,
        budget=budget,
        repeated=ledger.seen_last(typed),
        story=telling is not None,
        fit=persona_fit.read(typed, story=telling is not None),
    )
    trace.add("audition", verdict.reason or "ok")
    if not verdict.ok:
        return Abstain(verdict.reason)

    ledger.remember(typed)
    return line_rung.assemble(text=typed, trail=trace.trail)
