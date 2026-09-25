"""surfaceome_cohort_ranking.derive — pure ranking compute (no S3, unit-testable).

Composes a per-indication whole-surfaceome tumor-vs-normal ranking from three inputs:
  * `{indication}-dge-tumor-vs-normal-sensitivity-v1`  (per-gene DESeq2 sensitivity)
  * `surfaceome-family-classification-per-uniprot-v1`   (surface-only filter + family)
  * `cptac-protein-tumor-vs-normal-per-cohort-v1`       (protein concordance overlay; optional)

## Sensitivity schema is HETEROGENEOUS across indications (important)

The materialized sensitivity products carry a VARIABLE number of comparator "cells" — a
new-vintage product runs cells A+C (cells_ran=2), some only C (1, e.g. OV). (The ComBat cell B
was removed in analysis-methods#727; older materialized products may still carry log2fc_B/padj_B
— cells_ran=3 — and are read unchanged.) Column sets differ accordingly (log2fc_A/padj_A,
log2fc_C/padj_C, and on an older product log2fc_B/padj_B — any subset present). So the compute is
schema-adaptive: it discovers whichever `log2fc_*`/`padj_*` pairs exist and uses the pre-computed
robustness fields (`cells_ran`, `cells_supporting`, `dominant_direction`).

The original scaffold assumed a fixed 4-cell layout and filtered `cells_supporting >= 3` — that is
STALE: it returns zero rows against the real 1-2 cell products (and excludes single-cell indications
entirely). The robustness filter here is RELATIVE: keep genes tumor-up and supported by
`>= min(min_cells_supporting, cells_ran)` comparator cells — which scales from 1-cell (OV) to
multi-cell products without dropping any wired indication.

## Ranking

Per candidate row: term_c = log2fc_c * -log10(clip(padj_c, 1e-300)) over the comparator cells that
are present AND up-significant (log2fc>0, padj<0.05); mean over those cells, scaled by the
robustness fraction cells_supporting/cells_ran. Rank descending within the indication ->
tissue_rank (1=best), tissue_percentile_rna (100=best), cohort_rank_class.

## CPTAC protein overlay

Where the indication maps to a CPTAC cohort and the gene has protein coverage: the protein
tumor-vs-normal direction (from protein_expression_class) is compared to the (always tumor-up) RNA
call -> rna_protein_concordance; tissue_percentile_protein ranks the CPTAC-covered candidates by
protein_effect_size. No CPTAC cohort / no coverage -> 'no_protein', percentile NaN (data-unavailable,
NOT a negative signal).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

METHOD_VERSION = "0.1.0"

# Sensitivity indication code -> CPTAC proteogenomics cohort. Only clean 1:1 mappings; ambiguous
# spans (NSCLC = LUAD+LSCC) and cohorts CPTAC lacks (STAD, SKCM, ...) are intentionally absent ->
# rna_protein_concordance='no_protein'.
CPTAC_COHORT_MAP = {
    "BRCA": "BRCA",
    "COAD": "COAD",
    "COADREAD": "COAD",
    "READ": "COAD",
    "GBM": "GBM",
    "HNSC": "HNSCC",
    "LUAD": "LUAD",
    "LUSC": "LSCC",
    "OV": "OV",
    "PAAD": "PDAC",
    "UCEC": "UCEC",
    "KIRC": "CCRCC",
}

_PADJ_FLOOR = 1e-300
_SIG_Q = 0.05

# Per-indication normal-contrast caveat, propagated onto every ranked row for the indication
# (constant within an indication; empty string where there is nothing to flag). This is NOT
# derivable from the parquet alone: it encodes a biological property of the normal comparator, not a
# cell-count. LAML's only contrast is cell C (tumor vs GTEx whole blood; no adjacent normal), and
# whole blood carries a maturation-state confound — mature circulating blood vs immature leukemic
# blasts — so LAML surface ranks are direction/rank-informative but not magnitude-comparable to
# adjacent-normal-backed indications (mirrors the caveat on laml-dge-tumor-vs-normal-sensitivity-v1
# and the LAML DGE-publish decision, analysis-methods#734 Phase 2 / #789). Other GTEx-only
# single-cell-C indications (e.g. OV vs GTEx ovary) are tissue-matched and carry no such caveat, so
# this is keyed on the biological fact, not on cells_ran.
INDICATION_NORMAL_CAVEAT = {
    "LAML": (
        "normal contrast is GTEx whole blood (no adjacent normal; cell C sole contrast); "
        "maturation-state confound (mature circulating blood vs immature leukemic blasts) — "
        "consume direction/rank, not absolute magnitude"
    ),
}

OUTPUT_COLUMNS = [
    "indication",
    "gene_symbol",
    "uniprot_ac",
    "surface_protein_family",
    "cells_ran",
    "cells_supporting",
    "max_abs_log2fc",
    "ranking_score",
    "tissue_rank",
    "tissue_percentile_rna",
    "tissue_percentile_protein",
    "rna_protein_concordance",
    "cohort_rank_class",
    "normal_contrast_caveat",
    "method_version",
]


def _cell_pairs(columns) -> list[tuple[str, str]]:
    """Discover (log2fc_X, padj_X) column pairs present in a sensitivity frame."""
    pairs = []
    for c in columns:
        if c.startswith("log2fc_"):
            suffix = c[len("log2fc_") :]
            padj = f"padj_{suffix}"
            if padj in columns:
                pairs.append((c, padj))
    return pairs


def _ranking_score(row, pairs) -> float:
    """cells_supporting-weighted mean of log2fc * -log10(padj) over present, up-significant cells."""
    terms = []
    for lc, pc in pairs:
        lf = row.get(lc)
        pj = row.get(pc)
        if lf is None or pj is None:
            continue
        if isinstance(lf, float) and math.isnan(lf):
            continue
        if isinstance(pj, float) and math.isnan(pj):
            continue
        if lf > 0 and pj < _SIG_Q:
            terms.append(lf * -math.log10(max(pj, _PADJ_FLOOR)))
    if not terms:
        return 0.0
    mean_term = sum(terms) / len(terms)
    cr = row.get("cells_ran") or 0
    cs = row.get("cells_supporting") or 0
    robustness = (cs / cr) if cr else 0.0
    return float(mean_term * robustness)


def _cohort_rank_class(percentile: float) -> str:
    if percentile >= 99.0:
        return "top_1_percent"
    if percentile >= 95.0:
        return "top_5"
    if percentile >= 75.0:
        return "top_25"
    return "below_25_percent"


def _protein_direction(expr_class: Optional[str]) -> Optional[str]:
    if expr_class in ("strong_up", "modest_up"):
        return "up"
    if expr_class in ("strong_down", "modest_down"):
        return "down"
    if expr_class == "ns":
        return "ns"
    return None


def _surface_lookup(surface_df: pd.DataFrame) -> pd.DataFrame:
    """One row per gene_symbol for surface-confirmed proteins (highest-confidence wins)."""
    surf = surface_df[
        surface_df["is_surface_protein"].fillna(False)
        & surface_df["gene_symbol"].fillna("").astype(str).str.len().gt(0)
    ].copy()
    surf["gene_symbol"] = surf["gene_symbol"].astype(str).str.upper()
    score = surf.get("surfaceome_confidence_score")
    surf["_conf"] = score.fillna(0.0) if score is not None else 0.0
    surf = surf.sort_values("_conf", ascending=False).drop_duplicates("gene_symbol", keep="first")
    return surf.set_index("gene_symbol")[["uniprot_ac", "surface_protein_family"]]


def rank_indication(
    indication: str,
    sensitivity_df: pd.DataFrame,
    surface_df: pd.DataFrame,
    cptac_df: Optional[pd.DataFrame] = None,
    min_cells_supporting: int = 2,
) -> pd.DataFrame:
    """Rank the surface proteome for one indication. Returns the OUTPUT_COLUMNS frame (ranked)."""
    indication = indication.upper().strip()
    surf_map = _surface_lookup(surface_df)
    pairs = _cell_pairs(list(sensitivity_df.columns))

    df = sensitivity_df.copy()
    df["gene_symbol"] = df["gene_symbol"].astype(str).str.upper()
    df = df[df["gene_symbol"].isin(surf_map.index)]

    # Relative robustness filter: tumor-up + supported by all-or-min(threshold, cells_ran) cells.
    cells_ran = df["cells_ran"].fillna(0)
    cells_sup = df["cells_supporting"].fillna(0)
    eff_min = np.minimum(cells_ran, float(min_cells_supporting))
    keep = (df["dominant_direction"] == "up") & (cells_sup >= eff_min) & (cells_sup >= 1)
    df = df[keep].copy()

    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["ranking_score"] = df.apply(lambda r: _ranking_score(r, pairs), axis=1)
    df = df[df["ranking_score"] > 0].copy()
    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df = df.sort_values(["ranking_score", "gene_symbol"], ascending=[False, True]).reset_index(drop=True)
    n = len(df)
    df["tissue_rank"] = np.arange(1, n + 1)
    df["tissue_percentile_rna"] = 100.0 * (1.0 - (df["tissue_rank"] - 1) / max(n - 1, 1))
    df["cohort_rank_class"] = df["tissue_percentile_rna"].map(_cohort_rank_class)

    df["uniprot_ac"] = df["gene_symbol"].map(surf_map["uniprot_ac"])
    df["surface_protein_family"] = df["gene_symbol"].map(surf_map["surface_protein_family"])
    df["indication"] = indication
    df["normal_contrast_caveat"] = INDICATION_NORMAL_CAVEAT.get(indication, "")
    df["method_version"] = METHOD_VERSION

    # ── CPTAC protein overlay ──────────────────────────────────────────────
    df["tissue_percentile_protein"] = np.nan
    df["rna_protein_concordance"] = "no_protein"
    cohort = CPTAC_COHORT_MAP.get(indication)
    if cptac_df is not None and cohort is not None:
        cdf = cptac_df[cptac_df["cohort"].astype(str).str.upper() == cohort].copy()
        if not cdf.empty:
            cdf["gene_symbol"] = cdf["gene_symbol"].astype(str).str.upper()
            cdf = cdf.drop_duplicates("gene_symbol", keep="first").set_index("gene_symbol")
            eff = cdf["protein_effect_size"]
            expr = cdf["protein_expression_class"]

            def _conc(g):
                if g not in cdf.index:
                    return "no_protein"
                d = _protein_direction(expr.get(g))
                if d == "up":
                    return "agreement"  # RNA up (all candidates) + protein up
                if d == "down":
                    return "disagreement"
                if d == "ns":
                    return "rna_only"
                return "no_protein"

            df["rna_protein_concordance"] = df["gene_symbol"].map(_conc)
            covered = df["gene_symbol"].isin(cdf.index)
            if covered.any():
                sub = df.loc[covered, "gene_symbol"].map(eff)
                # rank covered candidates by protein effect size (desc) -> percentile
                order = sub.rank(method="min", ascending=True)  # 1=lowest
                m = covered.sum()
                df.loc[covered, "tissue_percentile_protein"] = 100.0 * (order - 1) / max(m - 1, 1)

    return df[OUTPUT_COLUMNS].copy()


def rank_all(
    sensitivity_by_indication: dict[str, pd.DataFrame],
    surface_df: pd.DataFrame,
    cptac_df: Optional[pd.DataFrame] = None,
    min_cells_supporting: int = 2,
) -> pd.DataFrame:
    """Rank every provided indication and concat into one long frame."""
    frames = []
    for ind, sens in sensitivity_by_indication.items():
        r = rank_indication(ind, sens, surface_df, cptac_df, min_cells_supporting)
        if not r.empty:
            frames.append(r)
    if not frames:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    return pd.concat(frames, ignore_index=True)
