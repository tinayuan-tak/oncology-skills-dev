"""Synthetic-data tests for the gnomad_constraint reader (no S3).

Validates: (1) the constraint_class classifier at each band + the card thresholds
(high_loeuf=0.45 as of the v4.1.1 refresh); (2) per-gene lookup against the
gnomad-constraint-per-gene-v1 product (one row per gene, already representative-
selected at derive time); (3) the not-in-table → `indeterminate` distinction (a real
read, gene absent) vs the graceful `data_unavailable` (couldn't read); (4) the
card-contract field set. The classifier is pure — most assertions need no file at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(METHODS_REPO))
from methods.gnomad_constraint import cli as gc  # noqa: E402
from methods.gnomad_constraint import read as gc_read  # noqa: E402


# --- classifier (pure; the card thresholds) -------------------------------

def test_classify_highly_constrained():
    # LOEUF <= 0.45 OR pLI >= 0.9
    assert gc.classify_constraint(pli=0.99, loeuf=0.15) == "highly_constrained"
    assert gc.classify_constraint(pli=None, loeuf=0.30) == "highly_constrained"   # LOEUF alone
    assert gc.classify_constraint(pli=0.95, loeuf=None) == "highly_constrained"   # pLI alone


def test_classify_moderately_constrained():
    assert gc.classify_constraint(pli=0.6, loeuf=0.5) == "moderately_constrained"
    assert gc.classify_constraint(pli=None, loeuf=0.55) == "moderately_constrained"


def test_classify_tolerant():
    assert gc.classify_constraint(pli=0.1, loeuf=1.2) == "tolerant"
    assert gc.classify_constraint(pli=0.0, loeuf=0.9) == "tolerant"


def test_classify_indeterminate_when_both_missing():
    assert gc.classify_constraint(pli=None, loeuf=None) == "indeterminate"


def test_band_boundaries_are_inclusive():
    # exactly at the high thresholds → highly_constrained
    assert gc.classify_constraint(pli=0.9, loeuf=1.0) == "highly_constrained"    # pLI==0.9
    assert gc.classify_constraint(pli=0.0, loeuf=0.45) == "highly_constrained"   # LOEUF==0.45 (v4.1.1 cutoff)
    # just inside the widened high band (would have been moderate under the old 0.35)
    assert gc.classify_constraint(pli=0.0, loeuf=0.40) == "highly_constrained"
    # just above the high LOEUF cutoff, below moderate → moderately_constrained
    assert gc.classify_constraint(pli=0.0, loeuf=0.46) == "moderately_constrained"
    # exactly at the moderate thresholds → moderately_constrained
    assert gc.classify_constraint(pli=0.5, loeuf=1.0) == "moderately_constrained"
    assert gc.classify_constraint(pli=0.0, loeuf=0.6) == "moderately_constrained"


# --- per-gene lookup + summary (synthetic parquet matching the product schema) ---

def _write_parquet(tmp_path):
    """Write a synthetic gnomad-constraint-per-gene-v1 product: one row per gene,
    columns gene_symbol, gene_id, pli, loeuf, mis_z, syn_z, obs_lof, exp_lof."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = tmp_path / "gnomad_constraint_per_gene.parquet"
    recs = [
        # TP53: highly constrained (representative row already chosen at derive time)
        {"gene_symbol": "TP53", "gene_id": "7157", "pli": 0.99, "loeuf": 0.12,
         "mis_z": 5.2, "syn_z": 0.3, "obs_lof": 1.0, "exp_lof": 38.0},
        # KRAS: highly constrained
        {"gene_symbol": "KRAS", "gene_id": "3845", "pli": 0.96, "loeuf": 0.20,
         "mis_z": 3.1, "syn_z": 0.2, "obs_lof": 2.0, "exp_lof": 20.0},
        # SCD: tolerant
        {"gene_symbol": "SCD", "gene_id": "6319", "pli": 0.02, "loeuf": 1.35,
         "mis_z": 0.1, "syn_z": 0.0, "obs_lof": 60.0, "exp_lof": 55.0},
    ]
    schema = pa.schema([
        ("gene_symbol", pa.string()), ("gene_id", pa.string()),
        ("pli", pa.float64()), ("loeuf", pa.float64()),
        ("mis_z", pa.float64()), ("syn_z", pa.float64()),
        ("obs_lof", pa.float64()), ("exp_lof", pa.float64()),
    ])
    pq.write_table(pa.Table.from_pylist(recs, schema=schema), p)
    return str(p)


