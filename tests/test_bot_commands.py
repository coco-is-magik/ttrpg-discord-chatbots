"""The command surface a human uses in Discord.

Everything runs without a gateway: interactions are fakes, ``tree.sync`` and
``Client.run`` are never called, and the socket guard in ``conftest.py`` refuses any
accidental connection. The point is to prove each command validates its input and
delegates to the conversation layer, not to re-test Discord.
"""

from __future__ import annotations

import asyncio

import pytest

from discord import app_commands

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.bot import (
    answer,
    edit,
    heal,
    hurt,
    specialty,
    undo,
    ungift,
    claim,
    done,
    export,
    gift,
    history,
    import_character,
    mission,
    unlock,
    _character_choices,
    _check_choices,
    ask,
    create_bot,
    join,
    leave,
    options,
    roll,
    say,
    sheet,
    spend,
    stop,
    voices,
    voice_readiness,
)
from ttrpg_chatbots.conversation import ConversationError
from ttrpg_chatbots.dice.parts import RollParts
from ttrpg_chatbots.dice.types import DiceError
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

    async def defer(self, thinking: bool = False, ephemeral: bool = False) -> None:
        self.deferred = True

    def is_done(self) -> bool:
        """Mirror Discord: once deferred or answered, the initial response is used up."""
        return self.deferred


class _Followup:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.ephemeral: list[bool] = []
        self.files: list = []
        self.embeds: list = []

    async def send(
        self, content: str = "", ephemeral: bool = False, file=None, embed=None
    ) -> None:
        self.messages.append(content)
        self.ephemeral.append(ephemeral)
        if file is not None:
            self.files.append(file)
        if embed is not None:
            self.embeds.append(embed)


class _User:
    display_name = "Tav"
    voice = None
    id = 4242


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


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


class _World:
    """Just enough world to turn an id into a display name."""

    _NAMES = {"brannoc": "Brannoc the Archivist", "sable": "Sable", "orla": "Orla"}

    def character(self, identifier):
        key = str(identifier).lower()
        if key not in self._NAMES:
            raise KeyError(identifier)
        return _Named(self._NAMES[key])


class _FakeConversation:
    """Records what it was asked; returns fixed answers."""

    world = _World()

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.error = error

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    def answer(self, prompt, *, character=None, speaker=None):
        self.calls.append(("answer", prompt, character, speaker))
        self._maybe_raise()
        return Answer(
            text="The tide-iron crown is lost.",
            source="reply:brannoch",
            detail={"character": "brannoc"},
        )

    def answer_and_speak(self, prompt, *, character=None, speaker=None):
        self.calls.append(("answer_and_speak", prompt, character, speaker))
        self._maybe_raise()
        return Answer(text="spoken", source="dice"), None

    def speak(self, text, *, character=None):
        self.calls.append(("speak", text, character))
        self._maybe_raise()
        raise AssertionError("never reached in these tests")

    def roll(self, parts):
        self.calls.append(("roll", parts))
        self._maybe_raise()
        return Answer(
            text="Brannoc the Archivist rolls 3d6: 4 + 5 + 2 = 11",
            source="dice",
            detail={"character": "Brannoc the Archivist", "hint": "`3d6`"},
        )

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
        "answer",
        "ask",
        "claim",
        "done",
        "edit",
        "export",
        "gift",
        "heal",
        "history",
        "hurt",
        "import",
        "join",
        "leave",
        "mission",
        "options",
        "ping",
        "roll",
        "say",
        "sheet",
        "specialty",
        "spend",
        "stop",
        "undo",
        "ungift",
        "unlock",
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


def test_roll_builds_a_structured_request_not_a_sentence() -> None:
    """The command must hand the roller options, not re-serialise text for a parser."""
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, 4, 6, -1, None, None, None, "Sable", None)

    calls = [call for call in conversation.calls if call[0] == "roll"]
    assert len(calls) == 1
    parts = calls[0][1]
    assert (parts.count, parts.sides, parts.modifier) == (4, 6, -1)
    assert parts.character == "Sable"
    assert all(call[0] != "answer" for call in conversation.calls)


def test_roll_passes_every_option_through() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, 5, 10, None, "hits", 8, None, "Sable", None)
    parts = conversation.calls[-1][1]
    assert (parts.count, parts.sides, parts.mode, parts.target) == (5, 10, "hits", 8)


