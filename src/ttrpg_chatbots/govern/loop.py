"""The only place that knows the order.

Eight rungs, each a module that answers one question: floor, phase, job, who, form, family, variant,
render. This file contains no wording and no rules of its own -- if a decision is being made here, it
is in the wrong module.

Anything the ladder cannot render this turn is an `Abstain`. Silence is a valid answer, and it is
how a half-built pipeline stays usable while the rest of it is written.
"""

from __future__ import annotations

import re

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
from ttrpg_chatbots.decide import persona_fit, reciprocate
from ttrpg_chatbots.decide.shelf import Shelf
from ttrpg_chatbots.decide.subject import Subject
from ttrpg_chatbots.decide.variant import Phrasebook
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.govern.trace import Recorder
from ttrpg_chatbots.life.state import Life
from ttrpg_chatbots.memory.long import Fact
from ttrpg_chatbots.perceive import sentiment as sentiment_rung
from ttrpg_chatbots.perceive import tone as tone_rung
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
    # A refusal, which finally makes the `decline` job reachable: it was in the vocabulary and never
    # chosen, because the *intent* named `decline` is a goodbye (social:goodbye) and goes to `close`.
    social.SOCIAL_REFUSAL: "refuse",
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
    #: How often he would rather hand the turn back than answer with a bare acknowledgement. The
    #: persona's number, not the ladder's: it is a property of the person, not of the turn.
    question_rate: float = 0.0
    #: The persona's own length multiplier. See `decide.length.budget`.
    verbosity: float = 1.0


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
        if looks_like_question(text):
            return "about_world"
        # **Bad news is a move, not a remark.** The lexicon knows a handful of complaints and
        # sympathies; sentiment knows whether the sentence is bad news at all, and it was being read
        # only to *rank* knowledge items -- never to route. Measured on a held-out probe: "my cat died"
        # routed as a neutral remark, was treated as something of theirs to engage with, and got
        # "is it any good?". The target decides which move: about them is sympathy, about the world is
        # a complaint to share.
        feeling = sentiment_rung.read(text)
        if feeling.polarity in ("negative", "mixed"):
            return "complain" if feeling.target == "it" else "comfort"
        return "remark"
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
        their_words=len(scene.utterance.text.split()),
        phase=where,
        story=telling is not None,
        verbosity=scene.verbosity,
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

    # Handing the turn back. `noted` is the job with the least to say ("yeah" to a statement he has
    # nothing to add to), so it is the one worth spending on a question instead -- and whether he does
    # is the persona's `question_rate`, not the ladder's decision. Measured: Otto's brief says he
    # prompts people to keep talking, and before this the rung that decides to hand the turn back was
    # referenced by nothing but its own test.
    if chosen == "noted" and remembered is None:
        # `remembered is None` is deliberate: asking after their dog is a stronger, more specific move
        # than a generic follow-up, and the `noted` book is the one that carries the recall family.
        # Measured: without this guard "my dog is called otis" got "is it any good?".
        tone = tone_rung.read(scene.utterance.text)
        if reciprocate.engage(
            question_rate=scene.question_rate,
            text=scene.utterance.text,
            tone=tone,
            already_asked=_asked_last(scene.turns),
            theirs=_about_them(scene.utterance.text),
            bad_news=sentiment_rung.read(scene.utterance.text).polarity in ("negative", "mixed"),
        ):
            # There is something of theirs to pick up: they answered a question of his, or they said
            # something about themselves. Measured both ways round -- engaging is right, and asking
            # "what about you?" in reply to "i have been rebuilding a fence myself" is not.
            chosen = "follow_up"
        elif reciprocate.hand_back(
            question_rate=scene.question_rate,
            text=scene.utterance.text,
            tone=tone,
            he_spoke=_he_spoke_last(scene.turns),
        ):
            # He has just spoken about himself, so the turn goes back to them.
            chosen = "ask_back"

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


def _about_them(text: str) -> bool:
    """Whether they said something about themselves -- a first-person statement.

    Two signals, and the second is the general one. A first-person pronoun is obvious ("i have been
    rebuilding a fence myself this month", "we got the shed up"). But **chat omits the subject**:
    "sorted the garage out", "went for a run" -- the person is the subject and never says so. A
    past-tense verb in front is that signal, and it is a linguistic category rather than a list of our
    examples, while "the game got cancelled" opens with a determiner and is not about them at all.

    Measured on a held-out probe: without the second signal, every subject-less statement was noted
    rather than engaged with -- 2 of 20 messages, and both of them the kind a friend would pick up.
    """
    words = [word.strip(".,!?;:'\"").lower() for word in (text or "").split()]
    if set(words) & FIRST_PERSON:
        return True
    return bool(words) and _PAST_VERB.match(words[0]) is not None


