"""Phase 1C: read-side all-gene-rank lookup accessors (fixture-only, no S3).

Loads the lookup module and monkeypatches its S3-reading inner functions
(_tumor_rows / _depmap_row) so the aggregation + classification + audit-string
logic is tested deterministically offline. The pushdown read itself is exercised
by the live smoke in the PR description, not here (unit tests stay S3-free).
"""
import importlib.util
from pathlib import Path

import pytest

LOOKUP = (Path(__file__).resolve().parents[3] / "methods"
          / "allgene_percentile_precompute" / "lookup.py")


def _load():
    spec = importlib.util.spec_from_file_location("allgene_lookup", LOOKUP)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---- DepMap panel-median accessor ----------------------------------------

def test_depmap_percentile_classifies_and_audits(monkeypatch):
    lk = _load()
    # (allgene_percentile, allgene_rank, n_genes, panel_median_log2tpm)
    monkeypatch.setattr(lk, "_depmap_row", lambda sym: (99.9, 17, 19215, 11.9))
    out = lk.depmap_allgene_percentile("GAPDH")
    assert out["allgene_percentile"] == pytest.approx(99.9)
    assert out["allgene_percentile_class"] == "top_1pct"
    assert "allgene-depmap-rank-26q1-v1" in out["allgene_percentile_context"]
    assert "17/19215" in out["allgene_percentile_context"]


def test_depmap_percentile_bottom_decile(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_depmap_row", lambda sym: (8.7, 15849, 19215, 0.0))
    out = lk.depmap_allgene_percentile("SFTPC")
    assert out["allgene_percentile_class"] == "bottom_decile"


def test_depmap_percentile_absent_gene_is_data_unavailable(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_depmap_row", lambda sym: None)
    out = lk.depmap_allgene_percentile("MADE_UP_GENE")
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "target absent" in out["allgene_percentile_context"]


# ---- Tumor per-study accessor --------------------------------------------

def test_tumor_percentile_averages_over_studies(monkeypatch):
    lk = _load()
    # rows = (group, allgene_percentile, allgene_rank, n_genes_in_group, median)
    monkeypatch.setattr(lk, "_tumor_rows", lambda ids, source: (
        ("COAD", 99.9, 5, 41000, 10.9), ("READ", 99.92, 4, 40000, 11.0)))
    out = lk.tumor_allgene_percentile(["ENSG1"], ["COAD", "READ"])
    assert out["allgene_percentile"] == pytest.approx((99.9 + 99.92) / 2)
    assert out["allgene_percentile_class"] == "top_1pct"
    assert out["allgene_percentile_by_study"] == {"COAD": 99.9, "READ": 99.92}
    # audit string names BOTH studies + the product — the anti-pooling guard.
    ctx = out["allgene_percentile_context"]
    assert "COAD" in ctx and "READ" in ctx and "allgene-tumor-rank-v1" in ctx


def test_tumor_percentile_filters_to_requested_studies(monkeypatch):
    lk = _load()
    # product returns extra studies; the accessor must keep only the indication's.
    monkeypatch.setattr(lk, "_tumor_rows", lambda ids, source: (
        ("COAD", 84.97, 100, 41000, 3.9), ("READ", 83.95, 110, 40000, 3.8),
        ("LUAD", 50.0, 200, 41000, 2.0)))
    out = lk.tumor_allgene_percentile(["ENSG1"], ["COAD", "READ"])
    assert set(out["allgene_percentile_by_study"]) == {"COAD", "READ"}  # LUAD excluded
    assert out["allgene_percentile"] == pytest.approx((84.97 + 83.95) / 2)
    assert out["allgene_percentile_class"] == "mid"


def test_tumor_percentile_absent_gene_is_data_unavailable(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_tumor_rows", lambda ids, source: ())
    out = lk.tumor_allgene_percentile(["ENSG1"], ["COAD"])
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "target absent" in out["allgene_percentile_context"]


def test_tumor_percentile_empty_inputs_short_circuit(monkeypatch):
    lk = _load()
    # No ensembl ids OR no studies → data_unavailable WITHOUT touching S3.
    called = {"n": 0}
    monkeypatch.setattr(lk, "_tumor_rows", lambda ids, source: called.__setitem__("n", called["n"] + 1) or ())
    assert lk.tumor_allgene_percentile([], ["COAD"])["allgene_percentile_class"] == "data_unavailable"
    assert lk.tumor_allgene_percentile(["ENSG1"], [])["allgene_percentile_class"] == "data_unavailable"
    assert called["n"] == 0  # short-circuited before any read


def test_custom_cutoffs_override_defaults(monkeypatch):
    lk = _load()
    monkeypatch.setattr(lk, "_depmap_row", lambda sym: (92.0, 1000, 19215, 5.0))
    # default: 92 >= 90 → top_decile
    assert lk.depmap_allgene_percentile("X")["allgene_percentile_class"] == "top_decile"
    # raised top_decile cutoff to 95 → 92 now merely mid
    assert lk.depmap_allgene_percentile(
        "X", cutoffs={"top_decile": 95.0})["allgene_percentile_class"] == "mid"
