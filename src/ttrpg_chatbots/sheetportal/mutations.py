"""Every accepted change to a sheet, with a receipt.

One place decides what a change costs, whether it is legal, and what is left afterwards. The
rules themselves live in :mod:`ttrpg_chatbots.sheets.systems.houseg`; this module only applies
them, so a caller cannot invent its own arithmetic and two surfaces cannot disagree.

Every function returns a :class:`Receipt` rather than mutating: the new sheet, a one-line
account of what happened, the cost paid, what remains, and any warnings. A change that cannot
explain itself in one line does not happen.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from ttrpg_chatbots.sheets.render import HEALTH_PENALTY
from ttrpg_chatbots.sheets.systems import houseg
from ttrpg_chatbots.sheets.types import (
    Ability,
    Gift,
    Sheet,
    Trait,
    UnknownTrait,
    normalise,
    resolve_name,
)

# Traits that can be raised by spending points. Gifts are awarded, not bought.
# "none" is a free edit: a GM correction, or a value set by hand in a draft.
POOLS = ("none", "freebies", "xp")
KINDS = ("attribute", "ability", "virtue", "background", "willpower", "morality")

# A Win is "10 XP and a Gift"; a surviving loss is "5 XP but no Gift" (rules, "What you get").
OUTCOMES = {"win": (houseg.XP_WIN, 1), "loss": (houseg.XP_LOSS, 0)}


class MutationError(RuntimeError):
    """A change that the rules do not allow, with the reason a player can act on."""


@dataclass(frozen=True)
class Receipt:
    """The result of one accepted change."""

    sheet: Sheet
    lines: tuple[str, ...]
    spent: Mapping[str, int] = field(default_factory=dict)
    remaining: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def __str__(self) -> str:
        # A free edit has nothing to charge for, so "0 none left" never appears.
        paid = ", ".join(
            f"{amount} {pool}"
            for pool, amount in self.spent.items()
            if amount and pool != "none"
        )
        left = ", ".join(
            f"{amount} {pool} left"
            for pool, amount in self.remaining.items()
            if pool in self.spent and pool != "none"
        )
        parts = ["; ".join(self.lines)]
        if paid:
            parts.append(paid)
        if left:
            parts.append(left)
        parts.extend(self.warnings)
        return " — ".join(parts)


# -- caps -------------------------------------------------------------------


def resolve_kind(sheet: Sheet, name: str, kind: str | None = None) -> str:
    """Which kind of trait ``name`` is, or raise naming the alternatives."""
    if kind is not None:
        if kind not in KINDS:
            raise MutationError(f"unknown trait kind {kind!r}; expected one of {', '.join(KINDS)}")
        return kind
    key = normalise(name)
    for candidate in ("attribute", "ability", "virtue", "background"):
        try:
            _current(sheet, candidate, name)
        except UnknownTrait:
            continue
        return candidate
    if key in {"willpower", "morality"}:
        return key
    raise MutationError(
        f"{sheet.name} has no trait called {name!r}. Known: "
        + ", ".join(sorted([*sheet.attributes, *sheet.abilities, *sheet.virtues]))
        + (f", {', '.join(sorted(t.name for t in sheet.backgrounds))}" if sheet.backgrounds else "")
    )


def cap_for(sheet: Sheet, kind: str, name: str = "") -> int:
    """The ceiling for a trait, honouring a Gift-raised cap recorded in ``meta['caps']``."""
    overrides = sheet.meta.get("caps") or {}
    if isinstance(overrides, Mapping):
        key = normalise(name)
        for trait, value in overrides.items():
            if normalise(str(trait)) == key:
                return int(value)
    if kind == "background":
        return houseg.BACKGROUND_CAP_VETERAN if sheet.veteran else houseg.BACKGROUND_CAP
    if kind in {"willpower", "morality"}:
        return houseg.TRACKER_CAP
    return houseg.TRAIT_CAP


def _current(sheet: Sheet, kind: str, name: str) -> int:
    if kind == "attribute":
        return sheet.attribute(name)
    if kind == "ability":
        return sheet.ability(name).rank
    if kind == "virtue":
        return int(sheet.virtues[resolve_name(name, sheet.virtues)])
    if kind == "background":
        return sheet.trait(name).dots
    if kind == "willpower":
        return sheet.willpower
    if kind == "morality":
        if sheet.morality is None:
            raise MutationError(f"{sheet.name} has no Morality to raise")
        return sheet.morality
    raise MutationError(f"unknown trait kind {kind!r}")


# -- cost -------------------------------------------------------------------


def cost_of(kind: str, current: int, to: int, *, pool: str, system=houseg) -> int:
    """What raising from ``current`` to ``to`` costs in ``pool``.

    Freebies are flat per point; experience is rating-dependent, so each step is priced on
    the rating it is raising *from*.
    """
    if pool not in POOLS:
        raise MutationError(f"unknown pool {pool!r}; expected one of {', '.join(POOLS)}")
    if pool == "none":
        return 0
    if to <= current:
        return 0
    if pool == "freebies":
        return system.freebie_cost(kind) * (to - current)
    return sum(system.advancement_cost(kind, step) for step in range(current, to))


# -- the operations ---------------------------------------------------------


def raise_trait(
    sheet: Sheet,
    name: str,
    *,
    to: int,
    kind: str | None = None,
    pool: str = "freebies",
    system=houseg,
) -> Receipt:
    """Raise one trait to ``to``, paying from ``pool``.

    Lowering is allowed and refunds nothing: a player changing their mind before a session is
    the common case, and an economy that punishes rethinking is one nobody uses.
    """
    kind = resolve_kind(sheet, name, kind)
    current = _current(sheet, kind, name)
    ceiling = cap_for(sheet, kind, name)
    if to > ceiling:
        tier = houseg.gift_tier(sheet.gift_count, veteran=sheet.veteran)
        raise MutationError(f"{name} is capped at {ceiling} for a {tier} character")
    if to == current:
        raise MutationError(f"{name} is already {current}")
    cost = cost_of(kind, current, to, pool=pool, system=system) if to > current else 0
    available = getattr(sheet, pool, 0) if pool != "none" else 0
    if cost > available:
        raise MutationError(
            f"{abs(to - current)} point(s) of {kind} costs {cost} {pool}; "
            f"{sheet.name} has {available}"
        )

    updated = _apply(sheet, kind, name, to)
    if pool != "none":
        updated = replace(updated, **{pool: available - cost})
    return Receipt(
        sheet=updated,
        lines=(f"{_label(sheet, kind, name)} {current}→{to}",),
        spent={pool: cost},
        remaining={pool: available - cost},
    )


def award_gift(
    sheet: Sheet,
    name: str,
    *,
    rating: int | None = None,
    source: str = "",
    description: str = "",
    approved: str = "",
) -> Receipt:
    """Record a Gift. No cost: Gifts are offered by a Harbinger, not bought."""
    if not name.strip():
        raise MutationError("a gift needs a name")
    if any(normalise(gift.name) == normalise(name) for gift in sheet.gifts):
        raise MutationError(f"{sheet.name} already holds a Gift called {name!r}")
    gift = Gift(
        name=name.strip(),
        rating=rating,
        source=source.strip(),
        description=description.strip(),
        approved=approved.strip(),
    )
    before = houseg.gift_tier(sheet.gift_count, veteran=sheet.veteran)
    updated = replace(sheet, gifts=(*sheet.gifts, gift))
    after = houseg.gift_tier(updated.gift_count, veteran=updated.veteran)
    shown = f"{gift.name} {rating}" if rating is not None else f"{gift.name} (flat)"
    warnings = (f"that is {updated.gift_count} Gifts — now {after}",) if after != before else ()
    return Receipt(
        sheet=updated,
        lines=(f"gained {shown}",),
        remaining={"gifts": updated.gift_count},
        warnings=warnings,
    )


def record_mission(
    sheet: Sheet, outcome: str, *, gift: str | None = None, rating: int | None = None
) -> Receipt:
    """Settle a Game: experience, and a Gift on a win.

    "Characters receive 10 XP and a Gift if they win. They get 5 XP but no Gift if they lose but
    survive."  A win without a named Gift is allowed — the offer may not be written down yet —
    but it is reported, because a Gift owed is easy to forget.
    """
    key = outcome.strip().lower()
    if key not in OUTCOMES:
        raise MutationError(f"unknown outcome {outcome!r}; expected win or loss")
    xp, gifts = OUTCOMES[key]
    updated = replace(sheet, xp=sheet.xp + xp)
    lines = [f"{key}: +{xp} xp"]
    warnings: list[str] = []

    if gifts and gift:
        won = award_gift(updated, gift, rating=rating)
        updated = won.sheet
        lines.extend(won.lines)
        warnings.extend(won.warnings)
    elif gifts:
        warnings.append("a Gift is owed: name it when the Harbinger offers it")

    return Receipt(
        sheet=updated,
        lines=tuple(lines),
        remaining={"xp": updated.xp, "gifts": updated.gift_count},
        warnings=tuple(warnings),
    )



def options(sheet: Sheet, *, pool: str = "freebies", system=houseg) -> tuple[str, ...]:
    """What the next point in each trait would cost — planning without committing."""
    lines = []
    for kind, names in (
        ("attribute", list(sheet.attributes)),
        ("ability", list(sheet.abilities)),
        ("virtue", list(sheet.virtues)),
        ("background", [trait.name for trait in sheet.backgrounds]),
    ):
        for name in names:
            current = _current(sheet, kind, name)
            ceiling = cap_for(sheet, kind, name)
            if current >= ceiling:
                continue
            cost = cost_of(kind, current, current + 1, pool=pool, system=system)
            lines.append(f"{name} {current}→{current + 1}: {cost} {pool}")
    return tuple(lines)


def explain(sheet: Sheet, name: str, *, kind: str | None = None) -> str:
    """Provenance for one trait, in the terms a player would use."""
    kind = resolve_kind(sheet, name, kind)
    current = _current(sheet, kind, name)
    ceiling = cap_for(sheet, kind, name)
    detail = ""
    if kind == "ability":
        ability = sheet.ability(name)
        detail = f" ({ability.category}"
        detail += f", {ability.specialty}" if ability.specialty else ""
        detail += ")"
    return f"{_label(sheet, kind, name)}: {current} of {ceiling}{detail}"


def current_rating(sheet: Sheet, kind: str, name: str) -> int:
    """The rating a trait holds now, whichever kind it is."""
    return _current(sheet, kind, name)


def _label(sheet: Sheet, kind: str, name: str) -> str:
    if kind == "attribute":
        return resolve_name(name, sheet.attributes)
    if kind == "ability":
        return sheet.ability(name).name
    if kind == "virtue":
        return resolve_name(name, sheet.virtues)
    if kind == "background":
        return sheet.trait(name).name
    return kind.capitalize()


def _apply(sheet: Sheet, kind: str, name: str, to: int) -> Sheet:
    """Return a sheet with one trait set, leaving everything else untouched."""
    if kind == "attribute":
        resolved = resolve_name(name, sheet.attributes)
        return replace(sheet, attributes={**sheet.attributes, resolved: to})
    if kind == "ability":
        resolved = sheet.ability(name).name
        ability = replace(sheet.abilities[resolved], rank=to)
        return replace(sheet, abilities={**sheet.abilities, resolved: ability})
    if kind == "virtue":
        resolved = resolve_name(name, sheet.virtues)
        return replace(sheet, virtues={**sheet.virtues, resolved: to})
    if kind == "background":
        target = sheet.trait(name)
        backgrounds = tuple(
            replace(trait, dots=to) if trait.name == target.name else trait
            for trait in sheet.backgrounds
        )
        return replace(sheet, backgrounds=backgrounds)
    if kind == "willpower":
        remaining = sheet.willpower_remaining
        if remaining is not None:
            remaining = min(remaining, to)
        return replace(sheet, willpower=to, willpower_remaining=remaining)
    if kind == "morality":
        return replace(sheet, morality=to)
    raise MutationError(f"unknown trait kind {kind!r}")



# -- direct edits ------------------------------------------------------------


def set_trait(
    sheet: Sheet, name: str, *, to: int, kind: str | None = None, system=houseg
) -> Receipt:
    """Set a trait to ``to`` with no cost: the workbench and GM corrections.

    Caps still apply. The rules cap traits at 5, so an editor that ignores them would let a
    typo become canon; a Gift that raises a cap is recorded in ``meta['caps']``.
    """
    return raise_trait(sheet, name, to=to, kind=kind, pool="none", system=system)


def set_specialty(sheet: Sheet, ability: str, specialty: str) -> Receipt:
    """Set (or clear) an ability's specialty."""
    target = sheet.ability(ability)
    if target.rank < 4:
        raise MutationError(
            f"{target.name} is rank {target.rank}; a specialty needs rank 4 or more"
        )
    cleaned = " ".join(specialty.split())
    if cleaned == target.specialty:
        raise MutationError(f"{target.name} already has that specialty")
    updated = replace(
        sheet,
        abilities={**sheet.abilities, target.name: replace(target, specialty=cleaned)},
    )
    shown = f"{target.name} specialty {cleaned or '(none)'}"
    return Receipt(sheet=updated, lines=(shown,))


