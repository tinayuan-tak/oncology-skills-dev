"""Synthetic-data tests for depmap_predictability_precompute.

No S3 / no boto3 needed. Builds small in-memory matrices that simulate the
DepMap layout and exercises the gene-symbol extractor, gene-set selector,
feature-matrix builder, RF trainer, and parquet writer in isolation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add the methods/ directory to sys.path so we can import the package as
# `depmap_predictability_precompute` (matches how the live framework imports it
# via _live_readers.py's _import_method helper).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_predictability_precompute import cli as e5cli  # noqa: E402


# ---------- _extract_symbol --------------------------------------------------

@pytest.mark.parametrize("col, expected", [
    ("KRAS", "KRAS"),
    ("KRAS (3845)", "KRAS"),
    ('"KRAS (3845)"', "KRAS"),
    ("BRCA1 (672)", "BRCA1"),
    ("AC10.4 (1234)", "AC10.4"),    # dot in symbol
    ("HLA-A (3105)", "HLA-A"),       # hyphen
    ("", None),
    ("   ", None),
    (None, None),
])
def test_extract_symbol(col, expected):
    assert e5cli._extract_symbol(col) == expected


# ---------- build_medium_gene_set -------------------------------------------

def _make_synthetic_chronos(n_lines=60, lineages=("A", "A", "A", "A", "A",
                                                     "B", "B", "B", "B", "B",
                                                     "C", "C", "C", "C", "C")):
    """Build a chronos DataFrame and accompanying Model.csv-shaped df where:
       - geneALPHA is strongly selective in lineage A only (median Chronos ~ -1.5)
       - geneBETA is flat across all lineages (median ~ 0)
       - geneGAMMA is moderately essential pan-cancer (median ~ -0.4)
    """
    rng = np.random.default_rng(42)
    # Tile the lineage pattern to reach n_lines
    cycles = (n_lines // len(lineages)) + 1
    full_lineages = (list(lineages) * cycles)[:n_lines]
    model_ids = [f"ACH-{i:06d}" for i in range(n_lines)]
    df = pd.DataFrame(index=pd.Index(model_ids, name="ModelID"),
                       columns=["geneALPHA", "geneBETA", "geneGAMMA"], dtype=float)
    for i, lin in enumerate(full_lineages):
        df.iloc[i, 0] = (rng.normal(-1.5, 0.2) if lin == "A" else rng.normal(0.0, 0.2))  # geneALPHA
        df.iloc[i, 1] = rng.normal(0.0, 0.2)                                             # geneBETA flat
        df.iloc[i, 2] = rng.normal(-0.4, 0.2)                                            # geneGAMMA
    model_meta = pd.DataFrame({"ModelID": model_ids, "OncotreeLineage": full_lineages})
    return df, model_meta


def test_build_medium_gene_set_selectivity():
    chronos, model = _make_synthetic_chronos()
    selected = e5cli.build_medium_gene_set(chronos, model,
                                              min_lines_per_lineage=5, threshold=0.3)
    # geneALPHA selected via lineage A's strong dependency (median -1.5)
    assert "geneALPHA" in selected
    # geneBETA flat (median ~0) should NOT be selected
    assert "geneBETA" not in selected
    # geneGAMMA is borderline (median -0.4 > 0.3) — should be selected
    assert "geneGAMMA" in selected


def test_build_medium_gene_set_min_lines_filter():
    # All lineages have only 3 cells each → no lineage qualifies → empty selection
    chronos, model = _make_synthetic_chronos(n_lines=9,
                                                 lineages=("A", "A", "A", "B", "B", "B", "C", "C", "C"))
    selected = e5cli.build_medium_gene_set(chronos, model,
                                              min_lines_per_lineage=5, threshold=0.3)
    assert selected == []


# ---------- build_lineage_one_hot -------------------------------------------

def test_lineage_one_hot_collapse_small_lineages():
    model = pd.DataFrame({
        "ModelID": [f"ACH-{i:06d}" for i in range(10)],
        # 6 of lineage X, 4 of lineage Y. With min=5, Y collapses to OTHER.
        "OncotreeLineage": (["X"] * 6) + (["Y"] * 4),
    })
    oh, cols = e5cli.build_lineage_one_hot(model, min_lines_per_lineage=5)
    assert "lineage_X" in cols
    assert "lineage_OTHER" in cols
    assert "lineage_Y" not in cols
    # Sum across rows of one-hot must equal 1 (each row picks exactly one bucket)
    assert (oh.sum(axis=1) == 1).all()


# ---------- build_feature_matrix_for_gene -----------------------------------

def _make_omics_for_one_gene(gene="geneALPHA", n_lines=120,
                                 own_expr_signal=True):
    """Construct a complete omics dict where:
       - chronos for `gene` is strongly correlated with own_expression
       - other cells have a flat distribution
    """
    rng = np.random.default_rng(0)
    model_ids = [f"ACH-{i:06d}" for i in range(n_lines)]
    lineages = (["A"] * (n_lines // 3)) + (["B"] * (n_lines // 3))
    lineages += ["C"] * (n_lines - len(lineages))
    model = pd.DataFrame({"ModelID": model_ids, "OncotreeLineage": lineages})
    expr = rng.normal(3, 1, n_lines).astype(np.float32)
    if own_expr_signal:
        y = -2.0 + 0.5 * expr + rng.normal(0, 0.1, n_lines).astype(np.float32)
    else:
        y = rng.normal(-0.5, 1.0, n_lines).astype(np.float32)
    chronos = pd.DataFrame({gene: y}, index=pd.Index(model_ids, name="ModelID"))
    expression = pd.DataFrame({gene: expr}, index=pd.Index(model_ids, name="ModelID"))
    cn = pd.DataFrame({gene: rng.normal(1.0, 0.1, n_lines).astype(np.float32)},
                        index=pd.Index(model_ids, name="ModelID"))
    mut_hot = pd.DataFrame({gene: np.zeros(n_lines, dtype="int8")},
                              index=pd.Index(model_ids, name="ModelID"))
    mut_dmg = mut_hot.copy()
    lineage_oh, _ = e5cli.build_lineage_one_hot(model, min_lines_per_lineage=5)
    return {
        "chronos": chronos, "expression": expression, "copy_number": cn,
        "mut_hotspot": mut_hot, "mut_damaging": mut_dmg, "lineage_one_hot": lineage_oh,
    }


def test_build_feature_matrix_assembles_correctly():
    omics = _make_omics_for_one_gene()
    X, y, fnames, mids = e5cli.build_feature_matrix_for_gene("geneALPHA", omics)
    assert X is not None
    assert X.shape[0] == y.shape[0]
    # 4 own-omics columns + at least one lineage one-hot column
    assert X.shape[1] >= 5
    assert "own_expression" in fnames
    assert "own_copy_number" in fnames
    assert any(f.startswith("lineage_") for f in fnames)


def test_build_feature_matrix_missing_target_returns_none():
    omics = _make_omics_for_one_gene()
    X, y, _, _ = e5cli.build_feature_matrix_for_gene("not_a_gene", omics)
    assert X is None and y is None


# ---------- train_one_gene → classification ---------------------------------

def test_train_one_gene_recovers_own_omics_signal():
    """When chronos is strongly correlated with own_expression, the trained
    model's top feature should be own_expression and the class own_omics_driven."""
    omics = _make_omics_for_one_gene(own_expr_signal=True)
    X, y, fnames, _ = e5cli.build_feature_matrix_for_gene("geneALPHA", omics)
    rec = e5cli.train_one_gene("geneALPHA", X, y, fnames, n_estimators=50, cv_n_splits=3)
    assert rec["gene_symbol"] == "geneALPHA"
    assert rec["predictability_r2"] > 0.5
    assert rec["predictability_class"] == "own_omics_driven"
    assert rec["top_features"][0]["feature"] == "own_expression"
    assert rec["dominant_feature_class"] == "own_expression"


