"""Single-cell normal-tissue cell-type presence primitives (numpy/pandas-only, no S3).

Reads the Tier-1 cross-donor aggregation product (sc-normal-celltype-expression-{tissue}-v1)
and classifies the gene's normal-tissue liability across all cell types. The Tier-1 product
already has cross-donor statistics (median_det, expressing_donor_fraction, n_donors_reliable)
— this module does NO further donor-level aggregation; it classifies across cell types.

LIABILITY LADDER (mirrors the F5 rules in surface-intrinsic.rules.yaml):
  HIGH_LIABILITY:      any cell type has median_det > 0.50 AND expressing_donor_fraction > 0.70
  MODERATE_LIABILITY:  any cell type has median_det > 0.20 OR expressing_donor_fraction > 0.30
  LOW_LIABILITY:       detected but below MODERATE thresholds
  NOT_EXPRESSED:       all cell types have median_det < 0.01
  data_unavailable:    no Tier-1 product, or all n_donors_reliable < MIN_RELIABLE_DONORS

Both HIGH thresholds must be met (AND): requiring BOTH magnitude and consistency prevents a
high-variance gene in one small-n donor from triggering a killer rule. MODERATE uses OR:
either consistent detection or high fraction is enough to warrant a safety flag.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- Thresholds (match the card's thresholds block in sc-normal-celltype-expression.card.yaml) ---
HIGH_LIABILITY_DET_THRESHOLD = 0.50
HIGH_LIABILITY_DONOR_FRACTION = 0.70
MODERATE_LIABILITY_DET = 0.20
MODERATE_DONOR_FRACTION = 0.30
NOT_EXPRESSED_CEILING = 0.01
MIN_RELIABLE_DONORS = 5

# Safety-essential normal cell types: any detection in these types forces a dedicated flag.
# These map to Census Cell Ontology labels (raw, no synonymy). Partial prefix matching is
# used where multiple subtypes share a lineage (e.g. "neuron" → "dopaminergic neuron").
SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES = (
    "cardiomyocyte",
    "cardiac muscle cell",
    "hepatocyte",
    "neuron",
    "kidney proximal tubule",
    "kidney collecting duct",
    "kidney loop of henle",
    "pneumocyte",       # alveolar type I/II
    "alveolar type",
    "enterocyte",
    "colonocyte",
    "hematopoietic stem cell",
    "erythroid progenitor",
)


def _is_safety_essential(cell_type: str) -> bool:
    ct = cell_type.lower()
    return any(ct.startswith(pfx) or pfx in ct for pfx in SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES)


def classify_sc_normal_expression(rows: pd.DataFrame) -> dict:
    """Classify normal-tissue liability from a Tier-1 gene rows DataFrame.

    `rows` is a DataFrame with columns: cell_type, n_donors_reliable,
    median_detection_fraction (or median_det), expressing_donor_fraction.
    Returned keys match the card's summary_fields.
    """
    if rows is None or rows.empty:
        return _data_unavailable_class()

    # Normalize column name (Tier-1 schema uses median_det, keep compat)
    det_col = "median_det" if "median_det" in rows.columns else "median_detection_fraction"
    frac_col = "expressing_donor_fraction"

    # Only trust rows with enough donors
    reliable = rows[rows["n_donors_reliable"] >= MIN_RELIABLE_DONORS].copy()
    if reliable.empty:
        return _data_unavailable_class(
            note="All cell types have n_donors_reliable < MIN_RELIABLE_DONORS — insufficient donor coverage"
        )

    # --- Safety-essential cell types ---
    # Floor at 0.05: the Tier-1 WHERE median_det > 0.01 filter lets near-zero values through;
    # below 0.05 is within census annotation noise (cell-type contaminants, misassignments).
    SAFETY_FLAG_FLOOR = 0.05
    safety_flags: dict[str, float] = {}
    for _, row in reliable.iterrows():
        det_val = float(row[det_col])
        if _is_safety_essential(str(row["cell_type"])) and det_val > SAFETY_FLAG_FLOOR:
            safety_flags[str(row["cell_type"])] = det_val

    # --- Liability classification ---
    # HIGH: any cell type exceeds both magnitude AND consistency thresholds (AND gate)
    high_mask = (reliable[det_col] > HIGH_LIABILITY_DET_THRESHOLD) & \
                (reliable[frac_col] > HIGH_LIABILITY_DONOR_FRACTION)
    if high_mask.any():
        liability = "HIGH_LIABILITY"
        # Report the triggering cell type (highest det among AND-gate passers), not the
        # global argmax: a cell at det=0.85/frac=0.40 (MODERATE only) must not shadow a
        # cell at det=0.55/frac=0.80 that actually fired the HIGH rule.
        anchor_rows = reliable[high_mask]
        anchor_row = anchor_rows.loc[anchor_rows[det_col].idxmax()]
    elif (reliable[det_col] > MODERATE_LIABILITY_DET).any() or \
         (reliable[frac_col] > MODERATE_DONOR_FRACTION).any():
        liability = "MODERATE_LIABILITY"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]
    elif (reliable[det_col] > NOT_EXPRESSED_CEILING).any():
        liability = "LOW_LIABILITY"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]
    else:
        liability = "NOT_EXPRESSED"
        anchor_row = reliable.loc[reliable[det_col].idxmax()]

    max_det_ct = str(anchor_row["cell_type"])
    max_det_val = float(anchor_row[det_col])
    max_frac_val = float(anchor_row[frac_col]) if frac_col in reliable.columns else None

    n_above_20 = int((reliable[det_col] > 0.20).sum())

    return {
        "sc_normal_expression_class": liability,
        "max_detection_cell_type": max_det_ct,
        "max_detection_fraction": max_det_val,
        "expressing_donor_fraction_max": max_frac_val,
        "safety_essential_flags": safety_flags,
        "n_cell_types_above_20pct": n_above_20,
        "n_reliable_cell_types": int(len(reliable)),
    }


def _data_unavailable_class(note: str = "") -> dict:
    return {
        "sc_normal_expression_class": "data_unavailable",
        "max_detection_cell_type": None,
        "max_detection_fraction": None,
        "expressing_donor_fraction_max": None,
        "safety_essential_flags": {},
        "n_cell_types_above_20pct": 0,
        "n_reliable_cell_types": 0,
        "_data_note": note or "No Tier-1 normal-tissue product available or insufficient donor coverage",
    }
