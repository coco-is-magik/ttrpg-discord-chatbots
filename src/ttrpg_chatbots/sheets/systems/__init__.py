"""System modules: one per game.

Each module owns its own file layout *and* its own resolution rules, and exposes the same
entry points, so the CLI and the bot never have to learn a game's specifics::

    SYSTEM                         short identifier, e.g. "house-games"
    read_sheet(grid)               -> Sheet
    build_pool(sheet, attr, ...)   -> PoolSpec
    resolve_pool(spec, roller, ..) -> PoolResult
"""

from ttrpg_chatbots.sheets.systems import houseg

SYSTEMS = {houseg.SYSTEM: houseg}

__all__ = ["SYSTEMS", "houseg"]