#: A word that looks like a past-tense verb: regular (`-ed`) or one of the common irregulars. A
#: category, not a topic list -- which is the difference between generalising and overfitting.
_PAST_VERB = re.compile(
    r"^(?:\w+ed|went|got|made|took|saw|did|had|came|gave|bought|sold|found|felt|kept|left|met|ran|"
    r"said|sent|sat|told|thought|wrote|ate|drank|slept|woke|broke|chose|drove|fell|flew|grew|knew|"
    r"lost|paid|put|read|rode|rose|sang|spoke|stood|swam|threw|wore|won|quit|finished|sorted)$"
)

#: Phrasings that carry a *special* reason to be said -- a memory, something on his calendar, a story,
#: an invitation. They are longer than the ordinary register, so they are the ones that may need to fall
#: back to it when the budget is tight.
SPECIAL_REGISTERS = frozenset({"recall", "event", "story", "plan"})

#: The words that make a message about the person saying it.
FIRST_PERSON = frozenset(
    {
        "i", "im", "i'm", "ive", "i've", "id", "i'd", "ill", "i'll",
        "me", "my", "mine", "myself", "we", "we're", "were", "us", "our", "ours",
    }
)


def _he_spoke_last(turns: tuple[Turn, ...]) -> bool:
    """Whether his last turn was about himself -- a hook, an explanation, or a story.

    Read from the act he recorded (`ladder|job|...`), because that is the only place the conversation
    knows what he was doing. This is what makes ``ask_back`` a *hand-back*: it is only natural once he
    has said something about his own day.
    """
    for turn in reversed(turns):
        if not turn.is_bot:
            continue
        parts = (turn.act or "").split("|")
        if len(parts) >= 2 and parts[0] == "ladder":
            return parts[1] in ("offer_hook", "explain", "tell_story")
        return False
    return False


def _asked_last(turns: tuple[Turn, ...]) -> bool:
    """Whether his last turn was already a question. Two in a row is an interrogation.

    **The question mark is not the last character.** The first version tested `endswith("?")`, and the
    style layer appends emoticons after the punctuation -- so "what about you? ^^" read as a statement,
    the rule never fired, and Otto asked the same person twice in a row. Measured in the channel:
    "playing video games" (an answer to his question) was met with "what have you been up to?".

    Asking the *last sentence* instead is what makes this independent of how a friend decorates a line.
    """
    for turn in reversed(turns):
        if not turn.is_bot:
            continue
        text = (turn.text or "").strip()
        return "?" in text.rsplit(".", 1)[-1]
    return False


def would_answer(*, scene: Scene, books: Shelf | None = None) -> bool:
    """Whether the ladder has a job for this message. The bot asks before it picks a path."""
    return isinstance(plan(scene=scene, books=books), Plan)


def _resay(book, register, chosen, scene, budget, style, ledger) -> str | None:
    """A different way of saying the same thing, or nothing if every variant repeats."""
    slots = values.build(
        job=chosen,
        life=scene.life,
        day=scene.day,
        name=scene.name,
        subject=scene.named[0] if scene.named else "",
        facts=scene.facts,
        remembered=None,
        subject_text=scene.subject.text if scene.subject else "",
        events=scene.events,
        story=None,
        point=False,
        plan=scene.life.plan(scene.day) if scene.life else None,
    )
    # The chosen family first, then the rest of the book. A register with two variants runs out on the
    # third ask -- measured with a new relationship, whose `dry` family has "{hook}" and "{short}"
    # and nothing else -- and a different register is a better answer than the identical line.
    order = list(book.variants(register))
    for family in book.families:
        if family != register:
            order.extend(book.variants(family))
    for template in order:
        candidate = fill.render(template, slots)
        if candidate is None:
            continue
        trimmed = trim.enforce(candidate, budget)
        if trimmed is None:
            continue
        typed = typing.apply(trimmed, style)
        if not ledger.seen_last(typed):
            return typed
    return None


