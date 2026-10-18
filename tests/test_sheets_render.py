"""The sheet as fixed-width text: alignment is the feature, so it is what gets tested."""

from __future__ import annotations

import re

import pytest

from ttrpg_chatbots.sheets.render import (
    DESCRIPTION_LIMIT,
    FIELD_VALUE_LIMIT,
    GROUP_GAP,
    EmbedField,
    EmbedSpec,
    embed_spec,
    NAME_WIDTH,
    RANK_WIDTH,
    SPECIALTY_WIDTH,
    clipped_specialty,
    health_state,
    render_sheet,
)
from ttrpg_chatbots.sheets.types import Ability, Gift, Sheet, Trait

COLUMN_WIDTH = NAME_WIDTH + SPECIALTY_WIDTH + RANK_WIDTH
HEALTH = (
    "Unharmed",
    "Bruised",
    "Hurt (-1)",
    "Injured (-1)",
    "Wounded (-2)",
    "Mauled (-2)",
    "Crippled (-5)",
    "Incapacitated",
)


def sheet(**kwargs) -> Sheet:
    base = dict(
        name="Molly MacIntosh",
        system="house-games",
        attributes={
            "Strength": 1,
            "Dexterity": 2,
            "Stamina": 5,
            "Charisma": 1,
            "Manipulation": 1,
            "Appearance": 4,
            "Perception": 1,
            "Intelligence": 5,
            "Wits": 4,
        },
        abilities={
            "Alertness": Ability("Alertness", rank=4, category="talent", specialty="Vision"),
            "Stealth": Ability("Stealth", rank=0, category="skill"),
            "Science": Ability(
                "Science", rank=5, category="knowledge", specialty="Alchemical Rituals"
            ),
        },
        virtues={"Conscience/Conviction": 3, "Self-Control/Instinct": 5, "Courage": 2},
        willpower=10,
        willpower_remaining=10,
        morality=8,
        health=HEALTH,
        backgrounds=(Trait("Cipher", dots=4), Trait("Occult Laboratory", dots=6)),
        gifts=(Gift("Thanatosis", rating=1), Gift("Alchemy", rating=1)),
        freebies=0,
        xp=0,
    )
    base.update(kwargs)
    return Sheet(**base)


def lines(text: str) -> list[str]:
    return text.splitlines()


# -- the top bar and the rule ------------------------------------------------


def test_the_top_bar_carries_name_system_and_both_pools() -> None:
    assert lines(render_sheet(sheet()))[0] == (
        "Molly MacIntosh · house-games · freebies 0 · xp 0"
    )


def test_attributes_read_across_physical_social_mental() -> None:
    rendered = render_sheet(sheet())
    assert "STR 1 CHA 1 PER 1" in rendered
    assert "DEX 2 MAN 1 INT 5" in rendered
    assert "STA 5 APP 4 WIT 4" in rendered


def test_virtues_and_trackers_sit_beside_the_attributes() -> None:
    rendered = render_sheet(sheet())
    assert "Conv 3  Moral 8" in rendered
    assert "Inst 5  Will  10/10" in rendered
    assert "Cour 2  Health 8/8 (-0)" in rendered


def test_the_three_blocks_start_at_fixed_columns() -> None:
    rendered = lines(render_sheet(sheet()))
    rule = [line for line in rendered if "Moral" in line or "Will " in line or "Health" in line]
    assert len(rule) == 3
    starts = {line.index(name) for line, name in zip(rule, ("Conv", "Inst", "Cour"))}
    assert len(starts) == 1  # all three virtue rows begin in the same column
    right = {line.index(name) for line, name in zip(rule, ("Cipher", "Occult Laboratory"))}
    assert len(right) == 1


def test_backgrounds_sit_on_the_right() -> None:
    rendered = render_sheet(sheet())
    assert "Cipher     4" in rendered
    assert "Occult Laboratory 6" in rendered


def test_a_missing_morality_does_not_crash_the_rule() -> None:
    assert "Moral -" in render_sheet(sheet(morality=None))


# -- abilities ---------------------------------------------------------------


def test_specialties_are_clipped_to_eight_characters() -> None:
    assert clipped_specialty("Alchemical Rituals") == "(Alchemic...)"
    assert clipped_specialty("Vision") == "(Vision)"
    assert clipped_specialty("") == "(None)"