def test_roll_sends_the_rendered_roll_with_its_hint() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, 3, 6, None, None, None, None, None, None)
    message = interaction.followup.messages[0]
    assert "3d6" in message
    assert "answered by `dice`" in message
    assert "`3d6`" in message  # the shorthand hint appended to the note


def test_roll_reports_a_dice_error_without_raising() -> None:
    message = "mode:hits needs a target, for example target:8"
    conversation = _FakeConversation(error=DiceError(message))
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction, None, None, None, "hits", None, None, None, None)
    assert interaction.followup.messages == [f"error: {message}"]


def test_bare_roll_is_allowed() -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    _invoke(roll, interaction)
    parts = conversation.calls[-1][1]
    assert parts == RollParts()


def test_character_autocomplete_offers_the_world() -> None:
    async def run() -> list[str]:
        bot = create_bot()
        try:
            choices = await _character_choices(_Interaction(bot), "")
            filtered = await _character_choices(_Interaction(bot), "sab")
        finally:
            await bot.close()
        return [choice.name for choice in choices], [c.name for c in filtered]

    everything, filtered = asyncio.run(run())
    assert "Sable" in everything
    assert filtered == [name for name in everything if "sab" in name.lower()]


def test_check_autocomplete_offers_the_worlds_checks() -> None:
    async def run() -> list[str]:
        bot = create_bot()
        try:
            choices = await _check_choices(_Interaction(bot), "ste")
        finally:
            await bot.close()
        return [choice.value for choice in choices]

    assert asyncio.run(run()) == ["stealth"]


def test_autocomplete_never_raises_when_the_world_is_missing() -> None:
    class _Broken:
        def character_names(self):
            raise RuntimeError("no data")

        def check_names(self):
            raise RuntimeError("no data")

        def close(self):
            pass

    async def run() -> tuple[list, list]:
        bot = create_bot()
        bot.conversation = _Broken()
        try:
            return (
                await _character_choices(_Interaction(bot), ""),
                await _check_choices(_Interaction(bot), ""),
            )
        finally:
            await bot.close()

    assert asyncio.run(run()) == ([], [])


@pytest.fixture
def seated(tmp_path, monkeypatch):
    """A seat list and a character file, wired to the bot through the environment."""
    from ttrpg_chatbots.character.store import CharacterStore
    from ttrpg_chatbots.character.types import Character
    from ttrpg_chatbots.sheets.interview import Interview, Question
    from ttrpg_chatbots.sheets.types import Ability, Sheet
    import json

    characters = tmp_path / "characters"
    store = CharacterStore(characters)
    for name, dex in (("Sable", 4), ("Dennis", 2)):
        sheet = Sheet(
            name=name,
            system="house-games",
            attributes={"Dexterity": dex},
            abilities={"Stealth": Ability("Stealth", rank=3)},
            virtues={"Courage": 3},
            willpower=3,
            morality=6,
            health=("Unharmed", "Bruised"),
            freebies=15,
        )
        interview = Interview(
            character=name, questions=(Question("Where from?", "A vat."),)
        )
        store.save(Character(sheet=sheet, interview=interview).seal())

    seats = [
        {
            "id": "truman",
            "kind": "human",
            "character": "sable",
            "world_character": "sable",
            "discord_id": 4242,
            "permissions": ["edit_own_sheet"],
        },
        {
            "id": "gm",
            "kind": "human",
            "character": "dennis",
            "world_character": "sable",
            "discord_id": 9999,
            "permissions": ["view_any_sheet", "award_gifts"],
        },
    ]
    seat_file = tmp_path / "seats.json"
    seat_file.write_text(json.dumps(seats), encoding="utf-8")

    monkeypatch.setenv("TTRPG_SEATS_FILE", str(seat_file))
    monkeypatch.setenv("TTRPG_CHARACTERS_DIR", str(characters))
    return store


