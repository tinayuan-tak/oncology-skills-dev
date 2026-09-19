"""The sc-normal clamp's GATING FIELD must reach `decision['headline']`.

`tvn-sc-normal-critical-organ-veto` reads `sc_normal_essential_veto_grade` — it was repointed off
`sc_normal_safety_essential_class` because the class is a near-constant (473 of the 504
corpus-20260914 pairs, 93.8%, against 329 / 65.3% for the grade, measured live 2026-09-19). Every
OTHER input to that arm was already projected: the class, the named driver cell and tissue, its
detection fraction, its atlas count, and a skill-side RE-DERIVATION of the severity
(`sc_normal_essential_severity`). The gating value itself was not — so a headline could carry a
`selective_with_normal_liability` verdict containing no field that explains the downgrade. Measured
on DLL3-SCLC: `cards[3].summary.sc_normal_essential_veto_grade == 'accessible_high_severity'` while
`headline.sc_normal_essential_veto_grade` was absent.

These tests are verdict-INERT by construction — they assert on projection, never on the resolved
spine, and `test_projection_does_not_move_the_verdict` pins that.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _test_support import load_run_py

ts = load_run_py(Path(__file__).resolve().parent.parent, "ts_run_veto_grade_projection")

_SC_NORMAL_CARD = "sc-normal-celltype-expression"
# The DLL3-SCLC shape, measured live: a colon enteric neuron at det 0.746 / donor 1.0 across 6
# atlases clears the classic high-severity rung, so the clamp fires and the verdict downgrades.
_DLL3_SC_NORMAL = {
    "sc_normal_expression_class": "HIGH_LIABILITY",
    "sc_normal_safety_essential_class": "critical_organ_liability",
    "sc_normal_essential_veto_grade": "accessible_high_severity",
    "sc_normal_essential_max_cell_type": "inhibitory motor neuron",
    "sc_normal_essential_max_tissue": "colon",
    "sc_normal_essential_max_detection_fraction": 0.7464788732394366,
    "sc_normal_essential_donor_fraction": 1.0,
    "sc_normal_essential_n_datasets_reliable": 6,
}
_CLAMPED = ("selective_with_normal_liability", "tvn-sc-normal-critical-organ-veto")


def _hl(sc_normal, verdict_pair=_CLAMPED):
    return ts._headline([{"card_id": _SC_NORMAL_CARD, "summary": dict(sc_normal)}], [], verdict_pair)


def test_the_gating_field_reaches_the_headline():
    """Anti-vacuity: `in` is not enough — a key absent from `_headline` would read as None here, so
    assert the VALUE arrived. This fails on the pre-fix code, where the key does not exist at all."""
    hl = _hl(_DLL3_SC_NORMAL)
    assert "sc_normal_essential_veto_grade" in hl, "the field the clamp gates on is not projected"
    assert hl["sc_normal_essential_veto_grade"] == "accessible_high_severity"


def test_the_gating_field_and_its_re_derivation_agree_on_this_record():
    """The pair exists so a reviewer can RECONCILE them. On a record carrying all three grading
    fields they must agree, or one of the two implementations has drifted — the defect
    SKILL_VERSION 1.25.0 closed by realigning the skill-side ladder with the method's.
    """
    hl = _hl(_DLL3_SC_NORMAL)
    grade = hl["sc_normal_essential_veto_grade"]
    derived = hl["sc_normal_essential_severity"]
    assert grade == f"accessible_{derived}", f"skill-side {derived!r} disagrees with method-side {grade!r}"


def test_both_halves_of_the_pair_reach_the_synthesis_layer():
    """Projecting the re-derivation but not the gating value was the worse half of the gap: a narrator
    could state a severity it computed itself while unable to cite the value the clamp keyed on."""
    assert "sc_normal_essential_severity" in ts._SYNTHESIS_FACET_KEYS
    assert "sc_normal_essential_veto_grade" in ts._SYNTHESIS_FACET_KEYS


@pytest.mark.parametrize(
    "grade",
    ["accessible_high_severity", "accessible_ungraded", "accessible_moderate_severity", "bbb_protected"],
)
def test_every_grade_token_projects_verbatim_including_the_non_firing_ones(grade):
    """The two KILLER-eligible tokens AND two that are not.

    A reviewer needs to see `accessible_moderate_severity` just as much as
    `accessible_high_severity` — it is the token that says the arm looked and did NOT fire, which is
    the difference between a clean pass and an unexamined one. Projecting only the firing values
    would make a near-miss indistinguishable from no evidence.
    """
    hl = _hl({**_DLL3_SC_NORMAL, "sc_normal_essential_veto_grade": grade})
    assert hl["sc_normal_essential_veto_grade"] == grade


def test_an_absent_grade_projects_none_rather_than_a_manufactured_value():
    """A pre-#647 card summary has no grade. None is the honest projection: the method did not say.
    Manufacturing a default here would let a missing column read as a measured non-liability."""
    sc = {k: v for k, v in _DLL3_SC_NORMAL.items() if k != "sc_normal_essential_veto_grade"}
    assert _hl(sc)["sc_normal_essential_veto_grade"] is None


def test_projection_does_not_move_the_verdict():
    """VERDICT-INERT, asserted rather than claimed: the resolved pair is passed IN and must come back
    out untouched, on both a clamped and an unclamped call."""
    for pair in (_CLAMPED, ("strong_tumor_selective", "tvn-strong-selective-supportive")):
        hl = _hl(_DLL3_SC_NORMAL, verdict_pair=pair)
        assert hl["selectivity_class"] == pair[0]
        assert hl["driving_rule_id"] == pair[1]
