"""Render a sheet for a Discord message.

Two presentations, one source of truth:

* an **embed** (the default) — the platform lays out the columns, it reads well on a phone, and
  a character portrait fits beside the numbers. Fields are three-inline-per-row, which is a
  three-column grid without any hand-computed padding.
* **fixed-width text** — for a code block, a file, or anyone who wants to copy the thing.

Nothing here imports Discord. A :class:`EmbedSpec` is the description of a message; the bot
turns it into ``discord.Embed``. That keeps the layout testable without a gateway, and means the
same spec could feed any other transport (a web page, an email) later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ttrpg_chatbots.sheets.types import Sheet

# Left block, middle block, then backgrounds on the right. The gutters are what make the three
# blocks line up across the page, so they are constants rather than literals.
LEFT_WIDTH = 23
MIDDLE_WIDTH = 27
GUTTER = "   "

# Abilities: three groups side by side, each a fixed name/specialty/rank triple.
NAME_WIDTH = 14
SPECIALTY_WIDTH = 13
RANK_WIDTH = 3
GROUP_GAP = "   "
SPECIALTY_CLIP = 8  # first eight characters, then "..."
GIFT_ROWS = 6  # a list longer than this spreads into columns

# Discord's own limits, so the spec cannot be built into something unsendable.
FIELD_VALUE_LIMIT = 1024
DESCRIPTION_LIMIT = 4096

ATTRIBUTE_ABBREVIATIONS = {
    "Strength": "STR",
    "Dexterity": "DEX",
    "Stamina": "STA",
    "Charisma": "CHA",
    "Manipulation": "MAN",
    "Appearance": "APP",
    "Perception": "PER",
    "Intelligence": "INT",
    "Wits": "WIT",
}
VIRTUE_ABBREVIATIONS = (
    ("Conscience/Conviction", "Conv"),
    ("Self-Control/Instinct", "Inst"),
    ("Courage", "Cour"),
)
HEALTH_PENALTY = re.compile(r"\(-(\d+)\)")


def render_sheet(sheet: Sheet) -> str:
    """The whole sheet as fixed-width text, without a code fence."""
    lines = [_header(sheet), ""]
    lines.extend(_rule(sheet).splitlines())
    lines.append("")
    lines.extend(_ability_table(sheet))
    gifts = _gifts(sheet)
    if gifts and gifts[0]:
        lines.append("")
        lines.extend(gifts)
    return "\n".join(line.rstrip() for line in lines).rstrip() + "\n"


def clipped_specialty(specialty: str) -> str:
    """``Hellfire Attacks`` -> ``(Hellfire...)``: eight characters, then an ellipsis."""
    text = (specialty or "").strip()
    if not text:
        return "(None)"
    if len(text) > SPECIALTY_CLIP:
        text = text[:SPECIALTY_CLIP] + "..."
    return f"({text})"


def _header(sheet: Sheet) -> str:
    """Name, system, then the two currencies — the numbers a player spends."""
    return f"{sheet.name} · {sheet.system} · freebies {sheet.freebies} · xp {sheet.xp}"


def _rule(sheet: Sheet) -> str:
    """Three rows: attributes | virtues and trackers | backgrounds."""
    left = [
        _attribute_cells(sheet, ("Strength", "Charisma", "Perception")),
        _attribute_cells(sheet, ("Dexterity", "Manipulation", "Intelligence")),
        _attribute_cells(sheet, ("Stamina", "Appearance", "Wits")),
    ]
    middle = _tracker_rows(sheet)
    right = [f"{trait.name:<10} {trait.dots}" for trait in sheet.backgrounds]

    rows = max(len(left), len(middle), len(right))
    lines = []
    for index in range(rows):
        lpart = left[index] if index < len(left) else ""
        mpart = middle[index] if index < len(middle) else ""
        rpart = right[index] if index < len(right) else ""
        lines.append(f"{lpart:<{LEFT_WIDTH}}{GUTTER}{mpart:<{MIDDLE_WIDTH}}{GUTTER}{rpart}")
    return "\n".join(lines)


def _attribute_cells(sheet: Sheet, names: tuple[str, str, str]) -> str:
    """``STR 1 CHA 1 PER 1`` — abbreviations, because anyone playing knows them."""
    cells = []
    for name in names:
        value = sheet.attributes.get(name)
        cells.append(f"{ATTRIBUTE_ABBREVIATIONS[name]} {'-' if value is None else value}")
    width = max(len(cell) for cell in cells)
    return " ".join(cell.ljust(width) for cell in cells)


def _tracker_rows(sheet: Sheet) -> list[str]:
    """Virtues, with Morality, Willpower and Health beside them."""
    values = []
    for name, abbreviation in VIRTUE_ABBREVIATIONS:
        values.append(f"{abbreviation} {sheet.virtues.get(name, 0)}")

    morality = "-" if sheet.morality is None else sheet.morality
    remaining = (
        sheet.willpower if sheet.willpower_remaining is None else sheet.willpower_remaining
    )
    health, maximum, penalty = health_state(sheet)

    return [
        f"{values[0]}  Moral {morality}",
        f"{values[1]}  Will  {remaining}/{sheet.willpower}",
        f"{values[2]}  Health {health}/{maximum} (-{penalty})",
    ]


def health_state(sheet: Sheet) -> tuple[int, int, int]:
    """``(current, maximum, wound penalty)``.

    Health is not tracked anywhere yet, so a sheet is assumed unhurt unless it records
    ``meta['health_current']``. The penalty is read from the level's own name, which is where
    the rules put it ("Hurt (-1)").
    """
    maximum = len(sheet.health)
    if maximum == 0:
        return 0, 0, 0
    raw = sheet.meta.get("health_current")
    current = maximum if raw is None else max(0, min(int(raw), maximum))
    # Walk down the track and keep the deepest numbered penalty reached: the last level
    # ("Incapacitated") carries no number of its own, but it is past "Crippled (-5)".
    penalty = 0
    for level in sheet.health[: maximum - current + 1]:
        match = HEALTH_PENALTY.search(level or "")
        if match:
            penalty = int(match.group(1))
    return current, maximum, penalty


def _ability_table(sheet: Sheet) -> list[str]:
    """Talents, skills and knowledges in three aligned columns, in sheet order."""
    groups = [
        [ability for ability in sheet.abilities.values() if ability.category == category]
        for category in ("talent", "skill", "knowledge")
    ]
    rows = max((len(group) for group in groups), default=0)
    blank = " " * (NAME_WIDTH + SPECIALTY_WIDTH + RANK_WIDTH)
    lines = []
    for index in range(rows):
        cells = []
        for group in groups:
            if index < len(group):
                ability = group[index]
                cells.append(
                    f"{ability.name[:NAME_WIDTH]:<{NAME_WIDTH}}"
                    f"{clipped_specialty(ability.specialty):<{SPECIALTY_WIDTH}}"
                    f"{ability.rank:>{RANK_WIDTH}}"
                )
            else:
                cells.append(blank)
        lines.append(GROUP_GAP.join(cells))
    return lines


def _gifts(sheet: Sheet) -> list[str]:
    """Gifts along the bottom, filling as many columns as the page is wide."""
    if not sheet.gifts:
        return [""]
    labels = [
        f"{gift.name} {gift.rating}" if gift.rating else f"{gift.name} (flat)"
        for gift in sheet.gifts
    ]
    widest = max(len(label) for label in labels) + len(GROUP_GAP)
    fits = max(1, min(4, _page_width() // widest))
    # Stack short lists; only spread into columns once the block would get tall. Two gifts
    # read as a list, sixteen read as a table.
    columns = 1 if len(labels) <= GIFT_ROWS else max(1, min(fits, -(-len(labels) // GIFT_ROWS)))
    rows = -(-len(labels) // columns)  # ceiling division
    lines = []
    for row in range(rows):
        cells = [
            labels[row + column * rows]
            for column in range(columns)
            if row + column * rows < len(labels)
        ]
        lines.append(GROUP_GAP.join(cell.ljust(widest) for cell in cells))
    return lines


def _page_width() -> int:
    """The width the ability table occupies: three columns and the gaps between them."""
    column = NAME_WIDTH + SPECIALTY_WIDTH + RANK_WIDTH
    return column * 3 + len(GROUP_GAP) * 2



# -- the embed ---------------------------------------------------------------


@dataclass(frozen=True)
class EmbedField:
    """One field of a message embed."""

    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True)
class EmbedSpec:
    """A message embed, described without Discord so it can be tested and reused."""

    title: str
    description: str = ""
    fields: tuple[EmbedField, ...] = ()
    thumbnail: str = ""
    footer: str = ""
    colour: int = 0x1F6F6F
    # A local image to upload with the message; when set, ``thumbnail`` refers to it as
    # ``attachment://<name>``, which is the only way a file-portrait can appear in an embed.
    attachment: str = ""

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("an embed needs a title")
        if len(self.description) > DESCRIPTION_LIMIT:
            raise ValueError(f"embed description is limited to {DESCRIPTION_LIMIT} characters")
        if len(self.fields) > 25:
            raise ValueError("an embed may hold at most 25 fields")
        for item in self.fields:
            if not item.value.strip():
                raise ValueError(f"embed field {item.name!r} has no value")
            if len(item.value) > FIELD_VALUE_LIMIT:
                raise ValueError(f"embed field {item.name!r} exceeds {FIELD_VALUE_LIMIT}")

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "fields": [
                {"name": item.name, "value": item.value, "inline": item.inline}
                for item in self.fields
            ],
            "thumbnail": self.thumbnail,
            "attachment": self.attachment,
            "footer": self.footer,
        }


def embed_spec(
    sheet: Sheet, *, footer: str = "", thumbnail: str = "", attachment: str = ""
) -> EmbedSpec:
    """The sheet as an embed: portrait beside the numbers, three-column blocks.

    Three inline fields per row is how Discord draws a grid, so no character padding is needed
    anywhere except inside the ability values — where names, specialties and ranks still line up
    in a short code block.
    """
    fields: list[EmbedField] = []

    for label, names in (
        ("Physical", ("Strength", "Dexterity", "Stamina")),
        ("Social", ("Charisma", "Manipulation", "Appearance")),
        ("Mental", ("Perception", "Intelligence", "Wits")),
    ):
        fields.append(EmbedField(label, _stacked_attributes(sheet, names)))

    fields.append(EmbedField("Virtues", _stacked_virtues(sheet)))
    fields.append(EmbedField("Trackers", _stacked_trackers(sheet)))
    fields.append(EmbedField("Backgrounds", _stacked_backgrounds(sheet)))

    categories = (("Talents", "talent"), ("Skills", "skill"), ("Knowledges", "knowledge"))
    for label, category in categories:
        value = _ability_block(sheet, category)
        if value:
            fields.append(EmbedField(label, value))

    if sheet.merits or sheet.flaws:
        fields.append(EmbedField("Merits & Flaws", _trait_lines(sheet.merits, sheet.flaws)))

    if sheet.gifts:
        fields.append(EmbedField("Gifts", _gift_lines(sheet), inline=False))

    return EmbedSpec(
        title=sheet.name,
        description=(
            f"{sheet.system} · freebies {sheet.freebies} · xp {sheet.xp}"
            + (f" · {sheet.gift_count} gifts" if sheet.gifts else "")
        ),
        fields=tuple(fields),
        thumbnail=thumbnail or portrait_url(sheet),
        attachment=attachment,
        footer=footer,
    )


def portrait_url(sheet: Sheet) -> str:
    """A portrait URL recorded on the sheet, if it is one (never a local path)."""
    raw = str(sheet.meta.get("portrait", "") or "")
    return raw if raw.startswith(("https://", "http://")) else ""


def _stacked_attributes(sheet: Sheet, names: tuple[str, str, str]) -> str:
    lines = []
    for name in names:
        value = sheet.attributes.get(name)
        lines.append(f"{ATTRIBUTE_ABBREVIATIONS[name]} {'-' if value is None else value}")
    return "\n".join(lines)


def _stacked_virtues(sheet: Sheet) -> str:
    return "\n".join(
        f"{abbreviation} {sheet.virtues.get(name, 0)}"
        for name, abbreviation in VIRTUE_ABBREVIATIONS
    )


def _stacked_trackers(sheet: Sheet) -> str:
    morality = "-" if sheet.morality is None else sheet.morality
    remaining = (
        sheet.willpower if sheet.willpower_remaining is None else sheet.willpower_remaining
    )
    health, maximum, penalty = health_state(sheet)
    return "\n".join(
        [
            f"Moral {morality}",
            f"Will {remaining}/{sheet.willpower}",
            f"Health {health}/{maximum} (-{penalty})",
        ]
    )


def _stacked_backgrounds(sheet: Sheet) -> str:
    if not sheet.backgrounds:
        return "none"
    return "\n".join(f"{trait.name} {trait.dots}" for trait in sheet.backgrounds)


def _ability_block(sheet: Sheet, category: str) -> str:
    """One category as a small code block, so names and ranks still align."""
    rows = [
        f"{ability.name[:NAME_WIDTH]:<{NAME_WIDTH}}"
        f"{clipped_specialty(ability.specialty):<{SPECIALTY_WIDTH}}"
        f"{ability.rank:>{RANK_WIDTH}}"
        for ability in sheet.abilities.values()
        if ability.category == category
    ]
    if not rows:
        return ""
    # A field is capped at 1024 characters, so a very long category is trimmed with a count
    # rather than turning the whole sheet into an unsendable message.
    fenced = "```" + chr(10) + "{}" + chr(10) + "```"
    while rows and len(fenced.format(chr(10).join(rows))) > FIELD_VALUE_LIMIT:
        rows.pop()
    rendered = chr(10).join(rows)
    hidden = len(
        [
            ability
            for ability in sheet.abilities.values()
            if ability.category == category
        ]
    ) - len(rows)
    if hidden:
        rendered += chr(10) + f"… and {hidden} more"
    return fenced.format(rendered.rstrip())


def _trait_lines(merits: tuple, flaws: tuple) -> str:
    """Merits and flaws as one code block; flaws are prefixed so the two read apart."""
    rows = [f"{trait.name} {trait.dots}" for trait in merits]
    rows += [f"({trait.name} {trait.dots})" for trait in flaws]
    width = max((len(row) for row in rows), default=0)
    body = "\n".join(
        row if row.startswith("(") else f"{row}".ljust(width) for row in rows
    )
    if len(body) > FIELD_LIMIT:
        kept = body[: FIELD_LIMIT - 12].rsplit("\n", 1)[0]
        return kept + "\n… and more"
    return f"```\n{body}\n```"


def _gift_lines(sheet: Sheet) -> str:
    """Gifts as a code block, one per line, ratings aligned."""
    rows = []
    for gift in sheet.gifts:
        rows.append(f"{gift.name}" if gift.rating is None else f"{gift.name}")
    width = max(len(row) for row in rows)
    rendered = []
    for gift in sheet.gifts:
        rating = f"{gift.rating}" if gift.rating else "(flat)"
        rendered.append(f"{gift.name:<{width}}  {rating}")
    fenced = "```" + chr(10) + "{}" + chr(10) + "```"
    while rendered and len(fenced.format(chr(10).join(rendered))) > FIELD_VALUE_LIMIT:
        rendered.pop()
    hidden = len(sheet.gifts) - len(rendered)
    body = chr(10).join(rendered)
    if hidden:
        body += chr(10) + f"… and {hidden} more"
    return fenced.format(body.rstrip())


# -- the two creation surfaces ------------------------------------------------

QUESTIONS_PER_PAGE = 12
BUILD_COLOUR = 0x2F6F4F


def creation_pages(character) -> int:
    """How many pages the questionnaire takes, at least one."""
    total = character.interview.total if character.interview is not None else 0
    return max(1, -(-total // QUESTIONS_PER_PAGE))


def questionnaire_embed(character, *, page: int = 0) -> EmbedSpec:
    """One page of the interview: numbered prompts, their answers, and progress.

    Answers are truncated for display — the sheet remembers them whole, and /story or /export
    is where long prose is read.
    """
    interview = character.interview
    if interview is None or not interview.questions:
        return EmbedSpec(
            title=f"{character.name} — questionnaire",
            description="No questionnaire attached yet.",
            colour=BUILD_COLOUR,
        )
    pages = creation_pages(character)
    page = max(0, min(page, pages - 1))
    start = page * QUESTIONS_PER_PAGE
    chunk = interview.questions[start : start + QUESTIONS_PER_PAGE]

    lines: list[str] = []
    for offset, question in enumerate(chunk, start=start + 1):
        answer = " ".join(question.answer.split())
        if len(answer) > 180:
            answer = answer[:177] + "..."
        lines.append(f"**{offset}.** {question.prompt}")
        lines.append(answer or "_unanswered — /answer " + str(offset) + " text:_")
        lines.append("")
    return EmbedSpec(
        title=f"{character.name} — questionnaire",
        description="\n".join(lines).strip(),
        footer=(
            f"{interview.answered}/{interview.total} answered · "
            f"page {page + 1}/{pages} · /page n to move"
        ),
        colour=BUILD_COLOUR,
    )


def build_embed(character, *, page: int = 0) -> EmbedSpec:
    """The sheet, with the creation budgets still to spend."""
    from dataclasses import replace as _replace

    from ttrpg_chatbots.character.build import remaining

    sheet = character.sheet
    spec = embed_spec(sheet)
    if character.build is None:
        return spec
    left = remaining(sheet, character.build)
    parts: list[str] = []
    for section in ("attributes", "abilities", "virtues", "backgrounds"):
        for group, value in left[section].items():
            budget = value + _spent(sheet, character.build, section, group)
            parts.append(f"{group} {budget - value}/{budget}")
    budget_line = " · ".join(parts)
    # The assignment is a choice, so it stays visible rather than implied by whichever group
    # happens to want points.
    assignment = " · ".join(
        f"{group} {budget}"
        for group, budget in (
            *character.build.attributes.items(),
            *character.build.abilities.items(),
        )
    )
    notes = [f"revision {character.revision}", "draft — nothing is final until /finish"]
    if character.interview is not None:
        notes.append(f"answers {character.interview.answered}/{character.interview.total}")
    return _replace(
        spec,
        description=(
            f"{spec.description}\n{budget_line}\n"
            f"`{assignment}` — /budget changes which group gets which"
        ),
        footer=" · ".join(notes),
        colour=BUILD_COLOUR,
    )


def _spent(sheet, build, section: str, group: str) -> int:
    """Spent so far in one group, for the ``spent/budget`` display."""
    from ttrpg_chatbots.character.build import (
        ability_spent,
        attribute_spent,
        background_spent,
        virtue_spent,
    )

    if section == "attributes":
        return attribute_spent(sheet)[group]
    if section == "abilities":
        return ability_spent(sheet)[group]
    if section == "virtues":
        return virtue_spent(sheet)
    return background_spent(sheet)
