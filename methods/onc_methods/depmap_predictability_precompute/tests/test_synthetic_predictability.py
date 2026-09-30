"""Synthetic-data tests for depmap_predictability_precompute v2.

No S3, no boto3, no XGBoost required. Builds small in-memory matrices to
exercise: gene-symbol extractor, gene-set selector, lineage one-hot builder,
arm-CN assignment logic, OncoKB driver-flag builder, feature-matrix assembly,
per-fold RF+optional-XGB training, bootstrap CI, classification, and parquet
schema.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from onc_methods.depmap_predictability_precompute import cli as e5cli
from onc_methods.depmap_predictability_precompute import features as feat

# ---------- Symbol extraction --------------------------------------------


@pytest.mark.parametrize(
    "col, expected",
    [
        ("KRAS", "KRAS"),
        ("KRAS (3845)", "KRAS"),
        ('"KRAS (3845)"', "KRAS"),
        ("BRCA1 (672)", "BRCA1"),
        ("AC10.4 (1234)", "AC10.4"),
        ("HLA-A (3105)", "HLA-A"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_extract_symbol(col, expected):
    assert feat.extract_symbol(col) == expected


# ---------- ENSG → HGNC resolution at feature naming (#806) ----------------


def test_extract_symbol_resolves_ensembl_id(monkeypatch):
    """A bare Ensembl-ID header resolves to its HGNC symbol via the sidecar map,
    so cross-gene feature names ship symbol-keyed (cn_<SYMBOL>, not cn_ENSG…)."""
    # Inject the sidecar cache directly — no S3.
    monkeypatch.setattr(
        feat,
        "_ensg_symbol_map",
        {"ENSG00000258790": "GOLGA8N", "ENSG00000141510": "TP53"},
    )
    assert feat.extract_symbol("ENSG00000258790") == "GOLGA8N"
    # A cn_ENSG… column (as in the FR kras_coadread fixture) now names cn_GOLGA8N.
    assert f"cn_{feat.extract_symbol('ENSG00000258790')}" == "cn_GOLGA8N"
    # Version suffix is stripped before lookup.
    assert feat.extract_symbol("ENSG00000141510.17") == "TP53"


def test_extract_symbol_unmapped_ensembl_id_falls_back(monkeypatch):
    """A genuinely-unmapped ENSG keeps its Ensembl ID as a breadcrumb (not dropped)."""
    monkeypatch.setattr(feat, "_ensg_symbol_map", {"ENSG00000141510": "TP53"})
    assert feat.extract_symbol("ENSG99999999999") == "ENSG99999999999"


def test_ensg_symbol_map_absent_sidecar_falls_back(monkeypatch):
    """If the sidecar can't be read, the loader returns {} and naming keeps the ENSG id."""

    def _boom(*a, **k):
        raise RuntimeError("no S3 in tests")

    monkeypatch.setattr(feat, "_ensg_symbol_map", None)
    monkeypatch.setattr(feat, "_s3_read_csv", _boom)
    assert feat._load_ensg_symbol_map() == {}
    assert feat.extract_symbol("ENSG00000258790") == "ENSG00000258790"


# ---------- Feature-class mapping -----------------------------------------


@pytest.mark.parametrize(
    "fname, expected",
    [
        ("own_expression", "own_expression"),
        ("own_copy_number", "own_copy_number"),
        ("own_mut_hotspot", "own_mut_hotspot"),
        ("own_mut_damaging", "own_mut_damaging"),
        ("expr_TP53", "cross_gene_expression"),
        ("cn_MYC", "cross_gene_copy_number"),
        ("arm_chr12p", "arm_level_cn"),
        ("driver_KRAS_GoF", "oncokb_gof"),
        ("driver_TP53_LoF", "oncokb_lof"),
        ("lineage_Bowel", "lineage"),
        ("something_else", "other"),
    ],
)
def test_feature_class_of(fname, expected):
    assert feat.feature_class_of(fname) == expected


# ---------- Lineage one-hot with sub-min collapse -------------------------


