"""Credential-less tests for the TPHP tumor-vs-adjacent-normal PROTEIN reader.

No S3: a synthetic local per-cohort parquet (the derived product's schema — gene_symbol, uniprot_ac,
cohort, tissue, n_tumor, n_normal, median_log2_tumor, median_log2_normal, log2_fc, p_value, q_value,
effect) is read via the `product_path` offline seam. Pins:
  * the emitted summary carries EVERY field the tumor-vs-normal-protein-abundance-tphp card declares
    (the reader-real-field-names drift class the tumor-selectivity replay exists to catch);
  * the CPTAC-ALIGNED field names (protein_effect_size / protein_bh_q_value) the tumor-selectivity
    run.py `_rna_protein_tvn_concordance` projection consumes are present + carry the product values;
  * INDICATION_TO_TPHP_COHORT resolves an OncoTree/TCGA code → the matching free-text cohort;
  * a supplied-but-UNMAPPED indication → data_unavailable (never leaks another cohort's contrast);
  * no-indication → the largest-|effect_size| cohort row (pan-cancer / target-only);
  * a gene with NO rows → data_unavailable (a genuine coverage gap, absence discipline);
  * a genuine 404-class fault → data_unavailable + _live_read_error (never crashes the compose path);
  * a transient/creds error is RE-RAISED (never masked as an empty protein footprint).
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

read = importlib.import_module("methods.tphp_tumor_vs_normal_protein.read")

# The fields the tumor-vs-normal-protein-abundance-tphp card declares in outputs.summary_fields — the
# reader MUST emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "cohort",
    "tissue",
    "protein_expression_class",
    "protein_effect_size",
    "protein_median_log2_tumor",
    "protein_median_log2_normal",
    "protein_p_value",
    "protein_bh_q_value",
    "n_tumor_samples",
    "n_normal_samples",
    "uniprot_ac",
    "stat_test_used",
    "method_version",
}
_EFFECT_VOCAB = {"strong_up", "modest_up", "unchanged", "modest_down", "strong_down", "data_unavailable"}

_COLS = [
    "gene_symbol",
    "uniprot_ac",
    "cohort",
    "tissue",
    "n_tumor",
    "n_normal",
    "median_log2_tumor",
    "median_log2_normal",
    "log2_fc",
    "p_value",
    "q_value",
    "effect",
]


def _row(gene, cohort, tissue, log2_fc, effect, q=0.001, n_tumor=40, n_normal=6, med_t=None, med_n=None, uac="P40199"):
    med_n = 5.0 if med_n is None else med_n
    med_t = (med_n + log2_fc) if med_t is None else med_t
    return {
        "gene_symbol": gene,
        "uniprot_ac": uac,
        "cohort": cohort,
        "tissue": tissue,
        "n_tumor": n_tumor,
        "n_normal": n_normal,
        "median_log2_tumor": med_t,
        "median_log2_normal": med_n,
        "log2_fc": log2_fc,
        "p_value": q / 2.0,
        "q_value": q,
        "effect": effect,
    }


def _write_product(tmp_path, rows) -> Path:
    df = pd.DataFrame(rows, columns=_COLS)
    p = tmp_path / "tphp_tvn.parquet"
    df.to_parquet(p, index=False)
    return p


def _fixture(tmp_path):
    # CEACAM5 across three cohorts; strongest tumor-up in Colon carcinoma (log2fc=3.0). Plus a
    # background gene so the pushdown must actually filter on gene_symbol.
    rows = [
        _row("CEACAM5", "Colon carcinoma", "colon", 3.0, "strong_up", q=1e-6),
        _row("CEACAM5", "Rectum carcinoma", "rectum", 2.2, "strong_up", q=1e-4),
        _row("CEACAM5", "Gastric carcinoma", "stomach", 0.4, "unchanged", q=0.30),
        _row("BRAF", "Colon carcinoma", "colon", 0.1, "unchanged", q=0.8, uac="P15056"),
    ]
    return _write_product(tmp_path, rows)


def test_summary_shape_matches_card_and_cptac_aligned(tmp_path):
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="COADREAD", product_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    # COADREAD → "Colon carcinoma" (mirrors the CPTAC COADREAD→COAD choice)
    assert out["cohort"] == "Colon carcinoma"
    assert out["tissue"] == "colon"
    assert out["protein_expression_class"] in _EFFECT_VOCAB
    assert out["protein_expression_class"] == "strong_up"
    # CPTAC-ALIGNED names carry the product's log2_fc / q_value (the projection consumes these).
    assert out["protein_effect_size"] == 3.0
    assert out["protein_bh_q_value"] == pytest.approx(1e-6)
    assert out["protein_median_log2_tumor"] == pytest.approx(8.0)
    assert out["protein_median_log2_normal"] == pytest.approx(5.0)
    assert out["n_tumor_samples"] == 40
    assert out["n_normal_samples"] == 6
    assert out["uniprot_ac"] == "P40199"
    assert out["stat_test_used"] == read.STAT_TEST
    assert out["method_version"] == read.METHOD_VERSION


def test_cptac_aligned_fields_feed_concordance_projection(tmp_path):
    """The two keys the tumor-selectivity `_rna_protein_tvn_concordance(rna_dir, effect, q)` projection
    reads — protein_effect_size + protein_bh_q_value — must be present + non-null on a real cohort so
    the SAME projection that runs over the CPTAC card summary consumes THIS card unchanged."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="READ", product_path=prod)
    assert out["cohort"] == "Rectum carcinoma"
    assert out["protein_effect_size"] is not None and out["protein_bh_q_value"] is not None
    # sign + significance the projection keys on: q<0.05, effect>0 → would read concordant with RNA-up.
    assert out["protein_effect_size"] > 0 and out["protein_bh_q_value"] < 0.05


