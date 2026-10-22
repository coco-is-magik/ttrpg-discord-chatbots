"""The ladder: one rung at a time, then all eight together for a greeting."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from ttrpg_chatbots.conv.types import (
    Abstain,
    Budget,
    Line,
    Relationship,
    Utterance,
)
from ttrpg_chatbots.decide import (
    depth,
    family,
    floor,
    form,
    job,
    length,
    phase,
    reciprocate,
    variant,
    who,
)
from ttrpg_chatbots.decide.variant import PhrasebookError, load
from ttrpg_chatbots.govern.loop import Scene, intent_of, reply
from ttrpg_chatbots.govern.repeat import Recent
from ttrpg_chatbots.perceive import addressee, attachments, inbound, modality, situation, tone
from ttrpg_chatbots.perceive.clock import read_clock
from ttrpg_chatbots.render import audition, fill, line, trim, typing

DATA = Path("examples/friends_world")
BOOK = DATA / "phrasebooks" / "greet.json"
FRIEND = Relationship(stage="friend", warmth=3)
MORNING = read_clock(datetime(2026, 10, 21, 8, 40))


# --- perceive ----------------------------------------------------------------------------------


def test_inbound_strips_mentions_and_keeps_words() -> None:
    utterance = inbound.read(text="<@1562461501888139297> hey there", speaker="noodle")

    assert utterance.text == "hey there"
    assert utterance.speaker == "noodle"


def test_a_reply_outranks_a_bare_mention() -> None:
    assert addressee.classify(mentioned=True, replied=True) == "reply"
    assert addressee.classify(mentioned=False, replied=False) == "unaddressed"


def test_modality_and_attachments() -> None:
    plain = inbound.read(text="hey")
    picture = inbound.read(text="look", attachments=1)

    assert modality.classify(plain) == "text"
    assert modality.classify(picture) == "image"
    assert attachments.describe(picture) is not None
    assert attachments.describe(picture).visible is False
    assert attachments.describe(plain) is None


def test_tone_is_read_not_guessed() -> None:
    assert tone.read("haha yeah that's brilliant") == "warm"
    assert tone.read("k") == "flat"
    assert tone.read("hey") == "terse"
    assert tone.read("what time is the thing") == "neutral"


def test_a_channel_name_says_what_room_it_is() -> None:
    assert situation.read(channel="game-night").kind == "ttrpg"
    assert situation.read(channel="general").kind == "chatting"
    assert situation.read(channel="general", table_active=True).kind == "ttrpg"


# --- decide ------------------------------------------------------------------------------------


def test_the_budget_mirrors_them() -> None:
    assert length.budget(their_words=1).max_words == 3
    assert length.budget(their_words=10).max_words == 12
    assert length.budget(their_words=40).max_words == 14
    assert length.budget(their_words=1, phase="substance").max_sentences == 2


def test_the_floor_says_no_to_the_right_things() -> None:
    assert isinstance(floor.decide(addressed="named"), type(floor.decide(addressed="named")))
    assert floor.decide(addressed="unaddressed").reason == "nobody was talking to him"
    assert floor.decide(addressed="named", asleep=True).reason == "he is asleep"


def test_phase_climbs_only_with_evidence() -> None:
    assert phase.read(turns_today=0) == "opening"
    assert phase.read(turns_today=3) == "pleasantries"
    assert phase.read(turns_today=3, named_subject=True) == "hook"
    assert phase.read(turns_today=3, depth=1) == "substance"
    assert phase.read(turns_today=3, closing=True) == "closing"


def test_depth_counts_only_leaning_in() -> None:
    from ttrpg_chatbots.reply.context import Turn

    short = (Turn("t", "hey"),)
    long = (Turn("t", "what do you think about the rangers this year"),)

    assert depth.read(short) == 0
    assert depth.read(long) == 1


def test_job_is_exactly_one_thing() -> None:
    assert job.choose(intent="greet", phase="opening") == "greet"
    assert job.choose(intent="complain", phase="hook") == "mirror"
    # A hook is only available when there is a life to draw on. Without one the honest answer is a
    # hedge, not a phrasebook line about nothing.
    assert job.choose(intent="about_me", phase="hook", depth=0, known=True) == "offer_hook"
    assert job.choose(intent="about_me", phase="hook", depth=0) == "hedge"
    # Depth does not turn a hook into a reason: measured live, "what are you up to" arrived
    # deep into a conversation and got a reason instead of the thing he was doing.
    assert job.choose(intent="about_me", phase="substance", depth=3, known=True) == "offer_hook"
        # The reason job belongs to the follow-up, not to depth.
    assert job.choose(intent="explain_me", phase="substance", depth=1, known=True) == "explain"


def test_who_speaks_depends_on_the_room() -> None:
    assert who.choose(situation="ttrpg", table_active=True) == "character"
    assert who.choose(situation="ttrpg", table_active=False) == "friend"
    assert who.choose(situation="chatting", table_active=True) == "friend"


def test_form_follows_the_budget() -> None:
    assert form.choose(job="greet", budget=Budget(2, 1)) == "word"
    assert form.choose(job="greet", budget=Budget(6, 1)) == "clause"
    assert form.choose(job="explain", budget=Budget(12, 2)) == "two_beat"


def test_family_uses_the_clock_and_the_relationship() -> None:
    assert family.choose(job="greet", relationship=FRIEND, part_of_day="morning") == "time_morning"
    assert family.choose(job="greet", relationship=FRIEND, part_of_day="evening") == "time_evening"
    assert family.choose(job="greet", relationship=Relationship(), part_of_day="afternoon") == "casual"
    # For mirror the phase outranks the register: a reaction first, the grievance only once they
    # have leaned in.
    assert family.choose(job="mirror", relationship=Relationship(), part_of_day="night") == "reaction"
    assert family.choose(job="mirror", relationship=FRIEND, part_of_day="night", depth=1) == "detail"


def test_reciprocation_never_nags() -> None:
    assert reciprocate.choose(form="clause_question").kind == "question"
    assert reciprocate.choose(form="clause_question", tone="terse").kind == "space"
    assert reciprocate.choose(form="clause_question", already_asked=True).kind == "none"


def test_a_variant_is_fresh_then_least_recent() -> None:
    book = load(BOOK)

    first = variant.choose(book=book, family="casual")
    second = variant.choose(book=book, family="casual", recent=(first,))

    assert first != second
    # A family that does not exist gets nothing. Borrowing another family's lines is how
    # a bot says "there he is" to a stranger: the phase is the boundary, not a suggestion.
    assert variant.choose(book=book, family="nonsense") is None


def test_a_broken_phrasebook_is_refused(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"job": "x", "families": {"a": {"variants": []}}}', encoding="utf-8")

    with pytest.raises(PhrasebookError, match="no variants"):
        load(path)


# --- render ------------------------------------------------------------------------------------


def test_fill_refuses_a_missing_slot() -> None:
    assert fill.render("hey {speaker}", {"speaker": "tav"}) == "hey tav"
    assert fill.render("hey {speaker}", {}) is None


def test_trim_drops_the_end_first() -> None:
    assert trim.enforce("there he is. good to see you.", Budget(3, 1)) == "there he is"
    assert trim.enforce("one two three four five", Budget(2, 1)) is None


def test_typing_applies_the_style() -> None:
    from ttrpg_chatbots.reply.style import Style

    assert typing.apply("Don't mention it.", Style(case="lower", drop_apostrophes=True, strip_final_period=True)) == "dont mention it"


def test_audition_rejects_what_it_should() -> None:
    assert audition.judge(text="hey", budget=Budget(3, 1)).ok is True
    assert audition.judge(text="", budget=Budget(3, 1)).reason == "nothing to say"
    assert audition.judge(text="a b c d e f g", budget=Budget(3, 1)).reason == "over budget"
    # Only a long line echoing itself is refused. A hook is one activity per day, so saying
    # "rebuilding the back fence" twice is a person, and refusing it produced 95 silences in 144.
    assert audition.judge(text="a b c d e", budget=Budget(9, 1), repeated=True).ok is True
    long_line = "a b c d e f g h i"
    assert audition.judge(text=long_line, budget=Budget(12, 1), repeated=True).reason == "he just said that"


def test_a_line_must_have_words() -> None:
    with pytest.raises(ValueError):
        line.assemble(text="  ")


# --- the ladder, end to end ---------------------------------------------------------------------


def _scene(text: str = "hey", **overrides) -> Scene:
    fields = {
        "utterance": Utterance(text=text, speaker="noodle"),
        "addressed": "named",
        "moment": MORNING,
        "relationship": FRIEND,
    }
    fields.update(overrides)
    return Scene(**fields)


def test_a_greeting_runs_the_whole_ladder() -> None:
    out = reply(scene=_scene("hey"), book=load(BOOK))

    assert isinstance(out, Line)
    rungs = [module for module, _ in out.trail.steps]
    assert rungs == [
        "intent", "phase", "length", "floor", "job", "who", "form", "family", "variant",
        "fill", "trim", "audition",
    ]
    assert out.trail.steps[2][1] == "Budget(max_words=3, max_sentences=1)"


def test_unaddressed_silence_is_an_abstain() -> None:
    out = reply(scene=_scene("hey", addressed="unaddressed"), book=load(BOOK))

    assert isinstance(out, Abstain)
    assert "nobody was talking" in out.reason


def test_asleep_silence_is_an_abstain() -> None:
    assert isinstance(reply(scene=_scene("hey", asleep=True), book=load(BOOK)), Abstain)


def test_a_stranger_gets_a_drier_hello_than_a_friend() -> None:
    friend = reply(scene=_scene("hey"), book=load(BOOK))
    stranger = reply(scene=_scene("hey", relationship=Relationship()), book=load(BOOK))

    assert friend.trail.steps[7][1] == "time_morning"
    assert stranger.trail.steps[7][1] == "casual"


def test_greetings_rotate_and_are_allowed_to_repeat() -> None:
    ledger = Recent()
    book = load(BOOK)
    lines = [reply(scene=_scene("hey"), book=book, recent=ledger) for _ in range(6)]

    assert all(isinstance(item, Line) for item in lines), "the ladder went quiet mid-conversation"
    assert len({item.text for item in lines}) > 1


def test_the_reply_fits_the_budget_the_human_set() -> None:
    out = reply(scene=_scene("hey"), book=load(BOOK))

    assert len(out.text.split()) <= 3


def test_intent_mapping_covers_the_lexicon() -> None:
    assert intent_of("hey") == "greet"
    assert intent_of("rough day") == "complain"
    assert intent_of("thanks") == "meta"
    assert intent_of("i am nervous") == "comfort"
    assert intent_of("good night") == "decline"
    # Anything the lexicon does not know is a question the ladder cannot answer, which is a hedge.
    # It used to become an acknowledgement, so "what is the plot of dune" got "any time".
    assert intent_of("what is the plot of dune") == "about_world"
    assert intent_of("why?") == "explain_me"
    # A statement is somebody talking, not a question he failed to understand.
    assert intent_of("i have been rebuilding a fence myself") == "remark"
