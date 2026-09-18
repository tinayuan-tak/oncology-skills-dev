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
    CLEAN_WINDOW_RATIO,
    MODALITY_TIER_THRESHOLD,
    compute_window_from_rows,
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
    """The MODALITY-TIER discriminator, which is this test's actual subject: one normal organ sitting
    BETWEEN the two tiers separates a strict-TCE liability from a clean ADC.

    The fixture no longer carries COLON. It used to (7.4 TPM, placed there as a NON-essential tissue),
    and the 2026-09-18 `gut` promotion made COLON essential — at 7.4 it clears the ADC tier (5.0) too,
    so BOTH arms flagged and the discriminator this test exists to prove became untestable here. The
    gut behaviour is not lost: it is pinned as its own case below, which is the honest split, because
    the tier discriminator and the gut-organ semantics are independent claims and a fixture that
    conflates them can only test one."""
    rows = _rows({"COAD": 1878.0}, {"LUNG": 3.3, "SKIN": 1.0})
    strict = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    adc = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["adc"])
    # strict (1.0): lung 3.3 >= 1.0 → essential-tissue liability, despite the enormous ratio
    assert strict["window_class"] == "essential_tissue_liability"
    assert strict["window_ratio_essential"] > 100  # ~569x — the ratio is huge
    assert strict["max_essential_normal_organ"] == "LUNG"
    # moderate/ADC (5.0): lung 3.3 < 5.0 → clean at the ADC tier (the ADC-vs-TCE discriminator)
    assert adc["window_class"] == "clean_window"


def test_normal_colon_is_an_essential_liability_at_both_tiers_for_a_gi_indication():
    """The gut half of the archetype above, pinned separately (2026-09-18 `gut` promotion).

    Normal colonic CEACAM5 at 7.4 TPM clears BOTH the strict (1.0) and the ADC (5.0) tier, so a
    CEACAM5-like antigen is an essential-tissue liability for a colorectal indication at every
    modality tier — which is the biologically correct answer, and the reason CEACAM5 ADCs carry GI
    toxicity rather than being spared by the tier.

    Note COLON here is the tumour's OWN ORIGIN organ, and it still counts. That is deliberate and
    documented at `window.py`'s ESSENTIAL_GTEX_TISSUES: the set is indication-INDEPENDENT and includes
    the origin (LUNG for LUAD, LIVER for LIHC), because you cannot spare the origin organ, and the
    sc-normal veto arm defers the origin call to exactly here. So this is the same rule that already
    governed LUNG-for-LUAD, now reaching the gut — not a new exception for it."""
    rows = _rows({"COAD": 1878.0}, {"LUNG": 3.3, "COLON": 7.4, "SKIN": 1.0})
    for tier in ("bite_tce", "adc"):
        r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD[tier])
        assert r["window_class"] == "essential_tissue_liability", tier
        # COLON (7.4), not LUNG (3.3), is the named driver — the max over the essential set moved.
        assert r["max_essential_normal_organ"] == "COLON", tier
        assert r["max_essential_normal_tpm"] == pytest.approx(7.4, abs=0.01), tier
    # CONTROL: the SAME fixture without the gut organ is clean at the ADC tier, so the flag above is
    # attributable to COLON specifically and not to the tumour value or the tier.
    no_gut = compute_window_from_rows(
        _rows({"COAD": 1878.0}, {"LUNG": 3.3, "SKIN": 1.0}), "COADREAD", MODALITY_TIER_THRESHOLD["adc"]
    )
    assert no_gut["window_class"] == "clean_window"


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
    rows = _rows({"COAD": 40.0}, {"LUNG": 1.0, "HEART": 0.5, "SKIN": 500.0, "SALIVARY_GLAND": 460.0})
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
    assert r["therapeutic_window_class"] == "clean_window"  # essential-only: still clean (unchanged)
    assert r["full_normal_window_class"] == "no_full_normal_window"  # pan-normal: SKIN breadth caught


