"""compute — genome-wide co-essentiality correlation kernel.

Pure functions: no I/O, no S3, no side effects. Testable with synthetic matrices.

Algorithm
---------
1. standardize(X): per-column (per-gene) z-score with NaN mean-imputation.
   - Subtract nanmean (center on per-gene mean across cell lines).
   - Fill residual NaN → 0.0  (post-centering: "unknown" = "average contribution")
   - Divide by nanstd; genes with std==0 are set to all-zeros (no signal).
   This ensures Pearson(Z.T @ Z / (n-1)) == pairwise Pearson on complete observations
   at the ~3.5% NaN level seen in DepMap 26Q1 (17,046 of 18,531 genes fully complete).
   Pairwise-complete deletion is unnecessary and O(n²)-expensive at this NaN density.

2. pearson_matrix(Z): Z.T @ Z / (n_cells - 1) → (n_genes, n_genes) float32.
   Single dense BLAS dgemm; ~4.5 s on the 1,538×18,531 DepMap 26Q1 matrix.

3. top_k_neighbors(corr, gene_symbols, k, min_abs_r):
   Per gene, collect the K strongest |r| partners above min_abs_r, excluding
   self. Returns a list of (gene_a, gene_b, pearson_r, abs_rank) tuples.
   Both positive (co-essential) and negative (anti-correlated) partners are kept
   — the sign carries biological meaning.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


TOP_K_DEFAULT = 100
MIN_ABS_R_DEFAULT = 0.20


def standardize(X: np.ndarray) -> np.ndarray:
    """Column-wise z-score with NaN mean-imputation. Returns float32 array."""
    X = X.astype(np.float32)
    col_mean = np.nanmean(X, axis=0)          # (n_genes,)
    X = X - col_mean[np.newaxis, :]           # center
    X = np.where(np.isnan(X), 0.0, X)        # impute post-centering NaN → 0
    col_std = np.std(X, axis=0, ddof=1)      # sample std → Z.T@Z/(n-1) == Pearson r
    nonzero = col_std > 0
    X[:, nonzero] = X[:, nonzero] / col_std[nonzero]
    return X


def pearson_matrix(Z: np.ndarray) -> np.ndarray:
    """Z.T @ Z / (n-1) → symmetric (n_genes, n_genes) Pearson matrix, float32."""
    n = Z.shape[0]
    return (Z.T @ Z / (n - 1)).astype(np.float32)


def top_k_neighbors(
    corr: np.ndarray,
    gene_symbols: list[str],
    k: int = TOP_K_DEFAULT,
    min_abs_r: float = MIN_ABS_R_DEFAULT,
) -> list[tuple[str, str, float, int]]:
    """Extract top-K signed neighbors per gene above |r| >= min_abs_r.

    Returns list of (gene_symbol, partner_symbol, pearson_r, abs_rank) sorted by
    gene_symbol. abs_rank is 1-based within each gene (rank 1 = strongest |r|).
    Self-correlations (r==1 on the diagonal) are excluded.
    """
    n = len(gene_symbols)
    rows: list[tuple[str, str, float, int]] = []

    for i in range(n):
        r_row = corr[i].copy()
        r_row[i] = 0.0                        # exclude self
        abs_r = np.abs(r_row)
        mask = (abs_r >= min_abs_r) & (np.arange(n) != i)  # belt + suspenders
        candidate_idx = np.where(mask)[0]

        if len(candidate_idx) == 0:
            continue

        # Sort candidates by |r| descending, take top-K
        order = np.argsort(-abs_r[candidate_idx])
        top_idx = candidate_idx[order[:k]]

        for rank, j in enumerate(top_idx, start=1):
            rows.append((gene_symbols[i], gene_symbols[j], float(r_row[j]), rank))

    return rows


def build_edges_dataframe(
    matrix: pd.DataFrame,
    k: int = TOP_K_DEFAULT,
    min_abs_r: float = MIN_ABS_R_DEFAULT,
) -> pd.DataFrame:
    """End-to-end: wide gene-effect DataFrame → long edges DataFrame.

    Args:
        matrix: cells × genes DataFrame (ModelID index, SYMBOL (entrez) or SYMBOL columns).
                NaN is allowed; columns with >50% NaN are dropped before correlation.
        k:      top-K neighbors per gene (default 100).
        min_abs_r: minimum |r| floor (default 0.20).

    Returns:
        DataFrame with columns: gene_symbol, partner_symbol, pearson_r, abs_rank, n_cell_lines.
        Sorted by gene_symbol for predicate-pushdown reads.
    """
    # Drop genes that are >50% NaN (too sparse for reliable correlation)
    frac_nan = matrix.isna().mean(axis=0)
    matrix = matrix.loc[:, frac_nan <= 0.50]

    gene_symbols = _strip_entrez(list(matrix.columns))
    n_cell_lines = int(matrix.shape[0])

    X = matrix.values.astype(np.float32)
    Z = standardize(X)
    corr = pearson_matrix(Z)

    rows = top_k_neighbors(corr, gene_symbols, k=k, min_abs_r=min_abs_r)

    df = pd.DataFrame(rows, columns=["gene_symbol", "partner_symbol", "pearson_r", "abs_rank"])
    df["n_cell_lines"] = n_cell_lines
    df = df.sort_values("gene_symbol").reset_index(drop=True)
    return df


def _strip_entrez(columns: list[str]) -> list[str]:
    """'KRAS (3845)' → 'KRAS'. Passthrough if no parens."""
    import re
    _re = re.compile(r'^"?([A-Za-z0-9._-]+)\s*\(\d+\)"?$')
    out = []
    for c in columns:
        m = _re.match(c)
        out.append(m.group(1) if m else c)
    return out
