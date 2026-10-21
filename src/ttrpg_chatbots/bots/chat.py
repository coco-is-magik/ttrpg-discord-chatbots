"""How a friend answers: the classifier, wired for Discord.

Deliberately classifier-only to begin with. That is not a placeholder: when a language model is
configured and then fails, this is the responder that catches the fall, so it is built and tested
as a first-class path rather than a stub.

Two layers, in order:

1. **social intents** (`reply/intents.py`) -- deterministic patterns for the handful of moves a
   group makes constantly: greetings, presence, thanks, goodbyes, apologies, agreement,
   smalltalk. These are matched before any compression work, because NCD is bad at short social
   phrases ("hey" scores 0.92 against its own anchor).
2. **knowledge** (`reply/replier.py`) -- tagged facts, gated by what the character knows, with a
   distance ceiling so an unrelated question is refused instead of answered with a rumour.

Both layers are stateless. What makes this a *conversation* is the third input, `context`:
the last few turns, and the transition table in the dataset directory that says which act
plausibly follows which. Context only ever does two things -- prefer a reading that makes
sense where the message landed, and stay quiet instead of repeating itself. Without it, every
answer is exactly what it was before.

The friends know only social tags today, so a lore question deflects honestly. When they get
characters at the table, the same class is pointed at the world dataset and they know those tags
too.
"""

from __future__ import annotations

import os
from pathlib import Path

from ttrpg_chatbots.life import LifeError, LifeVoice, load_lives
from ttrpg_chatbots.reply.context import Context
from ttrpg_chatbots.reply.datasets import load_world
from ttrpg_chatbots.reply.replier import Replier
from ttrpg_chatbots.reply import intents as social
from ttrpg_chatbots.reply.responder import answer_from_reply
from ttrpg_chatbots.reply.style import apply_style
from ttrpg_chatbots.reply.style import Style
from ttrpg_chatbots.reply.transitions import TransitionError, TransitionModel
from ttrpg_chatbots.reply.types import DatasetError, World
from ttrpg_chatbots.respond import Answer

DEFAULT_FRIENDS_DATA = Path("examples/friends_world")
FRIENDS_DATA_ENV = "TTRPG_FRIENDS_DATA"
TRANSITIONS_FILE = "transitions.json"
LIFE_FILE = "life.json"
# A machine-local table (for instance one imported from Switchboard, which may not be
# committed) overrides the one beside the dataset. The dataset keeps its authored table so a
# fresh clone behaves the same everywhere.
TRANSITIONS_ENV = "TTRPG_FRIENDS_TRANSITIONS"

# Measured on examples/friends_world: the closest a non-social question came to a social anchor
# was 0.714 ("tell me about the guild" against an apology). 0.65 leaves headroom below that, so
# anything that is not a recognised social move is refused rather than answered sideways.
DEFAULT_MAX_DISTANCE = 0.65

# Between "close enough to answer" and "close enough to be interesting" there is a band where a
# short hedge beats a confident answer to a different question. Measured here: a question that
# belongs to a subject lands at 0.18-0.55, an unrelated one at 0.74+.
DEFAULT_ASSURED = 0.45


class ChatError(RuntimeError):
    """Raised when a friend cannot answer: no dataset, an unknown character, or empty text."""


