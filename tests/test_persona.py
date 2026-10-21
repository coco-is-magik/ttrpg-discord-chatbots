"""The persona brief, and the data it claims to describe.

Two halves. The first is value-type behaviour: a persona record that is malformed or
self-contradictory must fail loudly at startup rather than half-work at midnight. The second is
the part that matters -- the brief is only true if the dataset agrees with it, so these tests read
the committed roster and the committed world and refuse to let them drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ttrpg_chatbots import jsonl
from ttrpg_chatbots.bots.chat import FriendChat
from ttrpg_chatbots.bots.identity import BotSpec, BotSpecError, bots_from_records
from ttrpg_chatbots.bots.persona import Persona, PersonaError, VoiceSpec

DATA = Path("examples/friends_world")
ROSTER = Path("examples/bots.example.json")

# --- the value type ----------------------------------------------------------------------------


def test_a_minimal_persona_is_enough() -> None:
    persona = Persona(name="TopGuy")

    assert persona.describe() == "TopGuy"
    assert persona.voice is None


def test_a_persona_needs_a_name() -> None:
    with pytest.raises(PersonaError, match="needs a name"):
        Persona(name="   ")


def test_a_topic_must_be_a_tag_that_can_be_looked_up() -> None:
    with pytest.raises(PersonaError, match="must be a tag"):
        Persona(name="TopGuy", topics=("hockey",))


def test_a_voice_needs_an_engine_and_a_name() -> None:
    with pytest.raises(PersonaError, match="needs an engine"):
        VoiceSpec(engine="  ", voice="en_US-ryan-high")
    with pytest.raises(PersonaError, match="needs a voice name"):
        VoiceSpec(engine="piper", voice=" ")


def test_a_voice_speed_must_be_a_sane_number() -> None:
    with pytest.raises(PersonaError, match="between"):
        VoiceSpec(engine="piper", voice="v", speed=0.0)
    with pytest.raises(PersonaError, match="between"):
        VoiceSpec(engine="piper", voice="v", speed=9.0)
    with pytest.raises(PersonaError, match="must be a number"):
        VoiceSpec(engine="piper", voice="v", speed=True)


def test_from_record_reads_every_field() -> None:
    persona = Persona.from_record(
        {
            "name": "TopGuy",
            "summary": "Big and warm.",
            "traits": ["jolly"],
            "values": ["honesty"],
            "topics": ["topic:hockey"],
            "signature": ["That is the truth of it"],
            "voice": {"engine": "piper", "voice": "en_US-ryan-high", "speed": 0.92},
        }
    )

    assert persona.topics == ("topic:hockey",)
    assert persona.voice is not None and persona.voice.speed == 0.92
    assert persona.describe() == "TopGuy (1 topics, piper:en_US-ryan-high at 0.92x)"


def test_from_record_names_the_offending_field() -> None:
    with pytest.raises(PersonaError, match="'name'"):
        Persona.from_record({"summary": "nameless"})
    with pytest.raises(PersonaError, match="'traits'"):
        Persona.from_record({"name": "TopGuy", "traits": "jolly"})
    with pytest.raises(PersonaError, match="voice.engine"):
        Persona.from_record({"name": "TopGuy", "voice": {"engine": 3, "voice": "x"}})


# --- the roster --------------------------------------------------------------------------------


def _record(**overrides) -> dict:
    record = {"id": "friend-a", "role": "friend", "persona": {"name": "TopGuy"}}
    record.update(overrides)
    return record


def test_a_friend_may_carry_a_persona() -> None:
    (spec,) = bots_from_records([_record()])

    assert spec.persona is not None and spec.persona.name == "TopGuy"


def test_the_helper_must_not_have_one() -> None:
    with pytest.raises(BotSpecError, match="helper has no personality"):
        bots_from_records([_record(id="ttrpg-bot", role="helper")])


def test_a_malformed_persona_names_the_bot() -> None:
    with pytest.raises(BotSpecError, match=r"bot 'friend-a'.*persona"):
        bots_from_records([_record(persona={"name": ""})])


def test_a_bot_without_a_persona_is_unchanged() -> None:
    (spec,) = bots_from_records([{"id": "friend-b", "role": "friend"}])

    assert spec.persona is None
    assert isinstance(spec, BotSpec)


# --- the brief against the committed data ------------------------------------------------------


def _roster() -> dict[str, BotSpec]:
    raw = json.loads(ROSTER.read_text(encoding="utf-8"))
    return {spec.id: spec for spec in bots_from_records(raw)}


def _chat() -> FriendChat:
    return FriendChat(DATA, seed="persona")


def test_the_committed_roster_gives_friend_a_a_persona() -> None:
    persona = _roster()["friend-a"].persona

    assert persona is not None
    assert persona.name == "TopGuy"
    assert persona.topics, "a persona with no subjects has nothing to say about anything"
    assert persona.voice is not None


def test_the_other_friends_stay_neutral_for_now() -> None:
    roster = _roster()

    # One at a time: giving friend-b a voice before its turn would be a decision nobody made.
    assert roster["friend-b"].persona is None
    assert roster["friend-c"].persona is None


def test_every_topic_is_a_tag_the_character_actually_knows() -> None:
    persona = _roster()["friend-a"].persona
    assert persona is not None
    character = _chat().world.character("friend-a")

    unknown = [topic for topic in persona.topics if topic not in character.known_tags]

    # Otherwise the brief would promise an interest the friend cannot discuss.
    assert not unknown, f"persona claims topics the character cannot answer: {unknown}"


def test_every_topic_has_something_to_say() -> None:
    persona = _roster()["friend-a"].persona
    assert persona is not None
    world = _chat().world
    tagged = {tag for item in world.knowledge for tag in item.tags}

    missing = [topic for topic in persona.topics if topic not in tagged]

    assert not missing, f"no knowledge carries these topics: {missing}"


def test_every_signature_line_is_really_in_his_mouth() -> None:
    persona = _roster()["friend-a"].persona
    assert persona is not None
    world = _chat().world
    topics = set(persona.topics)
    spoken = " ".join(
        [template.template for template in world.responses if template.character == "friend-a"]
        # A catchphrase can live in a stance he speaks as easily as in a social template.
        + [item.spoken for item in world.knowledge if item.tags & topics]
    )

    # A catchphrase nobody says is a lie in a config file.
    missing = [line for line in persona.signature if line not in spoken]

    assert not missing, f"signature lines absent from his lines: {missing}"


def test_the_voice_is_pinned_in_the_casting_table() -> None:
    persona = _roster()["friend-a"].persona
    assert persona is not None and persona.voice is not None
    rules = list(jsonl.read_jsonl(DATA / "voices.jsonl"))

    matched = [
        rule
        for rule in rules
        if "friend-a" in (rule.get("characters") or [])
        or "TopGuy" in (rule.get("characters") or [])
    ]

    assert matched, "no casting rule names friend-a"
    rule = matched[0]
    assert rule["engine"] == persona.voice.engine
    assert rule["voice"] == persona.voice.voice
    assert float(rule.get("speed", 1.0)) == persona.voice.speed


# --- what he actually says ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    [
        "do you like hockey?",
        "what about the rangers?",
        "what do you think of pokemon?",
        "tell me about rome",
        "who is terry davis",
        "do you hunt?",
        "fishing tips?",
        "what is a good woodworking joint?",
        "how do i get into computers?",
    ],
)
def test_his_subjects_get_an_answer_in_his_own_voice(question: str) -> None:
    answer = _chat().reply(question, "friend-a", speaker="Tav")

    assert answer is not None
    assert answer.detail["known"] is True
    assert answer.detail["tag"].startswith("topic:")
    # Owned templates only: no neutral wildcard leaking into his lines.
    assert answer.detail["template_id"].startswith("r-a-")


def test_a_question_outside_his_subjects_is_refused_honestly() -> None:
    answer = _chat().reply("what is the sunken crown?", "friend-a", speaker="Tav")

    assert answer is not None
    assert answer.detail["known"] is False
    assert answer.detail["knowledge_id"] is None
    assert answer.detail["template_id"].startswith("r-a-fallback")


def test_he_can_be_moved_by_somebody_having_a_bad_day() -> None:
    answer = _chat().reply("i'm really nervous about tomorrow", "friend-a", speaker="Tav")

    assert answer is not None
    assert answer.detail["tag"] == "social:comfort"
    assert answer.detail["template_id"].startswith("r-a-comfort")


def test_the_other_friends_do_not_borrow_his_voice() -> None:
    chat = _chat()

    for friend in ("friend-b", "friend-c"):
        answer = chat.reply("do you like hockey?", friend, speaker="Tav")
        assert answer is not None
        assert answer.detail["known"] is False
        assert answer.detail["template_id"].startswith("r-fallback")


# --- warm to the human, in every line ----------------------------------------------------------


def test_no_template_is_ever_cold_to_the_person_being_answered() -> None:
    # Firm opinions about the world are the point. Contempt for the human is not, and a template
    # is the wrong place to discover it.
    banned = (
        "stupid",
        "idiot",
        "shut up",
        "nobody cares",
        "don't care",
        "do not care about you",
        "boring",
        "whatever you say",
        "obviously",
        "you're wrong",
        "you are wrong",
    )
    world = _chat().world

    offenders = [
        (template.id, word)
        for template in world.responses
        for word in banned
        if word in template.template.lower()
    ]

    assert not offenders, f"hostile wording: {offenders}"


def test_every_character_can_still_say_i_dont_know() -> None:
    world = _chat().world

    for character in world.characters:
        # Own fallback pool, or the shared one -- either way the honest answer exists.
        fallbacks = [
            template
            for template in world.responses
            if template.character in {character.id, "*"} and "fallback" in template.tags
        ]
        assert fallbacks, f"{character.id} cannot answer anything it does not know"


def test_a_repeated_question_does_not_repeat_the_sentence() -> None:
    chat = _chat()
    lines = {chat.reply("hey", "friend-a", speaker="Tav").text for _ in range(6)}

    assert len(lines) > 1, "rotation is off, or there is only one greeting to give"


# --- the typing layer -----------------------------------------------------------------------


def test_his_persona_declares_how_he_types() -> None:
    style = _roster()["friend-a"].persona.style

    assert style is not None
    assert style.case == "lower"
    assert style.drop_apostrophes is True
    assert style.strip_final_period is True


def test_his_replies_are_typed_not_written() -> None:
    persona = _roster()["friend-a"].persona
    assert persona is not None
    chat = _chat()

    for question in ("hey", "thanks", "do you like hockey?", "i'm nervous about tomorrow"):
        answer = chat.reply(question, "friend-a", speaker="Tav", style=persona.style)
        assert answer is not None
        assert answer.text[:1].islower(), f"{question!r} was capitalised: {answer.text!r}"
        assert not answer.text.endswith("."), f"{question!r} ended in a full stop"
        # Apostrophes are dropped only where the word survives; the styles he uses are gone.
        for word in ("don't", "can't", "won't", "that's", "you're", "i've"):
            assert word not in answer.text, f"{question!r} still says {word!r}"


def test_style_is_not_applied_to_the_neutral_friends() -> None:
    # friend-b has no persona, so its lines stay tidy: the layer is opt-in, not global.
    answer = _chat().reply("hey", "friend-b", speaker="Tav")

    assert answer is not None
    assert answer.text[:1].isupper()
