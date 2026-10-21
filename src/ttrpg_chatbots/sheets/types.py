"""Value types for character sheets.

A :class:`Sheet` is a deliberately lossy *projection*: the numbers a bot needs to roll
dice and stay in character, not a model of any game's rules. A system module
(``ttrpg_chatbots.sheets.systems.<system>``) owns both its file layout and its
resolution rules, and translates its characters into this shape.

Keeping the projection small is what makes one reader per system tractable instead of
one research project per system.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

TALENT = "talent"
SKILL = "skill"
KNOWLEDGE = "knowledge"
CATEGORIES = (TALENT, SKILL, KNOWLEDGE)

# House-game traits are normally capped at 5, but nothing here enforces a system rule.
MAX_RANK = 10


class SheetError(RuntimeError):
    """Base class for sheet reading and resolution failures."""


class UnknownTrait(SheetError, ValueError):
    """Raised when a named trait is not on the sheet, or the name is ambiguous."""


def normalise(name: str) -> str:
    """Case- and whitespace-insensitive key, the way a player would type it."""
    return " ".join((name or "").split()).lower()


_SLUG = re.compile(r"[^a-z0-9]+")


def identifier(name: str) -> str:
    """A filename-safe identifier: ``"Molly MacIntosh"`` -> ``"molly-macintosh"``.

    One spelling for one thing: the id stored in a character file, the seat that names it and
    the file on disk are all this string, so a comparison cannot disagree with a path.
    """
    slug = _SLUG.sub("-", normalise(name)).strip("-")
    return slug or "unnamed"


def resolve_name(name: str, candidates: Iterable[str]) -> str:
    """Match ``name`` to one candidate: exact first, then a unique prefix.

    Players type "dex" and "int", so prefix matching earns its keep; ambiguity is an
    error rather than a guess, because rolling the wrong trait quietly is worse than
    being told to be specific.
    """
    wanted = normalise(name)
    if not wanted:
        raise UnknownTrait("no trait name given")
    known = list(candidates)
    for candidate in known:
        if normalise(candidate) == wanted:
            return candidate
    matches = [candidate for candidate in known if normalise(candidate).startswith(wanted)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        listed = ", ".join(sorted(known)) or "none"
        raise UnknownTrait(f"unknown trait {name!r}; known traits: {listed}")
    listed = ", ".join(sorted(matches))
    raise UnknownTrait(f"ambiguous trait {name!r}; it could be: {listed}")


@dataclass(frozen=True)
class Trait:
    """A named rating with dots."""

    name: str
    dots: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a trait needs a name")
        if not 0 <= self.dots <= MAX_RANK:
            raise ValueError(f"{self.name}: dots must be in 0..{MAX_RANK}, got {self.dots}")


@dataclass(frozen=True)
class Ability:
    """An ability: a rating, the category it belongs to, and any specialty."""

    name: str
    rank: int = 0
    category: str = SKILL
    specialty: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("an ability needs a name")
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.name}: category must be one of {CATEGORIES}")
        if not 0 <= self.rank <= MAX_RANK:
            raise ValueError(f"{self.name}: rank must be in 0..{MAX_RANK}, got {self.rank}")

    @property
    def trained(self) -> bool:
        return self.rank > 0


@dataclass(frozen=True)
class Gift:
    """A power the character has been given.

    House Games awards **one Gift per successful mission**, and a Gift is whatever the GM
    offered: a levelled discipline, a flat technique, anything printed in an oWoD book. So
    ``rating`` is optional — ``None`` means "flat, described only" — and ``source`` records
    where it came from, because the same column in the workbook legitimately holds both
    shapes. A rating of ``0`` is not a Gift; it is a *plan*, and lives in ``Sheet.planned``.
    """

    name: str
    rating: int | None = None
    source: str = ""
    description: str = ""
    approved: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a gift needs a name")
        if self.rating is not None:
            if isinstance(self.rating, bool) or not isinstance(self.rating, int):
                raise ValueError(f"{self.name}: rating must be a whole number or None")
            if not 0 <= self.rating <= MAX_RANK:
                raise ValueError(
                    f"{self.name}: rating must be in 0..{MAX_RANK}, got {self.rating}"
                )

    @property
    def is_rated(self) -> bool:
        return self.rating is not None

    def label(self) -> str:
        """``Thanatosis 1`` when it has levels, ``Walking Fire`` when it is flat."""
        return f"{self.name} {self.rating}" if self.rating else self.name

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name}
        if self.rating is not None:
            data["rating"] = self.rating
        if self.source:
            data["source"] = self.source
        if self.description:
            data["description"] = self.description
        if self.approved:
            data["approved"] = self.approved
        return data

    @classmethod
    def from_dict(cls, data: Any) -> Gift:
        if not isinstance(data, Mapping):
            raise ValueError("a gift must be an object")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("a gift needs a string 'name'")
        rating = data.get("rating")
        if rating is not None and (isinstance(rating, bool) or not isinstance(rating, int)):
            raise ValueError(f"{name}: 'rating' must be a whole number or absent")
        return cls(
            name=name.strip(),
            rating=rating,
            source=str(data.get("source", "") or ""),
            description=str(data.get("description", "") or ""),
            approved=str(data.get("approved", "") or ""),
        )


@dataclass(frozen=True)
class Sheet:
    """One character, reduced to the parts a bot can use."""

    name: str
    system: str
    id: str = ""
    attributes: Mapping[str, int] = field(default_factory=dict)
    abilities: Mapping[str, Ability] = field(default_factory=dict)
    virtues: Mapping[str, int] = field(default_factory=dict)
    willpower: int = 0
    willpower_remaining: int | None = None
    morality: int | None = None
    health: tuple[str, ...] = ()
    gifts: tuple[Gift, ...] = ()
    planned: tuple[Gift, ...] = ()
    backgrounds: tuple[Trait, ...] = ()
    # Merits cost the points the book gives them; a custom merit names its own value.
    merits: tuple[Trait, ...] = ()
    # Flaws are rated, and their ratings are the freebie points they hand back
    # ("FLAWS provide additional Freebie Points", capped at 7 unless two flaws).
    flaws: tuple[Trait, ...] = ()
    # The Veteran Template is a status earned by a solo Veteran Game, not a Gift count; it
    # changes the tier and raises the Background cap. Kept separate for that reason.
    veteran: bool = False
    # The two currencies the rules actually spend: freebie points at creation and experience
    # afterwards. Explicit fields, because a pool hidden in ``meta`` is how "why can't I
    # afford this?" becomes unanswerable.
    freebies: int = 0
    xp: int = 0
    meta: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a sheet needs a character name")
        if not self.system.strip():
            raise ValueError("a sheet needs a system name")

    @property
    def merit_points(self) -> int:
        """Freebie points a character has paid for merits."""
        return sum(trait.dots for trait in self.merits)

    @property
    def flaw_points(self) -> int:
        """Freebie points the Flaws are worth."""
        return sum(trait.dots for trait in self.flaws)

    @property
    def gift_count(self) -> int:
        """Gifts held: House Games awards one per successful mission."""
        return len(self.gifts)

    @property
    def key(self) -> str:
        """The character id: filename-safe and stable, e.g. ``molly-macintosh``."""
        return identifier(self.id or self.name)

    def attribute(self, name: str) -> int:
        resolved = resolve_name(name, self.attributes)
        return int(self.attributes[resolved])

    def ability(self, name: str) -> Ability:
        """The named ability; raises if the sheet does not carry it."""
        resolved = resolve_name(name, self.abilities)
        return self.abilities[resolved]

    def find_ability(self, name: str) -> Ability | None:
        """Like :meth:`ability`, but ``None`` instead of raising when unknown."""
        try:
            return self.ability(name)
        except UnknownTrait:
            return None

    def trait(self, name: str) -> Trait:
        """A rated, costed trait: backgrounds. Gifts are looked up with :meth:`gift`."""
        for trait in self.backgrounds:
            if normalise(trait.name) == normalise(name):
                return trait
        raise UnknownTrait(f"{self.name} has no trait called {name!r}")

    def gift(self, name: str) -> Gift:
        """A Gift by name, rated or flat."""
        for gift in self.gifts:
            if normalise(gift.name) == normalise(name):
                return gift
        raise UnknownTrait(f"{self.name} has no gift called {name!r}")

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready, for the CLI and for caching."""
        return {
            "name": self.name,
            "id": self.key,
            "system": self.system,
            "attributes": dict(self.attributes),
            "abilities": {
                key: {
                    "rank": ability.rank,
                    "category": ability.category,
                    "specialty": ability.specialty,
                }
                for key, ability in self.abilities.items()
            },
            "virtues": dict(self.virtues),
            "willpower": self.willpower,
            "willpower_remaining": self.willpower_remaining,
            "morality": self.morality,
            "health": list(self.health),
            "gifts": [gift.as_dict() for gift in self.gifts],
            "veteran": self.veteran,
            "freebies": self.freebies,
            "xp": self.xp,
            "planned": [gift.as_dict() for gift in self.planned],
            "backgrounds": [
                {"name": trait.name, "dots": trait.dots} for trait in self.backgrounds
            ],
            "merits": [{"name": trait.name, "dots": trait.dots} for trait in self.merits],
            "flaws": [{"name": trait.name, "dots": trait.dots} for trait in self.flaws],
            "meta": dict(self.meta),
            "source": self.source,
        }


