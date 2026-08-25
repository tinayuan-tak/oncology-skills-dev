"""Credential-less tests for the TPHP normal-tissue-protein reader.

No S3: a synthetic local long/tidy parquet (the derived product's schema — gene_symbol, uniprot_ac,
tissue, tissue_class, median_log2_abundance, median_intensity, n_samples, n_detected,
detection_rate) is read via the `product_path` offline seam. Pins:
  * the emitted summary carries EVERY field the normal-tissue-protein-abundance-tphp card declares
    (the reader-real-field-names drift class the tumor-selectivity replay exists to catch);
  * breadth class is computed on the ADULT tissue count (broad / moderate / restricted reachable);
  * fetal-vs-adult flag + highest-abundance tissue + max/median aggregates are correct;
  * a gene with NO rows → data_unavailable (a genuine coverage gap, absence discipline);
  * a genuine 404-class fault → data_unavailable + _live_read_error (never crashes the compose path);
  * a transient/creds error is RE-RAISED (never masked as an empty normal footprint).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

read = importlib.import_module("methods.tphp_normal_protein.read")

# The fields the normal-tissue-protein-abundance-tphp card declares in outputs.summary_fields — the
# reader MUST emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "normal_protein_breadth_class", "n_tissues_detected", "n_adult_tissues_detected",
    "n_fetal_groups_detected", "n_adult_tissues_total", "n_fetal_groups_total",
    "max_median_log2_abundance", "median_across_tissues_log2_abundance", "highest_abundance_tissue",
    "highest_abundance_tissue_class", "fetal_vs_adult_flag", "max_detection_rate", "uniprot_ac",
    "per_tissue_abundance", "method_version",
}
_BREADTH_VOCAB = {"broad_normal_protein", "moderate_normal_protein", "restricted_normal_protein",
                  "not_detected_in_normal_protein", "data_unavailable"}
_FETAL_VOCAB = {"adult_and_fetal", "adult_only", "fetal_only", "none", "data_unavailable"}

_COLS = ["gene_symbol", "uniprot_ac", "tissue", "tissue_class", "median_log2_abundance",
         "median_intensity", "n_samples", "n_detected", "detection_rate"]


def _write_product(tmp_path, rows) -> Path:
    """rows: list of dicts (product schema). Writes a synthetic long/tidy parquet."""
    df = pd.DataFrame(rows, columns=_COLS)
    p = tmp_path / "tphp_normal.parquet"
    df.to_parquet(p, index=False)
    return p


def _row(gene, tissue, tclass, log2, det_rate=1.0, n_samples=5, n_detected=5, uac="P00533"):
    return {"gene_symbol": gene, "uniprot_ac": uac, "tissue": tissue, "tissue_class": tclass,
            "median_log2_abundance": log2, "median_intensity": 2.0 ** log2,
            "n_samples": n_samples, "n_detected": n_detected, "detection_rate": det_rate}


def test_summary_shape_matches_card_and_aggregates(tmp_path):
    # EGFR detected in 12 adult tissues (moderate) + 1 fetal group; highest = liver at 9.0.
    rows = [_row("EGFR", f"adult_tissue_{i:02d}", "adult_normal", 3.0 + 0.1 * i) for i in range(12)]
    rows.append(_row("EGFR", "liver", "adult_normal", 9.0))          # the top adult tissue
    rows.append(_row("EGFR", "ectoderm", "fetal", 4.0, det_rate=0.5))
    # a background gene so the pushdown must actually filter on gene_symbol
    rows += [_row("BRAF", f"adult_tissue_{i:02d}", "adult_normal", 1.0) for i in range(3)]
    prod = _write_product(tmp_path, rows)

    out = read.read_target_summary("EGFR", indication="COADREAD", product_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    assert out["normal_protein_breadth_class"] in _BREADTH_VOCAB
    assert out["fetal_vs_adult_flag"] in _FETAL_VOCAB
    # 13 adult tissues (12 + liver) → moderate (>=10, <35); 1 fetal group.
    assert out["n_adult_tissues_detected"] == 13
    assert out["n_fetal_groups_detected"] == 1
    assert out["n_tissues_detected"] == 14
    assert out["normal_protein_breadth_class"] == "moderate_normal_protein"
    assert out["fetal_vs_adult_flag"] == "adult_and_fetal"
    assert out["highest_abundance_tissue"] == "liver"
    assert out["highest_abundance_tissue_class"] == "adult_normal"
    assert out["max_median_log2_abundance"] == 9.0
    assert out["uniprot_ac"] == "P00533"
    assert out["n_adult_tissues_total"] == read.N_ADULT_TISSUES_TOTAL
    # the display list is sorted by abundance descending and only carries EGFR rows
    assert out["per_tissue_abundance"][0]["tissue"] == "liver"
    assert len(out["per_tissue_abundance"]) == 14
    assert out["method_version"] == read.METHOD_VERSION


def test_broad_breadth_reachable(tmp_path):
    """Detected in >=35 adult tissues → broad_normal_protein (a housekeeping-like broad footprint —
    the on-target-off-tumor liability the tumor-selectivity comparator surfaces)."""
    rows = [_row("ACTB", f"adult_tissue_{i:02d}", "adult_normal", 8.0) for i in range(40)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("ACTB", product_path=prod)
    assert out["normal_protein_breadth_class"] == "broad_normal_protein"
    assert out["fetal_vs_adult_flag"] == "adult_only"


def test_restricted_breadth_reachable(tmp_path):
    rows = [_row("DLL3", "brain", "adult_normal", 5.0), _row("DLL3", "testis", "adult_normal", 4.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("DLL3", product_path=prod)
    assert out["normal_protein_breadth_class"] == "restricted_normal_protein"
    assert out["n_adult_tissues_detected"] == 2


def test_fetal_only_is_not_detected_in_adult(tmp_path):
    rows = [_row("MAGEA3", "endoderm", "fetal", 6.0), _row("MAGEA3", "mesoderm", "fetal", 5.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("MAGEA3", product_path=prod)
    assert out["normal_protein_breadth_class"] == "not_detected_in_normal_protein"
    assert out["fetal_vs_adult_flag"] == "fetal_only"
    assert out["n_adult_tissues_detected"] == 0
    assert out["n_fetal_groups_detected"] == 2


def test_gene_absent_is_data_unavailable(tmp_path):
    rows = [_row("EGFR", "liver", "adult_normal", 9.0)]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["normal_protein_breadth_class"] == "data_unavailable"
    assert out["fetal_vs_adult_flag"] == "data_unavailable"
    assert out["per_tissue_abundance"] == []
    assert out["max_median_log2_abundance"] is None
    # the gap path still emits every card-declared field (headline/display read via get → None safely)
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_definitive_absence_degrades_not_crashes(monkeypatch):
    """A genuine 404-class fault → data_unavailable + _live_read_error (honest degrade)."""
    def _boom(*a, **k):
        raise FileNotFoundError("no such key")
    monkeypatch.setattr(read, "load_and_classify", _boom)
    out = read.read_target_summary("EGFR", indication="COADREAD")
    assert out["_live_read_error"] == "tphp_normal_protein_read_failed"
    assert out["normal_protein_breadth_class"] == "data_unavailable"
    assert out["method_version"] == read.METHOD_VERSION


def test_transient_fault_is_reraised(monkeypatch):
    """A transient / non-definitive error must NOT be masked as an empty normal footprint — re-raise
    so the live-read seam surfaces the infra failure (absence discipline)."""
    def _boom(*a, **k):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(read, "load_and_classify", _boom)
    with pytest.raises(RuntimeError):
        read.read_target_summary("EGFR")
