"""measured_potency_tractability — the ChEMBL+BindingDB measured-potency fusion (verdict-driving, T3.1).

Pins classify_measured_bioactivity + the summary shape with injected rows (hermetic, no S3):
potent (<=1 uM in either source) > weak (measured, not potent) > no_measured_activity (in-source, no
value) > data_unavailable (absent from both). Max-potency-wins across the two independent sources.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.measured_potency_tractability.read import (  # noqa: E402
    classify_measured_bioactivity, measured_potency_for_gene, POTENT_PCHEMBL, POTENT_SERIES_MIN)


def test_absent_from_both_is_data_unavailable():
    # pure classifier: absent from both sources → coverage gap, never a false negative
    assert classify_measured_bioactivity(None, None) == "data_unavailable"


def test_chembl_potent_SERIES_is_potent():
    # a real chemotype series (>= POTENT_SERIES_MIN potent ligands) → STRONG
    assert classify_measured_bioactivity(
        {"best_pchembl": 7.5, "n_potent_ligands": 40}, None) == "potent_measured_ligand"


def test_single_potent_hit_is_only_WEAK_not_strong():
    # CALIBRATION: a single potent activity (best_pchembl>=6) with NO series is near-universal for
    # studied genes → must NOT be the strong verdict; it is weak_measured_ligand.
    assert classify_measured_bioactivity(
        {"best_pchembl": 7.5, "n_potent_ligands": 1}, None) == "weak_measured_ligand"
    assert classify_measured_bioactivity(
        {"best_pchembl": 9.0, "n_potent_ligands": 3}, None) == "weak_measured_ligand"


def test_bindingdb_potent_series_is_potent():
    assert classify_measured_bioactivity(
        None, {"has_sub_micromolar_binder": True, "n_potent_ligands": 25}) == "potent_measured_ligand"


def test_max_series_wins_across_sources():
    # thin ChEMBL but a potent BindingDB series -> potent (max-wins on the series)
    assert classify_measured_bioactivity(
        {"best_pchembl": 5.0, "n_potent_ligands": 0},
        {"best_p_affinity": 8.0, "n_potent_ligands": 30}) == "potent_measured_ligand"


def test_measured_but_not_potent_is_weak():
    assert classify_measured_bioactivity({"best_pchembl": 5.0, "n_potent_ligands": 0}, None) == "weak_measured_ligand"
    assert classify_measured_bioactivity(
        {"best_pchembl": 4.0, "n_potent_ligands": 0}, {"best_p_affinity": 5.5, "n_potent_ligands": 0}) == "weak_measured_ligand"


def test_in_source_no_value_is_no_measured_activity():
    # present in a source (row exists) but no potency value at all
    assert classify_measured_bioactivity(
        {"n_activities": 3, "best_pchembl": None, "n_potent_ligands": 0}, None) == "no_measured_activity"


def test_summary_shape_and_best_measured():
    out = measured_potency_for_gene("EGFR",
                                    chembl_row={"best_pchembl": 8.1, "n_potent_ligands": 40, "max_clinical_phase": 4},
                                    bdb_row={"best_p_affinity": 9.0, "n_potent_ligands": 120, "has_sub_micromolar_binder": True})
    assert out["measured_bioactivity_class"] == "potent_measured_ligand"
    assert out["best_measured_potency_neglog_m"] == 9.0    # max across sources
    assert out["chembl_max_clinical_phase"] == 4
    assert "POTENT" in out["measured_potency_context"]


def test_series_threshold_boundary():
    assert POTENT_SERIES_MIN == 10
    assert classify_measured_bioactivity({"best_pchembl": 7.0, "n_potent_ligands": 10}, None) == "potent_measured_ligand"
    assert classify_measured_bioactivity({"best_pchembl": 7.0, "n_potent_ligands": 9}, None) == "weak_measured_ligand"