def test_sheet_shows_the_callers_own_character(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user = _User()
    interaction.user.id = 4242
    _invoke(sheet, interaction)
    embed = interaction.followup.embeds[0]
    assert embed.title == "Sable"
    assert "house-games" in embed.description and "freebies 15" in embed.description
    assert any(field.name == "Physical" and "DEX 4" in field.value for field in embed.fields)
    assert any(field.name == "Skills" and "Stealth" in field.value for field in embed.fields)
    assert "revision 1" in embed.footer.text and "sealed" in embed.footer.text


def test_sheet_refuses_another_players_sheet(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction, "dennis")
    assert interaction.followup.messages == [
        "error: 'dennis' is not your character; yours is 'sable'"
    ]


def test_a_gm_may_view_another_sheet(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999
    _invoke(sheet, interaction)
    embed = interaction.followup.embeds[0]
    assert embed.title == "Dennis"
    assert any(field.name == "Physical" and "DEX 2" in field.value for field in embed.fields)

    _invoke(sheet, interaction, "sable")
    view = interaction.followup.embeds[-1]
    assert view.title == "Sable"
    assert "shown by gm" in view.footer.text


def test_sheet_explains_when_nobody_is_seated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_SEATS_FILE", str(tmp_path / "absent.json"))
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)
    assert "no character is bound to you" in interaction.followup.messages[0]


def test_sheet_reports_a_missing_character_file(seated, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_CHARACTERS_DIR", str(tmp_path / "empty"))
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)
    assert interaction.followup.messages[0].startswith("error: no character")


def test_roll_defaults_to_the_callers_seat(seated) -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    interaction.user.id = 4242
    _invoke(roll, interaction, 3, 6, None, None, None, None, None, None)
    assert conversation.calls[-1][1].character == "sable"


def test_an_explicit_character_still_wins(seated) -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    interaction.user.id = 4242
    _invoke(roll, interaction, 3, 6, None, None, None, None, "orla", None)
    assert conversation.calls[-1][1].character == "orla"


def test_ask_defaults_to_the_callers_seat(seated) -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    interaction.user.id = 4242
    _invoke(ask, interaction, "hello", None, False)
    assert conversation.calls == [("answer", "hello", "sable", "Tav")]


def test_an_answer_is_attributed_to_its_character(seated) -> None:
    conversation = _FakeConversation()
    interaction = _Interaction(_Bot(conversation))
    interaction.user.id = 4242
    _invoke(ask, interaction, "hello", None, False)
    message = interaction.followup.messages[0]
    assert message.startswith("**Brannoc the Archivist:**")


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



# -- spending from Discord ------------------------------------------------


def test_spend_raises_a_trait_and_persists_it(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(spend, interaction, "Dexterity", 5)
    receipt = interaction.followup.messages[0]
    assert "Dexterity 4→5" in receipt
    assert "5 freebies" in receipt
    assert "10 freebies left" in receipt

    # Written through the store, at a new revision, with a history line.
    reloaded = seated.load("sable")
    assert reloaded.sheet.attribute("Dexterity") == 5
    assert reloaded.sheet.freebies == 10
    assert reloaded.revision == 2
    assert reloaded.history[-1].kind == "sheet"
    assert "Dexterity 5" in reloaded.history[-1].summary


def test_spend_refuses_to_exceed_a_cap(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(spend, interaction, "Dexterity", 6)
    assert interaction.followup.messages[0] == (
        "error: Dexterity is capped at 5 for a Novice character"
    )
    assert seated.load("sable").sheet.attribute("Dexterity") == 4


def test_spend_refuses_what_cannot_be_afforded(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    # Spend the pool down precisely: 15 -> 11 -> 7 -> 2 -> 0.
    _invoke(spend, interaction, "Stealth", 5)  # 2 ability points = 4
    assert "4 freebies left" not in interaction.followup.messages[0]
    assert "11 freebies left" in interaction.followup.messages[0]
    _invoke(spend, interaction, "Courage", 5)  # 2 virtue points = 4
    _invoke(spend, interaction, "Dexterity", 5)  # 1 attribute point = 5
    assert "2 freebies left" in interaction.followup.messages[-1]
    _invoke(spend, interaction, "Willpower", 5)  # 2 willpower points = 2
    assert "0 freebies left" in interaction.followup.messages[-1]

    # Nothing left, so raising further is refused with the price. (Lowering is free, so
    # probing with a lower value would have proved nothing.)
    _invoke(spend, interaction, "Willpower", 6)
    assert interaction.followup.messages[-1] == (
        "error: 1 point(s) of willpower costs 1 freebies; Sable has 0"
    )


def test_spend_needs_the_edit_permission(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999  # the gm seat, which may only view
    _invoke(spend, interaction, "Dexterity", 5)
    assert "may not edit its sheet" in interaction.followup.messages[0]
    assert seated.load("dennis").sheet.attribute("Dexterity") == 2


def test_spend_says_so_when_nobody_is_seated(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_SEATS_FILE", str(tmp_path / "absent.json"))
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(spend, interaction, "Dexterity", 5)
    assert "no character is bound to you" in interaction.followup.messages[0]


def test_options_lists_what_can_be_raised(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(options, interaction)
    text = interaction.followup.messages[0]
    assert "Dexterity 4→5: 5 freebies" in text
    assert "Stealth 3→4: 2 freebies" in text


def test_options_explains_one_trait(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(options, interaction, "Stealth")
    text = interaction.followup.messages[0]
    assert "Stealth: 3 of 5" in text
    assert "next point: 2 freebies" in text


def test_options_says_when_a_trait_is_maxed(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(spend, interaction, "Dexterity", 5)
    _invoke(options, interaction, "Dexterity")
    assert "already at its cap" in interaction.followup.messages[-1]


def test_the_sheet_shows_the_pools(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)
    embed = interaction.followup.embeds[0]
    assert "freebies 15 · xp 0" in embed.description  # the top bar


# -- gifts, missions, provenance ------------------------------------------


def test_a_gift_needs_the_award_permission(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242  # truman, who may only edit their own sheet
    _invoke(gift, interaction, "Auspex", 1)
    assert "may not award Gifts" in interaction.followup.messages[0]


def test_a_gm_awards_a_gift_and_it_persists(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999
    _invoke(gift, interaction, "Walking Fire", None, "Moving x5", "sable")
    assert "gained Walking Fire (flat)" in interaction.followup.messages[0]

    reloaded = seated.load("sable")
    assert reloaded.sheet.gift_count == 1
    assert reloaded.sheet.gift("Walking Fire").description == "Moving x5"
    assert reloaded.history[-1].summary == "gained Walking Fire"


def test_a_win_pays_xp_and_a_gift(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999
    _invoke(mission, interaction, "win", "Thanatosis", 1, "sable")
    text = interaction.followup.messages[0]
    assert "+10 xp" in text
    assert "gained Thanatosis 1" in text

    reloaded = seated.load("sable")
    assert reloaded.sheet.xp == 10
    assert reloaded.sheet.gift_count == 1


def test_a_loss_pays_xp_without_a_gift(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999
    _invoke(mission, interaction, "loss", None, None, "sable")
    assert "loss: +5 xp" in interaction.followup.messages[0]
    assert seated.load("sable").sheet.gift_count == 0


def test_history_shows_the_change_that_was_made(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(spend, interaction, "Dexterity", 5)
    _invoke(history, interaction)
    text = interaction.followup.messages[-1]
    assert "revision" in text
    assert "Dexterity 5" in text
    assert "sheet" in text


def test_a_player_cannot_read_another_history(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(history, interaction, 5, "dennis")
    assert "viewing others needs" in interaction.followup.messages[0]


# -- the draft lifecycle and the file round trip --------------------------


def test_answering_a_sealed_character_is_refused(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(answer, interaction, 1, "elsewhere")
    assert "sealed" in interaction.followup.messages[0]
    assert "/unlock" in interaction.followup.messages[0]


def test_unlock_then_answer_then_done(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242

    _invoke(unlock, interaction, "the concept changed")
    assert "reopened" in interaction.followup.messages[-1]
    assert seated.load("sable").sealed is False

    _invoke(answer, interaction, 1, "Now from a lighthouse.")
    assert "answer 1/1" in interaction.followup.messages[-1]
    assert seated.load("sable").interview.at(1).answer == "Now from a lighthouse."

    _invoke(done, interaction)
    assert "sealed" in interaction.followup.messages[-1]
    reloaded = seated.load("sable")
    assert reloaded.sealed is True
    assert reloaded.ready is True
    # Unlock, amend, reseal: three events, in that order.
    assert [e.kind for e in reloaded.history][-3:] == ["revision", "answer", "sealed"]


def test_an_out_of_range_answer_names_the_range(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(unlock, interaction)
    _invoke(answer, interaction, 99, "nowhere")
    assert "no question 99" in interaction.followup.messages[-1]
    assert "numbered 1..1" in interaction.followup.messages[-1]


def test_export_sends_the_character_file(seated) -> None:
    import json

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(export, interaction)
    assert len(interaction.followup.files) == 1
    payload = json.loads(interaction.followup.files[0].fp.read().decode("utf-8"))
    assert payload["name"] == "Sable"
    assert payload["schema_version"] == 1


def test_import_replaces_the_character_from_a_file(seated) -> None:
    from ttrpg_chatbots.character.types import Character

    seated.interaction = None
    character = seated.load("sable")
    edited = character.with_sheet(
        character.sheet.__class__(
            **{**character.sheet.__dict__, "freebies": 3}
        ),
        summary="imported from the editor",
    )

    class _Attachment:
        async def read(self) -> bytes:
            return edited.to_json().encode("utf-8")

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(import_character, interaction, _Attachment())
    assert "imported" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.freebies == 3
    assert Character.from_json(seated.path("sable").read_text()).sheet.freebies == 3


def test_import_refuses_another_characters_file(seated) -> None:
    class _Attachment:
        async def read(self) -> bytes:
            return seated.load("dennis").to_json().encode("utf-8")

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(import_character, interaction, _Attachment())
    assert "that file is" in interaction.followup.messages[-1]
    assert seated.load("sable").name == "Sable"


# -- claiming a character without editing JSON ----------------------------


@pytest.fixture
def empty_table(seated, tmp_path, monkeypatch):
    """A character store with nobody seated: the first-run experience."""
    monkeypatch.setenv("TTRPG_SEATS_FILE", str(tmp_path / "no-seats-yet.json"))
    return seated


def test_sheet_before_claiming_says_what_to_do(empty_table) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)
    message = interaction.followup.messages[0]
    assert "/claim" in message
    assert "dennis" in message and "sable" in message


def test_claim_binds_you_to_an_unclaimed_character(empty_table, tmp_path, monkeypatch) -> None:
    seat_file = tmp_path / "no-seats-yet.json"
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242

    _invoke(claim, interaction, "sable")
    assert "is yours" in interaction.followup.messages[-1]
    assert seat_file.is_file()
    assert oct(seat_file.stat().st_mode)[-3:] == "600"  # a Discord id is personal data

    # And now the rest of the surface works, with no restart and no hand editing.
    _invoke(sheet, interaction)
    assert interaction.followup.embeds[-1].title == "Sable"


def test_claim_refuses_a_character_someone_plays(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 7777  # a stranger
    _invoke(claim, interaction, "sable")
    assert "already being played" in interaction.followup.messages[0]


def test_claim_refuses_to_move_an_existing_player(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242  # already plays sable
    _invoke(claim, interaction, "dennis")
    assert "already play" in interaction.followup.messages[0]


def test_claiming_your_own_character_twice_is_a_no_op(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(claim, interaction, "sable")
    assert "already play" in interaction.followup.messages[0]


def test_claim_names_an_unknown_character(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 7777
    _invoke(claim, interaction, "nobody")
    assert "no character" in interaction.followup.messages[0]


# -- portraits ------------------------------------------------------------


def test_a_local_portrait_is_uploaded_with_the_embed(seated, tmp_path, monkeypatch) -> None:
    portraits = tmp_path / "portraits"
    portraits.mkdir()
    (portraits / "sable.jpg").write_bytes(b"\xff\xd8\xff\xe0not really a jpeg")
    monkeypatch.setenv("TTRPG_PORTRAITS_DIR", str(portraits))

    character = seated.load("sable")
    portrait = character.sheet.__class__(
        **{**character.sheet.__dict__, "meta": {"portrait": "sable.jpg"}}
    )
    seated.save(character.with_sheet(portrait, summary="added a portrait"))

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)

    embed = interaction.followup.embeds[0]
    assert embed.thumbnail.url == "attachment://sable.jpg"
    assert len(interaction.followup.files) == 1  # it has to be uploaded to be visible


def test_a_missing_portrait_file_is_reported_not_faked(seated, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TTRPG_PORTRAITS_DIR", str(tmp_path / "absent"))
    character = seated.load("sable")
    portrait = character.sheet.__class__(
        **{**character.sheet.__dict__, "meta": {"portrait": "mystery.jpg"}}
    )
    seated.save(character.with_sheet(portrait, summary="a portrait we do not have"))

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)

    embed = interaction.followup.embeds[0]
    assert embed.thumbnail.url is None
    assert interaction.followup.files == []


def test_a_portrait_url_is_used_directly(seated) -> None:
    character = seated.load("sable")
    portrait = character.sheet.__class__(
        **{
            **character.sheet.__dict__,
            "meta": {"portrait": "https://example.test/sable.png"},
        }
    )
    seated.save(character.with_sheet(portrait, summary="remote portrait"))

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction)

    assert interaction.followup.embeds[0].thumbnail.url == "https://example.test/sable.png"
    assert interaction.followup.files == []  # nothing to upload


def test_the_code_style_never_uploads_a_portrait(seated, tmp_path, monkeypatch) -> None:
    portraits = tmp_path / "portraits"
    portraits.mkdir()
    (portraits / "sable.jpg").write_bytes(b"x")
    monkeypatch.setenv("TTRPG_PORTRAITS_DIR", str(portraits))
    character = seated.load("sable")
    portrait = character.sheet.__class__(
        **{**character.sheet.__dict__, "meta": {"portrait": "sable.jpg"}}
    )
    seated.save(character.with_sheet(portrait, summary="portrait"))

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(sheet, interaction, None, "code")

    assert interaction.followup.messages[-1].startswith("```")
    assert interaction.followup.files == []


# -- editing the sheet ----------------------------------------------------


def test_edit_sets_a_value_for_free(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(edit, interaction, "Dexterity", 2)  # Sable starts at 4: this lowers it
    assert "Dexterity 4→2" in interaction.followup.messages[-1]
    reloaded = seated.load("sable")
    assert reloaded.sheet.attribute("Dexterity") == 2
    assert reloaded.sheet.freebies == 15  # a free edit spends nothing


def test_edit_still_respects_caps(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(edit, interaction, "Dexterity", 9)
    assert "capped at 5" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.attribute("Dexterity") == 4


def test_edit_records_what_it_can_undo(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(edit, interaction, "Stealth", 2)
    event = seated.load("sable").history[-1]
    assert event.detail == {"trait": "Stealth", "kind": "ability", "before": 3, "after": 2}


def test_undo_puts_the_old_value_back(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(edit, interaction, "Stealth", 1)
    assert seated.load("sable").sheet.ability("Stealth").rank == 1

    _invoke(undo, interaction)
    assert "undid" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.ability("Stealth").rank == 3


def test_undo_with_nothing_to_undo_says_so(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(undo, interaction)
    assert "nothing to undo" in interaction.followup.messages[-1]


def test_specialty_can_be_set_and_cleared(seated) -> None:
    # Give Sable an ability at rank 4 first, then name its specialty.
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(edit, interaction, "Stealth", 4)
    _invoke(specialty, interaction, "Stealth", "dark  alleys")
    assert "Stealth specialty dark alleys" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.ability("Stealth").specialty == "dark alleys"

    _invoke(specialty, interaction, "Stealth", "")
    assert seated.load("sable").sheet.ability("Stealth").specialty == ""


def test_a_specialty_needs_rank_four(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(specialty, interaction, "Stealth", "anything")  # rank 3
    assert "rank 4 or more" in interaction.followup.messages[-1]


def test_hurt_and_heal_move_the_health_track(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(hurt, interaction, 1)
    assert "hurt 1" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.meta["health_current"] == 1

    _invoke(heal, interaction, 1)
    assert "healed 1" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.meta["health_current"] == 2


def test_healing_at_full_health_is_refused(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(heal, interaction, 1)
    assert "already at 2/2" in interaction.followup.messages[-1]


def test_undo_reverses_a_hurt(seated) -> None:
    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 4242
    _invoke(hurt, interaction, 2)
    assert seated.load("sable").sheet.meta["health_current"] == 0
    _invoke(undo, interaction)
    assert seated.load("sable").sheet.meta["health_current"] == 2


def test_ungift_removes_and_undo_restores(seated) -> None:
    from ttrpg_chatbots.sheets.types import Gift
    from ttrpg_chatbots.character.types import Character

    interaction = _Interaction(_Bot(_FakeConversation()))
    interaction.user.id = 9999  # the gm, who may award
    _invoke(gift, interaction, "Auspex", 2, "", "sable")
    assert seated.load("sable").sheet.gift_count == 1

    interaction.user.id = 4242
    _invoke(ungift, interaction, "Auspex")
    assert "lost Auspex" in interaction.followup.messages[-1]
    assert seated.load("sable").sheet.gift_count == 0
