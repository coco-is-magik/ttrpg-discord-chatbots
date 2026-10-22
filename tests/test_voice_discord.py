import discord

from ttrpg_chatbots.audio import DISCORD_FRAME_BYTES
from ttrpg_chatbots.voice.discord_voice import DiscordAudioSource, play_in
from ttrpg_chatbots.voice.player import VoicePlayer

from tts_support import FakeSource

FRAME = b"\x01" * DISCORD_FRAME_BYTES
SILENT = b"\x00" * DISCORD_FRAME_BYTES


def test_it_is_a_discord_audio_source() -> None:
    assert isinstance(DiscordAudioSource(VoicePlayer()), discord.AudioSource)


def test_reads_frames_then_reports_the_end() -> None:
    player = VoicePlayer()
    player.enqueue(FakeSource([FRAME]))
    source = DiscordAudioSource(player)

    assert source.read() == FRAME
    assert source.read() == b"", "b'' tells discord.py playback is over"
    assert source.is_opus() is False


def test_padding_keeps_the_stream_open_with_silence() -> None:
    player = VoicePlayer()
    player.enqueue(FakeSource([FRAME]))
    source = DiscordAudioSource(player, pad_silence=True)

    assert source.read() == FRAME
    assert source.read() == SILENT
    assert source.read() == SILENT


def test_cleanup_leaves_the_shared_queue_alone() -> None:
    """cleanup must not touch the player: it is called once per stream, the player outlives them.

    This test used to assert the opposite (that cleanup dropped the queue), which is what made him
    speak exactly once -- see the docstring on DiscordAudioSource.cleanup.
    """
    player = VoicePlayer()
    queued = FakeSource([FRAME])
    player.enqueue(queued)

    DiscordAudioSource(player).cleanup()

    assert queued.closes == 0, "a finished stream does not close the next clip"
    assert not player.is_idle(), "the queued clip is still there to play"


def test_play_in_hands_the_source_to_the_voice_client() -> None:
    class FakeVoiceClient:
        def __init__(self) -> None:
            self.played = []
            self.after = "unset"

        def play(self, source, *, after=None) -> None:
            self.played.append(source)
            self.after = after

    client = FakeVoiceClient()
    player = VoicePlayer()
    player.enqueue(FakeSource([FRAME]))

    source = play_in(client, player, after=lambda error: None)

    assert client.played == [source]
    assert isinstance(source, DiscordAudioSource)
    assert callable(client.after), "the caller is told when the stream ends"
