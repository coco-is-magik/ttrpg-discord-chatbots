"""Spoken form: the text a voice should read, which is not the text a person should read.

A screen reader and a friend's ear need different strings. ``$250`` is *read* as a symbol and three
zeros by an engine that was trained on prose; a person says "two hundred fifty dollars". Everything in
here exists to close that gap, and nothing in here touches what the bot *types* -- the text channel
keeps its symbols, because that is how people write.

One module per kind of thing, because the rules do not resemble each other:

``money``         ``$250`` -> ``two hundred fifty dollars``
``symbols``       ``&`` ``%`` ``@`` ``+`` ``=`` ``/`` ``#1``
``numbers``       cardinals, ordinals, decimals, years, clock times, ranges
``abbreviations`` ``Dr.`` ``e.g.`` ``etc.`` ``vs.`` and friends
``acronyms``      ``NCAA`` as letters, ``NASA`` as a word
``pipeline``      the order they run in, which is the part that is easy to get wrong
"""

from ttrpg_chatbots.tts.spoken.pipeline import say
from ttrpg_chatbots.tts.spoken.wrap import SpokenSynthesizer, unwrap, wrap

__all__ = ["SpokenSynthesizer", "say", "unwrap", "wrap"]