def test_gene_row_looked_up_and_classified(tmp_path):
    pq_path = _write_parquet(tmp_path)
    row = gc.load_constraint_row("TP53", parquet_path=pq_path)
    assert row is not None and row["gene_symbol"] == "TP53"
    s = gc.compute_summary(row, "TP53")
    assert s["constraint_class"] == "highly_constrained"
    assert s["pli_score"] == 0.99 and s["loeuf_score"] == 0.12
    assert s["mis_z_score"] == 5.2 and s["syn_z_score"] == 0.3
    assert s["obs_lof_count"] == 1 and s["exp_lof_count"] == 38.0
    assert s["method_version"] == gc.METHOD_VERSION


def test_lookup_is_case_insensitive(tmp_path):
    pq_path = _write_parquet(tmp_path)
    assert gc.load_constraint_row("kras", parquet_path=pq_path)["gene_symbol"] == "KRAS"


def test_tolerant_gene(tmp_path):
    pq_path = _write_parquet(tmp_path)
    s = gc.compute_summary(gc.load_constraint_row("SCD", parquet_path=pq_path), "SCD")
    assert s["constraint_class"] == "tolerant"


def test_gene_not_in_table_is_indeterminate_not_data_unavailable(tmp_path):
    pq_path = _write_parquet(tmp_path)
    row = gc.load_constraint_row("FOOBAR", parquet_path=pq_path)
    assert row is None
    s = gc.compute_summary(row, "FOOBAR")
    assert s["constraint_class"] == "indeterminate", (
        "a gene READ but absent from the table is indeterminate (real negative-ish), "
        "NOT data_unavailable (which means we couldn't read)")


def test_card_contract_fields_present(tmp_path):
    pq_path = _write_parquet(tmp_path)
    s = gc.compute_summary(gc.load_constraint_row("KRAS", parquet_path=pq_path), "KRAS")
    for f in ("constraint_class", "pli_score", "loeuf_score", "mis_z_score",
              "syn_z_score", "obs_lof_count", "exp_lof_count", "gene_length_bp",
              "method_version"):
        assert f in s, f"card-contract field missing: {f}"


# --- graceful degradation (the dispatcher entry) --------------------------

def test_read_target_summary_graceful_on_unreadable_source(monkeypatch):
    """If the source can't be loaded, read_target_summary must return
    data_unavailable + _live_read_error — NOT raise (framework degradation contract).
    Distinct from indeterminate (which is a successful read of an absent gene)."""
    def _boom(*a, **k):
        raise RuntimeError("s3 unreachable")
    monkeypatch.setattr(gc, "load_constraint_row", _boom)
    out = gc_read.read_target_summary(target="KRAS", indication="COADREAD")
    assert out["constraint_class"] == "data_unavailable"
    assert out["_live_read_error"] == "gnomad_constraint_read_failed"


# --- figure emission (viz-coverage backfill 2026-07-20) ------------------

def test_emit_constraint_gauge_writes_svg(tmp_path):
    """The gauge emitter writes an SVG from a summary dict (no S3). Covers the
    real-scores path + the indeterminate placeholder path."""
    import pytest
    pytest.importorskip("matplotlib")
    TC = "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
    summary = {"constraint_class": "highly_constrained", "pli_score": 0.99,
               "loeuf_score": 0.12, "method_version": gc.METHOD_VERSION}
    p = gc.emit_constraint_gauge(summary, "TP53", tmp_path / "tp53", TC)
    assert p.exists() and p.stat().st_size > 0
    # indeterminate (no scores) → placeholder panel, still an SVG
    p2 = gc.emit_constraint_gauge({"constraint_class": "indeterminate", "pli_score": None,
                                   "loeuf_score": None}, "FOO", tmp_path / "foo", TC)
    assert p2.exists()
