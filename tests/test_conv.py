"""The plan and the contracts: the manifest must match the tree, and the types must hold.

The manifest test is the one that makes single-purpose modularisation checkable: a module marked
built has to import, and a module marked planned must not exist, so nobody can leave a stub behind
and pretend the piece is done.
"""

from __future__ import annotations

import pytest

from ttrpg_chatbots.conv import MODULES, Abstain, Budget, Draft, Line, Trail, Utterance, check, summary
from ttrpg_chatbots.conv.manifest import BANDS, ManifestError, ModuleSpec, built, planned


def test_the_manifest_and_the_tree_agree() -> None:
    assert check() == ()


def test_the_plan_is_actually_a_plan() -> None:
    # The plan has to stay a plan: a complete list, and no module unaccounted for.
    assert len(MODULES) >= 45
    assert len(built()) >= 30
    assert len(built()) + len(planned()) == len(MODULES)


def test_every_band_has_work_in_it() -> None:
    for band in BANDS:
        assert any(module.band == band for module in MODULES), band


def test_no_module_is_listed_twice() -> None:
    names = [module.module for module in MODULES]
    assert len(names) == len(set(names))


def test_a_module_must_answer_exactly_one_question() -> None:
    for module in MODULES:
        question = module.question.strip()
        assert question, module.module
        assert len(question) <= 80, f"{module.module}: that is more than one question"
        assert question.count("?") <= 1, module.module


def test_a_bad_band_or_status_is_refused() -> None:
    with pytest.raises(ManifestError, match="band must be"):
        ModuleSpec(band="vibes", module="x", question="what?")
    with pytest.raises(ManifestError, match="status must be"):
        ModuleSpec(band="decide", module="x", question="what?", status="maybe")
    with pytest.raises(ManifestError, match="every module answers a question"):
        ModuleSpec(band="decide", module="x", question="  ")


def test_the_summary_reads_like_a_scoreboard() -> None:
    assert "built" in summary()


# --- contracts ---------------------------------------------------------------------------------


def test_a_budget_counts_words_and_sentences() -> None:
    budget = Budget(max_words=6, max_sentences=1)

    assert budget.fits("fighting with an old computer. you?") is True
    assert budget.fits("it gets to the boot screen and quits. tried three disks.") is False
    assert budget.fits("one two three four five six seven") is False


def test_a_budget_cannot_be_zero() -> None:
    with pytest.raises(ValueError, match="at least one word"):
        Budget(max_words=0)
    with pytest.raises(ValueError, match="at least one sentence"):
        Budget(max_sentences=0)


def test_a_train_records_every_rung() -> None:
    trail = Trail().add("floor", "speak").add("phase", "opening").add("job", "greet")

    assert trail.describe() == "floor=speak > phase=opening > job=greet"


def test_a_line_must_say_something() -> None:
    with pytest.raises(ValueError, match="must say something"):
        Line(text="   ")


def test_a_draft_and_an_abstain_are_different_answers() -> None:
    assert Draft(stage="greet", reference="g-warm-03").stage == "greet"
    assert isinstance(Abstain(reason="unaddressed"), Abstain)


def test_an_utterance_refuses_a_non_string() -> None:
    with pytest.raises(TypeError):
        Utterance(text=None)  # type: ignore[arg-type]
