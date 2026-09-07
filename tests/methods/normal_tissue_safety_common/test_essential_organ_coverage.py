"""CI guard for the shared essential-normal-organ set (cards review 2026-08-17, S1-3).

Prevents the three normal-tissue liability cards' essential/critical-organ lists from silently
diverging again — the divergence that let a thyroid/adrenal/vascular-toxic target (TSHR) read
`restricted_normal` and reach the surface-modality verdict as `both_viable`.

Enforces:
  1. SINGLE-SOURCE: each card's live essential set == the shared derived set.
  2. S1-3 COVERAGE: every source covers the endocrine/vascular/CNS organs its vocabulary supports.
  3. Each source's names are REAL (subset of that source's actual vocabulary), so no typo'd tissue
     name that can never match.
  4. The dead `ARTERY` GTEx entry is gone; SPLEEN stays out of canonical (held for review).
"""

from methods import normal_tissue_safety_common as eo


# --- 1. single-source: each card imports the shared set (identity / equality) ---


def test_gtex_stats_card_uses_shared_set():
    from methods.tcga_gtex_expression_distribution import stats

    assert set(stats.CRITICAL_NORMAL_TISSUES) == set(eo.GTEX_ESSENTIAL_TISSUES)


def test_hpa_card_uses_shared_set():
    from methods.hpa_normal_tissue_liability import cli

    assert set(cli.ESSENTIAL_TISSUES) == set(eo.HPA_ESSENTIAL_TISSUES)


def test_sc_normal_card_uses_shared_set():
    from methods.sc_normal_expression import read

    assert set(read.SAFETY_ESSENTIAL_TISSUES) == set(eo.SC_NORMAL_ESSENTIAL_TISSUES)


# --- 2. S1-3 coverage: endocrine/vascular/CNS organs a source can represent MUST be essential ---


def test_gtex_covers_required_endocrine_vascular_organs():
    req = eo.required_names(eo.GTEX_CROSSWALK)
    assert {"THYROID", "ADRENAL_GLAND", "PITUITARY", "BLOOD_VESSEL", "BRAIN"} <= req
    assert req <= set(eo.GTEX_ESSENTIAL_TISSUES)  # the S1-3 fix: all required organs covered


def test_hpa_covers_blood_vessel_and_flags_endocrine_substrate_gap():
    # HPA CAN represent vasculature (blood vessel) → it must be essential (was the code omission).
    assert "blood vessel" in eo.HPA_ESSENTIAL_TISSUES
    assert eo.required_names(eo.HPA_CROSSWALK) <= set(eo.HPA_ESSENTIAL_TISSUES)
    # HPA's 16-name field has NO thyroid/adrenal/pituitary — a documented substrate gap, so those
    # canonical organs crosswalk to None (must NOT be silently claimed as covered).
    for organ in ("thyroid", "adrenal_gland", "pituitary"):
        assert eo.HPA_CROSSWALK[organ] is None


def test_sc_normal_covers_brain_and_adrenal():
    assert "brain" in eo.SC_NORMAL_ESSENTIAL_TISSUES  # the advertised-but-unqueried CNS shard
    assert "adrenal_gland" in eo.SC_NORMAL_ESSENTIAL_TISSUES
    assert eo.required_names(eo.SC_NORMAL_CROSSWALK) <= set(eo.SC_NORMAL_ESSENTIAL_TISSUES)


# --- 3. names are real (subset of each source's actual vocabulary) ---


def test_gtex_names_are_real_gtex_tissues():
    # window.py's ESSENTIAL_GTEX_TISSUES is the known-good 15-name GTEx set; every name we emit must
    # be one of them (proves real recount3/GTEx labels AND that stats.py now aligns with the window
    # card — modulo SPLEEN, which the window card keeps and canonical holds).
    from methods.tcga_gtex_tpm_quantiles.window import ESSENTIAL_GTEX_TISSUES as WINDOW_SET

    assert set(eo.GTEX_ESSENTIAL_TISSUES) <= set(WINDOW_SET)
    assert "ARTERY" not in eo.GTEX_ESSENTIAL_TISSUES  # dead entry removed


def test_sc_normal_names_have_shards():
    # every always-on tissue must have a real single-cell normal shard.
    from methods.sc_normal_expression.read import TISSUE_TO_PRODUCT

    assert set(eo.SC_NORMAL_ESSENTIAL_TISSUES) <= set(TISSUE_TO_PRODUCT)


# --- 4. SPLEEN held out of canonical (documents the reserved decision) ---


def test_spleen_held_out_of_canonical():
    assert "spleen" not in eo.CANONICAL_VITAL_ORGANS
    # coverage-not-equality means a source MAY still list spleen (the GTEx window card does) without
    # violating the guard; this asserts we haven't quietly promoted it to canonical.
