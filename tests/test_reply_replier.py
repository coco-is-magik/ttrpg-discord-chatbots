import pytest

from ttrpg_chatbots.reply import compression
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.types import (
    Character,
    KnowledgeItem,
    ReplyUnavailable,
    ResponseTemplate,
    UnknownCharacter,
)

from reply_support import DEMO_WORLD, make_world


@pytest.fixture
def replier() -> Replier:
    return Replier(make_world())


@pytest.fixture(scope="module")
def demo() -> Replier:
    return Replier(load_world(DEMO_WORLD))


def test_answers_with_the_fact_in_character(replier) -> None:
    reply = replier.reply("tell me about the crown", "ann")

    assert reply.known is True
    assert reply.tag == "lore:relic"
    assert reply.knowledge_id == "k-crown"
    assert reply.template_id == "r-1"
    assert "tide-iron" in reply.text
    assert reply.distance is not None


def test_deflects_what_the_character_does_not_know(replier) -> None:
    reply = replier.reply("how deep is the quay?", "ann")

    assert reply.known is False
    assert reply.tag is None
    assert reply.knowledge_id is None
    assert reply.text == "I could not say."


def test_a_deflection_never_leaks_the_fact(demo) -> None:
    reply = demo.reply("what is the sunken crown?", "orla")

    assert reply.known is False
    assert "tide-iron" not in reply.text
    assert "Sunken Crown" not in reply.text


def test_selection_is_deterministic(replier) -> None:
    first = replier.reply("tell me about the crown", "ann")
    second = replier.reply("tell me about the crown", "ann")
    assert first.text == second.text
    assert first.template_id == second.template_id


def test_sentence_case_applies_when_a_slot_opens_the_line() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-1",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{subject} is old.",
            ),
        )
    )
    assert Replier(world).reply("tell me about the crown", "ann").text == "The crown is old."


def test_all_variants_are_reachable_across_different_questions() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-1",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{fact}",
            ),
            ResponseTemplate(
                id="r-2",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{topic}: {fact}",
            ),
        )
    )
    replier = Replier(world)
    used = {
        replier.reply(f"tell me about the crown, question {number}", "ann").template_id
        for number in range(20)
    }
    assert used == {"r-1", "r-2"}


def test_a_template_that_cannot_be_filled_is_skipped() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-0-needs-place",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="You mean {place}?",
            ),
            ResponseTemplate(
                id="r-1-plain", character="ann", tags=frozenset({"lore:relic"}), template="{fact}"
            ),
        )
    )
    reply = Replier(world).reply("tell me about the crown", "ann")

    assert reply.template_id == "r-1-plain"
    assert "{" not in reply.text and "}" not in reply.text


def test_deflects_when_no_template_for_the_tag_can_be_filled() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-needs-place",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="You mean {place}?",
            ),
            ResponseTemplate(
                id="r-fallback",
                character="ann",
                tags=frozenset({"fallback"}),
                template="I could not say.",
            ),
        )
    )
    reply = Replier(world).reply("tell me about the crown", "ann")

    assert reply.known is False
    assert reply.text == "I could not say."


def test_missing_fallback_is_an_error() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-1", character="ann", tags=frozenset({"lore:relic"}), template="{fact}"
            ),
        )
    )
    with pytest.raises(ReplyUnavailable, match="fallback"):
        Replier(world).reply("how deep is the quay?", "ann")


def test_wildcard_fallback_covers_a_character_without_one() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-any",
                character="*",
                tags=frozenset({"fallback"}),
                template="{character} has nothing to say.",
            ),
        )
    )
    assert Replier(world).reply("how deep is the quay?", "ann").text == "Ann has nothing to say."


def test_a_character_template_beats_the_wildcard() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-any",
                character="*",
                tags=frozenset({"fallback"}),
                template="{character} has nothing to say.",
            ),
            ResponseTemplate(
                id="r-specific",
                character="ann",
                tags=frozenset({"fallback"}),
                template="Not mine to say.",
            ),
        )
    )
    assert Replier(world).reply("how deep is the quay?", "ann").template_id == "r-specific"


