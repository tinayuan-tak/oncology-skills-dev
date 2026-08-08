"""Unit tests for methods/sclc_dge_tumor_vs_gtex.

SCLC has no open raw counts (EGA-controlled), so its GTEx-lung contrast is Welch
on log2(TPM+1) rather than DESeq2 on counts. These tests pin three things:

  1. The reused Welch kernel is BYTE-IDENTICAL to dge_tcga_gtex_precompute's
     (the reuse contract — same math, only the input unit differs).
  2. compute_cell_c emits the OV/DESeq2 sensitivity schema with A/B = NaN and a
     correctly-derived cell C, WITHOUT network (a hand-built fixture is patched
     in for the two long-TPM reads).
  3. The emitted rows classify correctly through the REAL downstream classifier
     (`dge_deseq2.read._classify_selectivity_from_sensitivity`) — an up/sig gene
     → strong_tumor_selective; a flat gene → not_informative. This guards the
     cell-C-only `tvn_gtex_only` regime end-to-end.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = __import__("methods.sclc_dge_tumor_vs_gtex.cli", fromlist=["cli"])


# ---------------------------------------------------------------------------
# 1. Welch kernel parity with the sibling counts-based method
# ---------------------------------------------------------------------------
def test_welch_kernel_identical_to_sibling():
    """Our vendored _welch_deg must match dge_tcga_gtex_precompute._welch_deg exactly."""
    sibling = __import__("methods.dge_tcga_gtex_precompute.cli", fromlist=["cli"])
    rng = np.random.default_rng(0)
    for _ in range(20):
        a = rng.normal(3.0, 1.0, size=rng.integers(2, 40))
        b = rng.normal(1.0, 1.2, size=rng.integers(2, 40))
        assert cli._welch_deg(a, b) == sibling._welch_deg(a, b)


def test_welch_degenerate_cases():
    assert cli._welch_deg(np.array([1.0]), np.array([1.0, 2.0])) == (0.0, 1.0)  # <2 on a side
    lfc, p = cli._welch_deg(np.array([2.0, 2.0]), np.array([1.0, 1.0]))          # zero variance both
    assert lfc == pytest.approx(1.0) and p == 1.0


def test_welch_sign_is_tumor_minus_normal():
    lfc, _ = cli._welch_deg(np.array([5.0, 5.1, 4.9]), np.array([1.0, 1.1, 0.9]))
    assert lfc > 0  # tumor > normal → positive


def test_bh_correct_matches_sibling():
    sibling = __import__("methods.dge_tcga_gtex_precompute.cli", fromlist=["cli"])
    p = np.array([0.001, 0.5, 0.02, 0.9, 0.0001])
    np.testing.assert_allclose(cli._bh_correct(p), sibling._bh_correct(p))


# ---------------------------------------------------------------------------
# 2. compute_cell_c emits the sensitivity schema (cell C only), no network
# ---------------------------------------------------------------------------
def _fixture_frames():
    """Two long-TPM tidy frames: DLL3 strongly up in tumor, GAPDH flat.

    3 genes × (5 tumor + 6 gtex) samples. Values chosen so DLL3 is a clear,
    significant up-call and GAPDH is flat/non-significant.
    """
    genes = [("ENSG_DLL3", "DLL3"), ("ENSG_GAPDH", "GAPDH"), ("ENSG_XIST", "XIST")]
    tumor_rows, gtex_rows = [], []
    tumor_expr = {"ENSG_DLL3": [6.0, 6.2, 5.8, 6.1, 5.9],   # high in tumor
                  "ENSG_GAPDH": [10.0, 10.1, 9.9, 10.0, 10.2],
                  "ENSG_XIST": [0.1, 0.0, 0.2, 0.1, 0.0]}    # off in tumor
    gtex_expr = {"ENSG_DLL3": [0.5, 0.4, 0.6, 0.5, 0.3, 0.5],  # low in lung
                 "ENSG_GAPDH": [10.0, 9.9, 10.1, 10.0, 10.2, 9.8],
                 "ENSG_XIST": [3.0, 3.1, 2.9, 3.0, 3.2, 2.8]}   # higher in normal
    for ens, sym in genes:
        for i, v in enumerate(tumor_expr[ens]):
            tumor_rows.append((sym, ens, f"T{i}", "SCLC", v))
        for i, v in enumerate(gtex_expr[ens]):
            gtex_rows.append((sym, ens, f"G{i}", "LUNG", v))
    cols = ["gene_symbol", "ensembl_gene_id", "sample_id", "group", "log2_tpm"]
    tumor = pd.DataFrame(tumor_rows, columns=cols).rename(columns={"group": "study"})
    gtex = pd.DataFrame(gtex_rows, columns=cols).rename(columns={"group": "tissue"})
    return tumor, gtex


def test_compute_cell_c_schema_and_biology(monkeypatch):
    tumor, gtex = _fixture_frames()

    def fake_read(manifest_id, s3fs, group_col, group_val):
        if manifest_id == cli.TUMOR_PRODUCT:
            return tumor.copy(), "s3://fake/sclc"
        return gtex.copy(), "s3://fake/gtex"

    monkeypatch.setattr(cli, "_read_long_tpm", fake_read)
    df, prov = cli.compute_cell_c(s3fs=None)

    # schema: OV sensitivity columns present, A/B all NaN, C populated
    for col in ("gene_symbol", "cells_ran", "cells_supporting", "dominant_direction",
                "sig_all_cells", "discordant", "log2fc_A", "padj_A", "log2fc_B",
                "padj_B", "log2fc_C", "padj_C", "max_abs_log2fc"):
        assert col in df.columns
    assert df["log2fc_A"].isna().all() and df["log2fc_B"].isna().all()
    assert df["padj_A"].isna().all() and df["padj_B"].isna().all()
    assert df["log2fc_C"].notna().all()
    assert (df["cells_ran"] == 1.0).all()
    assert (~df["discordant"]).all()

    # provenance: cohort sizes + adjacent=0
    assert prov["n_tumor"] == 5 and prov["n_gtex"] == 6 and prov["n_adjacent"] == 0
    assert prov["n_genes"] == 3

    # biology: DLL3 up + significant; GAPDH flat
    dll3 = df[df["gene_symbol"] == "DLL3"].iloc[0]
    assert dll3["log2fc_C"] > 2.0 and dll3["dominant_direction"] == "up"
    assert dll3["cells_supporting"] == 1.0
    gapdh = df[df["gene_symbol"] == "GAPDH"].iloc[0]
    assert abs(gapdh["log2fc_C"]) < 0.5


def test_compute_cell_c_drops_unmapped_symbols(monkeypatch):
    tumor, gtex = _fixture_frames()
    # null out one gene's symbol in BOTH frames → it must be dropped from output
    tumor.loc[tumor["ensembl_gene_id"] == "ENSG_XIST", "gene_symbol"] = None
    gtex.loc[gtex["ensembl_gene_id"] == "ENSG_XIST", "gene_symbol"] = None

    def fake_read(manifest_id, s3fs, group_col, group_val):
        return (tumor.copy(), "s3://fake") if manifest_id == cli.TUMOR_PRODUCT \
            else (gtex.copy(), "s3://fake")

    monkeypatch.setattr(cli, "_read_long_tpm", fake_read)
    df, _ = cli.compute_cell_c(s3fs=None)
    assert "XIST" not in set(df["gene_symbol"])
    assert set(df["gene_symbol"]) == {"DLL3", "GAPDH"}


# ---------------------------------------------------------------------------
# 3. Emitted rows classify correctly through the REAL downstream classifier
# ---------------------------------------------------------------------------
def test_emitted_rows_classify_downstream(monkeypatch):
    """A cell-C-only up/sig row must land as strong_tumor_selective; a flat row as
    not_informative — via the real dge_deseq2 classifier, in the tvn_gtex_only regime."""
    read = pytest.importorskip("methods.dge_deseq2.read")
    tumor, gtex = _fixture_frames()

    def fake_read(manifest_id, s3fs, group_col, group_val):
        return (tumor.copy(), "s3://fake") if manifest_id == cli.TUMOR_PRODUCT \
            else (gtex.copy(), "s3://fake")

    monkeypatch.setattr(cli, "_read_long_tpm", fake_read)
    df, _ = cli.compute_cell_c(s3fs=None)

    def to_reader_row(sym):
        r = df[df["gene_symbol"] == sym].iloc[0]
        # mirror read_tumor_vs_normal_sensitivity_gene_row's uppercase→lowercase mapping
        return {
            "gene_symbol": sym,
            "cells_ran": r["cells_ran"],
            "cells_supporting": r["cells_supporting"],
            "dominant_direction": r["dominant_direction"],
            "sig_all_cells": r["sig_all_cells"],
            "discordant": r["discordant"],
            "max_abs_log2fc": r["max_abs_log2fc"],
            "log2fc_cell_a": r["log2fc_A"], "q_value_cell_a": r["padj_A"],
            "log2fc_cell_b": r["log2fc_B"], "q_value_cell_b": r["padj_B"],
            "log2fc_cell_c": r["log2fc_C"], "q_value_cell_c": r["padj_C"],
        }

    assert read._classify_selectivity_from_sensitivity(to_reader_row("DLL3")) == "strong_tumor_selective"
    assert read._classify_selectivity_from_sensitivity(to_reader_row("GAPDH")) == "not_informative"
