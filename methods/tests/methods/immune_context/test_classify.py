"""immune_context.classify — per-indication T-cell-infiltration classifier (pure, no S3).

Pins the immune-hot/intermediate/cold ladder (anchored to pan-cancer CD8-fraction quartiles) + the
summarize reduction + the data_unavailable-abstains discipline, plus the two FAIL-CLOSED guards on a
relative deconvolution (lymphoid denominator, sample floor) and the heterogeneity / suppression fields.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.immune_context import classify as _cl  # noqa: E402
from methods.immune_context.classify import (  # noqa: E402
    CD8_FRACTION_COLD_MAX,
    CD8_FRACTION_HOT_MIN,
    LYMPHOID_DENOMINATOR_STUDIES,
    MIN_N_SAMPLES,
    T_CELL_COLUMNS,
    classify_immune_context,
    has_lymphoid_denominator,
    summarize_immune_context,
)


# ── the hot/intermediate/cold ladder ─────────────────────────────────────────
def test_immune_hot_at_or_above_q3():
    assert classify_immune_context(CD8_FRACTION_HOT_MIN) == "immune_hot"
    assert classify_immune_context(0.154) == "immune_hot"  # SKCM-like


def test_immune_cold_at_or_below_q1():
    assert classify_immune_context(CD8_FRACTION_COLD_MAX) == "immune_cold"
    assert classify_immune_context(0.022) == "immune_cold"  # LAML-like desert


def test_immune_intermediate_between():
    assert classify_immune_context(0.097) == "immune_intermediate"  # pan-cancer median


def test_none_cd8_is_data_unavailable_not_cold():
    # absence must ABSTAIN, never default to a (dangerous) false 'cold' call
    assert classify_immune_context(None) == "data_unavailable"


# ── summarize reduction ──────────────────────────────────────────────────────
def _row(cd8, others=0.0, treg=None, m2=None, m1=None):
    r = {c: others for c in T_CELL_COLUMNS}
    r["T.cells.CD8"] = cd8
    if treg is not None:
        r["T.cells.regulatory..Tregs."] = treg
    if m2 is not None:
        r["Macrophages.M2"] = m2
    if m1 is not None:
        r["Macrophages.M1"] = m1
    return r


def _cohort(cd8_values, **kw):
    """A cohort at/above the admissibility floor, so a test about the LADDER is not silently a test
    about the sample floor. Repeats the given values until n >= MIN_N_SAMPLES (median preserved)."""
    reps = -(-MIN_N_SAMPLES // len(cd8_values))  # ceil
    return pd.DataFrame([_row(v, **kw) for v in cd8_values for _ in range(reps)])


def test_summarize_medians_and_class():
    s = summarize_immune_context(_cohort([0.13, 0.15, 0.20]))  # median CD8 = 0.15 → hot
    assert s["immune_context_class"] == "immune_hot"
    assert s["median_cd8_fraction"] == 0.15
    assert s["n_samples"] >= MIN_N_SAMPLES
    assert s["median_total_t_cell_fraction"] >= 0.15  # CD8 + other T subsets


def test_summarize_empty_is_data_unavailable():
    s = summarize_immune_context(pd.DataFrame())
    assert s["immune_context_class"] == "data_unavailable"
    assert s["n_samples"] == 0
    assert s["median_cd8_fraction"] is None


def test_summarize_missing_cd8_column_is_data_unavailable():
    s = summarize_immune_context(pd.DataFrame([{"B.cells.naive": 0.1}]))
    assert s["immune_context_class"] == "data_unavailable"


def test_cold_indication_summarizes_cold():
    assert summarize_immune_context(_cohort([0.05, 0.06, 0.07]))["immune_context_class"] == "immune_cold"


# ── F5: the sample floor ─────────────────────────────────────────────────────
def test_thin_cohort_abstains_rather_than_classing():
    """A median over a handful of samples is a wide-CI guess. Pre-fix this returned a confident
    `immune_hot`; the sibling absolute-TIL reader has applied the same floor since v1.0.0."""
    df = pd.DataFrame([_row(0.15)] * (MIN_N_SAMPLES - 1))
    s = summarize_immune_context(df)
    assert s["immune_context_class"] == "data_unavailable"
    assert s["n_samples"] == MIN_N_SAMPLES - 1  # the thinness is REPORTED, not hidden
    assert s["median_cd8_fraction"] is None  # ...and the number it would have published is withheld
    assert str(MIN_N_SAMPLES) in s["_data_note"]


def test_floor_is_exactly_inclusive_at_min_n():
    assert summarize_immune_context(pd.DataFrame([_row(0.15)] * MIN_N_SAMPLES))["immune_context_class"] == "immune_hot"


def test_floor_matches_the_corroborating_saltz_reader():
    """The two readers corroborate each other on the immune-context headline (the orthogonal-platform
    confidence ruler), so an n one calls too thin must not be an n the other scores confidently."""
    saltz = pytest.importorskip("methods.til_fraction_saltz.read")
    assert MIN_N_SAMPLES == saltz.MIN_N


def test_ladder_enforces_the_floor_when_n_is_supplied():
    assert classify_immune_context(0.15, n_samples=MIN_N_SAMPLES - 1) == "data_unavailable"
    assert classify_immune_context(0.15, n_samples=MIN_N_SAMPLES) == "immune_hot"
    # n omitted → the PURE ladder (the antigen-conditioned facet applies its own floor)
    assert classify_immune_context(0.15) == "immune_hot"


# ── S1: the lymphoid-denominator guard ───────────────────────────────────────
def test_lymphoid_studies_fail_closed_with_a_valid_looking_median():
    """THE POINT OF THE GUARD: DLBC's CD8 share (0.1142) is arithmetically fine and would class
    `immune_hot`. The denominator is the malignant B-cell clone, and DLBCL is TCE-VALIDATED
    (glofitamab, mosunetuzumab), so this is exactly where the skill will be asked for an effector read."""
    df = _cohort([0.1142])
    assert summarize_immune_context(df)["immune_context_class"] == "immune_hot"  # ungated: confident nonsense
    s = summarize_immune_context(df, studies=["DLBC"])
    assert s["immune_context_class"] == "lymphoid_denominator_unreliable"
    assert s["median_cd8_fraction"] is None  # withheld, not published-with-a-caveat
    assert "DLBC" in s["_data_note"]


def test_guard_is_distinct_from_data_unavailable():
    """There IS a cohort; its denominator is wrong. Collapsing the two tokens would tell the reader
    'no data' when the honest statement is 'the reference frame does not apply here'."""
    assert summarize_immune_context(_cohort([0.1142]), studies=["DLBC"])["immune_context_class"] != "data_unavailable"


@pytest.mark.parametrize("study", sorted(LYMPHOID_DENOMINATOR_STUDIES))
def test_every_guarded_study_fails_closed(study):
    assert summarize_immune_context(_cohort([0.12]), studies=[study])["immune_context_class"] == (
        "lymphoid_denominator_unreliable"
    )


def test_guard_fires_on_ANY_pooled_study_not_all():
    """Pooling a lymphoid study with a solid one contaminates the pooled median, so one bad study
    poisons the read."""
    assert has_lymphoid_denominator(["COAD", "DLBC"]) is True
    assert summarize_immune_context(_cohort([0.12]), studies=["COAD", "DLBC"])["immune_context_class"] == (
        "lymphoid_denominator_unreliable"
    )


def test_guard_is_case_and_whitespace_insensitive():
    # keyed on the resolved study code, so an alias map that yields ' dlbc ' is still caught
    assert has_lymphoid_denominator([" dlbc "]) is True


def test_guard_does_not_fire_on_solid_tumours():
    for studies in (["SKCM"], ["COAD", "READ"], ["LUAD", "LUSC"], None, []):
        assert has_lymphoid_denominator(studies) is False


def test_tgct_is_deliberately_not_guarded():
    """TGCT (0.1130 → immune_hot) is a surprising class but an ADMISSIBLE read: seminoma has genuinely
    brisk lymphocytic infiltrate, so the leukocyte denominator IS infiltrate. Guarding it would be
    guarding on outlier-ness instead of on mechanism, which is what this whole check exists to avoid."""
    assert "TGCT" not in LYMPHOID_DENOMINATOR_STUDIES
    assert summarize_immune_context(_cohort([0.1130]), studies=["TGCT"])["immune_context_class"] == "immune_hot"


def test_guard_precedes_the_read_so_no_median_is_ever_computed():
    """The guard must not depend on rows: read.py fires it BEFORE the S3 read, so an empty frame plus
    a lymphoid study must still produce the guard token rather than data_unavailable."""
    assert summarize_immune_context([], studies=["LAML"])["immune_context_class"] == "lymphoid_denominator_unreliable"


def test_abstain_and_scored_summaries_share_a_key_set():
    """A consumer must never have to branch on the class to know which fields exist."""
    scored = summarize_immune_context(_cohort([0.15], treg=0.01, m2=0.2, m1=0.03))
    for abstained in (
        summarize_immune_context(pd.DataFrame()),
        summarize_immune_context(_cohort([0.12]), studies=["DLBC"]),
        summarize_immune_context(pd.DataFrame([_row(0.15)] * 3)),
    ):
        assert set(scored) - set(abstained) == set(), set(scored) - set(abstained)


# ── S3: heterogeneity (the cohort median hides a bimodal cohort) ──────────────
def test_hot_sample_fraction_separates_bimodal_from_uniform_cohorts():
    """Two cohorts with the SAME `immune_intermediate` median: one uniformly middling, one bimodal
    (the MSI-H-colorectal shape — a strongly infiltrated minority the median erases)."""
    uniform = summarize_immune_context(_cohort([0.097]))
    bimodal = summarize_immune_context(_cohort([0.02, 0.02, 0.20, 0.20]))
    assert uniform["immune_context_class"] == bimodal["immune_context_class"] == "immune_intermediate"
    assert uniform["cd8_hot_sample_fraction"] == 0.0
    assert bimodal["cd8_hot_sample_fraction"] == 0.5  # half the cohort is above the hot cut


def test_hot_sample_fraction_uses_the_same_cut_as_the_class():
    hot = summarize_immune_context(_cohort([CD8_FRACTION_HOT_MIN]))
    assert hot["cd8_hot_sample_fraction"] == 1.0  # inclusive at the cut, like the ladder


# ── S5: the suppressive side of the TME ──────────────────────────────────────
def test_cd8_treg_and_m2_ratios_are_emitted():
    s = summarize_immune_context(_cohort([0.15], treg=0.0137, m2=0.2380, m1=0.0337))
    assert s["cd8_treg_ratio"] == round(0.15 / 0.0137, 3)
    assert s["cd8_m2_ratio"] == round(0.15 / 0.2380, 3)
    assert s["median_treg_fraction"] == 0.0137
    assert s["median_m2_macrophage_fraction"] == 0.238
    assert s["median_m1_macrophage_fraction"] == 0.0337


def test_ratios_are_reproducible_from_the_published_medians():
    """The ratio of MEDIANS, not the median of per-sample ratios — so a reader can recompute it from
    the two fields printed beside it."""
    s = summarize_immune_context(_cohort([0.10, 0.20], treg=0.02))
    assert s["cd8_treg_ratio"] == round(s["median_cd8_fraction"] / s["median_treg_fraction"], 3)


def test_zero_suppressor_median_gives_none_not_infinity():
    """LM22 assigns an exact 0.0 to an absent subset, so a per-sample ratio can be infinite. An
    undefined ratio must not read as 'infinitely favourable'."""
    s = summarize_immune_context(_cohort([0.15], treg=0.0, m2=0.0))
    assert s["cd8_treg_ratio"] is None
    assert s["cd8_m2_ratio"] is None


def test_suppressor_columns_absent_from_the_frame_give_none():
    # the CIBERSORT product carries all 22 LM22 columns, but the reduction must not require them
    df = pd.DataFrame([{"T.cells.CD8": 0.15}] * MIN_N_SAMPLES)
    s = summarize_immune_context(df)
    assert s["immune_context_class"] == "immune_hot"
    assert s["cd8_treg_ratio"] is None and s["cd8_m2_ratio"] is None


def test_the_new_fields_do_not_move_the_class():
    """Additive by construction: the class is still a pure function of the median CD8 fraction (and
    the two fail-closed guards). A suppressive TME informs; it does not silently demote."""
    # both Treg denominators are ABOVE MIN_RATIO_DENOMINATOR_FRACTION, so this stays a test about the
    # class being insensitive to suppression and does not quietly become a test of the ratio floor.
    hot_clean = summarize_immune_context(_cohort([0.15], treg=0.006, m2=0.01))
    hot_suppressed = summarize_immune_context(_cohort([0.15], treg=0.10, m2=0.40))
    assert hot_clean["immune_context_class"] == hot_suppressed["immune_context_class"] == "immune_hot"
    assert hot_clean["cd8_treg_ratio"] > hot_suppressed["cd8_treg_ratio"]


def test_column_constants_match_the_lm22_names_in_the_t_cell_tuple():
    """Guards a typo in a hand-transcribed LM22 column name — the failure would be a silently None
    ratio, which looks exactly like 'this cohort has no Tregs'."""
    assert _cl.TREG_COLUMN in T_CELL_COLUMNS
    assert _cl.CD8_COLUMN in T_CELL_COLUMNS


# ── ratio denominator noise floor (2026-09-13, found by the 20-target panel) ──
def test_a_noise_floor_denominator_abstains_instead_of_reporting_a_176x_ratio():
    """The GBM row of the panel: cohort median Treg 0.0002 turned CD8:Treg into 176.0 in the one
    indication whose own class token says immune_cold, next to a 2.6-14 range everywhere else. A
    denominator at the deconvolution's noise floor is not a small denominator, it is an absent one."""
    s = summarize_immune_context(_cohort([0.0406], treg=0.0002, m2=0.5063))
    assert s["immune_context_class"] == "immune_cold"
    assert s["cd8_treg_ratio"] is None  # was 176.009
    assert s["median_treg_fraction"] == 0.0002  # the medians still SHOW why it abstained
    assert s["cd8_m2_ratio"] is not None  # the M2 denominator is real — only the Treg one abstains


def test_the_floor_does_not_touch_the_denominators_the_panel_actually_produced():
    """Non-vacuity partner: the floor must be BELOW every real read or it would silently delete the
    field. These are the two extremes of the measured panel (ESCA 0.0061, SKCM 0.0284)."""
    for treg, expected in ((0.0061, 13.8), (0.0284, 5.4)):
        s = summarize_immune_context(_cohort([0.0844 if treg < 0.01 else 0.1543], treg=treg, m2=0.2))
        assert s["cd8_treg_ratio"] is not None
        assert abs(s["cd8_treg_ratio"] - expected) < 0.5, (treg, s["cd8_treg_ratio"])


def test_the_floor_is_a_floor_not_a_zero_check():
    """Pins that the guard is MIN_RATIO_DENOMINATOR_FRACTION and not the old `<= 0`: a denominator just
    under the floor abstains, one just over it scores."""
    f = _cl.MIN_RATIO_DENOMINATOR_FRACTION
    assert summarize_immune_context(_cohort([0.15], treg=f * 0.99))["cd8_treg_ratio"] is None
    assert summarize_immune_context(_cohort([0.15], treg=f * 1.01))["cd8_treg_ratio"] is not None