# ── AXIS-B companion class (2026-08-08 selectivity review): full_normal_window_class ──
def test_full_normal_window_class_clean_when_low_across_whole_atlas():
    # CLDN6 oncofetal: low in EVERY normal (essential AND non-essential) → clean on both axes.
    rows = _rows({"OV": 34.9}, {"BONE_MARROW": 0.49, "BRAIN": 0.2, "SKIN": 0.3})
    r = compute_window_from_rows(rows, "OV", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["full_normal_window_class"] == "clean_full_normal_window"
    assert r["therapeutic_window_class"] == "clean_window"  # both axes agree → genuinely clean


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
    assert r["window_class"] == "not_expressed_in_cohort"  # NOT essential_tissue_liability, NOT clean


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
    assert r["window_class"] == "narrow_window"  # lung 5 < 10 (no liability) but ratio < 4x
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
    THERAPEUTIC_WINDOW_CLEAN_RATIO,
    THERAPEUTIC_WINDOW_MIN_RATIO,
)


def test_therapeutic_window_class_clean_high_ratio():
    # CEACAM5-like huge ratio → clean_window on therapeutic_window_class (even though legacy = liability)
    rows = _rows({"COAD": 1878.0}, {"LUNG": 3.3, "COLON": 7.4})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["therapeutic_window_class"] == "clean_window"
    assert r["window_class"] == "essential_tissue_liability"  # legacy UNCHANGED (byte-stable)


