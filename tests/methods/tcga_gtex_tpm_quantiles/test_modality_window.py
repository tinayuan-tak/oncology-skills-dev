"""tcga_gtex_tpm_quantiles.window — modality therapeutic-window scorer (pure, no S3, synthetic frames).

Pins the biologics clean-antigen window signal re-homed on the framework's TPM quantile product,
including the two deliberate corrections over the source repo's shipped scorer:
  - THEME-1: BOTH window_essential + window_full_normal emitted (TACSTD2-type non-essential dirtiness);
  - COHORT-HONESTY: near-zero tumor → not_expressed_in_cohort, never a false clean/dirty (DLL3-type).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_tpm_quantiles.window import (  # noqa: E402
    compute_window_from_rows, MODALITY_TIER_THRESHOLD, CLEAN_WINDOW_RATIO,
)


def _log2(tpm):  # helper: linear TPM -> the product's stored log2(TPM+1)
    return math.log2(tpm + 1.0)


def _rows(tumor: dict, normal: dict):
    """tumor: {study: linear_tpm}; normal: {gtex_group: linear_tpm} -> quantile-shaped DataFrame."""
    recs = []
    for study, tpm in tumor.items():
        recs.append({"source": "tcga_tumor", "group": study, "median": _log2(tpm)})
    for grp, tpm in normal.items():
        recs.append({"source": "gtex_normal", "group": grp, "median": _log2(tpm)})
    return pd.DataFrame(recs)


# ── the CEACAM5 archetype: huge window, still a strict-TCE liability ──────────
def test_ceacam5_like_strict_liability_but_adc_clean():
    rows = _rows({"COAD": 1878.0}, {"LUNG": 3.3, "COLON": 7.4, "SKIN": 1.0})
    strict = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    adc = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["adc"])
    # strict (1.0): lung 3.3 >= 1.0 → essential-tissue liability, despite the enormous ratio
    assert strict["window_class"] == "essential_tissue_liability"
    assert strict["window_ratio_essential"] > 100      # ~440x — the ratio is huge
    assert strict["max_essential_normal_organ"] == "LUNG"
    # moderate/ADC (5.0): lung 3.3 < 5.0 → clean at the ADC tier (the ADC-vs-TCE discriminator)
    assert adc["window_class"] == "clean_window"


# ── CLDN6 oncofetal: clean across all tiers ──────────────────────────────────
def test_cldn6_like_clean_window():
    rows = _rows({"OV": 34.9}, {"BONE_MARROW": 0.49, "BRAIN": 0.2})
    r = compute_window_from_rows(rows, "OV", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_class"] == "clean_window"
    assert r["window_ratio_essential"] >= CLEAN_WINDOW_RATIO


# ── THEME-1 FIX: TACSTD2-type — clean vs essential, DIRTY in a non-essential tissue ──
def test_theme1_full_normal_denominator_exposes_nonessential_dirtiness():
    # tumor modest; essential organs all low (would look clean essential-only), but SKIN (non-essential)
    # is very high — the essential-only ratio hides it; the full-normal ratio must expose it.
    rows = _rows({"COAD": 40.0},
                 {"LUNG": 1.0, "HEART": 0.5, "SKIN": 500.0, "SALIVARY_GLAND": 460.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["adc"])
    # essential-only: max essential = LUNG 1.0 < 5.0 → no essential liability; ratio ~20x → clean
    assert r["window_class"] == "clean_window"
    assert r["window_ratio_essential"] > 10
    # BUT the full-normal denominator catches SKIN → a << 1 full-normal ratio the reader MUST surface
    assert r["max_full_normal_organ"] == "SKIN"
    assert r["window_ratio_full_normal"] < 1.0
    # the two ratios DIVERGE by >10x — the exact signal the essential-only scorer would hide
    assert r["window_ratio_essential"] / r["window_ratio_full_normal"] > 10
    # axis-B companion (2026-08-08 selectivity review): therapeutic_window_class (essential-only) is
    # clean, but the full-normal companion must flag the non-essential breadth as a veto candidate.
    assert r["therapeutic_window_class"] == "clean_window"          # essential-only: still clean (unchanged)
    assert r["full_normal_window_class"] == "no_full_normal_window" # pan-normal: SKIN breadth caught


# ── AXIS-B companion class (2026-08-08 selectivity review): full_normal_window_class ──
def test_full_normal_window_class_clean_when_low_across_whole_atlas():
    # CLDN6 oncofetal: low in EVERY normal (essential AND non-essential) → clean on both axes.
    rows = _rows({"OV": 34.9}, {"BONE_MARROW": 0.49, "BRAIN": 0.2, "SKIN": 0.3})
    r = compute_window_from_rows(rows, "OV", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["full_normal_window_class"] == "clean_full_normal_window"
    assert r["therapeutic_window_class"] == "clean_window"          # both axes agree → genuinely clean


def test_full_normal_window_class_narrow_band():
    # tumor 40, worst full-normal 12 → ratio ~3.2 ∈ [1,5): narrow (real but modest) pan-normal window.
    rows = _rows({"COAD": 40.0}, {"LUNG": 1.0, "COLON": 12.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["adc"])
    assert 1.0 <= r["window_ratio_full_normal"] < 5.0
    assert r["full_normal_window_class"] == "narrow_full_normal_window"


def test_full_normal_window_class_not_expressed_mirrors_therapeutic():
    rows = _rows({"LUAD": 0.3}, {"PITUITARY": 3.9, "SKIN": 1.0})
    r = compute_window_from_rows(rows, "LUAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["full_normal_window_class"] == "not_expressed_in_cohort"


# ── COHORT-HONESTY: DLL3-in-LUAD near-zero tumor → not a candidate call, not "clean" ──
def test_cohort_honesty_near_zero_tumor_is_not_expressed_not_clean():
    rows = _rows({"LUAD": 0.3}, {"PITUITARY": 3.9, "BRAIN": 1.0})
    r = compute_window_from_rows(rows, "LUAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_class"] == "not_expressed_in_cohort"   # NOT essential_tissue_liability, NOT clean


def test_indication_with_no_tumor_rows_is_data_unavailable():
    # target measured in normal only, or the indication's studies absent → data_unavailable (cohort gap)
    rows = _rows({"BRCA": 50.0}, {"LUNG": 1.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_class"] == "data_unavailable"
    assert "_data_note" in r


def test_unmapped_indication_is_data_unavailable():
    rows = _rows({"COAD": 100.0}, {"LUNG": 1.0})
    r = compute_window_from_rows(rows, "NOT_AN_INDICATION", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_class"] == "data_unavailable"


def test_empty_rows_is_data_unavailable():
    assert compute_window_from_rows(pd.DataFrame(), "COADREAD")["window_class"] == "data_unavailable"
    assert compute_window_from_rows(None, "COADREAD")["window_class"] == "data_unavailable"


# ── narrow window: expressed, no essential liability, but ratio below the clean bar ──
def test_narrow_window_when_ratio_subthreshold():
    # tumor 8, max essential 5 (below strict? no — use antibody tier 10 so no liability), ratio ~1.5x
    rows = _rows({"COAD": 8.0}, {"LUNG": 5.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["antibody"])  # tier 10
    assert r["window_class"] == "narrow_window"       # lung 5 < 10 (no liability) but ratio < 4x
    assert r["window_ratio_essential"] < CLEAN_WINDOW_RATIO


def test_multi_study_indication_takes_max_tumor():
    # COADREAD = COAD + READ; target high in COAD, low in READ → numerator uses the max (COAD)
    rows = _rows({"COAD": 200.0, "READ": 2.0}, {"LUNG": 0.5})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["tumor_tpm"] == pytest.approx(200.0, rel=0.01)
    assert r["window_class"] == "clean_window"


# ── therapeutic_window_class: the PURELY RATIO-BASED re-tier (selectivity veto instrument, INC-1/2) ──
# The legacy window_class collapses high-ratio genes (CEACAM5 558x) into essential_tissue_liability
# alongside housekeeping genes (0.5x); therapeutic_window_class keys on the RATIO only, so it
# separates them (backtest-validated: housekeeping <1 = no_therapeutic_window; antigens >1 = window).
from methods.tcga_gtex_tpm_quantiles.window import (  # noqa: E402
    THERAPEUTIC_WINDOW_CLEAN_RATIO, THERAPEUTIC_WINDOW_MIN_RATIO,
)


def test_therapeutic_window_class_clean_high_ratio():
    # CEACAM5-like huge ratio → clean_window on therapeutic_window_class (even though legacy = liability)
    rows = _rows({"COAD": 1878.0}, {"LUNG": 3.3, "COLON": 7.4})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["therapeutic_window_class"] == "clean_window"
    assert r["window_class"] == "essential_tissue_liability"   # legacy UNCHANGED (byte-stable)


def test_therapeutic_window_class_no_window_housekeeping():
    # housekeeping signature: tumor BELOW the worst critical normal → ratio < 1 → the VETO value
    rows = _rows({"COAD": 40.0}, {"MUSCLE": 90.0, "COLON": 50.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_ratio_essential"] < 1.0
    assert r["therapeutic_window_class"] == "no_therapeutic_window"


def test_therapeutic_window_class_narrow_between_1_and_5():
    rows = _rows({"COAD": 30.0}, {"LUNG": 12.0})   # ratio ~ (30+1)/(12+1) = 2.4
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert THERAPEUTIC_WINDOW_MIN_RATIO <= r["window_ratio_essential"] < THERAPEUTIC_WINDOW_CLEAN_RATIO
    assert r["therapeutic_window_class"] == "narrow_window"


def test_therapeutic_window_class_not_expressed_guard():
    rows = _rows({"COAD": 0.3}, {"LUNG": 0.1})   # tumor below expression floor
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["therapeutic_window_class"] == "not_expressed_in_cohort"