def test_every_ability_column_lines_up() -> None:
    rendered = lines(render_sheet(sheet()))
    table = [
        line
        for line in rendered
        if "(" in line and not line.startswith(("STR", "DEX", "STA"))
    ]
    assert table, "the ability table should have rows"
    for index in range(1, 3):
        offset = index * (COLUMN_WIDTH + len(GROUP_GAP))
        # Nothing may start in the gap itself.
        assert all(line[offset - 1] == " " for line in table)


def test_talents_skills_and_knowledges_are_in_their_own_columns() -> None:
    rendered = render_sheet(sheet())
    alertness = next(line for line in lines(rendered) if line.startswith("Alertness"))
    stealth = next(line for line in lines(rendered) if "Stealth" in line)
    science = next(line for line in lines(rendered) if "Science " in line)
    assert alertness.index("Alertness") < stealth.index("Stealth") < science.index("Science")


def test_an_untrained_ability_still_shows_a_rank() -> None:
    # Stealth is the only skill, so its cell is followed by the knowledge column.
    assert re.search(r"Stealth\s+\(None\)\s+0", render_sheet(sheet()))


def test_the_rows_are_never_blank_inside_the_table() -> None:
    # A group with fewer entries is padded, not shifted: one ability, one padded row.
    thin = sheet(abilities={"Alertness": Ability("Alertness", rank=4, category="talent")})
    table = [line for line in lines(render_sheet(thin)) if line.startswith("Alertness")]
    assert len(table) == 1
    assert table[0].rstrip().endswith("4")  # the rank, right-aligned
    assert len(table[0]) >= COLUMN_WIDTH  # padded to at least one full column


def test_a_short_column_pads_with_spaces() -> None:
    thin = sheet(abilities={"Alertness": Ability("Alertness", rank=4, category="talent")})
    rendered = [line for line in lines(render_sheet(thin)) if "(" in line]
    assert all(len(line) >= COLUMN_WIDTH for line in rendered)


# -- health ------------------------------------------------------------------


def test_health_is_full_by_default() -> None:
    assert health_state(sheet()) == (8, 8, 0)


def test_a_recorded_wound_shows_its_penalty() -> None:
    hurt = sheet(meta={"health_current": 6})  # reached "Hurt (-1)"
    assert health_state(hurt) == (6, 8, 1)
    assert "Health 6/8 (-1)" in render_sheet(hurt)


def test_an_out_of_range_health_value_is_clamped() -> None:
    assert health_state(sheet(meta={"health_current": 99})) == (8, 8, 0)
    assert health_state(sheet(meta={"health_current": -3})) == (0, 8, 5)


def test_a_sheet_with_no_health_track_renders_zeroes() -> None:
    assert health_state(sheet(health=())) == (0, 0, 0)


# -- gifts -------------------------------------------------------------------


def test_two_gifts_stack_in_one_column() -> None:
    assert "Thanatosis 1\nAlchemy 1" in render_sheet(sheet())


def test_flat_gifts_are_labelled_as_such() -> None:
    assert "Walking Fire (flat)" in render_sheet(sheet(gifts=(Gift("Walking Fire"),)))


def test_many_gifts_spread_into_columns() -> None:
    many = sheet(gifts=tuple(Gift(f"Gift {n}") for n in range(12)))
    rendered = lines(render_sheet(many))
    gift_rows = [line for line in rendered if line.startswith("Gift ")]
    assert 1 < len(gift_rows) < 12  # fewer rows than gifts: they spread
    assert any(line.count("Gift ") >= 2 for line in gift_rows)  # and into columns


def test_no_gifts_means_no_gift_block() -> None:
    rendered = render_sheet(sheet(gifts=()))
    assert "flat" not in rendered
    assert not rendered.endswith("\n\n")


@pytest.mark.parametrize("count", [1, 2, 6, 7, 13, 25])
def test_gift_layout_survives_any_count(count: int) -> None:
    rendered = render_sheet(sheet(gifts=tuple(Gift(f"Gift {n}") for n in range(count))))
    assert rendered.count("Gift ") == count


# -- shape -------------------------------------------------------------------


def test_no_line_has_trailing_whitespace() -> None:
    for line in lines(render_sheet(sheet())):
        assert line == line.rstrip()


def test_the_whole_sheet_fits_a_discord_message() -> None:
    rendered = render_sheet(sheet(gifts=tuple(Gift(f"Gift {n}") for n in range(20))))
    assert len(rendered) < 4000  # Discord's embed description limit, with room for a fence
    assert max(len(line) for line in lines(rendered)) <= 100


