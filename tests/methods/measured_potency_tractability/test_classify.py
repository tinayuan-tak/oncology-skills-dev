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
    classify_measured_bioactivity, measured_potency_for_gene, POTENT_PCHEMBL, POTENT_SERIES_MIN,
    classify_chembl_clinical_phase)


def test_chembl_clinical_phase_class_2026_08_24():
    assert classify_chembl_clinical_phase({"max_clinical_phase": 4}) == "approved"
    assert classify_chembl_clinical_phase({"max_clinical_phase": 4.0}) == "approved"
    assert classify_chembl_clinical_phase({"max_clinical_phase": 2}) == "clinical"
    assert classify_chembl_clinical_phase({"max_clinical_phase": 1}) == "clinical"
    assert classify_chembl_clinical_phase({"max_clinical_phase": 0.5}) == "preclinical_or_none"  # Early Phase 1 — conservative
    assert classify_chembl_clinical_phase({"max_clinical_phase": 0}) == "preclinical_or_none"
    assert classify_chembl_clinical_phase({"max_clinical_phase": None}) == "preclinical_or_none"  # row exists, no phase
    assert classify_chembl_clinical_phase(None) == "data_unavailable"                             # no ChEMBL row
    # surfaced in the summary dict
    g = measured_potency_for_gene("EGFR", chembl_row={"max_clinical_phase": 4}, bdb_row=None)
    assert g["chembl_clinical_phase_class"] == "approved"


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


# ── RD1: a TRANSIENT load failure must NOT poison the lru_cache (must be retried) ───────────────
import pytest  # noqa: E402
import pandas as pd  # noqa: E402
import methods.measured_potency_tractability.read as _R  # noqa: E402


def test_transient_load_raises_and_is_not_cached(monkeypatch):
    """A transient (non-absent) load error must PROPAGATE and NOT be memoized by @lru_cache, so the
    next target in a batch retries instead of inheriting a poisoned None. Regression for RD1."""
    _R._load_indexed.cache_clear()
    calls = {"n": 0}

    def flaky(path_or_none, bucket, key):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 throttle")   # non-absent → must propagate
        return pd.DataFrame([{"uniprot_id": "P00533", "best_pchembl": 7.5, "n_potent_ligands": 40}])

    monkeypatch.setattr(_R, "_read_parquet", flaky)
    with pytest.raises(RuntimeError):
        _R._load_indexed()
    # the raised load was NOT cached → this call re-enters _read_parquet and succeeds.
    idx = _R._load_indexed()
    assert idx is not None and idx[0] is not None
    _R._load_indexed.cache_clear()


def test_genuine_absence_returns_none_not_raise(monkeypatch):
    """A definitive NoSuchKey (product genuinely absent) → None (honest data_unavailable), not a raise."""
    from botocore.exceptions import ClientError
    _R._load_indexed.cache_clear()

    def absent(path_or_none, bucket, key):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(_R, "_read_parquet", absent)
    chembl_idx, bdb_idx = _R._load_indexed()
    assert chembl_idx is None and bdb_idx is None
    assert _R._lookup(chembl_idx, "EGFR") is None    # None-safe lookup → data_unavailable downstream
    _R._load_indexed.cache_clear()


def test_nan_pchembl_is_not_a_measured_value():
    """S2 (cards review 2026-08-17): a ChEMBL row that EXISTS but carries a NaN best_pchembl (present
    in ChEMBL, no quantified potency) must NOT be credited as weak_measured_ligand, and NaN must not
    leak into best_measured_potency_neglog_m. (GPR151-class false positive.)"""
    nan_row = {"best_pchembl": float("nan"), "n_potent_ligands": 0}
    assert classify_measured_bioactivity(nan_row, None) == "no_measured_activity"
    g = measured_potency_for_gene("GPR151", chembl_row=nan_row, bdb_row=None)
    assert g["measured_bioactivity_class"] == "no_measured_activity"
    assert g["best_measured_potency_neglog_m"] is None   # NaN no longer leaks into the emitted field
