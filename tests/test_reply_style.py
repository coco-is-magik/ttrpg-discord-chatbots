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


class TestOttoStyle:
    """Stutter and emoticons: two levers that exist because of one character's brief.

    They are levers rather than hardcoded behaviour because the *next* friend may want neither, and
    because hesitation has to survive into the voice -- a synthesiser reads "h- hello" as a false
    start, so a hesitant character does not need an engine that can act.

    The **space** after the hyphen is the audible part. Measured on `en_US-ryan-medium`: the first
    version's "I-I think it is late again" came out 1.29 s against a 1.20 s baseline, a 90 ms
    difference nobody hears, while "th- this is the train" was 1.35 s against 0.79 s.
    """

    def test_a_stutter_false_starts_the_opening_word(self) -> None:
        style = Style(stutter_rate=1.0)
        assert apply_style("hello there", style) == "He- hello there"
        assert apply_style("i think so", style) == "I- i think so", "a one-letter word keeps one letter"
        assert apply_style("thinking about it", style) == "Th- thinking about it"

    def test_a_one_letter_word_is_stuttered_too(self) -> None:
        """"i" is the commonest opening word there is, and "i- i think" is a real false start.

        The first version skipped one-letter words because "i-i" (no space) just looked like a typo;
        with the space it reads as hesitation, and excluding it left most of his lines unstuttered.
        """
        style = Style(stutter_rate=1.0)
        assert apply_style("i think so", style) == "I- i think so"

    def test_stutter_is_deterministic(self) -> None:
        style = Style(stutter_rate=0.5)
        assert apply_style("hello there", style) == apply_style("hello there", style)

    def test_an_emoticon_is_appended_from_the_pool(self) -> None:
        style = Style(emoji_rate=1.0, emojis=("^^", ":3"))
        result = apply_style("hello", style)
        assert result.startswith("Hello ")
        assert result.split()[-1] in {"^^", ":3"}

    def test_the_emoticon_survives_a_stripped_final_period(self) -> None:
        style = Style(strip_final_period=True, emoji_rate=1.0, emojis=(":3",))
        assert apply_style("hello there.", style) == "Hello there :3"

    def test_a_rate_with_no_pool_is_refused(self) -> None:
        # Otherwise the rate would silently do nothing, which is worse than an error.
        with pytest.raises(ValueError, match="non-empty emojis pool"):
            Style(emoji_rate=0.5)

    def test_rates_outside_zero_to_one_are_refused(self) -> None:
        with pytest.raises(ValueError, match="stutter_rate must be between"):
            Style(stutter_rate=2.0)
        with pytest.raises(ValueError, match="emoji_rate must be between"):
            Style(emoji_rate=-1.0)

    def test_the_pool_is_read_from_a_persona_record(self) -> None:
        style = Style.from_record({"emoji_rate": 0.4, "emojis": ["^^", ":3"], "stutter_rate": 0.2})

        assert style.emojis == ("^^", ":3")
        assert style.emoji_rate == 0.4
        assert "stutter" in style.describe()


class TestHesitationFillers:
    """A spoken hesitation: "um, i think so".

    Added because the false start alone was not audible. Measured on `en_US-ryan-medium`, "I-I think"
    bought 90 ms while "I, um, think" bought a full second -- so a character who is meant to *sound*
    hesitant needs both levers, and the filler is the one the ear actually notices.
    """

    def test_a_filler_rate_needs_a_pool(self) -> None:
        with pytest.raises(ValueError, match="fillers pool"):
            Style(filler_rate=0.5)

    def test_a_filler_hesitates_before_the_line(self) -> None:
        style = Style(filler_rate=1.0, fillers=("um",))
        assert apply_style("i think so", style) == "Um, i think so"

    def test_the_filler_is_deterministic(self) -> None:
        style = Style(filler_rate=1.0, fillers=("um", "ah"))
        assert apply_style("hello there", style) == apply_style("hello there", style)

    def test_the_filler_is_not_itself_stuttered(self) -> None:
        """The false start lands on the line's own first word, not on the hesitation in front of it."""
        style = Style(stutter_rate=1.0, filler_rate=1.0, fillers=("um",))
        result = apply_style("thinking about it", style)
        assert result == "Um, th- thinking about it"

    def test_a_filler_outside_its_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="filler_rate must be between"):
            Style(filler_rate=1.5, fillers=("um",))

    def test_blank_fillers_are_refused(self) -> None:
        with pytest.raises(ValueError, match="fillers must be non-blank"):
            Style(filler_rate=0.5, fillers=("um", "  "))

    def test_a_record_can_carry_the_pool(self) -> None:
        style = Style.from_record({"filler_rate": 0.4, "fillers": ["um", "ah"]})
        assert style.fillers == ("um", "ah")
        assert "40% fillers" in style.describe()

    def test_a_record_with_a_bad_pool_names_the_field(self) -> None:
        with pytest.raises(ValueError, match="style.fillers"):
            Style.from_record({"fillers": "um"})


class TestOneEmoticonPerLine:
    """A line that already ends in an emoticon does not get a second one.

    Measured: a phrasebook variant ending in "^^" came out as "what about you? ^^ (◕‿◕)" once the
    style layer appended its own. The pool *is* the vocabulary of these marks, so membership in it is
    what the check tests -- not a hand-written list of emoticons.
    """

    def test_a_line_that_already_has_one_is_left_alone(self) -> None:
        style = Style(emoji_rate=1.0, emojis=("^^", ":3"))
        assert apply_style("what about you? ^^", style) == "What about you? ^^"
        assert apply_style("hello :3", style) == "Hello :3"

    def test_a_line_without_one_still_gets_one(self) -> None:
        style = Style(emoji_rate=1.0, emojis=("^^",))
        assert apply_style("hello there", style) == "Hello there ^^"

    def test_an_emoticon_in_the_middle_is_not_the_end(self) -> None:
        style = Style(emoji_rate=1.0, emojis=("^^",))
        assert apply_style("^^ hello", style) == "^^ hello ^^"
