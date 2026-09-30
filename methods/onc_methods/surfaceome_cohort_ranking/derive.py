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
schema-adaptive: it discovers whichever `log2fc_*`/`padj_*` pairs exist and RE-DERIVES its robustness
inputs from those per-cell columns directly (see `_arms_ran` / `_cells_supporting`) rather than trusting
the shipped `cells_ran`/`cells_supporting` fusion columns (the tumor-up direction gate still reads the
shipped `dominant_direction` — re-deriving direction is the upstream fusion-semantics problem, out of
scope for this ranking-credit fix).

Why re-derive (analysis-methods#864): the shipped `cells_ran` counts non-NaN padj, which conflates
"the comparator arm did not run for this product" (a genuine 1-arm product, e.g. OV/LAML vs GTEx) with
"the arm ran but NA-filtered THIS gene" (a 2-arm product where one arm's padj is NaN). Under the old
consumer a gene significant in ONE arm only because the other arm filtered it read `cells_ran=1` ->
robustness `1/1=1.0` and passed `>= min(threshold, 1)=1`, out-ranking a gene genuinely measured in both
arms but supported in one (`1/2=0.5`, dropped). The re-derivation sets `cells_ran` = the number of arms
the PRODUCT actually ran — `(log2fc, padj)` pairs whose padj carries any non-NaN value (a NaN padj for a
gene is a run-then-filtered arm that still counts; a column that is all-NaN, e.g. SCLC's carried-but-unrun
padj_A/padj_B, does not) — and `cells_supporting` = up-significant MEASURED arms for the gene.

The original scaffold assumed a fixed 4-cell layout and filtered `cells_supporting >= 3` — that is
STALE: it returns zero rows against the real 1-2 cell products (and excludes single-cell indications
entirely). The robustness filter here is RELATIVE: keep genes up-supported by
`>= min(min_cells_supporting, cells_ran)` comparator cells — which scales from 1-cell (OV) to
multi-cell products without dropping any wired indication, and holds a 2-arm product's
single-arm-supported genes to the same bar as any other two-arm gene.

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


def _arms_ran(sensitivity_df: pd.DataFrame, pairs) -> int:
    """Number of comparator arms the PRODUCT actually ran — the robustness DENOMINATOR
    (analysis-methods#864). It is the count of `(log2fc, padj)` column pairs whose padj
    column carries at least one non-NaN value across the product.

    This is deliberately NOT the shipped per-gene `cells_ran` (which counts a single
    gene's non-NaN padj cells) and NOT the raw column-pair count `len(pairs)`:
      * The shipped `cells_ran` CONFLATES "the arm never ran for this product" with "the
        arm ran but NA-filtered THIS gene". Trusting it let a gene significant in ONE arm
        only because the other filtered it read `cells_ran=1` -> robustness `1/1=1.0` and
        pass `>= min(threshold, 1)=1`, out-ranking a gene measured in both arms but
        supported in one (`1/2=0.5`). A gene NA-filtered in an arm the product DID run
        must keep that arm in its denominator, so it earns partial (not full) robustness.
      * `len(pairs)` over-counts the other way: a product can CARRY an arm's columns while
        that arm ran for no gene at all (e.g. SCLC ships `padj_A`/`padj_B` entirely NaN;
        only cell C ran). Counting such a carried-but-unrun column would wrongly demand
        2-arm support and drop every gene. Requiring at least one non-NaN value excludes
        those unrun arms, so a de-facto 1-arm product reads `arms_ran=1` and its cell-C
        hits survive exactly as OV/LAML (genuine 1-arm) do.
    """
    n = 0
    for _lc, pc in pairs:
        if pc in sensitivity_df.columns and sensitivity_df[pc].notna().any():
            n += 1
    return n


def _cells_supporting(row, pairs) -> int:
    """Comparator arms where THIS gene is measured (non-NaN padj) AND up-significant
    (log2fc > 0, padj < _SIG_Q) — the robustness numerator, re-derived from the per-cell
    columns rather than the shipped `cells_supporting` fusion column."""
    n = 0
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
            n += 1
    return n


def _ranking_score(row, pairs, cells_ran: int, cells_supporting: int) -> float:
    """robustness-weighted mean of log2fc * -log10(padj) over present, up-significant cells.

    `robustness = cells_supporting / cells_ran` uses the re-derived inputs (product
    arms-ran denominator, per-gene up-significant numerator; see `_arms_ran` /
    `_cells_supporting`), NOT the shipped fusion columns, so a gene supported in one arm
    of an N-arm product is weighted 1/N rather than an inflated 1.0.
    """
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
    robustness = (cells_supporting / cells_ran) if cells_ran else 0.0
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

    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    # Re-derive the robustness inputs from the per-cell padj/log2fc columns directly
    # (analysis-methods#864) instead of trusting the shipped cells_ran/cells_supporting
    # fusion columns, whose NA-conflation credits single-arm-supported genes. cells_ran is
    # the product's arms-RAN count (constant within the indication; see `_arms_ran`);
    # cells_supporting is per-gene up-significant measured arms.
    #
    # The tumor-up DIRECTION gate still reads the shipped `dominant_direction`. Per-cell
    # log2fc>0 is NOT a sufficient direction test on its own: a gene can be up-significant
    # in the adjacent-normal arms (A/B) yet strongly DOWN vs GTEx (cell C) — a discordant
    # gene whose dominant contrast is down. Re-deriving the dominant direction is the
    # upstream cells_ran/sig fusion semantics problem (this issue's SOFT dep), out of scope
    # here; trusting the shipped direction keeps the tumor-up filter unchanged while only
    # the robustness CREDIT is corrected.
    arms_ran = _arms_ran(sensitivity_df, pairs)
    df["cells_ran"] = arms_ran
    df["cells_supporting"] = df.apply(lambda r: _cells_supporting(r, pairs), axis=1)

    # Relative robustness filter: tumor-up AND up-supported by >= min(threshold, arms_ran)
    # arms. Because arms_ran is the product's arm count, a gene supported in one arm of a
    # 2-arm product (whether the other arm NA-filtered it or tested it non-significant) is
    # held to eff_min=2 and dropped — symmetric with any two-arm-measured gene — while a
    # de-facto 1-arm product (arms_ran=1, e.g. OV/LAML or an all-NaN-A/B product like SCLC)
    # keeps eff_min=1 and its single-arm hits survive.
    eff_min = min(arms_ran, min_cells_supporting)
    keep = (df["dominant_direction"] == "up") & (df["cells_supporting"] >= eff_min) & (df["cells_supporting"] >= 1)
    df = df[keep].copy()

    if df.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    df["ranking_score"] = df.apply(lambda r: _ranking_score(r, pairs, arms_ran, int(r["cells_supporting"])), axis=1)
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