def test_therapeutic_window_class_no_window_housekeeping():
    # housekeeping signature: tumor BELOW the worst critical normal → ratio < 1 → the VETO value
    rows = _rows({"COAD": 40.0}, {"MUSCLE": 90.0, "COLON": 50.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["window_ratio_essential"] < 1.0
    assert r["therapeutic_window_class"] == "no_therapeutic_window"


def test_therapeutic_window_class_narrow_between_1_and_5():
    rows = _rows({"COAD": 30.0}, {"LUNG": 12.0})  # ratio ~ (30+1)/(12+1) = 2.4
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert THERAPEUTIC_WINDOW_MIN_RATIO <= r["window_ratio_essential"] < THERAPEUTIC_WINDOW_CLEAN_RATIO
    assert r["therapeutic_window_class"] == "narrow_window"


def test_therapeutic_window_class_not_expressed_guard():
    rows = _rows({"COAD": 0.3}, {"LUNG": 0.1})  # tumor below expression floor
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["therapeutic_window_class"] == "not_expressed_in_cohort"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# SUBSTRATE CORRECTIONS (2026-09-12 denominator audit). Every test below FAILS on the pre-fix
# scorer — the pre-existing suite could not detect either change because its synthetic frames
# never made BONE_MARROW or TESTIS the argmax.
# ══════════════════════════════════════════════════════════════════════════════════════════════
from methods.tcga_gtex_tpm_quantiles.marrow import (  # noqa: E402
    MARROW_ORGAN_LABEL,
    SUBSTRATE_GENE_ABSENT,
    SUBSTRATE_PRIMARY,
    SUBSTRATE_UNAVAILABLE,
)
from methods.tcga_gtex_tpm_quantiles.window import (  # noqa: E402
    CELL_LINE_GTEX_GROUPS,
    ESSENTIAL_GTEX_TISSUES,
    PRIVILEGED_NORMAL_SITES,
)


# ── 1. the K-562 label: excluded as SUBSTRATE, still named as an essential ORGAN ──────────────
def test_bone_marrow_is_an_essential_organ_but_not_a_valid_substrate():
    """The two sets are deliberately overlapping: marrow IS life-critical (so the shared canonical
    vital-organ crosswalk keeps it), but the product's GTEx rows for it are a cell line."""
    assert "BONE_MARROW" in ESSENTIAL_GTEX_TISSUES  # policy: marrow is essential
    assert "BONE_MARROW" in CELL_LINE_GTEX_GROUPS  # substrate: these rows are K-562
    assert "TESTIS" not in ESSENTIAL_GTEX_TISSUES  # privileged-site scoping is full-normal-ONLY


def test_gtex_bone_marrow_rows_can_never_set_the_essential_denominator():
    # K-562 signature: absurdly high (HBG1 reads 11,161 TPM there). Pre-fix this was the argmax and
    # drove the ratio to ~0.02 → no_therapeutic_window. It must now be invisible to both denominators.
    rows = _rows({"COAD": 200.0}, {"BONE_MARROW": 9000.0, "LUNG": 1.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["max_essential_normal_organ"] == "LUNG"
    assert r["max_essential_normal_tpm"] == pytest.approx(1.0, rel=0.01)
    assert r["therapeutic_window_class"] == "clean_window"  # was no_therapeutic_window pre-fix
    assert r["excluded_cell_line_groups"] == ["BONE_MARROW"]


def test_gtex_bone_marrow_rows_can_never_set_the_full_normal_denominator():
    rows = _rows({"COAD": 200.0}, {"BONE_MARROW": 9000.0, "SKIN": 3.0})
    r = compute_window_from_rows(rows, "COADREAD", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["max_full_normal_organ"] == "SKIN"
    assert r["full_normal_window_class"] == "clean_full_normal_window"
    # ...and not smuggled in through the privileged-site companion either
    assert r["max_full_normal_organ_incl_privileged"] == "SKIN"
    assert r["n_gtex_tissues"] == 1  # SKIN only — BONE_MARROW is not counted as a tissue


# ── 2. the repoint: primary marrow, injected, DOES gate ───────────────────────────────────────
def test_primary_marrow_sets_the_essential_denominator_when_it_is_the_worst_organ():
    """The CLEC12A/AML archetype: window 4.55 on K-562 → 0.76 on primary marrow (nTPM 75.3).
    This is the liability the cell-line substrate hid, and it must now bite."""
    rows = _rows({"BRCA": 55.0}, {"LUNG": 1.0, "BONE_MARROW": 0.1})
    r = compute_window_from_rows(
        rows,
        "BRCA",
        MODALITY_TIER_THRESHOLD["bite_tce"],
        marrow_tpm=75.3,
        marrow_substrate=SUBSTRATE_PRIMARY,
    )
    assert r["max_essential_normal_organ"] == MARROW_ORGAN_LABEL
    assert r["max_essential_normal_tpm"] == pytest.approx(75.3, rel=0.01)
    assert r["window_ratio_essential"] < 1.0
    assert r["therapeutic_window_class"] == "no_therapeutic_window"
    assert r["marrow_tpm"] == pytest.approx(75.3, rel=0.01)
    assert r["marrow_substrate"] == SUBSTRATE_PRIMARY
    assert r["n_essential_organs"] == 2  # LUNG + BONE_MARROW_PRIMARY (the K-562 rows do not count)


def test_primary_marrow_also_enters_the_full_normal_denominator():
    rows = _rows({"BRCA": 55.0}, {"LUNG": 1.0, "SKIN": 2.0})
    r = compute_window_from_rows(
        rows,
        "BRCA",
        MODALITY_TIER_THRESHOLD["bite_tce"],
        marrow_tpm=75.3,
        marrow_substrate=SUBSTRATE_PRIMARY,
    )
    assert r["max_full_normal_organ"] == MARROW_ORGAN_LABEL
    assert r["full_normal_window_class"] == "no_full_normal_window"


def test_primary_marrow_participates_in_the_absolute_modality_tier_gate():
    """Not only the ratio: marrow must be able to trip the legacy absolute-tier liability call."""
    rows = _rows({"BRCA": 5000.0}, {"LUNG": 0.1})
    r = compute_window_from_rows(
        rows,
        "BRCA",
        MODALITY_TIER_THRESHOLD["adc"],  # tier 5.0
        marrow_tpm=30.6,
        marrow_substrate=SUBSTRATE_PRIMARY,  # CD33-like
    )
    assert r["window_class"] == "essential_tissue_liability"  # marrow 30.6 >= 5.0
    assert r["therapeutic_window_class"] == "clean_window"  # ratio is still huge — both are true


def test_marrow_organ_label_is_distinguishable_from_the_discredited_gtex_group():
    """An archived run must be attributable to a substrate. `BONE_MARROW_PRIMARY` != `BONE_MARROW`."""
    assert MARROW_ORGAN_LABEL != "BONE_MARROW"
    assert MARROW_ORGAN_LABEL not in ESSENTIAL_GTEX_TISSUES


# ── 3. absent marrow is HONEST, never a silent zero ───────────────────────────────────────────
def test_absent_marrow_substrate_is_never_scored_as_zero():
    """marrow == 0 would read as a CLEAN window on the framework's most safety-critical organ. An
    unavailable substrate must instead shrink the declared organ count and say so."""
    rows = _rows({"BRCA": 55.0}, {"LUNG": 1.0})
    r = compute_window_from_rows(rows, "BRCA", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["marrow_tpm"] is None  # NOT 0.0
    assert r["marrow_substrate"] == SUBSTRATE_UNAVAILABLE
    assert r["n_essential_organs"] == 1  # LUNG only — the shortfall is VISIBLE
    assert r["max_essential_normal_organ"] == "LUNG"


def test_definitive_marrow_absence_is_reported_distinctly_from_a_read_failure():
    rows = _rows({"BRCA": 55.0}, {"LUNG": 1.0})
    absent = compute_window_from_rows(
        rows, "BRCA", marrow_substrate=SUBSTRATE_GENE_ABSENT, marrow_note="not in HPA consensus"
    )
    assert absent["marrow_substrate"] == SUBSTRATE_GENE_ABSENT
    assert absent["_marrow_note"] == "not in HPA consensus"
    assert absent["marrow_substrate"] != SUBSTRATE_UNAVAILABLE  # transient vs definitive, not fused


def test_data_unavailable_still_carries_the_substrate_provenance():
    r = compute_window_from_rows(pd.DataFrame(), "COADREAD")
    assert r["marrow_substrate"] == SUBSTRATE_UNAVAILABLE
    assert r["excluded_cell_line_groups"] == ["BONE_MARROW"]
    assert r["privileged_normal_sites_excluded"] == ["TESTIS"]


# ── 4. TESTIS: out of the pan-normal KILL denominator, still fully reported ────────────────────
def test_testis_does_not_gate_the_full_normal_kill():
    """The cancer-testis antigen archetype (CTAG1B/NY-ESO-1 full-normal 0.17, MAGEA4 0.04, PRAME
    0.28 — all testis-driven). Testis sits behind the blood-testis barrier: real, reported, but
    not dose-limiting the way liver/marrow are, so it must not mint the pan-normal KILL."""
    rows = _rows({"SKCM": 30.0}, {"TESTIS": 400.0, "LUNG": 0.5, "SKIN": 1.0})
    r = compute_window_from_rows(rows, "SKCM", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["max_full_normal_organ"] == "SKIN"  # NOT TESTIS
    assert r["window_ratio_full_normal"] > 5.0
    assert r["full_normal_window_class"] == "clean_full_normal_window"  # was no_full_normal_window


def test_testis_is_still_reported_both_ways():
    """ "Excluded from the KILL denominator, still report it" — the excluded value and the window it
    WOULD have produced are both emitted, so nothing is hidden from the card or the narrative."""
    rows = _rows({"SKCM": 30.0}, {"TESTIS": 400.0, "LUNG": 0.5, "SKIN": 1.0})
    r = compute_window_from_rows(rows, "SKCM", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["privileged_normal_sites_excluded"] == ["TESTIS"]
    assert r["privileged_normal_tpm"]["TESTIS"] == pytest.approx(400.0, rel=0.01)
    assert r["max_full_normal_organ_incl_privileged"] == "TESTIS"
    assert r["max_full_normal_tpm_incl_privileged"] == pytest.approx(400.0, rel=0.01)
    assert r["window_ratio_full_normal_incl_privileged"] < 1.0  # the suppressed KILL is auditable


def test_testis_exclusion_does_not_touch_the_essential_window():
    """TESTIS was never in the essential set, so window_ratio_essential must be byte-identical."""
    rows = _rows({"SKCM": 30.0}, {"TESTIS": 400.0, "LUNG": 0.5})
    r = compute_window_from_rows(rows, "SKCM", MODALITY_TIER_THRESHOLD["bite_tce"])
    assert r["max_essential_normal_organ"] == "LUNG"
    assert r["window_ratio_essential"] == pytest.approx((30.0 + 1.0) / (0.5 + 1.0), rel=0.01)


def test_privileged_exclusion_cannot_hide_a_non_privileged_liability():
    """Guard against over-reach: TROP2's salivary/skin liability must still mint the pan-normal KILL
    even when testis is higher still. The exclusion removes ONE site, not the arm's teeth."""
    rows = _rows({"BRCA": 40.0}, {"TESTIS": 900.0, "SALIVARY_GLAND": 460.0, "LUNG": 1.0})
    r = compute_window_from_rows(rows, "BRCA", MODALITY_TIER_THRESHOLD["adc"])
    assert r["max_full_normal_organ"] == "SALIVARY_GLAND"
    assert r["full_normal_window_class"] == "no_full_normal_window"


def test_privileged_set_is_exactly_testis():
    """Scope pin: this decision covered TESTIS only. Adding a site here is a verdict-moving change
    that needs its own measurement, so the set is asserted exactly, not just for membership."""
    assert PRIVILEGED_NORMAL_SITES == frozenset({"TESTIS"})