def test_train_one_gene_unpredictable_when_pure_noise():
    omics = _make_omics_for_one_gene(own_expr_signal=False)
    X, y, fnames, _ = e5cli.build_feature_matrix_for_gene("geneALPHA", omics)
    rec = e5cli.train_one_gene("geneALPHA", X, y, fnames, n_estimators=50, cv_n_splits=3)
    # No real signal → r2 should be ≤ R2_MODERATE (0.3); class = unpredictable
    assert rec["predictability_r2"] < e5cli.R2_HIGH
    assert rec["predictability_class"] in ("unpredictable", "weakly_predictable")


# ---------- _classify_predictability boundaries -----------------------------

@pytest.mark.parametrize("top_feature, r2, expected_class", [
    ("own_expression", 0.7, "own_omics_driven"),
    ("own_copy_number", 0.55, "own_omics_driven"),
    ("own_mut_hotspot", 0.6, "own_omics_driven"),
    ("own_mut_damaging", 0.51, "own_omics_driven"),
    ("lineage_Bowel", 0.65, "lineage_driven"),
    ("own_expression", 0.4, "weakly_predictable"),
    ("lineage_Lung", 0.35, "weakly_predictable"),
    ("own_expression", 0.1, "unpredictable"),
    ("lineage_OTHER", 0.05, "unpredictable"),
])
def test_classify_predictability_boundaries(top_feature, r2, expected_class):
    pred, _ = e5cli._classify_predictability(top_feature, r2)
    assert pred == expected_class


# ---------- write_parquet → schema + row-group --------------------------------

def test_write_parquet_schema_and_predicate_pushdown(tmp_path):
    import pyarrow.parquet as pq
    records = [
        {
            "gene_symbol": "KRAS",
            "n_cell_lines_evaluated": 1200,
            "predictability_r2": 0.62,
            "top_features": [
                {"feature": "own_mut_hotspot", "feature_class": "own_mut_hotspot", "importance": 0.45},
                {"feature": "lineage_Bowel", "feature_class": "lineage", "importance": 0.20},
            ],
            "dominant_feature_class": "own_mut_hotspot",
            "predictability_class": "own_omics_driven",
        },
        {
            "gene_symbol": "TP53",
            "n_cell_lines_evaluated": 1300,
            "predictability_r2": 0.18,
            "top_features": [
                {"feature": "own_mut_damaging", "feature_class": "own_mut_damaging", "importance": 0.10},
            ],
            "dominant_feature_class": "unpredictable",
            "predictability_class": "unpredictable",
        },
    ]
    out_file = tmp_path / "predictability_per_gene.parquet"
    e5cli.write_parquet(records, out_file)
    assert out_file.exists()
    # Schema check
    table = pq.read_table(out_file)
    assert table.column_names == [
        "gene_symbol", "n_cell_lines_evaluated", "predictability_r2",
        "top_features", "dominant_feature_class", "predictability_class",
    ]
    # Predicate pushdown for KRAS
    krastable = pq.read_table(out_file, filters=[("gene_symbol", "=", "KRAS")])
    assert krastable.num_rows == 1
    assert krastable.column("predictability_class")[0].as_py() == "own_omics_driven"
    assert krastable.column("top_features")[0].as_py()[0]["feature"] == "own_mut_hotspot"
