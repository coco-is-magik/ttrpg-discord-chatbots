"""The layer below the message: deriving parts, and (later) choosing their shape.

One question per module: `derive` reads the parts out of existing text, and a later `recipe` will choose
which parts a turn should have before the words are chosen. See `docs/TEXTURE.md`.
"""

from ttrpg_chatbots.parts.derive import read

__all__ = ["read"]