def test_a_multi_tagged_fact_is_answerable_by_either_specialist() -> None:
    """One fact, two tags: each character answers from the tag it knows."""
    world = make_world(
        knowledge=(
            KnowledgeItem(
                id="k-greyfall",
                text="At Greyfall the fleet broke on the reef.",
                tags=frozenset({"lore:history", "lore:geography"}),
                slots={"place": "Greyfall"},
            ),
        ),
        responses=(
            ResponseTemplate(
                id="r-h",
                character="ann",
                tags=frozenset({"lore:history"}),
                template="Old ground: {fact}",
            ),
            ResponseTemplate(
                id="r-g",
                character="bob",
                tags=frozenset({"lore:geography"}),
                template="You mean {place}? {fact}",
            ),
        ),
        characters=(
            Character(id="ann", name="Ann", known_tags=frozenset({"lore:history"})),
            Character(id="bob", name="Bob", known_tags=frozenset({"lore:geography"})),
        ),
    )
    replier = Replier(world)

    assert replier.reply("what happened at greyfall?", "ann").tag == "lore:history"
    assert replier.reply("what happened at greyfall?", "bob").tag == "lore:geography"


def test_speaker_is_filled_when_given() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-1",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{speaker}, {fact}",
            ),
        )
    )
    reply = Replier(world).reply("tell me about the crown", "ann", speaker="Tav")
    assert reply.text.startswith("Tav, ")


def test_a_template_needing_the_speaker_is_skipped_when_absent() -> None:
    world = make_world(
        responses=(
            ResponseTemplate(
                id="r-0",
                character="ann",
                tags=frozenset({"lore:relic"}),
                template="{speaker} asked about {fact}",
            ),
            ResponseTemplate(
                id="r-1", character="ann", tags=frozenset({"lore:relic"}), template="{fact}"
            ),
            ResponseTemplate(
                id="r-3", character="ann", tags=frozenset({"fallback"}), template="I could not say."
            ),
        )
    )
    assert Replier(world).reply("tell me about the crown", "ann").template_id == "r-1"


def test_max_distance_turns_a_weak_match_into_a_deflection() -> None:
    strict = Replier(make_world(), max_distance=0.01)
    # Deliberately does not *name* the subject: naming it is evidence the ceiling does not
    # override (see test_a_named_subject_is_answered_even_past_the_ceiling).
    assert strict.reply("tell me about something old and iron", "ann").known is False


def test_a_named_subject_is_answered_even_past_the_ceiling() -> None:
    # "the crown" is in the message, so the question is about the crown however it is phrased.
    strict = Replier(make_world(), max_distance=0.01)

    reply = strict.reply("tell me about the crown", "ann")

    assert reply is not None and reply.known is True
    assert reply.tag == "lore:relic"


def test_empty_query_is_rejected(replier) -> None:
    with pytest.raises(ValueError, match="query"):
        replier.reply("   ", "ann")


def test_unknown_character_is_rejected(replier) -> None:
    with pytest.raises(UnknownCharacter):
        replier.reply("the crown", "nobody")


def test_bad_top_k_is_rejected() -> None:
    with pytest.raises(ValueError, match="top_k"):
        Replier(make_world(), top_k=0)


def test_the_compressor_can_be_overridden() -> None:
    replier = Replier(make_world(), compressor=compression.get("gzip"))
    assert replier.classify("the crown").compressor == "gzip"


KNOWS = [
    ("what is the sunken crown?", "brannoc"),
    ("who controls the dry docks in the reach?", "brannoc"),
    ("what happened at greyfall?", "brannoc"),
    ("when is the turning tide rite spoken?", "sable"),
    ("where does the tide never leave?", "sable"),
    ("does the wreck still ring its bell?", "orla"),
    ("what is the harbour council buying?", "orla"),
]

DOES_NOT_KNOW = [
    ("what is the sunken crown?", "orla"),
    ("does the wreck still ring its bell?", "brannoc"),
    ("when is the turning tide rite spoken?", "orla"),
]


@pytest.mark.parametrize("query,character", KNOWS)
def test_demo_characters_answer_what_they_know(demo, query, character) -> None:
    reply = demo.reply(query, character)

    assert reply.known is True, reply
    assert reply.knowledge_id is not None
    assert reply.tag in demo.world.character(character).known_tags
    assert reply.text


@pytest.mark.parametrize("query,character", DOES_NOT_KNOW)
def test_demo_characters_deflect_what_they_do_not_know(demo, query, character) -> None:
    reply = demo.reply(query, character)

    assert reply.known is False
    assert reply.knowledge_id is None
    assert reply.text