def test_unmapped_indication_is_data_unavailable_no_leak(tmp_path):
    """A supplied-but-unmapped indication must NOT leak another cohort's contrast (the product is a
    PER-COHORT differential). BRCA has no unambiguous single TPHP cohort → data_unavailable."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="BRCA", product_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["cohort"] is None
    assert out["protein_effect_size"] is None
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_no_indication_returns_best_effect_cohort(tmp_path):
    """Target-only / pan-cancer query (no indication) → the largest-|effect_size| cohort row."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", product_path=prod)
    assert out["cohort"] == "Colon carcinoma"  # |3.0| is the max across the three cohorts
    assert out["protein_effect_size"] == 3.0


def test_gene_absent_is_data_unavailable(tmp_path):
    prod = _fixture(tmp_path)
    out = read.read_target_summary("GHOSTGENE", indication="COADREAD", product_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["cohort"] is None
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_target_absent_from_mapped_cohort_is_data_unavailable(tmp_path):
    """Gene present in the product but NOT quantified in the mapped cohort → data_unavailable (honest;
    the gene's rows exist for other cohorts but not the queried one)."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="GBM", product_path=prod)  # no Glioblastoma row
    assert out["protein_expression_class"] == "data_unavailable"
    assert "cohort" in out


def test_read_all_cohorts_sorted_by_abs_effect(tmp_path):
    prod = _fixture(tmp_path)
    panel = read.read_all_cohorts("CEACAM5", product_path=prod)
    assert [r["cohort"] for r in panel] == ["Colon carcinoma", "Rectum carcinoma", "Gastric carcinoma"]
    assert panel[0]["protein_effect_size"] == 3.0


def test_indication_map_values_are_verbatim_cohorts():
    """Every mapped cohort string must be one of the product's real cohort names (guards a typo in the
    free-text map — enumerated from S3 2026-08-25)."""
    real_cohorts = {
        "Breast carcinoma (Luminal A)",
        "Breast carcinoma (Luminal B, HER2-)",
        "Breast carcinoma (TNBC)",
        "Cervical carcinoma",
        "Colon carcinoma",
        "Diffused large B-cell carcinoma",
        "Endometrial carcinoma",
        "Esophageal carcinoma",
        "Fallopian tube carcinoma",
        "Gallbladder carcinoma",
        "Gastric carcinoma",
        "Gastrointestinal stromal tumors",
        "Glioblastoma",
        "Hepatocellular carcinoma",
        "Laryngocarcinoma",
        "Lung carcinoma",
        "Pancreas carcinoma",
        "Rectum carcinoma",
        "Renal carcinoma",
        "Testis carcinoma",
        "Thymoma and thymic carcinoma",
        "Tongue carcinoma",
    }
    unknown = set(read.INDICATION_TO_TPHP_COHORT.values()) - real_cohorts
    assert not unknown, f"INDICATION_TO_TPHP_COHORT maps to non-existent cohort(s): {sorted(unknown)}"


def test_definitive_absence_degrades_not_crashes(monkeypatch):
    """A genuine 404-class fault → data_unavailable + _live_read_error (honest degrade)."""

    def _boom(*a, **k):
        raise FileNotFoundError("no such key")

    monkeypatch.setattr(read, "_read_rows_from_derived", _boom)
    out = read.read_target_summary("CEACAM5", indication="COADREAD")
    assert out["_live_read_error"] == "tphp_tumor_vs_normal_protein_read_failed"
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["method_version"] == read.METHOD_VERSION


def test_transient_fault_is_reraised(monkeypatch):
    """A transient / non-definitive error must NOT be masked as an empty protein footprint — re-raise
    so the live-read seam surfaces the infra failure (absence discipline)."""

    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(read, "_read_rows_from_derived", _boom)
    with pytest.raises(RuntimeError):
        read.read_target_summary("CEACAM5", indication="COADREAD")
