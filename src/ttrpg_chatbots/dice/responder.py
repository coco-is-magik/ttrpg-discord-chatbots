"""A responder that rolls instead of talking when the message asks for a roll.

Composable on both sides: wrap the classifier and "roll stealth" works with no model at
all, and it is also the last link in the chain when an LLM has no tool support or decides
not to use it. Everything else in the message goes to the wrapped responder unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ttrpg_chatbots.dice.checks import Checkbook
from ttrpg_chatbots.dice.intent import parse_instruction
from ttrpg_chatbots.dice.roller import Roller
from ttrpg_chatbots.dice.types import DiceError
from ttrpg_chatbots.respond import Answer, Responder


class DiceResponder:
    """Rolls when the prompt is a roll instruction; otherwise delegates."""

    def __init__(
        self,
        roller: Roller,
        fallback: Responder,
        *,
        checks: Checkbook | None = None,
        character: str = "",
        characters: Mapping[str, str] | Sequence[str] | None = None,
    ) -> None:
        self._roller = roller
        self._fallback = fallback
        self._checks = checks if checks is not None else Checkbook()
        self._character = (character or "").strip()
        self._characters = characters

    @property
    def name(self) -> str:
        return "dice"

    @property
    def fallback_name(self) -> str:
        return self._fallback.name

    def answer(self, prompt: str) -> Answer:
        request = parse_instruction(prompt, checks=self._checks, characters=self._characters)
        if request is None:
            return self._fallback.answer(prompt)

        character = request.character or self._character
        if not character:
            raise DiceError(
                "this message asks for a roll but does not say who is rolling; "
                "say 'roll 3d6 for <name>' or set a default character"
            )

        result = self._roller.roll(request.spec, character=character)
        return Answer(
            text=result.render(),
            source="dice",
            detail={
                "character": character,
                "roll": result.as_dict(),
                "check": request.check.id if request.check is not None else None,
            },
        )
