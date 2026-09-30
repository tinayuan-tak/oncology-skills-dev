"""tcga_gtex_tpm_quantiles — the pan-cancer by-tissue TPM distribution SUMMARY product.

The product precomputes per-(gene, source, group) five-number summaries of log2(TPM+1) from the
two long TPM products, stacked so TCGA-tumor (per study) + GTEx-normal (per tissue) share ONE gene
axis + ONE log2(TPM+1) unit. Tests build two tiny synthetic long products, run the real DuckDB
aggregation, and pin: the stacked source axis; the quantiles match numpy on the known input; the
sort key + dtypes; that the ensembl_gene_id axis is shared across sources.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("duckdb")
pytest.importorskip("pyarrow")


cli = importlib.import_module("onc_methods.tcga_gtex_tpm_quantiles.cli")


def _write_long(path: Path, group_col: str, rows: list[dict]) -> None:
    """rows: {gene_symbol, ensembl_gene_id, sample_id, <group_col>, log2_tpm}."""
    pd.DataFrame(rows).to_parquet(path, index=False)


def _make_products(tmp: Path):
    # GENEA in two TCGA studies (COAD, GBM) + one GTEx tissue (COLON). Known values so the
    # quantiles are checkable against numpy exactly.
    coad_vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    gbm_vals = [8.0, 9.0, 10.0]
    colon_vals = [0.5, 1.5, 2.5, 3.5]
    tcga_rows = [
        {"gene_symbol": "GENEA", "ensembl_gene_id": "ENSG1", "sample_id": f"t{i}", "study": "COAD", "log2_tpm": v}
        for i, v in enumerate(coad_vals)
    ] + [
        {"gene_symbol": "GENEA", "ensembl_gene_id": "ENSG1", "sample_id": f"g{i}", "study": "GBM", "log2_tpm": v}
        for i, v in enumerate(gbm_vals)
    ]
    gtex_rows = [
        {"gene_symbol": "GENEA", "ensembl_gene_id": "ENSG1", "sample_id": f"n{i}", "tissue": "COLON", "log2_tpm": v}
        for i, v in enumerate(colon_vals)
    ]
    tcga_p = tmp / "tcga_long.parquet"
    gtex_p = tmp / "gtex_long.parquet"
    _write_long(tcga_p, "study", tcga_rows)
    _write_long(gtex_p, "tissue", gtex_rows)
    return tcga_p, gtex_p, {"COAD": coad_vals, "GBM": gbm_vals, "COLON": colon_vals}


def test_stacked_source_axis_and_groups(tmp_path):
    tcga_p, gtex_p, _vals = _make_products(tmp_path)
    df = cli.build(str(tcga_p), str(gtex_p))
    assert set(df["source"]) == {"tcga_tumor", "gtex_normal"}
    tumor_groups = set(df[df["source"] == "tcga_tumor"]["group"])
    normal_groups = set(df[df["source"] == "gtex_normal"]["group"])
    assert tumor_groups == {"COAD", "GBM"} and normal_groups == {"COLON"}
    # shared ensembl axis across sources (the co-plot invariant)
    assert set(df["ensembl_gene_id"]) == {"ENSG1"}


def test_quantiles_match_numpy(tmp_path):
    tcga_p, gtex_p, vals = _make_products(tmp_path)
    df = cli.build(str(tcga_p), str(gtex_p))
    for group, expected in vals.items():
        row = df[df["group"] == group].iloc[0]
        a = np.asarray(expected, dtype=float)
        assert int(row["n"]) == len(expected)
        assert row["min"] == pytest.approx(a.min(), abs=1e-4)
        assert row["max"] == pytest.approx(a.max(), abs=1e-4)
        # quantile_cont == numpy 'linear' (both interpolate)
        assert row["median"] == pytest.approx(np.percentile(a, 50), abs=1e-4)
        assert row["q1"] == pytest.approx(np.percentile(a, 25), abs=1e-4)
        assert row["q3"] == pytest.approx(np.percentile(a, 75), abs=1e-4)
        assert row["mean"] == pytest.approx(a.mean(), abs=1e-4)


def test_sorted_and_dtypes(tmp_path):
    tcga_p, gtex_p, _vals = _make_products(tmp_path)
    df = cli.build(str(tcga_p), str(gtex_p))
    # sorted by (ensembl_gene_id, source, group)
    key = list(zip(df["ensembl_gene_id"], df["source"], df["group"]))
    assert key == sorted(key)
    assert str(df["n"].dtype) == "int32"
    for c in ("min", "q1", "median", "q3", "max", "mean"):
        assert str(df[c].dtype) == "float32"


def test_null_log2tpm_excluded(tmp_path):
    # a NaN log2_tpm row must not inflate n or perturb the quantile
    tcga_rows = [
        {"gene_symbol": "GENEB", "ensembl_gene_id": "ENSG2", "sample_id": "a", "study": "COAD", "log2_tpm": 5.0},
        {
            "gene_symbol": "GENEB",
            "ensembl_gene_id": "ENSG2",
            "sample_id": "b",
            "study": "COAD",
            "log2_tpm": float("nan"),
        },
    ]
    gtex_rows = [
        {"gene_symbol": "GENEB", "ensembl_gene_id": "ENSG2", "sample_id": "c", "tissue": "COLON", "log2_tpm": 1.0}
    ]
    tcga_p = tmp_path / "t.parquet"
    gtex_p = tmp_path / "g.parquet"
    _write_long(tcga_p, "study", tcga_rows)
    _write_long(gtex_p, "tissue", gtex_rows)
    df = cli.build(str(tcga_p), str(gtex_p))
    coad = df[(df["source"] == "tcga_tumor") & (df["group"] == "COAD")].iloc[0]
    assert int(coad["n"]) == 1 and coad["median"] == pytest.approx(5.0)
