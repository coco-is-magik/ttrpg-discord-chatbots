"""The conversation layer: one answer chain and one cast, no front end attached."""

from __future__ import annotations

import pytest

from ttrpg_chatbots.conversation import Conversation, ConversationError

DEMO = "examples/demo_world"


def conversation(**kwargs) -> Conversation:
    return Conversation(data=DEMO, **kwargs)  # type: ignore[arg-type]


def test_it_lists_the_characters_it_can_speak_for() -> None:
    chat = conversation()
    assert {"Brannoc the Archivist", "Sable", "Orla the Tavernkeep"} <= set(
        chat.character_names()
    )


def test_a_classifier_answer_names_the_character_and_the_source() -> None:
    answer = conversation().answer("what is the sunken crown?", character="brannoc")
    assert answer.source.startswith("reply:")
    assert answer.text.strip()
    assert "brannoc" in answer.source


def test_an_unknown_character_lists_the_known_ones() -> None:
    with pytest.raises(ConversationError, match="known:"):
        conversation().answer("hello", character="nobody")


def test_an_empty_prompt_is_refused() -> None:
    with pytest.raises(ConversationError, match="nothing to answer"):
        conversation().answer("   ")


def test_the_default_character_is_the_first_in_the_world() -> None:
    chat = conversation()
    assert chat.resolve(None) is chat.world.characters[0]


def test_a_roll_instruction_is_answered_by_the_dice() -> None:
    answer = conversation(seed=1).answer("roll 3d6", character="sable")
    assert answer.source == "dice"
    assert "3d6" in answer.text


def test_a_model_goes_first_when_it_is_switched_on(monkeypatch) -> None:
    """With ``use_llm`` the model leads, so a dead model must still produce an answer."""
    from ttrpg_chatbots.llm.types import LlmUnavailable

    def dead_backend(config):
        raise LlmUnavailable("no server on 127.0.0.1:5000")

    monkeypatch.setattr("ttrpg_chatbots.conversation.build_backend", dead_backend)
    chat = conversation(seed=2, use_llm=True)
    answer = chat.answer("roll 2d6", character="sable")
    assert answer.source == "dice"
    assert answer.degraded is True
    assert "unreachable" in (answer.fallback_reason or "")


def test_a_missing_dataset_is_reported_clearly(tmp_path) -> None:
    chat = Conversation(data=tmp_path)
    with pytest.raises(ConversationError, match="cannot load"):
        chat.answer("hello")


def test_each_character_answers_as_themselves_on_one_conversation() -> None:
    """Regression: a single cached responder made everyone answer as the first asker."""
    chat = conversation(seed=3)
    asked = "what is the sunken crown?"
    brannoc = chat.answer(asked, character="brannoc")
    sable = chat.answer(asked, character="sable")
    orla = chat.answer(asked, character="orla")

    assert brannoc.source == "reply:brannoc"
    assert sable.source == "reply:sable"
    assert orla.source == "reply:orla"
    assert brannoc.text != sable.text != orla.text
    # The two who do not know the lore deflect instead of inventing it.
    assert "tide-iron" in brannoc.text
    assert "tide-iron" not in sable.text
    assert "tide-iron" not in orla.text


def test_a_roll_is_attributed_to_the_character_asked() -> None:
    chat = conversation(seed=4)
    assert chat.answer("roll stealth", character="sable").text.startswith("Sable")
    assert chat.answer("roll stealth", character="brannoc").text.startswith("Brannoc")


def test_two_speakers_do_not_share_a_responder() -> None:
    chat = conversation(seed=6)
    first = chat.answer("who controls the dry docks?", character="brannoc", speaker="Tav")
    second = chat.answer("who controls the dry docks?", character="brannoc", speaker="Nia")
    assert first.text.strip() and second.text.strip()
    assert len(chat._responders) == 2


def test_the_default_synthesizer_is_loaded_once_and_closed(monkeypatch) -> None:
    """Loading a piper voice costs seconds; a bot speaking many lines must not pay it each
    time."""
    from ttrpg_chatbots.audio.pcm import PcmAudio

    built = []
    closed = []

    class FakeSynth:
        name = "fake"

        def synthesize(self, text):
            return PcmAudio(pcm=b"\x00\x00" * 2205, sample_rate=22050)

        def close(self):
            closed.append(True)

    def fake_resolve(engine=None, **kwargs):
        built.append(engine)
        return FakeSynth()

    monkeypatch.setattr("ttrpg_chatbots.tts.resolve_synthesizer", fake_resolve)
    chat = conversation()
    first = chat.speak("one")
    second = chat.speak("two")
    assert first.duration_s == second.duration_s
    assert built == [None]  # loaded once, not twice
    assert closed == []
    chat.close()
    assert closed == [True]


def test_answers_are_reproducible_with_a_seed() -> None:
    first = conversation(seed=7).answer("roll 3d6", character="sable").text
    again = conversation(seed=7).answer("roll 3d6", character="sable").text
    assert first == again
