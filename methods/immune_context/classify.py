"""immune_context.classify — per-indication tumor immune-context (T-cell infiltration) classifier.

The EFFECTOR arm of the biologics story (the IO-target-ID seed note's method #2): a T-cell engager
redirects cytotoxic T cells to the antigen, so it can only work where T cells are PRESENT to be
redirected. Surface antigen presence (surface-modality-fit) answers "is there a target?"; this
answers the orthogonal "is there an effector population?" — immune-hot vs immune-cold.

Pure over per-sample CIBERSORT LM22 leukocyte fractions (no S3 here). Substrate:
gdc-pancanatlas-immune-2018 (Thorsson 2018) — 22 leukocyte subtypes per TCGA sample, grouped by TCGA
study (CancerType). The core TCE-relevant signal is the CD8 (+ total) T-cell fraction of the
leukocyte compartment.

v1 is target-INDEPENDENT (tier: indication): the immune landscape of the indication. The sharper
antigen-CONDITIONED join (are the ANTIGEN-HIGH patients also T-cell-high?) is a deferred v2 facet —
it needs a per-sample antigen-expression join on TCGA barcode (a documented sample-id-join trap).

Thresholds are anchored to the PAN-CANCER across-study distribution (data-driven, not arbitrary):
CD8-fraction study medians across 33 TCGA studies have quartiles ~[0.084, 0.097, 0.113].
"""

from __future__ import annotations

from typing import Optional

# The LM22 columns that are T cells (CIBERSORT relative fractions of the leukocyte compartment).
T_CELL_COLUMNS = (
    "T.cells.CD8",
    "T.cells.CD4.naive",
    "T.cells.CD4.memory.resting",
    "T.cells.CD4.memory.activated",
    "T.cells.follicular.helper",
    "T.cells.regulatory..Tregs.",
    "T.cells.gamma.delta",
)
CD8_COLUMN = "T.cells.CD8"

# Pan-cancer across-study CD8-fraction quartiles (measured on the 33-study medians). A study at/above
# the pan-cancer Q3 is immune-hot for its CD8 compartment; at/below Q1 is immune-cold; between is
# intermediate. Anchored to the data so "hot"/"cold" means "relative to the pan-cancer landscape".
CD8_FRACTION_HOT_MIN = 0.113  # >= pan-cancer Q3 → immune-hot
CD8_FRACTION_COLD_MAX = 0.084  # <= pan-cancer Q1 → immune-cold


def classify_immune_context(cd8_fraction: Optional[float]) -> str:
    """immune_context_class from the indication's median CD8 T-cell fraction of the leukocyte pool.

    immune_hot          — CD8 fraction >= pan-cancer Q3 (ample effector population; TCE-favorable)
    immune_intermediate — between Q1 and Q3
    immune_cold         — CD8 fraction <= pan-cancer Q1 (T-cell-excluded/desert; TCE efficacy at risk)
    data_unavailable    — no CIBERSORT samples for the indication (abstain, never a false 'cold')
    """
    if cd8_fraction is None:
        return "data_unavailable"
    if cd8_fraction >= CD8_FRACTION_HOT_MIN:
        return "immune_hot"
    if cd8_fraction <= CD8_FRACTION_COLD_MAX:
        return "immune_cold"
    return "immune_intermediate"


def summarize_immune_context(rows) -> dict:
    """Reduce per-sample CIBERSORT rows (for ONE indication's studies) to an immune-context summary.

    `rows`: list of dicts (or DataFrame) with the LM22 fraction columns. Returns the median CD8 +
    total-T-cell fraction across samples, n_samples, and the class. Empty input → data_unavailable
    (honest — an indication with no CIBERSORT coverage is a gap, not a cold tumor)."""
    import numpy as np
    import pandas as pd

    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty or CD8_COLUMN not in df.columns:
        return {
            "immune_context_class": "data_unavailable",
            "median_cd8_fraction": None,
            "median_total_t_cell_fraction": None,
            "n_samples": 0,
        }
    tcols = [c for c in T_CELL_COLUMNS if c in df.columns]
    total_t = df[tcols].sum(axis=1)
    cd8_med = float(np.median(df[CD8_COLUMN].astype(float)))
    return {
        "immune_context_class": classify_immune_context(cd8_med),
        "median_cd8_fraction": round(cd8_med, 4),
        "median_total_t_cell_fraction": round(float(np.median(total_t)), 4),
        "n_samples": int(len(df)),
    }