def test_lineage_one_hot_collapse_small_lineages():
    model = pd.DataFrame(
        {
            "ModelID": [f"ACH-{i:06d}" for i in range(10)],
            "OncotreeLineage": (["X"] * 6) + (["Y"] * 4),
        }
    )
    oh = feat.build_lineage_one_hot(model, min_lines_per_lineage=5)
    assert "lineage_X" in oh.columns
    assert "lineage_OTHER" in oh.columns
    assert "lineage_Y" not in oh.columns
    assert (oh.sum(axis=1) == 1).all()


# ---------- Arm assignment logic (cytoband + coords) ----------------------


def test_assign_genes_to_arms_basic():
    coords = pd.DataFrame(
        {
            "hgnc_symbol": ["KRAS", "MYC", "TP53"],
            "chrom_name": ["12", "8", "17"],
            "gene_start": [25358180, 127735434, 7668421],
            "gene_end": [25403854, 127741434, 7687490],
        }
    )
    cytoband = pd.DataFrame(
        {
            "chrom": ["chr12", "chr12", "chr8", "chr17"],
            "chromStart": [0, 35000000, 100000000, 0],
            "chromEnd": [35000000, 133275309, 145138636, 30000000],
            "name": ["p13.33", "q11.21", "q24.13", "p13.3"],
            "gieStain": ["gneg", "gneg", "gpos25", "gneg"],
        }
    )
    gene_to_arm = feat.assign_genes_to_arms(coords, cytoband)
    assert gene_to_arm["KRAS"] == "chr12p"  # position on p-arm of chr12
    assert gene_to_arm["MYC"] == "chr8q"  # q-arm of chr8
    assert gene_to_arm["TP53"] == "chr17p"  # p-arm of chr17


# ---------- OncoKB driver flag builder ------------------------------------


def test_compute_oncokb_driver_flags_maps_correctly():
    oncokb = pd.DataFrame(
        {
            "hugoSymbol": ["KRAS", "TP53", "MYC"],
            "geneType": ["ONCOGENE", "TSG", "ONCOGENE"],
        }
    )
    lines = [f"ACH-{i:06d}" for i in range(5)]
    hotspot = pd.DataFrame(
        {
            "KRAS": [1, 0, 1, 0, 0],
            "MYC": [0, 0, 0, 0, 0],
            "TP53": [0, 0, 0, 1, 0],
        },
        index=pd.Index(lines, name="ModelID"),
    ).astype("int8")
    damaging = pd.DataFrame(
        {
            "KRAS": [0, 0, 0, 0, 0],
            "TP53": [0, 1, 1, 0, 1],
            "MYC": [0, 0, 0, 0, 0],
        },
        index=pd.Index(lines, name="ModelID"),
    ).astype("int8")
    flags = feat.compute_oncokb_driver_flags(oncokb, hotspot, damaging)
    # KRAS oncogene → GoF column from hotspot
    assert "driver_KRAS_GoF" in flags.columns
    assert list(flags["driver_KRAS_GoF"]) == [1, 0, 1, 0, 0]
    # TP53 TSG → LoF column from damaging
    assert "driver_TP53_LoF" in flags.columns
    assert list(flags["driver_TP53_LoF"]) == [0, 1, 1, 0, 1]
    # MYC has no mutation → GoF column all zero
    assert "driver_MYC_GoF" in flags.columns
    assert flags["driver_MYC_GoF"].sum() == 0
    # No TP53_GoF or KRAS_LoF (not eligible per role)
    assert "driver_TP53_GoF" not in flags.columns
    assert "driver_KRAS_LoF" not in flags.columns


# ---------- build_gene_feature_matrix (integration) -----------------------


