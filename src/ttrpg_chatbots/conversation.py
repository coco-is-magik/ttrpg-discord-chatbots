"""Everything a chat front end needs, with no front end in it.

:class:`Conversation` owns the answer chain and the voices: dice first (free and
deterministic), the language model next when it is switched on, and the compression
classifier as the safety net. It returns :class:`~ttrpg_chatbots.respond.Answer` objects
and :class:`~ttrpg_chatbots.audio.pcm.PcmAudio` clips, so a Discord command, a terminal or
a future web front end all call the same two or three methods.

Nothing here imports ``discord``. Everything is built lazily and closed explicitly, so a
bot that only answers ``/ping`` never loads a dataset or a speech model.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ttrpg_chatbots.audio.pcm import PcmAudio
from ttrpg_chatbots.dice.checks import load_checks
from ttrpg_chatbots.dice.responder import DiceResponder
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.tool import DiceTool
from ttrpg_chatbots.llm import build_backend, load_llm_config
from ttrpg_chatbots.llm.fallback import FallbackResponder
from ttrpg_chatbots.llm.prompt import persona_from
from ttrpg_chatbots.llm.responder import LlmResponder
from ttrpg_chatbots.llm.tools import ToolBox
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply.responder import ClassifierResponder
from ttrpg_chatbots.reply.types import DatasetError, World
from ttrpg_chatbots.respond import Answer, Responder
from ttrpg_chatbots.tts import VoiceCast, VoiceDirectory, load_voice_directory

DEFAULT_DATA = Path("examples/demo_world")


class ConversationError(RuntimeError):
    """Raised when a request cannot be answered or spoken."""


@dataclass
class Conversation:
    """Answers prompts as one of a world's characters, and speaks the result."""

    data: Path = DEFAULT_DATA
    use_llm: bool = False
    seed: int | None = None
    _world: World | None = field(default=None, repr=False)
    _cast: VoiceCast | None = field(default=None, repr=False)
    _synthesizer: object = field(default=None, repr=False)
    # Keyed by (character id, speaker): a responder is bound to one character's tags and
    # one speaker's name, so it must not be shared between them.
    _responders: dict[tuple[str, str | None], Responder] = field(
        default_factory=dict, repr=False
    )

    @property
    def world(self) -> World:
        """The loaded world, read once."""
        if self._world is None:
            try:
                self._world = load_world(self.data)
            except (DatasetError, OSError, ValueError) as error:
                raise ConversationError(f"cannot load {self.data}: {error}") from error
        return self._world

    def character_names(self) -> tuple[str, ...]:
        """The characters a caller may ask for, by display name."""
        return tuple(character.name for character in self.world.characters)

    def resolve(self, name: str | None):
        """A character by id or name; the first one when ``name`` is empty."""
        world = self.world
        try:
            return world.character(name or world.characters[0].id)
        except Exception as error:  # noqa: BLE001 - reported as a usable message
            known = ", ".join(self.character_names()) or "none"
            raise ConversationError(f"no character {name!r}; known: {known}") from error

    def _answers(self, character, speaker: str | None) -> Responder:
        """Dice, then the model when enabled, then the classifier.

        Cached per ``(character, speaker)``: the classifier is gated by that character's
        tags and fills ``{speaker}``, so sharing one responder across characters would
        answer everyone as whoever asked first.
        """
        key = (character.id, speaker)
        if key not in self._responders:
            classifier = ClassifierResponder(
                Replier(self.world), character.id, speaker=speaker
            )
            names = {
                alias.lower(): who.name
                for who in self.world.characters
                for alias in who.aliases
            }
            self._responders[key] = DiceResponder(
                Roller(random.Random(self.seed) if self.seed is not None else None),
                classifier,
                checks=load_checks(self.data),
                character=character.name,
                characters=names,
            )
        dice = self._responders[key]
        if not self.use_llm:
            return dice
        config = load_llm_config()
        if not config.enabled:
            raise ConversationError("TTRPG_LLM_BACKEND is off, so there is no model to use")
        primary = LlmResponder(
            lambda: build_backend(config),
            persona_from(character),
            name=f"llm:{config.backend}",
            tools=ToolBox(
                DiceTool(Roller(), load_checks(self.data), default_character=character.name)
            ),
        )
        return FallbackResponder(primary, dice)

    def answer(
        self, prompt: str, *, character: str | None = None, speaker: str | None = None
    ) -> Answer:
        """Reply to ``prompt`` in one character's voice."""
        if not prompt.strip():
            raise ConversationError("nothing to answer")
        who = self.resolve(character)
        return self._answers(who, speaker).answer(prompt)

    def speak(self, text: str, *, character: str | None = None) -> PcmAudio:
        """Synthesize ``text`` with the character's cast voice, or the default engine."""
        if not text.strip():
            raise ConversationError("nothing to speak")
        if not character:
            # Loading a voice costs ~2 s, so keep it: a bot says many unattributed lines.
            return self._default_synthesizer().synthesize(text)
        return self._voice_cast().synthesize(text, self.resolve(character))

    def _default_synthesizer(self):
        if self._synthesizer is None:
            from ttrpg_chatbots.tts import resolve_synthesizer

            self._synthesizer = resolve_synthesizer()
        return self._synthesizer

    def answer_and_speak(
        self, prompt: str, *, character: str | None = None, speaker: str | None = None
    ) -> tuple[Answer, PcmAudio | None]:
        """Answer, then speak it. A speech failure keeps the text."""
        answer = self.answer(prompt, character=character, speaker=speaker)
        try:
            clip = self.speak(
                answer.text, character=answer.detail.get("character") or character
            )
        except Exception:  # noqa: BLE001 - the text is still worth delivering
            return answer, None
        return answer, clip

    def voices(self) -> Sequence[dict[str, object]]:
        """Which voice each character is cast to, for diagnostics."""
        directory = self._voice_directory()
        return tuple(
            {
                "character": character.id,
                "name": character.name,
                "voice": directory.resolve(character).describe(),
            }
            for character in self.world.characters
        )

    def _voice_directory(self) -> VoiceDirectory:
        world = self.world
        return load_voice_directory(
            self.data,
            known_tags={tag for character in world.characters for tag in character.tags},
            known_characters={
                alias
                for character in world.characters
                for alias in (character.id, character.name)
            },
        )

    def _voice_cast(self) -> VoiceCast:
        if self._cast is None:
            self._cast = VoiceCast(self._voice_directory())
        return self._cast

    def close(self) -> None:
        """Release loaded voices and the default synthesizer."""
        if self._cast is not None:
            self._cast.close()
            self._cast = None
        if self._synthesizer is not None:
            self._synthesizer.close()
            self._synthesizer = None