def _second_chance(
    *,
    books: Shelf | None,
    book: Phrasebook,
    register: str,
    chosen: str,
    scene: Scene,
    budget: Budget,
    style: Style | None,
    ledger: Recent,
    telling: Any,
    refused: str,
) -> tuple[str, str] | None:
    """Another way of saying it, or a hedge -- because silence is the worst outcome of the three.

    Two steps, in order of preference:

    1. **Another phrasing of the same thing.** Every family in the book, not just the chosen one: a
       reason that ends on a beat in one wording often does not in another.
    2. **A hedge.** If the material itself is the problem -- the activity's reason, the story, the
       fact -- no wording will save it, and `?` or "say more?" is a better answer than nothing. The
       hedge is a different job's book on purpose, and it is the *only* cross-book fallback allowed:
       it says nothing about the subject, so it cannot be wrong about it.

    Returns the line and a label for the trace, or ``None`` to abstain.
    """
    slots = values.build(
        job=chosen,
        life=scene.life,
        day=scene.day,
        name=scene.name,
        subject=scene.named[0] if scene.named else "",
        facts=scene.facts,
        remembered=None,
        subject_text=scene.subject.text if scene.subject else "",
        events=scene.events,
        story=telling.story if telling else None,
        point=telling is not None and telling.mode == "point",
        plan=scene.life.plan(scene.day) if scene.life else None,
    )
    order = list(book.variants(register))
    for family in book.families:
        if family != register:
            order.extend(book.variants(family))
    for template in order:
        text = fill.render(template, slots)
        if text is None:
            continue
        trimmed = trim.enforce(text, budget)
        if trimmed is None:
            continue
        typed = typing.apply(trimmed, style)
        if ledger.seen_last(typed):
            continue
        if not audition.judge(
            text=typed,
            budget=budget,
            repeated=False,
            story=telling is not None,
            fit=persona_fit.read(typed, story=telling is not None),
        ).ok:
            continue
        return typed, f"another phrasing of {chosen}"

    if books is None or chosen == "hedge":
        return None
    hedge = books.for_job("hedge")
    if hedge is None:
        return None
    for family in hedge.families:
        for template in hedge.variants(family):
            text = fill.render(template, slots)
            if text is None or ledger.seen_last(typing.apply(text, style)):
                continue
            trimmed = trim.enforce(text, budget)
            if trimmed is None:
                continue
            return typing.apply(trimmed, style), f"hedged ({refused})"
    return None


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
    if trimmed is None and register in SPECIAL_REGISTERS:
        # A *special* phrasing that does not fit falls back to the ordinary one, rather than going
        # silent. The template stage already did this; the trim stage did not, so a plan line that was
        # one sentence too long for a five-word question produced nothing at all -- measured on
        # "are you free this weekend".
        ordinary = family_rung.choose(
            job=chosen,
            relationship=scene.relationship,
            part_of_day=moment.part_of_day,
            depth=depth,
            subject=scene.subject is not None,
        )
        alternative = variant.choose(
            book=chosen_book, family=ordinary, recent=ledger.recent(), budget=budget
        )
        if alternative is not None:
            refilled = fill.render(alternative, slots)
            if refilled is not None:
                retrimmed = trim.enforce(refilled, budget)
                if retrimmed is not None:
                    trace.add("fallback", f"{ordinary} (no room for {register})")
                    register, template, text, trimmed = ordinary, alternative, refilled, retrimmed
    trace.add("trim", trimmed or "over budget")
    if trimmed is None:
        return Abstain("over budget")

    typed = typing.apply(trimmed, style)
    if ledger.seen_last(typed):
        # Say the same *thing* differently before giving up on saying it. Measured: "what are you up
        # to" twice in a minute produced the identical line, because a four-word answer is allowed to
        # repeat and the hook value does not change with the wording.
        alternative = _resay(chosen_book, register, chosen, scene, budget, style, ledger)
        if alternative is not None:
            typed = alternative
            trace.add("resay", typed)
    verdict = audition.judge(
        text=typed,
        budget=budget,
        repeated=ledger.seen_last(typed),
        story=telling is not None,
        fit=persona_fit.read(typed, story=telling is not None),
    )
    trace.add("audition", verdict.reason or "ok")
    if not verdict.ok:
        # A refused candidate is not the end of the turn. `render/audition`'s own docstring promises
        # that "on a reject the ladder asks decide.variant for another candidate" -- it did not, and
        # the gap produced silence whenever the *material* was the problem: measured on "why?",
        # where one activity's reason ended on a beat and the whole answer vanished.
        rescued = _second_chance(
            books=books,
            book=chosen_book,
            register=register,
            chosen=chosen,
            scene=scene,
            budget=budget,
            style=style,
            ledger=ledger,
            telling=telling,
            refused=verdict.reason,
        )
        if rescued is None:
            return Abstain(verdict.reason)
        typed, trace_label = rescued
        trace.add("rescue", trace_label)

    ledger.remember(typed)
    return line_rung.assemble(text=typed, trail=trace.trail)