class FriendChat:
    """A frontier-free responder shared by every friend in the process."""

    def __init__(
        self,
        data: Path | str | None = None,
        *,
        max_distance: float | None = DEFAULT_MAX_DISTANCE,
        rotate: bool = True,
        seed: str = "",
        transitions: Path | str | None = None,
    ) -> None:
        self._data = (
            Path(data)
            if data is not None
            else Path(os.environ.get(FRIENDS_DATA_ENV, str(DEFAULT_FRIENDS_DATA)))
        )
        self._max_distance = max_distance
        self._rotate = rotate
        self._seed = seed
        # An explicit path wins. Otherwise a local override (see TRANSITIONS_ENV), otherwise
        # ``transitions.json`` beside the dataset. A path that does not exist means "no table" --
        # the same behaviour as a dataset that never shipped one: context then changes nothing.
        if transitions is not None:
            self._transitions_path = Path(transitions)
        else:
            override = os.environ.get(TRANSITIONS_ENV, "").strip()
            self._transitions_path = (
                Path(override) if override else self._data / TRANSITIONS_FILE
            )
        self._transitions_model: TransitionModel | None = None
        self._transitions_loaded = False
        self._world: World | None = None
        self._replier: Replier | None = None
        self._lives: dict | None = None
        self._voice_ref: LifeVoice | None = None

    @property
    def data(self) -> Path:
        return self._data

    @property
    def world(self) -> World:
        """The dataset, loaded once. A failure is reported as ChatError, not a traceback."""
        if self._world is None:
            try:
                self._world = load_world(self._data)
            except (DatasetError, OSError, ValueError) as error:
                raise ChatError(
                    f"cannot load the friends dataset {self._data}: {error}"
                ) from error
        return self._world

    @property
    def transitions(self) -> TransitionModel | None:
        """The act table beside the dataset, or ``None`` when there is none."""
        if not self._transitions_loaded:
            try:
                self._transitions_model = TransitionModel.from_file(self._transitions_path)
            except (TransitionError, OSError) as error:
                raise ChatError(
                    f"cannot load the transition table {self._transitions_path}: {error}"
                ) from error
            self._transitions_loaded = True
        return self._transitions_model

    @property
    def replier(self) -> Replier:
        if self._replier is None:
            self._replier = Replier(
                self.world,
                max_distance=self._max_distance,
                rotate=self._rotate,
                seed=self._seed,
                transitions=self.transitions,
                assured=DEFAULT_ASSURED,
            )
        return self._replier

    def friends(self) -> tuple[str, ...]:
        """The friend ids this dataset can answer as."""
        return tuple(character.id for character in self.world.characters)

    @property
    def voice_ref(self) -> LifeVoice | None:
        """The friends' lives, loaded once. ``None`` when nobody has one yet."""
        if self._voice_ref is None:
            try:
                self._lives = load_lives(self._data / LIFE_FILE)
            except LifeError as error:
                raise ChatError(f"cannot load the friends' lives: {error}") from error
            self._voice_ref = LifeVoice(self._lives)
        return self._voice_ref or None

    def _from_life(
        self,
        prompt: str,
        friend: str,
        *,
        style: Style | None,
        addressed: bool,
        force_tag: str | None,
        context: Context | None = None,
    ) -> Answer | None:
        """Answer out of what he is in the middle of, when the move is his own life.

        This is deliberately ahead of the classifier: "what are you up to" and "rough day" are
        not questions about facts, and answering them from a knowledge bank is how a person ends
        up sounding like a wiki with a personality painted on.
        """
        if not addressed or force_tag is not None:
            return None
        voice = self.voice_ref
        if voice is None or not voice.has(friend):
            return None
        intent = self.replier.choose(prompt, friend, context)
        if intent in (social.SOCIAL_PRESENCE, social.SOCIAL_SMALLTALK):
            text = voice.doing(friend)
        elif intent == social.SOCIAL_ROUGH:
            text = voice.commiserate(friend)
        elif intent == social.SOCIAL_WHY:
            text = voice.elaborate(friend)
        else:
            return None
        if not text:
            return None
        activity = voice.current(friend)
        return Answer(
            text=apply_style(text, style),
            source=f"life:{friend}",
            detail={
                "tag": intent,
                "character": friend,
                "activity": activity.id if activity else None,
            },
        )

    def reply(
        self,
        text: str,
        friend: str,
        *,
        speaker: str | None = None,
        context: Context | None = None,
        addressed: bool = True,
        style: Style | None = None,
        force_tag: str | None = None,
    ) -> Answer | None:
        """Answer ``text`` as ``friend``, or return ``None`` to say nothing.

        ``None`` is a decision, not a failure: an unprompted remark that the friend has
        already answered is better left alone. ``address`` it -- a mention -- and the
        friend always answers.
        """
        prompt = (text or "").strip()
        if not prompt:
            raise ChatError("nothing to answer: the message was empty")
        try:
            self.world.character(friend)
        except DatasetError as error:
            raise ChatError(str(error)) from error

        from_life = self._from_life(
            prompt,
            friend,
            style=style,
            addressed=addressed,
            force_tag=force_tag,
            context=context,
        )
        if from_life is not None:
            return from_life

        reply = self.replier.reply(
            prompt,
            friend,
            speaker=speaker,
            context=context,
            addressed=addressed,
            style=style,
            force_tag=force_tag,
        )
        if reply is None:
            return None
        return answer_from_reply(reply)
