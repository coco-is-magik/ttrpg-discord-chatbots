"""Dice: game-neutral pools, four ways to read them, and a tool for LLMs.

``Roller`` turns a :class:`RollSpec` (count, sides, modifier) plus a character into a
:class:`RollResult`. ``mode`` decides what matters: ``list`` shows the dice, ``sum`` adds
them, ``hits`` counts dice at or above a target, and ``check`` compares the total against
a difficulty. Named checks come from ``checks.jsonl`` so a table can say "roll stealth".

Two ways in for a language model:

* :class:`DiceTool` -- JSON Schema plus an executor, for real tool calling;
* :class:`DiceResponder` -- an instruction parser, for when no model is deciding.
"""

from ttrpg_chatbots.dice.checks import Check, Checkbook, checks_from_records, load_checks
from ttrpg_chatbots.dice.intent import RollRequest, parse_instruction
from ttrpg_chatbots.dice.notation import is_notation, parse_notation
from ttrpg_chatbots.dice.responder import DiceResponder
from ttrpg_chatbots.dice.roller import RandomSource, Roller
from ttrpg_chatbots.dice.tool import TOOL_NAME, DiceTool, ToolOutcome, tool_schema
from ttrpg_chatbots.dice.types import (
    MODES,
    CheckError,
    DiceError,
    NotationError,
    RollResult,
    RollSpec,
    notation_of,
)

__all__ = [
    "MODES",
    "TOOL_NAME",
    "Check",
    "CheckError",
    "Checkbook",
    "DiceError",
    "DiceResponder",
    "DiceTool",
    "NotationError",
    "RandomSource",
    "RollRequest",
    "RollResult",
    "RollSpec",
    "Roller",
    "ToolOutcome",
    "checks_from_records",
    "is_notation",
    "load_checks",
    "notation_of",
    "parse_instruction",
    "parse_notation",
    "tool_schema",
]