def test_a_sheet_with_no_abilities_or_backgrounds_still_renders() -> None:
    bare = sheet(abilities={}, backgrounds=(), gifts=())
    rendered = render_sheet(bare)
    assert "Molly MacIntosh" in rendered
    assert "STR 1" in rendered



# -- the embed ---------------------------------------------------------------


def names_of(spec) -> list[str]:
    return [field.name for field in spec.fields]


def test_the_embed_is_a_three_column_grid_of_inline_fields() -> None:
    fields = list(embed_spec(sheet()).fields)
    assert [field.name for field in fields[:3]] == ["Physical", "Social", "Mental"]
    assert all(field.inline for field in fields[:9])  # the grid; gifts span the width
    assert fields[0].value.splitlines() == ["STR 1", "DEX 2", "STA 5"]


def test_trackers_and_backgrounds_follow_the_attributes() -> None:
    fields = {field.name: field.value for field in embed_spec(sheet()).fields}
    assert fields["Virtues"] == "Conv 3\nInst 5\nCour 2"
    assert "Will 10/10" in fields["Trackers"]
    assert "Health 8/8 (-0)" in fields["Trackers"]
    assert fields["Backgrounds"] == "Cipher 4\nOccult Laboratory 6"


def test_abilities_are_one_code_block_each() -> None:
    fields = {field.name: field.value for field in embed_spec(sheet()).fields}
    assert fields["Talents"].startswith("```") and fields["Talents"].endswith("```")
    assert "Alertness" in fields["Talents"] and "(Vision)" in fields["Talents"]
    assert "Stealth" in fields["Skills"]
    assert "Science" in fields["Knowledges"]
    # A category with nothing in it is omitted rather than emitted empty.
    assert "Knowledges" in fields


def test_an_empty_category_is_not_a_field() -> None:
    only_talents = sheet(
        abilities={"Alertness": Ability("Alertness", 4, "talent")}, gifts=()
    )
    assert names_of(embed_spec(only_talents)) == [
        "Physical",
        "Social",
        "Mental",
        "Virtues",
        "Trackers",
        "Backgrounds",
        "Talents",
    ]


def test_gifts_are_one_full_width_code_block() -> None:
    gifts = next(field for field in embed_spec(sheet()).fields if field.name == "Gifts")
    assert gifts.inline is False
    assert gifts.value.startswith("```") and gifts.value.endswith("```")
    # One per line, ratings aligned.
    body = gifts.value.strip("`").splitlines()
    assert body[1].split() == ["Thanatosis", "1"]
    assert body[2].split() == ["Alchemy", "1"]


def test_gifts_are_omitted_when_there_are_none() -> None:
    assert "Gifts" not in names_of(embed_spec(sheet(gifts=())))


def test_the_top_bar_is_the_description() -> None:
    spec = embed_spec(sheet(), footer="revision 2 · sealed")
    assert spec.title == "Molly MacIntosh"
    assert spec.description.startswith("house-games · freebies 0 · xp 0")
    assert spec.footer == "revision 2 · sealed"


def test_a_portrait_becomes_the_thumbnail() -> None:
    illustrated = sheet(meta={"portrait": "https://example.test/molly.png"})
    assert embed_spec(illustrated).thumbnail == "https://example.test/molly.png"


def test_a_missing_or_bogus_portrait_is_ignored() -> None:
    assert embed_spec(sheet()).thumbnail == ""
    assert embed_spec(sheet(meta={"portrait": "not a url"})).thumbnail == ""
    assert embed_spec(sheet(meta={"portrait": "javascript:alert(1)"})).thumbnail == ""


def test_the_embed_stays_inside_discords_limits() -> None:
    big = sheet(
        abilities={
            f"Ability {n}": Ability(f"Ability {n}", 3, "talent", "specialty") for n in range(40)
        },
        gifts=tuple(Gift(f"Gift {n}") for n in range(40)),
    )
    spec = embed_spec(big)
    assert len(spec.fields) <= 25
    assert all(len(field.value) <= FIELD_VALUE_LIMIT for field in spec.fields)
    assert len(spec.description) <= DESCRIPTION_LIMIT


def test_an_empty_field_is_refused() -> None:
    with pytest.raises(ValueError, match="no value"):
        EmbedSpec(title="x", fields=(EmbedField("Empty", ""),))
