"""The data behind the spoken form: language facts, not persona facts.

Everything here is editable in one place on purpose. A character may want their own pronunciations
(``"TopGuy"`` should not be read as two words), and that belongs in a persona-level override; this
file is only what is true of the language.
"""

from __future__ import annotations

#: Symbol -> the word a person says. Applied *before* numbers, so ``10%`` becomes ``10 percent`` and
#: then ``ten percent``.
SYMBOLS: dict[str, str] = {
    "&": "and",
    "%": "percent",
    "@": "at",
    "+": "plus",
    "=": "equals",
    "/": "slash",
    "*": "star",
    "~": "about",
    "×": "times",
    "→": "to",
    "°": "degrees",
    "£": "pounds",  # only when money.py did not already claim it
    "©": "copyright",
    "®": "registered",
    "™": "trademark",
}

#: Currency symbol -> (major singular, major plural, minor singular, minor plural).
CURRENCY: dict[str, tuple[str, str, str, str]] = {
    "$": ("dollar", "dollars", "cent", "cents"),
    "£": ("pound", "pounds", "penny", "pence"),
    "€": ("euro", "euros", "cent", "cents"),
    "¥": ("yen", "yen", "", ""),
    "₹": ("rupee", "rupees", "paisa", "paise"),
}

#: Abbreviation -> spoken form. Keys are matched on word boundaries, case-insensitively.
ABBREVIATIONS: dict[str, str] = {
    "dr.": "Doctor",
    "mr.": "Mister",
    "mrs.": "Missus",
    "ms.": "Miss",
    "prof.": "Professor",
    "sr.": "Senior",
    "jr.": "Junior",
    "st.": "Street",  # before a capitalised word it is a saint; see abbreviations.py
    "ave.": "Avenue",
    "rd.": "Road",
    "blvd.": "Boulevard",
    "apt.": "apartment",
    "dept.": "department",
    "est.": "estimated",
    "approx.": "approximately",
    "no.": "number",
    "vol.": "volume",
    "min.": "minimum",
    "max.": "maximum",
    "vs.": "versus",
    "etc.": "et cetera",
    "e.g.": "for example",
    "i.e.": "that is",
    "cf.": "compare",
    "al.": "al",  # "et al." is handled by the multi-word pass
    "lb.": "pounds",
    "lbs.": "pounds",
    "oz.": "ounces",
    "ft.": "feet",
    "mi.": "miles",
    "hr.": "hours",
    "hrs.": "hours",
    "sec.": "seconds",
    "p.": "page",
    "pp.": "pages",
}

#: Multi-word abbreviations, matched first because they contain single ones.
PHRASES: dict[str, str] = {
    "et al.": "et al",
    "a.k.a.": "also known as",
    "aka": "also known as",
    "asap": "as soon as possible",
    "fyi": "for your information",
    "btw": "by the way",
    "imho": "in my humble opinion",
    "tbh": "to be honest",
    "irl": "in real life",
}

#: All-caps words said as a word rather than spelled out. Everything else in caps is spelled.
SAID_AS_WORDS: frozenset[str] = frozenset(
    {"NASA", "NATO", "SCUBA", "LASER", "RADAR", "SONAR", "AIDS", "ASCII", "GIF", "JPEG", "PNG"}
)

#: Short words that are already how people say them, so they are never spelled out.
NEVER_SPELLED: frozenset[str] = frozenset({"I", "A", "OK", "TV", "PC", "AI", "AM", "PM", "US", "UK"})