def remove_gift(sheet: Sheet, name: str) -> Receipt:
    """Drop a Gift that should not be there."""
    target = sheet.gift(name)
    remaining = tuple(gift for gift in sheet.gifts if gift.name != target.name)
    if not remaining and sheet.gift_count == 1:
        pass
    return Receipt(
        sheet=replace(sheet, gifts=remaining),
        lines=(f"lost {target.name}",),
        remaining={"gifts": len(remaining)},
    )


def adjust_health(sheet: Sheet, *, levels: int, system=houseg) -> Receipt:
    """Mark or clear damage on the health track.

    The track is the one thing that changes every session, so it is a first-class edit rather
    than something to hand-tune in JSON. ``levels`` is signed: negative takes damage.
    """
    maximum = len(sheet.health)
    if maximum == 0:
        raise MutationError(f"{sheet.name} has no health track")
    current, _, _ = _health_now(sheet)
    updated_value = max(0, min(maximum, current + levels))
    if updated_value == current:
        raise MutationError(
            f"{sheet.name} is already at {current}/{maximum}"
        )
    meta = {**sheet.meta, "health_current": updated_value}
    updated = replace(sheet, meta=meta)
    moved = updated_value - current
    word = "hurt" if moved < 0 else "healed"
    return Receipt(
        sheet=updated,
        lines=(f"{word} {abs(moved)}: health {updated_value}/{maximum}",),
        remaining={"health": updated_value},
    )


def health_level(sheet: Sheet) -> int:
    """How much health the sheet says it has left."""
    return _health_now(sheet)[0]


def set_health(sheet: Sheet, value: int) -> Receipt:
    """Put the health track at an exact level (used by undo)."""
    maximum = len(sheet.health)
    if maximum == 0:
        raise MutationError(f"{sheet.name} has no health track")
    target = max(0, min(int(value), maximum))
    if target == _health_now(sheet)[0]:
        raise MutationError(f"{sheet.name} is already at {target}/{maximum}")
    updated = replace(sheet, meta={**sheet.meta, "health_current": target})
    return Receipt(
        sheet=updated,
        lines=(f"health {target}/{maximum}",),
        remaining={"health": target},
    )


def _health_now(sheet: Sheet) -> tuple[int, int, int]:
    """Current health, maximum, and the wound penalty reached (mirrors the renderer)."""
    maximum = len(sheet.health)
    raw = sheet.meta.get("health_current")
    current = maximum if raw is None else max(0, min(int(raw), maximum))
    penalty = 0
    for level in sheet.health[: maximum - current + 1]:
        match = HEALTH_PENALTY.search(level or "")
        if match:
            penalty = int(match.group(1))
    return current, maximum, penalty
