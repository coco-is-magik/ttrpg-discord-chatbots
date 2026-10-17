"""Value types for character sheets.

A :class:`Sheet` is a deliberately lossy *projection*: the numbers a bot needs to roll
dice and stay in character, not a model of any game's rules. A system module
(``ttrpg_chatbots.sheets.systems.<system>``) owns both its file layout and its
resolution rules, and translates its characters into this shape.

Keeping the projection small is what makes one reader per system tractable instead of
one research project per system.
"""

from __future__ import annotations

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
    powers: tuple[Trait, ...] = ()
    backgrounds: tuple[Trait, ...] = ()
    meta: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("a sheet needs a character name")
        if not self.system.strip():
            raise ValueError("a sheet needs a system name")

    @property
    def key(self) -> str:
        """Stable identifier, defaulting to the normalised name."""
        return self.id or normalise(self.name)

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
        for group in (self.powers, self.backgrounds):
            for trait in group:
                if normalise(trait.name) == normalise(name):
                    return trait
        raise UnknownTrait(f"{self.name} has no trait called {name!r}")

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
            "powers": [{"name": trait.name, "dots": trait.dots} for trait in self.powers],
            "backgrounds": [
                {"name": trait.name, "dots": trait.dots} for trait in self.backgrounds
            ],
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
        id=str(data.get("id", "") or ""),
        attributes={str(key): int(value) for key, value in attributes.items()},
        abilities=abilities,
        virtues={str(k): int(v) for k, v in (data.get("virtues") or {}).items()},
        willpower=int(data.get("willpower", 0) or 0),
        willpower_remaining=(
            None if data.get("willpower_remaining") is None else int(data["willpower_remaining"])
        ),
        morality=None if data.get("morality") is None else int(data["morality"]),
        health=tuple(str(level) for level in (data.get("health") or ())),
        powers=tuple(
            Trait(name=str(entry["name"]), dots=int(entry.get("dots", 0)))
            for entry in (data.get("powers") or ())
        ),
        backgrounds=tuple(
            Trait(name=str(entry["name"]), dots=int(entry.get("dots", 0)))
            for entry in (data.get("backgrounds") or ())
        ),
        meta=dict(data.get("meta") or {}),
        source=str(data.get("source", "") or ""),
    )

