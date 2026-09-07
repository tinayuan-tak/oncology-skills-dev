"""Unit tests for methods/depmap_coessentiality/compute.py.

All tests are synthetic (no S3, no large parquet). The key invariants:

1. standardize() correctly z-scores columns; NaN mean-imputed (post-center → 0).
2. pearson_matrix() == Z.T @ Z / (n-1); diagonal is 1.0 (within float32 tolerance).
3. top_k_neighbors() excludes self, respects min_abs_r floor, ranks by |r|,
   returns correct sign.
4. build_edges_dataframe() end-to-end: planted correlation recovers correctly,
   >50%-NaN columns dropped, entrez-suffix stripped.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
COMPUTE_PY = REPO / "methods" / "depmap_coessentiality" / "compute.py"


def _load():
    spec = importlib.util.spec_from_file_location("coess_compute", COMPUTE_PY)
    m = importlib.util.module_from_spec(spec)
    sys.modules["coess_compute"] = m
    spec.loader.exec_module(m)
    return m


compute = _load()


# ---------------------------------------------------------------------------
# standardize()
# ---------------------------------------------------------------------------

class TestStandardize:
    def test_zero_mean_unit_std(self):
        rng = np.random.default_rng(0)
        X = rng.standard_normal((50, 10)).astype(np.float32)
        Z = compute.standardize(X)
        np.testing.assert_allclose(Z.mean(axis=0), 0.0, atol=1e-5)
        # standardize divides by sample std (ddof=1), so sample std of Z == 1.0
        np.testing.assert_allclose(Z.std(axis=0, ddof=1), 1.0, atol=1e-4)

    def test_nan_imputed_as_zero_post_centering(self):
        # A column with a NaN: after centering, NaN → 0 (mean-imputation = zero deviation)
        X = np.array([[1.0, np.nan], [2.0, 3.0], [3.0, 5.0]], dtype=np.float32)
        Z = compute.standardize(X)
        assert not np.any(np.isnan(Z)), "No NaNs should remain after standardize()"

    def test_constant_column_zeroed(self):
        X = np.ones((10, 3), dtype=np.float32)
        Z = compute.standardize(X)
        np.testing.assert_array_equal(Z, 0.0)

    def test_returns_float32(self):
        X = np.random.default_rng(1).standard_normal((20, 5))
        Z = compute.standardize(X)
        assert Z.dtype == np.float32


# ---------------------------------------------------------------------------
# pearson_matrix()
# ---------------------------------------------------------------------------

class TestPearsonMatrix:
    def test_diagonal_is_one(self):
        rng = np.random.default_rng(2)
        X = rng.standard_normal((30, 8)).astype(np.float32)
        Z = compute.standardize(X)
        C = compute.pearson_matrix(Z)
        np.testing.assert_allclose(np.diag(C), 1.0, atol=1e-5)

    def test_symmetric(self):
        rng = np.random.default_rng(3)
        X = rng.standard_normal((20, 6)).astype(np.float32)
        Z = compute.standardize(X)
        C = compute.pearson_matrix(Z)
        np.testing.assert_allclose(C, C.T, atol=1e-6)

    def test_known_correlation(self):
        # Two genes with identical profiles → r == 1.0
        x = np.arange(10, dtype=np.float32)
        X = np.column_stack([x, x])
        Z = compute.standardize(X)
        C = compute.pearson_matrix(Z)
        np.testing.assert_allclose(C[0, 1], 1.0, atol=1e-5)

    def test_anticorrelated(self):
        x = np.arange(10, dtype=np.float32)
        X = np.column_stack([x, -x])
        Z = compute.standardize(X)
        C = compute.pearson_matrix(Z)
        np.testing.assert_allclose(C[0, 1], -1.0, atol=1e-5)


# ---------------------------------------------------------------------------
# top_k_neighbors()
# ---------------------------------------------------------------------------

class TestTopKNeighbors:
    def _make_identity_corr(self, n: int) -> np.ndarray:
        """Correlation matrix with off-diagonal 0 (no neighbours above floor)."""
        return np.eye(n, dtype=np.float32)

    def test_self_excluded(self):
        corr = np.array([[1.0, 0.8], [0.8, 1.0]], dtype=np.float32)
        rows = compute.top_k_neighbors(corr, ["A", "B"], k=5, min_abs_r=0.0)
        for gene, partner, r, rank in rows:
            assert gene != partner, "Self-pair must never appear"

    def test_min_abs_r_floor(self):
        corr = np.array([[1.0, 0.15, 0.9], [0.15, 1.0, 0.3], [0.9, 0.3, 1.0]], dtype=np.float32)
        rows = compute.top_k_neighbors(corr, ["A", "B", "C"], k=5, min_abs_r=0.5)
        # Only the 0.9 pair should survive
        partners_A = [(p, r) for g, p, r, _ in rows if g == "A"]
        assert len(partners_A) == 1
        assert partners_A[0][0] == "C"

    def test_rank_is_1_based_and_sorted(self):
        corr = np.array([[1.0, 0.7, 0.5], [0.7, 1.0, 0.3], [0.5, 0.3, 1.0]], dtype=np.float32)
        rows = compute.top_k_neighbors(corr, ["A", "B", "C"], k=5, min_abs_r=0.0)
        a_rows = sorted([(r, rank) for g, p, r, rank in rows if g == "A"], key=lambda x: x[1])
        assert a_rows[0][1] == 1          # rank 1 is the strongest
        assert abs(a_rows[0][0]) >= abs(a_rows[1][0])  # monotone decreasing |r|

    def test_sign_preserved(self):
        corr = np.array([[1.0, -0.8], [-0.8, 1.0]], dtype=np.float32)
        rows = compute.top_k_neighbors(corr, ["A", "B"], k=1, min_abs_r=0.0)
        assert rows[0][2] < 0.0, "Negative r must not be flipped to positive"

    def test_no_partners_returns_empty(self):
        corr = self._make_identity_corr(3)
        rows = compute.top_k_neighbors(corr, ["A", "B", "C"], k=5, min_abs_r=0.5)
        assert rows == []

    def test_top_k_respects_cap(self):
        n = 10
        # All off-diagonal = 0.5
        corr = np.full((n, n), 0.5, dtype=np.float32)
        np.fill_diagonal(corr, 1.0)
        genes = [f"G{i}" for i in range(n)]
        rows = compute.top_k_neighbors(corr, genes, k=3, min_abs_r=0.0)
        for g in genes:
            ranks = [rank for gene, _, _, rank in rows if gene == g]
            assert len(ranks) <= 3, f"Gene {g} returned more than k=3 neighbours"


# ---------------------------------------------------------------------------
# build_edges_dataframe() — end-to-end
# ---------------------------------------------------------------------------

class TestBuildEdgesDataframe:
    def _planted_df(self) -> pd.DataFrame:
        """Three correlated + one anti-correlated gene planted in noise."""
        rng = np.random.default_rng(42)
        n_cells = 50
        shared = rng.standard_normal(n_cells)
        noise = lambda: rng.standard_normal(n_cells) * 0.2
        G_A = shared + noise()
        G_B = shared + noise()
        G_C = shared + noise()
        G_D = -shared + noise()   # anti-correlated
        G_E = rng.standard_normal(n_cells)   # independent
        return pd.DataFrame({
            "GENE_A (1)": G_A, "GENE_B (2)": G_B, "GENE_C (3)": G_C,
            "GENE_D (4)": G_D, "GENE_E (5)": G_E,
        })

    def test_entrez_suffix_stripped(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.0)
        for sym in edges["gene_symbol"].unique():
            assert "(" not in sym, f"Entrez suffix not stripped: {sym}"

    def test_planted_corr_appears_as_top_partner(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.3)
        # GENE_A's rank-1 partner should be GENE_B or GENE_C
        a_top = edges[edges["gene_symbol"] == "GENE_A"].sort_values("abs_rank").iloc[0]
        assert a_top["partner_symbol"] in ("GENE_B", "GENE_C")

    def test_anti_correlated_sign_preserved(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.3)
        # GENE_D should surface in GENE_A's partners with negative r
        a_rows = edges[edges["gene_symbol"] == "GENE_A"]
        d_row = a_rows[a_rows["partner_symbol"] == "GENE_D"]
        if len(d_row):
            assert d_row["pearson_r"].iloc[0] < 0.0

    def test_high_nan_column_dropped(self):
        df = self._planted_df()
        # Poison one column with >50% NaN
        df["GENE_Z (99)"] = np.where(
            np.arange(len(df)) < len(df) * 0.6, np.nan, 1.0
        )
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.0)
        assert "GENE_Z" not in edges["gene_symbol"].values

    def test_n_cell_lines_column_constant(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.0)
        assert edges["n_cell_lines"].nunique() == 1
        assert edges["n_cell_lines"].iloc[0] == len(df)

    def test_output_sorted_by_gene_symbol(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.0)
        symbols = list(edges["gene_symbol"])
        assert symbols == sorted(symbols), "Output must be sorted by gene_symbol"

    def test_output_columns(self):
        df = self._planted_df()
        edges = compute.build_edges_dataframe(df, k=4, min_abs_r=0.0)
        expected = {"gene_symbol", "partner_symbol", "pearson_r", "abs_rank", "n_cell_lines"}
        assert set(edges.columns) == expected
