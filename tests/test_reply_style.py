"""The typing layer: what it changes, and what it refuses to change.

Style is presentation, so the tests are about the two failure modes that matter: it must never
alter meaning ("I'll" must not become "ill") and it must be deterministic, so a replay is a replay
and a test can assert a specific line.
"""

from __future__ import annotations

import pytest

from ttrpg_chatbots.reply.style import DEFAULT_STYLE, Style, apply_style


def test_the_default_style_is_the_old_behaviour() -> None:
    # Nothing that has not opted in may change its text.
    assert apply_style("hello there.") == "Hello there."
    assert apply_style("hello there.", DEFAULT_STYLE) == "Hello there."
    assert apply_style("  hey  ") == "Hey"


def test_a_skipped_style_leaves_the_text_alone() -> None:
    text = "don't do that."

    assert apply_style(text, Style(case="as-written")) == text


def test_lower_case_only_lowers_the_opening_letter() -> None:
    styled = apply_style("Hey hey. Original Six.", Style(case="lower"))

    assert styled == "hey hey. Original Six."


def test_a_shout_keeps_its_volume() -> None:
    # "HAH. no thanks" must not become "hAH".
    assert apply_style("HAH. no thanks", Style(case="lower")) == "HAH. no thanks"


def test_apostrophes_drop_only_where_the_word_stays_a_word() -> None:
    style = Style(case="as-written", drop_apostrophes=True)

    assert apply_style("don't mention it", style) == "dont mention it"
    assert apply_style("that's past my knowledge", style) == "thats past my knowledge"


def test_apostrophes_never_create_another_word() -> None:
    style = Style(case="as-written", drop_apostrophes=True)

    # "ill", "well" and "id" are real words, so those forms keep their apostrophe.
    assert apply_style("i'll say it louder", style) == "i'll say it louder"
    assert apply_style("we'll see", style) == "we'll see"
    assert apply_style("i'd rather not", style) == "i'd rather not"


def test_a_final_full_stop_can_be_dropped() -> None:
    style = Style(case="as-written", strip_final_period=True)

    assert apply_style("see ya.", style) == "see ya"
    assert apply_style("see ya!", style) == "see ya!"
    assert apply_style("really..", style) == "really.."


def test_typos_are_rare_and_deterministic() -> None:
    style = Style(typo_rate=0.5)

    first = apply_style("it's just about done", style)
    second = apply_style("it's just about done", style)

    assert first == second, "the same line must render the same way twice"


def test_a_zero_typo_rate_never_touches_anything() -> None:
    style = Style(typo_rate=0.0)

    for text in ("just about with something because", "nothing to see here"):
        assert apply_style(text, style).lower() == text


def test_a_typo_never_invents_a_word_outside_the_list() -> None:
    style = Style(typo_rate=1.0)

    styled = apply_style("hockey is the best game", style)

    # Nothing eligible, so nothing changes beyond the casing rule.
    assert styled == "Hockey is the best game"


def test_every_typo_is_a_transposition_of_a_real_word() -> None:
    from ttrpg_chatbots.reply.style import _TYPOS

    for word, typo in _TYPOS.items():
        assert sorted(word) == sorted(typo), f"{typo!r} is not a reordering of {word!r}"
        assert typo != word


def test_style_rejects_a_case_it_does_not_have() -> None:
    with pytest.raises(ValueError, match="case must be one of"):
        Style(case="shouty")


def test_a_typo_rate_must_be_a_fraction() -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        Style(typo_rate=2.0)
    with pytest.raises(ValueError, match="must be a number"):
        Style(typo_rate=True)


def test_from_record_reads_a_persona_style() -> None:
    style = Style.from_record(
        {"case": "lower", "drop_apostrophes": True, "strip_final_period": True, "typo_rate": 0.05}
    )

    assert style.describe() == "lower, no apostrophes, no full stop, 5% typos"


def test_from_record_names_the_bad_field() -> None:
    with pytest.raises(ValueError, match="style.case"):
        Style.from_record({"case": 3})
    with pytest.raises(ValueError, match="drop_apostrophes"):
        Style.from_record({"drop_apostrophes": "yes"})
    with pytest.raises(ValueError, match="style:"):
        Style.from_record({"case": "shouty"})
