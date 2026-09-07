"""Credential-less tests for gdsc_drug_activity — synthetic local parquet seams (no S3).

Builds a small per-gene product parquet + a target-resolution sidecar in tmp_path, points the cli
helpers at them via the product_path/sidecar_path offline seams, and verifies:
  - direct gene_symbol match + potency classification (potent / moderate / weak)
  - HGNC-alias sidecar fallback (framework RPS6KA1 -> GDSC token RSK1)
  - unmatched symbol -> no_compounds_found (a measured weak-negative, NOT data_unavailable)
  - NaN numeric -> None
  - read.py graceful degradation on read failure -> _live_read_error + data_unavailable
  - the emitted summary key-set matches the gdsc-drug-activity card contract exactly
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root -> `methods` importable

from methods.gdsc_drug_activity import cli as gcli  # noqa: E402
from methods.gdsc_drug_activity import read as gread  # noqa: E402

# The exact summary key-set the gdsc-drug-activity card declares (summary_fields must match the reader).
_EXPECTED_KEYS = {
    "gdsc_activity_class",
    "n_drugs",
    "n_cell_lines_tested",
    "median_ln_ic50",
    "median_auc",
    "min_median_ln_ic50",
    "most_sensitive_drug_name",
    "datasets",
    "looks_like_gene_symbol",
    "gdsc_target_token",
    "resolved_via",
    "method_version",
}


def _make_product(path: Path):
    """A per-gene GDSC product matching the derived schema (gene-sorted)."""
    rows = [
        # gene_symbol, looks_like, n_drugs, n_cell, n_curves, median_ln, median_auc, min_median_ln, msdid, msdname, datasets
        ("EGFR", True, 19, 977, 18452, 2.03, 0.91, -0.50, "273", "CUDC-101", "GDSC1|GDSC2"),
        ("MET", True, 7, 900, 6000, 3.10, 0.95, 1.50, "1", "Foretinib", "GDSC1|GDSC2"),
        ("FOO", True, 2, 400, 800, 5.20, 0.97, 4.00, "9", "ToolCmpd", "GDSC2"),
        # NaN median_auc + potent RSK1 token (alias of RPS6KA1)
        ("RSK1", True, 3, 500, 1500, 0.90, float("nan"), 0.20, "77", "BI-D1870", "GDSC1"),
    ]
    tbl = pa.table(
        {
            "gene_symbol": pa.array([r[0] for r in rows], pa.string()),
            "looks_like_gene_symbol": pa.array([r[1] for r in rows], pa.bool_()),
            "n_drugs": pa.array([r[2] for r in rows], pa.int64()),
            "n_cell_lines_tested": pa.array([r[3] for r in rows], pa.int64()),
            "n_curves": pa.array([r[4] for r in rows], pa.int64()),
            "median_ln_ic50": pa.array([r[5] for r in rows], pa.float64()),
            "median_auc": pa.array([r[6] for r in rows], pa.float64()),
            "min_median_ln_ic50": pa.array([r[7] for r in rows], pa.float64()),
            "most_sensitive_drug_id": pa.array([r[8] for r in rows], pa.string()),
            "most_sensitive_drug_name": pa.array([r[9] for r in rows], pa.string()),
            "datasets": pa.array([r[10] for r in rows], pa.string()),
        }
    )
    pq.write_table(tbl, str(path))


def _make_sidecar(path: Path):
    rows = [
        ("EGFR", "EGFR", "resolved"),
        ("MET", "MET", "resolved"),
        ("RSK1", "RPS6KA1", "deprecated_remapped"),
        ("FOO", "", "no_hgnc_mapping"),
    ]
    tbl = pa.table(
        {
            "native_row_key": pa.array([r[0] for r in rows], pa.string()),
            "hgnc_primary_symbol_at_resolution": pa.array([r[1] for r in rows], pa.string()),
            "resolution_status": pa.array([r[2] for r in rows], pa.string()),
        }
    )
    pq.write_table(tbl, str(path))


@pytest.fixture()
def product(tmp_path):
    p = tmp_path / "gdsc.parquet"
    s = tmp_path / "gdsc.sidecar.parquet"
    _make_product(p)
    _make_sidecar(s)
    return p, s


def test_direct_potent(product):
    p, s = product
    out = gcli.load_and_classify("EGFR", product_path=p, sidecar_path=s)
    assert out["gdsc_activity_class"] == "potent_activity"
    assert out["resolved_via"] == "direct"
    assert out["gdsc_target_token"] == "EGFR"
    assert out["n_drugs"] == 19
    assert out["n_cell_lines_tested"] == 977
    assert out["most_sensitive_drug_name"] == "CUDC-101"
    assert out["datasets"] == "GDSC1|GDSC2"
    assert out["looks_like_gene_symbol"] is True
    assert {k for k in out if not k.startswith("_")} == _EXPECTED_KEYS


def test_direct_moderate(product):
    p, s = product
    out = gcli.load_and_classify("MET", product_path=p, sidecar_path=s)
    assert out["gdsc_activity_class"] == "moderate_activity"
    assert out["resolved_via"] == "direct"


def test_direct_weak(product):
    p, s = product
    out = gcli.load_and_classify("FOO", product_path=p, sidecar_path=s)
    assert out["gdsc_activity_class"] == "weak_activity"


def test_case_insensitive_direct(product):
    p, s = product
    out = gcli.load_and_classify("egfr", product_path=p, sidecar_path=s)
    assert out["gdsc_target_token"] == "EGFR"
    assert out["resolved_via"] == "direct"


def test_hgnc_alias_fallback(product):
    """Framework symbol RPS6KA1 is not a native token; the sidecar maps it to the GDSC token RSK1."""
    p, s = product
    out = gcli.load_and_classify("RPS6KA1", product_path=p, sidecar_path=s)
    assert out["resolved_via"] == "hgnc_alias"
    assert out["gdsc_target_token"] == "RSK1"
    assert out["gdsc_activity_class"] == "moderate_activity"  # min_median_ln_ic50 = 0.20
    # NaN median_auc -> None
    assert out["median_auc"] is None


def test_unmatched_is_no_compounds_found(product):
    p, s = product
    out = gcli.load_and_classify("ZZZ9", product_path=p, sidecar_path=s)
    assert out["gdsc_activity_class"] == "no_compounds_found"
    assert out["n_drugs"] == 0
    assert out["min_median_ln_ic50"] is None
    assert out["gdsc_target_token"] is None
    assert out["resolved_via"] is None
    assert {k for k in out if not k.startswith("_")} == _EXPECTED_KEYS


def test_read_target_summary_graceful_on_failure(monkeypatch):
    """read.py converts an infra failure into _live_read_error + data_unavailable (never crashes)."""

    def _boom(target, indication=None):
        raise RuntimeError("s3 exploded")

    monkeypatch.setattr(gcli, "load_and_classify", _boom)
    out = gread.read_target_summary("EGFR")
    assert out["gdsc_activity_class"] == "data_unavailable"
    assert out["_live_read_error"] == "gdsc_drug_activity_read_failed"
    # DISTINCT from no_compounds_found: infra gap, not a measured negative.
    assert out["gdsc_activity_class"] != "no_compounds_found"
    assert set(out) >= _EXPECTED_KEYS


def test_read_target_summary_success_path(monkeypatch, product):
    """read.py passes through the real pipeline result (indication accepted, not consumed)."""
    p, s = product
    real = gcli.load_and_classify
    monkeypatch.setattr(
        gcli, "load_and_classify", lambda target, indication=None: real(target, product_path=p, sidecar_path=s)
    )
    out = gread.read_target_summary("EGFR", indication="COADREAD")
    assert out["gdsc_activity_class"] == "potent_activity"
    assert out["resolved_via"] == "direct"


def test_classify_bands():
    assert gcli._classify(-0.1) == "potent_activity"
    assert gcli._classify(0.0) == "potent_activity"
    assert gcli._classify(1.0) == "moderate_activity"
    assert gcli._classify(3.0) == "moderate_activity"
    assert gcli._classify(3.01) == "weak_activity"
    assert gcli._classify(None) == "weak_activity"
