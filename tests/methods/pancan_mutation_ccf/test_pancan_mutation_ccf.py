"""Tests for pancan_mutation_ccf — mutation clonality (cancer-cell-fraction).

Hermetic: read_clonality over a synthetic materialized product (present / gene-absent / product-absent).
Live (skip without S3 creds): the BIOLOGY GATE — aggregate_clonality("COADREAD") must reproduce the
known clonal architecture (the CRC truncal founders APC/TP53/KRAS predominantly_clonal), the validation
that makes the durability signal real rather than artifactual.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from methods.pancan_mutation_ccf.read import read_clonality


def _write_product(tmp_path: Path) -> Path:
    import pandas as pd
    df = pd.DataFrame([
        {"indication": "COADREAD", "gene_symbol": "APC", "n_mutant_samples": 395,
         "clonal_fraction": 0.93, "median_ccf": 1.18, "clonality_class": "predominantly_clonal",
         "evidence_tier": "inferred_diploid"},
        {"indication": "COADREAD", "gene_symbol": "ARID1A", "n_mutant_samples": 58,
         "clonal_fraction": 0.41, "median_ccf": 0.72, "clonality_class": "mixed_clonality",
         "evidence_tier": "inferred_diploid"},
    ])
    p = tmp_path / "COADREAD-clonality.parquet"
    df.to_parquet(p)
    return p


def test_read_clonality_present(tmp_path):
    p = _write_product(tmp_path)
    r = read_clonality("APC", "COADREAD", product_path=str(p))
    assert r["clonality_class"] == "predominantly_clonal"
    assert r["clonal_fraction"] == pytest.approx(0.93)
    assert r["n_mutant_samples"] == 395
    assert r["evidence_tier"] == "inferred_diploid"


def test_read_clonality_mixed(tmp_path):
    p = _write_product(tmp_path)
    r = read_clonality("ARID1A", "COADREAD", product_path=str(p))
    assert r["clonality_class"] == "mixed_clonality"


def test_read_clonality_gene_absent_is_data_unavailable(tmp_path):
    p = _write_product(tmp_path)
    r = read_clonality("EGFR", "COADREAD", product_path=str(p))   # not in the product (below floor)
    assert r["clonality_class"] == "data_unavailable"
    assert "not recurrently mutated" in r["_missing_reason"]


def test_read_clonality_product_absent_is_data_unavailable(tmp_path):
    r = read_clonality("APC", "COADREAD", product_path=str(tmp_path / "nope.parquet"))
    assert r["clonality_class"] == "data_unavailable"
    assert "no clonality product" in r["_missing_reason"]


@pytest.mark.skipif(not os.environ.get("AWS_PROFILE"),
                    reason="live S3 test — needs AWS_PROFILE (MC3 + PanCanAtlas ABSOLUTE)")
def test_coadread_truncal_founders_are_clonal_biology_gate():
    """BIOLOGY GATE: the CRC truncal founders (APC, TP53, KRAS — the Vogelstein adenoma→carcinoma
    sequence) must resolve predominantly_clonal with a high clonal fraction. Guards the ccf pipeline
    against an inversion/units bug that would make the durability signal artifactual."""
    from methods.pancan_mutation_ccf.cli import aggregate_clonality
    try:
        rows = {r["gene_symbol"]: r for r in aggregate_clonality("COADREAD")}
    except Exception as e:  # noqa: BLE001 — AWS_PROFILE set but S3 unreachable/denied → skip, not fail
        if any(k in str(e) for k in ("AccessDenied", "credential", "Unable to locate", "ExpiredToken", "NoSuchKey")):
            import pytest as _p
            _p.skip(f"live S3 unreachable despite AWS_PROFILE ({type(e).__name__}); biology gate skipped")
        raise
    for founder in ("APC", "TP53", "KRAS"):
        r = rows.get(founder)
        assert r is not None, f"{founder} missing from COADREAD clonality"
        assert r["clonality_class"] == "predominantly_clonal", f"{founder}: {r['clonality_class']}"
        assert r["clonal_fraction"] >= 0.8, f"{founder} clonal_fraction {r['clonal_fraction']} < 0.8"
