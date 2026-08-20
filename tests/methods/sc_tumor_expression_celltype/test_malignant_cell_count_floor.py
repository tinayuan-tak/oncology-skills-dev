"""Regression (tumor-presence expert review, finding G3): the single-cell reliability floor must gate
on malignant CELLS, not only DONOR count.

Bug: `classify_sc_expression` abstained only when `malignant_n_donors < MIN_RELIABLE_DONORS (5)`, and
`compartment_summary` computed each donor's detection_fraction as an unweighted mean with NO minimum-
cells-per-donor filter (n_cells was summed for display only). So a pooled cube with single-digit cells
per donor — the pan-renal KIRC (~74 total malignant cells) and pan-gynecologic OV (~106) 3CA cubes —
could clear the >=5-donor floor and emit a confident `malignant_broadly_detected` call indistinguishable
from the ~509k-malignant-cell COADREAD read.

Fix: (1) drop (dataset, donor) strata with < MIN_CELLS_PER_DONOR (20) cells BEFORE the cross-donor
median/IQR; (2) abstain (data_unavailable) when the reliable malignant compartment has
< MIN_MALIGNANT_CELLS_TOTAL (100) cells; (3) surface `malignant_n_cells`.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(REPO))
from methods.sc_tumor_expression_celltype import stats as S  # noqa: E402


def _rows(spec):
    """spec: (compartment, dataset_id, donor_id, n_cells, detection_fraction, abundance)."""
    return [{"gene_symbol": "EPCAM", "compartment": c, "dataset_id": ds, "donor_id": d,
             "n_cells": n, "detection_fraction": det, "abundance_log1p_cp10k": ab}
            for (c, ds, d, n, det, ab) in spec]


# --- per-donor cell floor in compartment_summary ----------------------------

def test_compartment_summary_drops_sub_floor_donors():
    """A donor with < MIN_CELLS_PER_DONOR cells is dropped before the cross-donor median. Two 3-cell
    donors (each detection 0.0) must NOT drag down a 500-cell donor at 0.9 — they are unreliable."""
    rows = _rows([
        ("malignant", "dsA", "big",  500, 0.9, 3.0),
        ("malignant", "dsB", "tiny1", 3, 0.0, 0.0),
        ("malignant", "dsC", "tiny2", 4, 0.0, 0.0),
    ])
    cs = S.compartment_summary(rows)
    assert cs["malignant"]["n_donors"] == 1                    # only the 500-cell donor survives
    assert cs["malignant"]["n_donors_dropped_low_cells"] == 2
    assert cs["malignant"]["n_cells_total"] == 500             # reliable cells only
    assert cs["malignant"]["median_detection_fraction"] == 0.9


def test_compartment_summary_omits_compartment_when_all_donors_sub_floor():
    """If every donor in a compartment is under the cell floor, the compartment is omitted (honest gap)
    rather than emitting a call resting on a handful of cells."""
    rows = _rows([("malignant", "dsA", "d1", 5, 0.6, 1.0),
                  ("malignant", "dsB", "d2", 8, 0.7, 1.2)])
    cs = S.compartment_summary(rows)
    assert "malignant" not in cs


# --- total malignant-cell floor in classify_sc_expression -------------------

def test_thin_pooled_cube_is_data_unavailable_despite_enough_donors():
    """THE KIRC/OV case: 5 donors (clears MIN_RELIABLE_DONORS) but only ~74 total malignant cells
    (below MIN_MALIGNANT_CELLS_TOTAL=100) → data_unavailable, NOT a confident malignant call."""
    cs = {"malignant": {"n_donors": 5, "n_cells_total": 74,
                        "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "data_unavailable"
    assert r["malignant_n_cells"] == 74                        # surfaced for legibility


def test_well_sampled_cube_still_classifies_and_surfaces_cell_count():
    """A cube clearing BOTH floors (5 donors, 1000 cells) still classifies, and now reports
    malignant_n_cells."""
    cs = {"malignant": {"n_donors": 5, "n_cells_total": 1000,
                        "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    r = S.classify_sc_expression(cs)
    assert r["sc_expression_class"] == "malignant_broadly_detected"
    assert r["malignant_n_cells"] == 1000


def test_cell_floor_boundary_at_100():
    """Exactly MIN_MALIGNANT_CELLS_TOTAL (100) cells passes; 99 abstains."""
    at = {"malignant": {"n_donors": 5, "n_cells_total": 100,
                        "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    below = {"malignant": {"n_donors": 5, "n_cells_total": 99,
                          "median_detection_fraction": 0.7, "median_abundance_log1p_cp10k": 3.0}}
    assert S.classify_sc_expression(at)["sc_expression_class"] == "malignant_broadly_detected"
    assert S.classify_sc_expression(below)["sc_expression_class"] == "data_unavailable"
