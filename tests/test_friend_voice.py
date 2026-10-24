"""A friend in a voice channel: join, speak, leave.

No Discord and no synthesiser here: the channel, the voice client and the cast are all fakes, because
what is worth testing is the bookkeeping -- moving between channels, refusing to speak when he has not
joined, and reporting a permission failure as advice rather than a traceback.
"""

from __future__ import annotations

import asyncio

import discord
import pytest

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.bots.voice import FriendVoice, VoiceUnavailable


class _Clip:
    sample_rate = 22050
    channels = 1
    pcm = b"\x00\x00" * 22050  # one second of silence


class _Cast:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, speaker) -> PcmAudio:
        self.calls.append((text, speaker.id))
        return _Clip()


class _VoiceClient:
    """A stand-in for discord.py's voice client, faithful where it matters.

    ``play`` refuses while something is playing, exactly as discord.py does, and ``after`` fires when
    the stream ends. Without both of those, the bug this file now covers ("he speaks once and never
    again") cannot be reproduced.
    """

    def __init__(self, channel) -> None:
        self.channel = channel
        self.connected = True
        self.playing = False
        self.disconnected = False
        self.moved_to = None
        self.started = 0
        self.stops = 0
        self._after = None
        self._source = None

    def is_connected(self) -> bool:
        return self.connected

    def is_playing(self) -> bool:
        return self.playing

    def play(self, source, *, after=None) -> None:
        if self.playing:
            raise discord.ClientException("Already playing audio.")
        self.playing = True
        self.started += 1
        self._source = source
        self._after = after

    def stop(self) -> None:
        self.stops += 1
        self.playing = False
        if self._after is not None:
            self._after(None)

    def drain(self) -> int:
        """Read the stream to exhaustion the way the audio thread would."""
        frames = 0
        while True:
            if self._source is None:
                break
            frame = self._source.read()
            if not frame:
                break
            frames += 1
        self.playing = False
        if self._after is not None:
            self._after(None)
        return frames

    async def move_to(self, channel) -> None:
        self.moved_to = channel
        self.channel = channel

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True


class _Channel:
    def __init__(self, name: str = "General", *, fail: BaseException | None = None) -> None:
        self.name = name
        self.id = hash(name) & 0xFFFF
        self.fail = fail
        self.connected = 0

    async def connect(self, *, self_deaf: bool = False):
        if self.fail is not None:
            raise self.fail
        self.connected += 1
        return _VoiceClient(self)


def _room(**kwargs) -> FriendVoice:
    return FriendVoice(friend="friend-a", cast=kwargs.pop("cast", _Cast()), **kwargs)


def test_he_joins_moves_and_leaves() -> None:
    room = _room()
    lounge, study = _Channel("Lounge"), _Channel("Study")

    assert "joined Lounge" in asyncio.run(room.join(lounge))
    assert "already in Lounge" in asyncio.run(room.join(lounge))
    assert "moved to Study" in asyncio.run(room.join(study))
    assert "left Study" in asyncio.run(room.leave())
    assert not room.connected


def test_leaving_when_he_was_never_there_is_not_an_error() -> None:
    assert "was not in a voice channel" in asyncio.run(_room().leave())


def test_speaking_uses_his_own_casting() -> None:
    cast = _Cast()
    room = _room(cast=cast)
    asyncio.run(room.join(_Channel()))

    message = asyncio.run(room.say("there he is"))

    assert cast.calls == [("there he is", "friend-a")], "cast by friend id, not by the helper"
    assert message.startswith("spoke 1.0s")


def test_he_refuses_to_speak_before_joining() -> None:
    with pytest.raises(VoiceUnavailable, match="join one first"):
        asyncio.run(_room().say("hello"))


def test_a_missing_permission_is_reported_as_advice() -> None:
    # A test command should say what to grant, not raise a traceback into the command handler.
    channel = _Channel("Lounge", fail=discord.Forbidden(_Response(403), "denied"))

    with pytest.raises(VoiceUnavailable, match="Connect and Speak"):
        asyncio.run(_room().join(channel))


