"""Character sheets: read somebody else's sheet, then roll from it.

The layering is deliberate, so a new game is one module rather than a rewrite:

* :mod:`ttrpg_chatbots.sheets.types` -- the neutral projection. A :class:`Sheet` is the
  handful of numbers a bot needs, not a rules engine.
* :mod:`ttrpg_chatbots.sheets.xlsx` -- a workbook reader using only the standard
  library, so reading a sheet adds no dependency.
* :mod:`ttrpg_chatbots.sheets.systems` -- one module per game, owning both its cell map
  and its resolution rules.
* :mod:`ttrpg_chatbots.sheets.cli` -- the front end.

House Games comes first because its rules document is short enough to implement
faithfully; the tools for the commercial systems stay external and are read through
their save files, one adapter at a time.
"""

from ttrpg_chatbots.sheets.types import (
    CATEGORIES,
    KNOWLEDGE,
    SKILL,
    TALENT,
    Ability,
    Sheet,
    SheetError,
    Trait,
    UnknownTrait,
    normalise,
    resolve_name,
)
from ttrpg_chatbots.sheets.xlsx import (
    Grid,
    WorkbookError,
    column_index,
    column_letters,
    join_ref,
    read_grid,
    sheet_names,
    split_ref,
)

__all__ = [
    "CATEGORIES",
    "KNOWLEDGE",
    "SKILL",
    "TALENT",
    "Ability",
    "Grid",
    "Sheet",
    "SheetError",
    "Trait",
    "UnknownTrait",
    "WorkbookError",
    "column_index",
    "column_letters",
    "join_ref",
    "normalise",
    "read_grid",
    "resolve_name",
    "sheet_names",
    "split_ref",
]
