"""The command surface a human uses in Discord.

Everything runs without a gateway: interactions are fakes, ``tree.sync`` and
``Client.run`` are never called, and the socket guard in ``conftest.py`` refuses any
accidental connection. The point is to prove each command validates its input and
delegates to the conversation layer, not to re-test Discord.
"""

from __future__ import annotations

import asyncio

from discord import app_commands

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.bot import (
    ask,
    create_bot,
    join,
    leave,
    roll,
    say,
    stop,
    voices,
    voice_readiness,
)
from ttrpg_chatbots.conversation import ConversationError
from ttrpg_chatbots.respond import Answer


class _Command:
    """Minimal stand-in for the command object attached to an interaction."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.qualified_name = name


class _Response:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.deferred = False
        self.ephemeral: list[bool] = []

    async def send_message(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append(content)
        self.ephemeral.append(ephemeral)

    async def defer(self, thinking: bool = False) -> None:
        self.deferred = True

    def is_done(self) -> bool:
        """Mirror Discord: once deferred or answered, the initial response is used up."""
        return self.deferred


class _Followup:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ephemeral: list[bool] = []

    async def send(self, content: str, ephemeral: bool = False) -> None:
        self.messages.append(content)
        self.ephemeral.append(ephemeral)


class _User:
    display_name = "Tav"
    voice = None


class _Guild:
    def __init__(self, client=None) -> None:
        self.id = 1
        self.voice_client = client


class _Interaction:
    def __init__(self, client, *, guild=None) -> None:
        self.response = _Response()
        self.followup = _Followup()
        self.client = client
        self.user = _User()
        self.guild = guild
        self.command = None


class _FakeVoiceClient:
    """Enough of a VoiceClient to satisfy the command layer."""

    def __init__(self) -> None:
        self.connected = True
        self.played: list = []

    def is_connected(self) -> bool:
        return self.connected

    def play(self, source) -> None:
        self.played.append(source)

    @property
    def guild(self):
        return _Guild(self)


class _FakeConversation:
    """Records what it was asked; returns fixed answers."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    def answer(self, prompt, *, character=None, speaker=None):
        self.calls.append(("answer", prompt, character, speaker))
        self._maybe_raise()
        return Answer(text="The tide-iron crown is lost.", source="reply:brannoch")

    def answer_and_speak(self, prompt, *, character=None, speaker=None):
        self.calls.append(("answer_and_speak", prompt, character, speaker))
        self._maybe_raise()
        return Answer(text="spoken", source="dice"), None

    def speak(self, text, *, character=None):
        self.calls.append(("speak", text, character))
        self._maybe_raise()
        raise AssertionError("never reached in these tests")

    def voices(self):
        self.calls.append(("voices",))
        self._maybe_raise()
        return ({"character": "sable", "name": "Sable", "voice": "piper:x"},)

    def close(self) -> None:
        self.calls.append(("close",))


def _clip(seconds: float = 0.5) -> PcmAudio:
    """A real PcmAudio, so the commands touch the real attribute names."""
    frames = int(22050 * seconds)
    return PcmAudio(pcm=b"\x00\x00" * frames, sample_rate=22050)


class _SpeakingConversation(_FakeConversation):
    """Returns real clips, which is what exposed the attribute-name bug."""

    def answer_and_speak(self, prompt, *, character=None, speaker=None):
        self.calls.append(("answer_and_speak", prompt, character, speaker))
        self._maybe_raise()
        return Answer(text="spoken", source="dice"), _clip()

    def speak(self, text, *, character=None):
        self.calls.append(("speak", text, character))
        self._maybe_raise()
        return _clip()


class _Bot:
    def __init__(self, conversation) -> None:
        self.conversation = conversation
        self.players: dict = {}


def _invoke(command, interaction, *args, **kwargs):
    return asyncio.run(command.callback(interaction, *args, **kwargs))


def test_every_command_the_guide_documents_is_registered() -> None:
    async def build() -> set[str]:
        bot = create_bot()
        try:
            return {command.name for command in bot.tree.get_commands()}
        finally:
            await bot.close()

    assert asyncio.run(build()) == {
        "ping",
        "ask",
        "roll",
        "join",
        "leave",
        "say",
        "stop",
        "voices",
    }


def test_ask_reports_the_reply_and_its_source() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(ask, interaction, "what is the sunken crown?", "brannoch", False)

    assert conversation.calls == [
        ("answer", "what is the sunken crown?", "brannoch", "Tav")
    ]
    assert interaction.response.deferred is True
    message = interaction.followup.messages[0]
    assert "tide-iron crown" in message
    assert "answered by `reply:brannoch`" in message


def test_ask_with_speak_but_no_voice_channel_skips_synthesis() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(ask, interaction, "hello", None, True)
    # Answering in text, not synthesizing audio nobody can hear.
    assert [call[0] for call in conversation.calls] == ["answer"]
    assert "run /join first" in interaction.followup.messages[0]


def test_ask_with_speak_in_a_call_uses_the_speaking_path() -> None:
    conversation = _FakeConversation()
    client = _FakeVoiceClient()
    interaction = _Interaction(_Bot(conversation), guild=_Guild(client))
    _invoke(ask, interaction, "hello", "sable", True)
    assert [call[0] for call in conversation.calls] == ["answer_and_speak"]
    assert "nothing was spoken" in interaction.followup.messages[0]


