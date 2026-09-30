"""Regression (tumor-presence expert review, finding G8): read-time ambient-RNA (soup) risk flag.

Cell-free 'soup' mRNA is captured in every 10x droplet, leaking a dominant compartment's signal into all
others (~10% typical, SoupX Young & Behjati 2020). That can push a malignant detection fraction across
the subset floor into a spurious tumor-cell-intrinsic call. This is NOT decontamination (an upstream
SoupX/DecontX step in the pseudobulk build); it is a verdict-INERT flag that fires when a
malignant_subset_detected call's detection sits within the plausible-soup fraction of a much-more-detected
non-malignant compartment, so a consumer treats the tumor-cell-intrinsic attribution with caution.
"""

from __future__ import annotations

from onc_methods.sc_tumor_expression_celltype import stats as S


def _cs(mal_det, immune_det, n_cells=1000):
    cs = {
        "malignant": {
            "n_donors": 6,
            "n_cells_total": n_cells,
            "median_detection_fraction": mal_det,
            "median_abundance_log1p_cp10k": 1.0,
        }
    }
    if immune_det is not None:
        cs["immune"] = {
            "n_donors": 8,
            "n_cells_total": 5000,
            "median_detection_fraction": immune_det,
            "median_abundance_log1p_cp10k": 2.0,
        }
    return cs


def test_subset_within_soup_range_of_dominant_compartment_is_possible():
    # malignant 0.12 (just over the 0.10 subset floor) vs immune 0.9 → 0.12 <= 0.15*0.9=0.135 → possible
    r = S.classify_sc_expression(_cs(0.12, 0.9))
    assert r["sc_expression_class"] == "malignant_subset_detected"
    assert r["ambient_contamination_risk"] == "possible"


def test_subset_well_above_soup_range_is_low():
    # malignant 0.30 vs immune 0.9 → 0.30 > 0.135 → not soup-plausible → low
    r = S.classify_sc_expression(_cs(0.30, 0.9))
    assert r["sc_expression_class"] == "malignant_subset_detected"
    assert r["ambient_contamination_risk"] == "low"


def test_broadly_detected_is_not_flagged_even_if_other_compartment_higher():
    # malignant 0.6 (broadly detected, intrinsic) even with a higher immune compartment → low risk
    r = S.classify_sc_expression(_cs(0.6, 0.95))
    assert r["sc_expression_class"] == "malignant_broadly_detected"
    assert r["ambient_contamination_risk"] == "low"


def test_no_dominant_other_compartment_is_low():
    # malignant subset with no other compartment to leak from → low (nothing to attribute to soup)
    r = S.classify_sc_expression(_cs(0.12, None))
    assert r["ambient_contamination_risk"] == "low"


def test_data_unavailable_paths_carry_the_field():
    assert S.classify_sc_expression({})["ambient_contamination_risk"] == "data_unavailable"
    # underpowered (too few malignant cells) → data_unavailable class AND risk
    r = S.classify_sc_expression(_cs(0.12, 0.9, n_cells=50))
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["ambient_contamination_risk"] == "data_unavailable"
