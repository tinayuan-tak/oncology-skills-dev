"""Mutation-teeth for the MEASURED-ABSENCE power gate in presence_claims (issue #1743).

Two claims could emit a confident measured-negative (`absent`/`negative`) from an under-powered study,
violating the gap!=absent discipline (claim_vector_core.SIGNAL_ORD: unmeasured/underpowered -> None):

  * Claim C (`_claim_C`): `broadly_low` -> absent and `microenvironment_dominant` -> negative used the
    single-cell donor count only for corroboration, never as a gate. A thin sc study asserted absence.
  * Claim D (`_claim_D`): `not_tumor_elevated` -> absent even when the breadth was tested over a handful
    of cohorts. The `unmeasured` path only fired for a sentinel breadth class, not for thin n.

The fix gates the confident negative behind a power floor (single-source in presence_tiers.py):
  * Claim C: sc_malignant_n_donors >= MIN_RELIABLE_DONORS(5) AND sc_malignant_n_cells >=
    MIN_MALIGNANT_CELLS_TOTAL(100); else -> `underpowered`. Missing/non-finite n reads under-powered.
  * Claim D: n_tested >= BREADTH_ABSENCE_N_FLOOR(5); else -> `underpowered`.

DISCIPLINE:
  * We store the RAW headline INPUTS and RE-DERIVE the claim through presence_claim_vector — never
    fixture a derived claim value (a derived fixture can never fail).
  * Mutation direction: the low-power cases assert `underpowered` — pre-fix these were `absent`/`negative`
    (RED before the fix, GREEN after). The just-ABOVE-floor and positive-class cases assert the confident
    value is UNCHANGED — they guard against over-gating and fail only if the confident path is broken.
    Proof of RED pre-fix is recorded in the PR (running this file against pre-fix `main` reds exactly the
    low-power asserts and leaves the confident-path asserts green).
"""

from __future__ import annotations

import math

from _skills_common.presence_claims import presence_claim_vector  # noqa: E402

# ── Claim C: single-cell malignant-intrinsic measured-absence ────────────────────────────────────


def _c(cls, n_donors=None, n_cells=None):
    """RAW single-cell headline inputs; re-derive Claim C in-test (never fixture the claim value)."""
    hl = {
        "sc_expression_class": cls,
        "sc_malignant_detection_fraction": 0.02,
    }
    if n_donors is not None:
        hl["sc_malignant_n_donors"] = n_donors
    if n_cells is not None:
        hl["sc_malignant_n_cells"] = n_cells
    return presence_claim_vector(hl, [])["C"]


def test_claim_c_broadly_low_underpowered_when_donors_below_floor():
    # 4 donors (< MIN_RELIABLE_DONORS=5), cells adequate -> cannot assert absence. Pre-fix: "absent".
    assert _c("broadly_low", n_donors=4, n_cells=5000)["signal"] == "underpowered"


def test_claim_c_broadly_low_underpowered_when_cells_below_floor():
    # 50 donors (adequate) but only 99 malignant cells (< MIN_MALIGNANT_CELLS_TOTAL=100). Pre-fix "absent".
    assert _c("broadly_low", n_donors=50, n_cells=99)["signal"] == "underpowered"


def test_claim_c_microenvironment_dominant_underpowered_when_thin():
    # `microenvironment_dominant` -> negative is likewise a measured negative; thin study cannot assert it.
    assert _c("microenvironment_dominant", n_donors=3, n_cells=40)["signal"] == "underpowered"


def test_claim_c_missing_n_is_underpowered():
    # A MISSING donor/cell count is UNDER-powered, not silently-passing (feedback_nonfinite_sentinel).
    assert _c("broadly_low")["signal"] == "underpowered"
    assert _c("broadly_low", n_donors=200)["signal"] == "underpowered"  # cells missing
    assert _c("broadly_low", n_cells=5000)["signal"] == "underpowered"  # donors missing


def test_claim_c_nonfinite_n_is_underpowered():
    # +Inf/nan are NUMBERS: pd.isna(Inf) is False and Inf >= 100 is True, so a bare >= would admit them.
    for bad in (math.inf, float("nan")):
        assert _c("broadly_low", n_donors=bad, n_cells=5000)["signal"] == "underpowered"
        assert _c("broadly_low", n_donors=200, n_cells=bad)["signal"] == "underpowered"