def sheet_from_dict(data: Any) -> Sheet:
    """Rebuild a :class:`Sheet` from :meth:`Sheet.as_dict` output."""
    if not isinstance(data, Mapping):
        raise SheetError("a sheet must be a JSON object")
    name = data.get("name")
    system = data.get("system")
    if not isinstance(name, str) or not name.strip():
        raise SheetError("a sheet needs a 'name'")
    if not isinstance(system, str) or not system.strip():
        raise SheetError("a sheet needs a 'system'")

    attributes = data.get("attributes") or {}
    if not isinstance(attributes, Mapping):
        raise SheetError("'attributes' must be an object of numbers")
    abilities: dict[str, Ability] = {}
    for key, value in (data.get("abilities") or {}).items():
        if not isinstance(value, Mapping):
            raise SheetError(f"ability {key!r} must be an object")
        abilities[str(key)] = Ability(
            name=str(key),
            rank=int(value.get("rank", 0)),
            category=str(value.get("category", SKILL)),
            specialty=str(value.get("specialty", "") or ""),
        )

    return Sheet(
        name=name.strip(),
        system=system.strip(),
        id=identifier(str(data.get("id", "") or "")),
        attributes={str(key): int(value) for key, value in attributes.items()},
        abilities=abilities,
        virtues={str(k): int(v) for k, v in (data.get("virtues") or {}).items()},
        willpower=int(data.get("willpower", 0) or 0),
        willpower_remaining=(
            None if data.get("willpower_remaining") is None else int(data["willpower_remaining"])
        ),
        morality=None if data.get("morality") is None else int(data["morality"]),
        health=tuple(str(level) for level in (data.get("health") or ())),
        gifts=tuple(Gift.from_dict(entry) for entry in (data.get("gifts") or ())),
        planned=tuple(Gift.from_dict(entry) for entry in (data.get("planned") or ())),
        veteran=bool(data.get("veteran", False)),
        freebies=int(data.get("freebies", 0) or 0),
        xp=int(data.get("xp", 0) or 0),
        backgrounds=tuple(
            Trait(name=str(entry["name"]), dots=int(entry.get("dots", 0)))
            for entry in (data.get("backgrounds") or ())
        ),
        merits=tuple(
            Trait(name=str(entry["name"]), dots=int(entry.get("dots", 0)))
            for entry in (data.get("merits") or ())
        ),
        flaws=tuple(
            Trait(name=str(entry["name"]), dots=int(entry.get("dots", 0)))
            for entry in (data.get("flaws") or ())
        ),
        meta=dict(data.get("meta") or {}),
        source=str(data.get("source", "") or ""),
    )

