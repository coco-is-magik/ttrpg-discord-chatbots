"""Characters: build, randomise, import, update -- and keep the history.

Six small pieces instead of one large one, so each has exactly one job:

* :mod:`~ttrpg_chatbots.character.types` -- ``Character`` and ``Event``: the native
  structure, JSON on disk, with the interview sealed once it is complete.
* :mod:`~ttrpg_chatbots.character.store` -- ``CharacterStore``: one file per character,
  written atomically.
* :mod:`~ttrpg_chatbots.character.creation` -- the interview-then-mechanics wizard.
* :mod:`~ttrpg_chatbots.character.prompting` -- the ``Prompter`` seam that keeps the
  wizard ignorant of whether a terminal or Discord is answering.
* :mod:`~ttrpg_chatbots.character.randomiser` -- legal random mechanics, or assignment of
  a finished premade character.
* :mod:`~ttrpg_chatbots.character.importer` -- a one-way read of the old workbook, so the
  spreadsheet becomes a source rather than a dependency.

Mechanics live in :mod:`ttrpg_chatbots.sheets` (a ``Sheet``), prose in
:mod:`ttrpg_chatbots.sheets.interview` (an ``Interview``); a ``Character`` is the pair
plus what has happened since.
"""

from ttrpg_chatbots.character.creation import ask_interview, ask_mechanics, start_character
from ttrpg_chatbots.character.importer import import_character, import_workbook, importable_names
from ttrpg_chatbots.character.prompting import Prompter, PrompterError
from ttrpg_chatbots.character.randomiser import (
    assign_premade,
    pool_by_system,
    random_character,
    random_mechanics,
)
from ttrpg_chatbots.character.store import CharacterStore
from ttrpg_chatbots.character.types import (
    EVENT_KINDS,
    SCHEMA_VERSION,
    Character,
    CharacterError,
    Event,
    interview_digest,
)

__all__ = [
    "EVENT_KINDS",
    "SCHEMA_VERSION",
    "Character",
    "CharacterError",
    "CharacterStore",
    "Event",
    "Prompter",
    "PrompterError",
    "ask_interview",
    "ask_mechanics",
    "assign_premade",
    "import_character",
    "import_workbook",
    "importable_names",
    "interview_digest",
    "pool_by_system",
    "random_character",
    "random_mechanics",
    "start_character",
]
