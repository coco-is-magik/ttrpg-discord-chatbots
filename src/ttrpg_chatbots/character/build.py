"""Creation budgets: the group spend a character is built from.

This is not how advancement works. At creation the book spends **group budgets** — attributes
7/5/3, abilities 13/9/5, virtues 7, backgrounds 5 — each assigned to one group and spent
*exactly*; freebie points (15 + flaws) then top up whatever is still under a cap. Charging
freebies per point, which is what :func:`~ttrpg_chatbots.sheetportal.mutations.raise_trait` does,
is the advancement shape and would let a player buy a fourth attribute dot instead of spending
the 3-budget.

So a :class:`Build` records only *which budget went to which group*. Everything else — how much
is spent, what is left, whether the character is legal — is derived from the sheet, so the build
and the sheet can never disagree, and resuming a half-built character is just reading it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import Sheet

# The three groups, in the book's order. Budget values come from the system module.
ATTRIBUTE_GROUPS = tuple(houseg.ATTRIBUTE_GROUPS)
ABILITY_GROUPS = tuple(houseg.ABILITY_LISTS)
CATEGORY_BY_GROUP = {group: group for group in ABILITY_GROUPS}


class BuildError(RuntimeError):
    """A build that cannot be read, or a change it does not allow."""


@dataclass(frozen=True)
class Build:
    """Which budget each group got. Defaults match the book's own example order."""

    attributes: Mapping[str, int] = field(
        default_factory=lambda: dict(zip(ATTRIBUTE_GROUPS, houseg.ATTRIBUTE_BUDGETS))
    )
    abilities: Mapping[str, int] = field(
        default_factory=lambda: dict(zip(ABILITY_GROUPS, houseg.ABILITY_BUDGETS))
    )
    virtues: int = houseg.VIRTUE_POINTS
    backgrounds: int = houseg.BACKGROUND_POINTS

    def __post_init__(self) -> None:
        self._check(self.attributes, ATTRIBUTE_GROUPS, houseg.ATTRIBUTE_BUDGETS, "attribute")
        self._check(self.abilities, ABILITY_GROUPS, houseg.ABILITY_BUDGETS, "ability")
        if self.virtues != houseg.VIRTUE_POINTS:
            raise BuildError(f"virtues are fixed at {houseg.VIRTUE_POINTS}, got {self.virtues}")
        if self.backgrounds != houseg.BACKGROUND_POINTS:
            raise BuildError(
                f"backgrounds are fixed at {houseg.BACKGROUND_POINTS}, got {self.backgrounds}"
            )

    @staticmethod
    def _check(
        groups: Mapping[str, int], names: tuple[str, ...], budgets: tuple[int, ...], label: str
    ) -> None:
        if set(groups) != set(names):
            raise BuildError(f"{label} groups must be exactly {list(names)}, got {list(groups)}")
        if sorted(groups.values()) != sorted(budgets):
            raise BuildError(
                f"{label} budgets must be exactly {sorted(budgets)}, got {sorted(groups.values())}"
            )

    def assigned(self, section: str, order: tuple[str, str, str]) -> Build:
        """Give each group a different budget: first gets 7 (13), then 5 (9), then 3 (5).

        The rules say "you may spend seven points in one group, five in one group, and three in
        the remaining group" — which group gets which is the player's choice, so this is a
        first-class operation rather than a fixed table.
        """
        if section == "attributes":
            groups, budgets = ATTRIBUTE_GROUPS, houseg.ATTRIBUTE_BUDGETS
        elif section == "abilities":
            groups, budgets = ABILITY_GROUPS, houseg.ABILITY_BUDGETS
        else:
            raise BuildError(f"unknown section {section!r}; expected attributes or abilities")
        cleaned = tuple(group.strip() for group in order)
        if set(cleaned) != set(groups) or len(set(cleaned)) != len(cleaned):
            raise BuildError(
                f"{section} must name each of {list(groups)} exactly once, got {list(cleaned)}"
            )
        mapping = dict(zip(cleaned, budgets))
        if section == "attributes":
            return Build(
                attributes=mapping,
                abilities=self.abilities,
                virtues=self.virtues,
                backgrounds=self.backgrounds,
            )
        return Build(
            attributes=self.attributes,
            abilities=mapping,
            virtues=self.virtues,
            backgrounds=self.backgrounds,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "attributes": dict(self.attributes),
            "abilities": dict(self.abilities),
            "virtues": self.virtues,
            "backgrounds": self.backgrounds,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Build:
        if not isinstance(data, Mapping):
            raise BuildError("a build must be an object")
        try:
            return cls(
                attributes=dict(data.get("attributes") or {}),
                abilities=dict(data.get("abilities") or {}),
                virtues=int(data.get("virtues", houseg.VIRTUE_POINTS)),
                backgrounds=int(data.get("backgrounds", houseg.BACKGROUND_POINTS)),
            )
        except (TypeError, ValueError) as error:
            raise BuildError(f"invalid build: {error}") from error


# -- derived state -----------------------------------------------------------


def attribute_spent(sheet: Sheet) -> dict[str, int]:
    """Points spent in each attribute group. Every attribute starts at 1."""
    return {
        group: sum(max(0, sheet.attributes.get(name, 1) - 1) for name in names)
        for group, names in houseg.ATTRIBUTE_GROUPS.items()
    }


def ability_spent(sheet: Sheet) -> dict[str, int]:
    """Points spent in each ability group. Every ability starts at 0."""
    spent = {group: 0 for group in ABILITY_GROUPS}
    for ability in sheet.abilities.values():
        spent[ability.category] = spent.get(ability.category, 0) + ability.rank
    return spent


def virtue_spent(sheet: Sheet) -> int:
    """Virtues start at 1 each, so the spend is the total minus three."""
    return max(0, sum(sheet.virtues.values()) - len(sheet.virtues))


def background_spent(sheet: Sheet) -> int:
    return sum(trait.dots for trait in sheet.backgrounds)


def remaining(sheet: Sheet, build: Build | None = None) -> dict[str, dict[str, int]]:
    """What is left in every budget. Negative means overspent."""
    build = build or Build()
    attributes = attribute_spent(sheet)
    abilities = ability_spent(sheet)
    return {
        "attributes": {
            group: build.attributes[group] - attributes.get(group, 0)
            for group in ATTRIBUTE_GROUPS
        },
        "abilities": {
            group: build.abilities[group] - abilities.get(group, 0)
            for group in ABILITY_GROUPS
        },
        "virtues": {"Virtues": build.virtues - virtue_spent(sheet)},
        "backgrounds": {"Backgrounds": build.backgrounds - background_spent(sheet)},
    }


def problems(sheet: Sheet, build: Build | None = None) -> tuple[str, ...]:
    """Everything that stops this being a legal starting character.

    Exact spending is the requirement: a budget left partly unspent is as wrong as one
    overspent, because the points cannot be banked.
    """
    left = remaining(sheet, build)
    found: list[str] = []
    for section, groups in left.items():
        for group, value in groups.items():
            if value > 0:
                found.append(f"{group}: {value} point(s) unspent")
            elif value < 0:
                found.append(f"{group}: {-value} point(s) over budget")
    return tuple(found)


def group_remaining(sheet: Sheet, trait: str, kind: str, build: Build | None = None) -> int:
    """How much room the budget for this trait's group has left."""
    left = remaining(sheet, build)
    if kind == "attribute":
        for group, names in houseg.ATTRIBUTE_GROUPS.items():
            if trait in names:
                return left["attributes"][group]
        raise BuildError(f"unknown attribute {trait!r}")
    if kind == "ability":
        ability = sheet.ability(trait)
        return left["abilities"][ability.category]
    if kind == "virtue":
        return left["virtues"]["Virtues"]
    if kind == "background":
        return left["backgrounds"]["Backgrounds"]
    raise BuildError(f"{kind!r} is not bought from a creation budget")



def derive_trackers(sheet: Sheet) -> Sheet:
    """Morality and Willpower *begin* as sums of virtues, and only at creation.

    "MORALITY begins equal to Conviction + Self-Control ... increasing them later does not
    increase Morality" and "WILLPOWER begins equal to Courage". So while a character is being
    built the two trackers follow the virtues; once sealed they are independent values.
    """
    conviction = int(sheet.virtues.get("Conscience/Conviction", 1))
    self_control = int(sheet.virtues.get("Self-Control/Instinct", 1))
    courage = int(sheet.virtues.get("Courage", 1))
    return replace(
        sheet,
        morality=conviction + self_control,
        willpower=courage,
        willpower_remaining=courage,
    )