def test_claim_c_broadly_low_stays_absent_at_the_floor():
    # NEGATIVE-DIRECTION guard (over-gating): EXACTLY at both floors (5 donors, 100 cells) the confident
    # `absent` must still emit. Fails only if the boundary is set wrong (e.g. `>` instead of `>=`).
    d = _c("broadly_low", n_donors=5, n_cells=100)
    assert d["signal"] == "absent"


def test_claim_c_microenvironment_dominant_stays_negative_when_powered():
    d = _c("microenvironment_dominant", n_donors=200, n_cells=500000)
    assert d["signal"] == "negative"


def test_claim_c_underpowered_signal_carries_underpowered_corroboration():
    # A gated negative carries no measured corroboration rung (off-scale, matching the signal).
    assert _c("broadly_low", n_donors=4, n_cells=5000)["corroboration"] == "underpowered"


def test_claim_c_positive_class_is_not_power_gated():
    # NEGATIVE-DIRECTION guard: the gate touches ONLY the absence classes. A positive detection with a
    # thin donor count keeps its positive signal (its thin-ness shows in corroboration, not the signal).
    assert _c("malignant_broadly_detected", n_donors=2, n_cells=10)["signal"] == "strong"
    assert _c("malignant_subset_detected", n_donors=2, n_cells=10)["signal"] == "weak"


# ── Claim D: breadth (generality) measured-absence ───────────────────────────────────────────────


def _d(breadth_cls, n_cohorts=None, n_indications=None):
    """RAW breadth headline inputs; re-derive Claim D in-test."""
    hl = {"tumor_elevation_breadth_class": breadth_cls}
    if n_cohorts is not None:
        hl["tumor_elevation_n_cohorts_tested"] = n_cohorts
    if n_indications is not None:
        hl["rna_tumor_elevation_n_indications_tested"] = n_indications
    return presence_claim_vector(hl, [])["D"]


def test_claim_d_not_tumor_elevated_underpowered_below_floor():
    # 4 cohorts (< BREADTH_ABSENCE_N_FLOOR=5) cannot support "elevated in NO cohort". Pre-fix: "absent".
    assert _d("not_tumor_elevated", n_cohorts=4)["signal"] == "underpowered"


def test_claim_d_not_tumor_elevated_underpowered_carries_underpowered_corroboration():
    assert _d("not_tumor_elevated", n_cohorts=4)["corroboration"] == "underpowered"


def test_claim_d_not_tumor_elevated_thin_via_rna_indications_underpowered():
    # n_tested is max(cohorts, rna-indications); a thin RNA-only roster is equally under-powered.
    assert _d("not_tumor_elevated", n_indications=2)["signal"] == "underpowered"


def test_claim_d_nonfinite_n_tested_is_underpowered():
    # Inf/nan cohort count must NOT read as adequately powered (feedback_nonfinite_sentinel).
    for bad in (math.inf, float("nan")):
        assert _d("not_tumor_elevated", n_cohorts=bad)["signal"] == "underpowered"


def test_claim_d_not_tumor_elevated_stays_absent_at_the_floor():
    # NEGATIVE-DIRECTION guard (over-gating): EXACTLY at the floor (5 cohorts) the confident `absent`
    # must still emit, with the moderate corroboration rung. Fails only if the boundary is set wrong.
    d = _d("not_tumor_elevated", n_cohorts=5)
    assert d["signal"] == "absent"
    assert d["corroboration"] == "moderate"


def test_claim_d_not_tumor_elevated_stays_absent_well_above_floor():
    d = _d("not_tumor_elevated", n_cohorts=26)
    assert d["signal"] == "absent"
    assert d["corroboration"] == "high"


def test_claim_d_positive_breadth_is_not_power_gated():
    # NEGATIVE-DIRECTION guard: the gate touches ONLY `not_tumor_elevated`. A positive breadth class
    # with a thin roster keeps its positive signal (thin-ness shows in corroboration).
    assert _d("multi_tumor_elevated", n_cohorts=1)["signal"] == "moderate"
    assert _d("broadly_tumor_elevated", n_cohorts=1)["signal"] == "strong"