class _Response:
    """The minimum an HTTPException needs to build a message."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "Forbidden"


def test_the_bot_resolves_his_own_voice_not_the_default() -> None:
    # A bare VoiceCast() resolves to the built-in narrator voice, which would make "his voice" a lie.
    # The casting rule in the world directory is where the persona pins the engine and the length
    # scale, so this checks the bot actually reads it.
    from ttrpg_chatbots.bots.voice import _speaker

    profile = FriendVoice(friend="friend-a")._cast_or_default().profile_for(_speaker("friend-a"))

    assert profile.engine == "piper"
    assert profile.voice == "en_US-joe-medium", "the deep voice chosen by measurement"
    assert profile.speed > 1.0, "piper's length scale: above 1 is slower, which is the brief"


def test_a_friend_with_no_cast_rule_gets_the_default() -> None:
    from ttrpg_chatbots.bots.voice import _speaker

    profile = FriendVoice(friend="friend-d")._cast_or_default().profile_for(_speaker("friend-d"))

    assert profile.engine is None, "a friend nobody has cast yet has no voice"


def test_speaking_twice_in_a_row_works() -> None:
    """The bug from the channel: he spoke once and the command never worked again.

    The old guard asked discord.py whether it was playing and skipped starting playback when it said
    yes. This walks the full lifecycle -- speak, stream ends, speak again -- and asserts both clips
    reached the client.
    """
    room = _room()
    asyncio.run(room.join(_Channel("General")))
    client = room._client

    assert asyncio.run(room.say("there he is")).startswith("spoke")
    assert client.started == 1
    assert client.drain() > 0, "the audio thread plays it out and the stream ends"

    second = asyncio.run(room.say("and again"))
    assert second.startswith("spoke"), "a second clip starts a new stream, it is not swallowed"
    assert client.started == 2
    assert client.drain() > 0

    assert asyncio.run(room.say("and a third")).startswith("spoke")
    assert client.started == 3


def test_a_clip_queued_while_speaking_is_appended() -> None:
    """A clip arriving mid-sentence joins the same stream instead of being dropped."""
    room = _room()
    asyncio.run(room.join(_Channel("General")))
    client = room._client

    asyncio.run(room.say("first"))
    queued = asyncio.run(room.say("second"))

    assert queued.startswith("queued")
    assert client.started == 1, "no second stream while one is running"
    assert client.stops == 0, "a healthy stream is never stopped"
    assert room._player.queued == 2


def test_a_stale_player_is_taken_back() -> None:
    """If discord.py thinks something is playing that we do not, we stop it and carry on."""
    room = _room()
    asyncio.run(room.join(_Channel("General")))
    client = room._client

    client.playing = True  # a stream we lost track of
    out = asyncio.run(room.say("hello"))

    assert out.startswith("spoke")
    assert client.stops == 1
    assert client.started == 1


def test_leaving_clears_playback_state() -> None:
    """After leaving, speaking is refused -- and rejoining works."""
    room = _room()
    channel = _Channel("General")
    asyncio.run(room.join(channel))
    asyncio.run(room.say("hello"))
    asyncio.run(room.leave())

    assert room._speaking is False
    with pytest.raises(VoiceUnavailable):
        asyncio.run(room.say("anyone there"))

    asyncio.run(room.join(channel))
    assert asyncio.run(room.say("back again")).startswith("spoke")


def test_a_collected_stream_does_not_delete_the_next_clip() -> None:
    """The measured root cause of "he speaks once and never again".

    discord.py's AudioPlayer calls ``source.cleanup()`` from ``__del__``, and the player that ended
    one stream is collected exactly when the next one starts. When ``cleanup`` cleared the shared
    VoicePlayer, the audio queued for the *next* clip was deleted before it could be read.
    """
    import gc

    from ttrpg_chatbots.audio.pcm import PcmAudio
    from ttrpg_chatbots.voice.discord_voice import DiscordAudioSource
    from ttrpg_chatbots.voice.player import VoicePlayer
    from ttrpg_chatbots.voice.sources import PcmFrameSource

    clip = PcmAudio(pcm=b"\x01\x00" * 8000, sample_rate=22050, channels=1)
    player = VoicePlayer()

    first = DiscordAudioSource(player)
    player.say(PcmFrameSource(clip))
    frames = 0
    while first.read():  # the audio thread plays it out to the end
        frames += 1
    assert frames > 0, "the first clip plays"

    # what discord.py does when the next stream is started: the finished player is collected
    del first
    gc.collect()

    player.say(PcmFrameSource(clip))
    assert player.queued == 1, "a collected stream must not clear the shared queue"
    assert DiscordAudioSource(player).read(), "the next clip still has audio"