def _make_omics_bundle(n_lines=200, gene_of_interest="KRAS"):
    """Build a minimal omics bundle with 3 genes (KRAS, TP53, MYC) and one
    chronos target correlated with own_expression."""
    rng = np.random.default_rng(0)
    model_ids = [f"ACH-{i:06d}" for i in range(n_lines)]
    lineages = (["A"] * (n_lines // 3)) + (["B"] * (n_lines // 3))
    lineages += ["C"] * (n_lines - len(lineages))
    model_df = pd.DataFrame({"ModelID": model_ids, "OncotreeLineage": lineages})

    # Expression: KRAS's own_expression drives its chronos
    expr_kras = rng.normal(3, 1, n_lines).astype(np.float32)
    y = -2.0 + 0.5 * expr_kras + rng.normal(0, 0.1, n_lines).astype(np.float32)
    idx = pd.Index(model_ids, name="ModelID")

    chronos = pd.DataFrame(
        {
            gene_of_interest: y,
            "TP53": rng.normal(-0.3, 0.3, n_lines).astype(np.float32),
            "MYC": rng.normal(-0.5, 0.4, n_lines).astype(np.float32),
        },
        index=idx,
    )
    expression = pd.DataFrame(
        {
            gene_of_interest: expr_kras,
            "TP53": rng.normal(4, 1, n_lines).astype(np.float32),
            "MYC": rng.normal(5, 1, n_lines).astype(np.float32),
        },
        index=idx,
    )
    cn = pd.DataFrame(
        {
            gene_of_interest: rng.normal(1.0, 0.1, n_lines).astype(np.float32),
            "TP53": rng.normal(1.0, 0.1, n_lines).astype(np.float32),
            "MYC": rng.normal(1.0, 0.1, n_lines).astype(np.float32),
        },
        index=idx,
    )
    mh = pd.DataFrame(
        {
            gene_of_interest: np.zeros(n_lines, dtype="int8"),
            "TP53": np.zeros(n_lines, dtype="int8"),
            "MYC": np.zeros(n_lines, dtype="int8"),
        },
        index=idx,
    )
    md = mh.copy()
    lineage_oh = feat.build_lineage_one_hot(model_df, min_lines_per_lineage=5)
    # Empty derived matrices
    arm_cn = pd.DataFrame(index=idx)
    driver_flags = pd.DataFrame(index=idx)
    return {
        "chronos": chronos,
        "expression": expression,
        "copy_number": cn,
        "mut_hotspot": mh,
        "mut_damaging": md,
        "lineage_one_hot": lineage_oh,
        "arm_level_cn": arm_cn,
        "driver_flags": driver_flags,
        "model_df": model_df,
    }


def test_build_gene_feature_matrix_assembles_and_has_own_cols():
    omics = _make_omics_bundle()
    fm = feat.build_gene_feature_matrix("KRAS", omics, min_cell_lines=50)
    assert fm is not None
    X, y, names = fm["X"], fm["y"], fm["feature_names"]
    assert X.shape[0] == y.shape[0] >= 50
    assert "own_expression" in names
    assert "own_copy_number" in names
    # Cross-gene expression should include TP53 + MYC but not KRAS (own is separate)
    assert "expr_TP53" in names and "expr_MYC" in names
    assert "expr_KRAS" not in names
    assert any(n.startswith("lineage_") for n in names)


def test_build_gene_feature_matrix_missing_target_returns_none():
    omics = _make_omics_bundle()
    fm = feat.build_gene_feature_matrix("NOT_A_GENE", omics, min_cell_lines=50)
    assert fm is None


# ---------- Bootstrap CI on r² --------------------------------------------


def test_bootstrap_r2_ci_returns_reasonable_bounds():
    rng = np.random.default_rng(0)
    n = 500
    y_true = rng.normal(0, 1, n)
    # A strong-signal case: y_oof correlated with truth
    y_oof = 0.7 * y_true + 0.3 * rng.normal(0, 1, n)
    lo, hi = e5cli.bootstrap_r2_ci(y_oof, y_true, n=100)
    assert 0 <= lo <= hi <= 1
    # Point r² should be ~0.5; CI should span it
    r_point = e5cli._pearson_r(y_oof, y_true)
    r2_point = r_point**2
    assert lo - 0.15 <= r2_point <= hi + 0.15


# ---------- QuantileKFold split invariants --------------------------------


def test_quantile_kfold_partitions_exclusively_and_stratifies():
    rng = np.random.default_rng(0)
    y = rng.normal(0, 1, 300)
    X = rng.normal(0, 1, (300, 5))
    splitter = e5cli.QuantileKFold(n_splits=3, random_state=42)
    all_test_indices = []
    for train, test in splitter.split(X, y):
        assert len(set(train).intersection(set(test))) == 0
        all_test_indices.extend(test.tolist())
    # Each sample appears in exactly one test fold
    assert sorted(all_test_indices) == list(range(300))


# ---------- Classifier boundaries ----------------------------------------


@pytest.mark.parametrize(
    "r2_rf, r2_ci_lo, top_class, expected",
    [
        (0.5, 0.4, "own_expression", "own_omics_driven"),
        (0.45, 0.35, "own_mut_hotspot", "own_omics_driven"),
        (0.55, 0.4, "lineage", "context_or_driver_dependent"),
        (0.55, 0.4, "arm_level_cn", "context_or_driver_dependent"),
        (0.55, 0.4, "oncokb_gof", "context_or_driver_dependent"),
        (0.3, 0.15, "own_expression", "weakly_predictable"),
        (0.2, 0.05, "cross_gene_expression", "weakly_predictable"),
        (0.1, 0.02, "own_expression", "unpredictable"),
    ],
)
def test_classify_boundaries(r2_rf, r2_ci_lo, top_class, expected):
    pred, _ = e5cli._classify(r2_rf, r2_ci_lo, top_class)
    assert pred == expected


# ---------- train_gene end-to-end (with real RF, small feature-space) ----


def test_train_gene_recovers_own_omics_signal():
    omics = _make_omics_bundle(n_lines=300)
    rec = e5cli.train_gene("KRAS", omics)
    assert rec is not None
    assert rec["gene_symbol"] == "KRAS"
    # Signal is intentionally strong (KRAS Chronos = f(KRAS expression))
    assert rec["pearson_r_squared_rf"] > 0.4
    assert rec["top_features_rf_shap"][0]["feature"] == "own_expression"
    assert rec["predictability_class"] in ("own_omics_driven", "weakly_predictable")


# ---------- Parquet schema (v2) --------------------------------------------


def test_write_parquet_v2_schema(tmp_path):
    rec = {
        "gene_symbol": "KRAS",
        "n_cell_lines_evaluated": 1500,
        "pearson_r_rf": 0.62,
        "pearson_r_squared_rf": 0.38,
        "pearson_r_squared_rf_ci_lo": 0.31,
        "pearson_r_squared_rf_ci_hi": 0.44,
        "top_features_rf_shap": [
            {
                "feature": "own_mut_hotspot",
                "feature_class": "own_mut_hotspot",
                "importance": 0.15,
                "rf_importance": 0.12,
            },
        ],
        "dominant_feature_class": "own_mut_hotspot",
        "predictability_class": "own_omics_driven",
        "per_lineage_predictability": [
            {"lineage": "Bowel", "n_cell_lines": 80, "r2": 0.55, "top_feature": "own_mut_hotspot"},
        ],
    }
    out = tmp_path / "predictability_per_gene.parquet"
    e5cli.write_parquet([rec], out)
    assert out.exists()
    tbl = pq.read_table(out)
    assert "pearson_r_squared_rf_ci_lo" in tbl.column_names
    assert "per_lineage_predictability" in tbl.column_names
    # #807: retired XGB dual-model columns must not be in the schema.
    for retired in ("pearson_r_xgb", "pearson_r_squared_xgb", "model_agreement", "delta_r2", "top_features_xgb_shap"):
        assert retired not in tbl.column_names
    # Predicate pushdown works
    krastable = pq.read_table(out, filters=[("gene_symbol", "=", "KRAS")])
    assert krastable.num_rows == 1
    assert krastable.column("predictability_class")[0].as_py() == "own_omics_driven"