def test_ask_reports_a_conversation_error_without_raising() -> None:
    conversation = _FakeConversation(error=ConversationError("no such character 'x'"))
    interaction = _Interaction(_Bot(conversation))
    _invoke(ask, interaction, "hello", "x", False)
    assert interaction.followup.messages == ["error: no such character 'x'"]


def test_roll_needs_dice_or_a_check() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, None, None, None)
    assert conversation.calls == []
    assert "give dice" in interaction.response.messages[0]
    assert interaction.response.ephemeral == [True]


def test_roll_builds_an_instruction_from_a_check_or_notation() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, None, "stealth", "sable")
    _invoke(roll, interaction, "3d6", None, None)
    assert [call[1] for call in conversation.calls] == ["roll stealth", "roll 3d6"]


def test_say_needs_a_voice_connection() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(say, interaction, "hello", None)
    assert conversation.calls == []
    assert "run /join first" in interaction.response.messages[0]


def test_say_queues_real_audio_and_confirms() -> None:
    """Regression: this raised AttributeError on ``duration_seconds`` after queueing.

    The audio played, the follow-up never arrived, and Discord showed "thinking" forever.
    """
    conversation = _SpeakingConversation()
    client = _FakeVoiceClient()
    interaction = _Interaction(_Bot(conversation), guild=_Guild(client))
    _invoke(say, interaction, "the night is cold", "orla")

    bot = interaction.client
    assert conversation.calls == [("speak", "the night is cold", "orla")]
    assert interaction.followup.messages == ["speaking 0.5 s (queued: 1)"]
    assert bot.players[1].queued == 1
    assert client.played  # the playback stream was started


def test_ask_with_speak_queues_real_audio() -> None:
    conversation = _SpeakingConversation()
    client = _FakeVoiceClient()
    interaction = _Interaction(_Bot(conversation), guild=_Guild(client))
    _invoke(ask, interaction, "hello", "sable", True)

    assert interaction.followup.messages[0].startswith("spoken")
    assert interaction.client.players[1].queued == 1


def test_a_failing_command_answers_instead_of_leaving_thinking() -> None:
    """The tree's error handler must complete the interaction."""

    async def run() -> None:
        bot = create_bot()
        interaction = _Interaction(bot)
        interaction.response.deferred = True
        interaction.command = _Command("ask")
        try:
            error = app_commands.CommandInvokeError(_Command("ask"), AttributeError("boom"))
            await bot.tree.on_error(interaction, error)
        finally:
            await bot.close()
        assert "boom" in interaction.followup.messages[0]
        assert "ask" in interaction.followup.messages[0]

    asyncio.run(run())


def test_the_error_handler_handles_an_unanswered_interaction() -> None:
    class _Undone:
        message = ""

        def is_done(self) -> bool:
            return False

        async def send_message(self, content, ephemeral=False):
            self.message = content

    async def run() -> str:
        bot = create_bot()
        interaction = _Interaction(bot)
        interaction.response = _Undone()
        try:
            await bot.tree.on_error(interaction, ValueError("nope"))
        finally:
            await bot.close()
        return interaction.response.message

    assert "nope" in asyncio.run(run())


def test_leave_says_so_when_not_connected() -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    _invoke(leave, interaction)
    assert interaction.response.messages == ["not in a voice channel"]


def test_stop_says_so_when_nothing_is_queued() -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    _invoke(stop, interaction)
    assert interaction.response.messages == ["nothing is playing"]


def test_voices_lists_the_cast_and_reports_voice_readiness() -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    _invoke(voices, interaction)
    message = interaction.followup.messages[0]
    assert "sable" in message
    assert "voice" in message.lower()


def test_voices_reports_an_error_instead_of_the_cast() -> None:
    conversation = _FakeConversation(error=ConversationError("cannot load data"))
    interaction = _Interaction(_Bot(conversation))
    _invoke(voices, interaction)
    assert interaction.followup.messages == ["error: cannot load data"]


def test_join_explains_what_is_missing_when_voice_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "ttrpg_chatbots.bot.voice_readiness", lambda: (False, "voice unavailable: missing x")
    )
    interaction = _Interaction(_Bot(_FakeConversation()), guild=_Guild())
    _invoke(join, interaction)
    assert interaction.response.messages == ["voice unavailable: missing x"]
    assert interaction.response.ephemeral == [True]


def test_join_asks_for_a_channel_when_the_caller_is_not_in_one(monkeypatch) -> None:
    monkeypatch.setattr("ttrpg_chatbots.bot.voice_readiness", lambda: (True, "voice ready"))
    interaction = _Interaction(_Bot(_FakeConversation()), guild=_Guild())
    _invoke(join, interaction)
    assert "join a voice channel first" in interaction.response.messages[0]


def test_voice_readiness_reports_missing_pynacl(monkeypatch) -> None:
    ready, detail = voice_readiness()
    assert isinstance(ready, bool) and detail

    real_import = __import__

    def no_nacl(name, *args, **kwargs):
        if name == "nacl":
            raise ImportError("blocked for the test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_nacl)
    ready, detail = voice_readiness()
    assert ready is False
    assert "PyNaCl" in detail

