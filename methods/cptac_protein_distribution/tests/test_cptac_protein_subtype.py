"""Unit tests for the subtype-stratified CPTAC protein reader (pure logic + monkeypatched reader)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cptac_protein_distribution.read import (  # noqa: E402
    _protein_class, _classify_subtype_signal, _subtype_rollup, read_stratified_protein,
    build_protein_subtype_panorama)


def test_protein_class_bands():
    assert _protein_class(1.0) == "protein_elevated"
    assert _protein_class(0.0) == "protein_neutral"
    assert _protein_class(-1.0) == "protein_reduced"
    assert _protein_class(None) == "insufficient"


def test_subtype_signal_vs_pooled():
    assert _classify_subtype_signal(1.0, 0.0) == "enriched"
    assert _classify_subtype_signal(-1.0, 0.0) == "depleted"
    assert _classify_subtype_signal(0.1, 0.0) == "uniform"
    assert _classify_subtype_signal(None, 0.0) is None


def test_rollup_axis_quality_and_stratification():
    records = [
        {"stratum": "MSI_H", "evidence_state": "measured", "median_log2_ratio": 0.9},
        {"stratum": "MSS", "evidence_state": "measured", "median_log2_ratio": 0.1},
    ]
    out = _subtype_rollup(records, pooled_median=0.1)
    assert out["subtype_axis_available"] is True
    assert out["subtype_axis_quality"] == "powered"          # 2 measured strata
    assert out["n_subtypes_measured"] == 2
    assert out["subtype_stratification_class"] == "subtype_enriched"   # MSI_H enriched vs pooled 0.1
    # underpowered -> axis quality drops
    under = [{"stratum": "MSI_H", "evidence_state": "underpowered", "median_log2_ratio": 0.9}]
    assert _subtype_rollup(under, 0.1)["subtype_axis_quality"] == "underpowered"


def _fake_per_sample():
    # 40 MSI_H aliquots (elevated), 40 MSS (neutral); tumor condition, COAD cohort
    rows = []
    for i in range(40):
        rows.append({"gene_symbol": "EPCAM", "cohort": "COAD", "aliquot_submitter_id": f"MSI_{i}",
                     "condition": "Tumor", "log2_ratio": 1.2})
    for i in range(40):
        rows.append({"gene_symbol": "EPCAM", "cohort": "COAD", "aliquot_submitter_id": f"MSS_{i}",
                     "condition": "Tumor", "log2_ratio": 0.0})
    return pd.DataFrame(rows)


def test_read_stratified_protein_filters_and_classifies(monkeypatch):
    import methods.cptac_protein_deg.read as cpr
    monkeypatch.setattr(cpr, "read_per_sample", lambda t: _fake_per_sample())
    # single-call (no subgroups) with an explicit member filter -> the MSI_H stratum
    rec = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD",
                                  _sample_id_filter={f"MSI_{i}" for i in range(40)})
    assert rec["subgroup_n"] == 40
    assert rec["evidence_state"] == "measured"
    assert rec["protein_class"] == "protein_elevated"
    assert rec["median_log2_ratio"] == 1.2
    # a stratum below the n-floor -> underpowered
    rec2 = read_stratified_protein("EPCAM", "COADREAD", cohort="COAD",
                                   _sample_id_filter={"MSS_0", "MSS_1"})
    assert rec2["subgroup_n"] == 2 and rec2["evidence_state"] == "underpowered"


def test_build_panorama_no_shard_is_honest_false():
    # an indication with no landed CPTAC shard -> honest subtype_axis_available:false, no S3 touched
    pan = build_protein_subtype_panorama("EPCAM", "GBM", subgroups=["x"])
    assert pan["subtype_axis_available"] is False
    assert pan["subtype_axis_quality"] == "unavailable"
    assert pan["subtype_stratification_class"] == "subtype_axis_unavailable"
