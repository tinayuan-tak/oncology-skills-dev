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

import re

import numpy as np
import pandas as pd

# --- Thresholds (match the card's thresholds block in sc-normal-celltype-expression.card.yaml) ---
HIGH_LIABILITY_DET_THRESHOLD = 0.50
HIGH_LIABILITY_DONOR_FRACTION = 0.70
MODERATE_LIABILITY_DET = 0.20
MODERATE_DONOR_FRACTION = 0.30
NOT_EXPRESSED_CEILING = 0.01
MIN_RELIABLE_DONORS = 5

# Normal-tissue ABUNDANCE bands (#984 Tier-2): the liability ladder above is DETECTION-only, so a normal
# cell detected at trivial vs high abundance reads the same liability — yet detection >0.2 spans a ~25x
# abundance range (median_abund log1p_cp10k). These fixed bands are the p25/p75 of the detected-abundance
# distribution, VALIDATED as tissue-invariant across colon/lung/kidney/liver/brain/pancreas (p25≈0.20-0.26,
# p75≈0.61-0.66), so fixed constants are tissue-robust. Classified at the LIABILITY-anchor cell type.
# VERDICT-INERT (display/confidence): a low_abundance normal liability (e.g. FOLR1/ERBB2-class) is a
# candidate veto down-weight, but that is a SEPARATE backtest-gated change in tumor-selectivity.
NORMAL_ABUND_HIGH = 0.64
NORMAL_ABUND_MODERATE = 0.24

# Safety-essential normal cell types: any detection in these types forces a dedicated flag.
# These map to Census Cell Ontology labels (raw, no synonymy). WHOLE-TOKEN matching is used so a
# lineage token matches its subtypes wherever the token appears as a standalone word (e.g. "neuron"
# → "dopaminergic neuron", "cardiac neuron", "central nervous system neuron"), WITHOUT matching a
# different word that merely CONTAINS the token as a substring (e.g. "neuron" must NOT match
# "non-neuronal cell" / "neuronal-restricted precursor"). See _is_safety_essential.
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
    # S1-3 (cards review 2026-08-17): CNS glia + adrenal endocrine cells, so the newly always-on
    # brain + adrenal_gland shards actually flag their essential cell types ("neuron" already covers
    # CNS neurons; adrenal cortical/medullary + chromaffin were previously unflagged).
    "astrocyte",
    "oligodendrocyte",
    "adrenal",           # adrenal cortical / gland cells
    "chromaffin",        # adrenal medulla
)


# Precompiled whole-token matchers, one per prefix. `\b...\b` requires a word boundary on BOTH
# sides, so a token matches its subtypes ("neuron" → "dopaminergic neuron") but NOT a longer word
# that merely embeds it ("neuron" ∉ "neuronal-restricted precursor" — the trailing \b fails because
# "neuron" is followed by "al"). Multi-word prefixes ("kidney loop of henle", "type b pancreatic
# cell") match as a contiguous token run. This replaces the former `pfx in ct` substring test, whose
# mid-word matches produced false essential flags; it can only REMOVE false positives, never add.
_SAFETY_ESSENTIAL_PATTERNS = tuple(
    re.compile(r"\b" + re.escape(pfx) + r"\b") for pfx in SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES
)


def _is_safety_essential(cell_type: str) -> bool:
    ct = cell_type.lower()
    return any(pat.search(ct) for pat in _SAFETY_ESSENTIAL_PATTERNS)


def classify_sc_normal_expression(rows: pd.DataFrame, origin_tissues=None) -> dict:
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
    # OFF-ORIGIN critical-organ floor (0.20, backtest-gated 2026-09-04): a hit in a NON-origin critical
    # organ only flips the verdict to critical_organ_liability if its detection clears this higher bar.
    # 0.05–0.20 in an off-origin organ is the scRNA ambient-contamination / marginal-annotation band — a
    # single-atlas det=0.156 "L4/5 cortical neuron" hit for a GI cadherin (CDH17) is not a real CNS
    # liability, yet under the 0.05 floor it flipped CDH17/COADREAD to critical via off-origin-dominates.
    # Aligns with MODERATE_LIABILITY_DET (0.20). Backtest: separates the CDH17 false positive (0.156) from
    # every true positive — DLL3 0.815 / FOLR1 0.708 / ERBB2 0.607 / MSLN 0.413. Origin-tissue essential
    # hits keep the 0.05 floor (they are window-arbitrated, not a hard veto). Sub-floor off-origin hits are
    # still recorded in safety_essential_flags for transparency; they simply do not flip the class.
    CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR = 0.20
    safety_flags: dict[str, float] = {}
    # ORGAN-AWARE split (axis-D best-practice, 2026-08-07): a safety-essential-cell hit in a
    # NON-tissue-of-origin CRITICAL organ (heart/liver/kidney/marrow) is the hard-veto disqualifier
    # (the HER2-CAR-lung / MAGE-A3-cardiac / CEA-colitis failure class); a hit ONLY in the tumor's
    # OWN tissue-of-origin (e.g. FOLR1 in lung pneumocytes for NSCLC) is on-tissue and arbitrated by
    # the therapeutic-window axis, NOT vetoed. Requires the per-row `tissue` column + the caller's
    # origin_tissues; if tissue info is absent (older callers), we degrade to the un-split behavior.
    has_tissue = "tissue" in reliable.columns
    has_datasets = "n_datasets_reliable" in reliable.columns
    _e_abund_col = "median_abund" if "median_abund" in reliable.columns else None
    _e_frac = frac_col in reliable.columns
    origin = {str(t).lower().strip() for t in (origin_tissues or [])}
    essential_off_origin = False   # a hit in a critical organ that is NOT the tumor's tissue-of-origin
    essential_origin_only = False  # essential hits, but ALL in the tissue-of-origin
    # Per-essential-cell records so the veto's NAMED driver (organ/cell/detection/atlas-count) can be
    # surfaced downstream — the pooled max_detection_cell_type below is the argmax over ALL cell types
    # and can name a NON-essential epithelial cell while the veto actually fired on an essential one
    # (the anonymous-verdict gap: the skill/headline never named the organ that drove the clamp).
    essential_records: list[dict] = []
    for _, row in reliable.iterrows():
        det_val = float(row[det_col])
        if _is_safety_essential(str(row["cell_type"])) and det_val > SAFETY_FLAG_FLOOR:
            safety_flags[str(row["cell_type"])] = det_val
            row_tissue = str(row["tissue"]).lower().strip() if has_tissue else None
            is_origin = bool(row_tissue is not None and origin and row_tissue in origin)
            if is_origin:
                essential_origin_only = True
            elif det_val > CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR:
                # non-origin critical organ (or tissue unknown → treat as off-origin, conservative),
                # ABOVE the ambient-contamination floor → the hard-veto class.
                essential_off_origin = True
            # else: off-origin but sub-floor (0.05–0.20) → recorded in flags/records for transparency,
            # does NOT flip to critical_organ_liability (marginal single-atlas / ambient-noise band).
            essential_records.append({
                "cell_type": str(row["cell_type"]),
                "tissue": str(row["tissue"]) if has_tissue else None,
                "median_detection_fraction": det_val,
                "expressing_donor_fraction": float(row[frac_col]) if _e_frac else None,
                "n_datasets_reliable": int(row["n_datasets_reliable"]) if has_datasets else None,
                "median_abund": float(row[_e_abund_col])
                                if _e_abund_col is not None and pd.notna(row[_e_abund_col]) else None,
                "is_off_origin": not is_origin,
            })

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

    # #984 Tier-2: ABUNDANCE at the liability-anchor cell type — how MUCH the target is expressed in the
    # normal cell that drives the liability, not just whether it is detected. Tissue-robust fixed bands.
    _abund_col = "median_abund" if "median_abund" in reliable.columns else None
    peak_abund = (float(anchor_row[_abund_col])
                  if _abund_col is not None and pd.notna(anchor_row[_abund_col]) else None)
    if peak_abund is None:
        abundance_class = "data_unavailable"
    elif peak_abund >= NORMAL_ABUND_HIGH:
        abundance_class = "high_abundance"
    elif peak_abund >= NORMAL_ABUND_MODERATE:
        abundance_class = "moderate_abundance"
    else:
        abundance_class = "low_abundance"

    n_above_20 = int((reliable[det_col] > 0.20).sum())

    # NAMED essential-cell driver: the worst essential cell the veto actually keyed on. When an
    # off-origin critical-organ hit fired (→ critical_organ_liability), name the argmax-detection cell
    # AMONG the ABOVE-FLOOR off-origin essential hits (the veto driver, not a sub-floor ambient hit); when
    # only origin-tissue essential hits fired, name the origin cell; when NO liability class fired (only
    # sub-floor off-origin hits), name nothing. This lets the verdict/headline say "kidney proximal tubule,
    # 3 atlases" instead of an anonymous flag — and never names a sub-floor hit that did not move the class.
    if essential_off_origin:
        _driver_pool = [e for e in essential_records
                        if e["is_off_origin"] and e["median_detection_fraction"] > CRITICAL_ORGAN_OFF_ORIGIN_DET_FLOOR]
    elif essential_origin_only:
        _driver_pool = essential_records
    else:
        _driver_pool = []
    essential_driver = (max(_driver_pool, key=lambda e: e["median_detection_fraction"])
                        if _driver_pool else None)

    # Normal cell-type DETECTION CEILING across ALL reliable cell types — the honest denominator for a
    # single-cell tumor-vs-normal WINDOW (the positive use of the atlas, not only the safety veto). This
    # is the true global max, distinct from max_detection_fraction (the liability-anchor cell, which for
    # HIGH is the AND-gate argmax, not necessarily the global max).
    ceiling_det = float(reliable[det_col].max())

    # Ranked per-cell-type footprint (top by detection) — the normal analogue of the tumor card's
    # per_compartment vector. Surfaces the full liability landscape (not just the argmax cell type)
    # for the summary and the normal-tissue liability figure. Safety-essential cell types are flagged.
    _has_tissue = "tissue" in reliable.columns
    _has_frac = frac_col in reliable.columns
    _pct_abund_col = "median_abund" if "median_abund" in reliable.columns else None
    _has_datasets = "n_datasets_reliable" in reliable.columns
    per_cell_type_top = []
    for _, r in reliable.sort_values(det_col, ascending=False).head(15).iterrows():
        per_cell_type_top.append({
            "cell_type": str(r["cell_type"]),
            "tissue": str(r["tissue"]) if _has_tissue else None,
            "median_detection_fraction": float(r[det_col]),
            "expressing_donor_fraction": float(r[frac_col]) if _has_frac else None,
            "n_donors_reliable": int(r["n_donors_reliable"]),
            # median_abund (magnitude, not just detection breadth) + n_datasets_reliable (independent-atlas
            # replication) were read from Tier-1 but dropped from the footprint — surface them so a
            # confidence/abundance gate and the narrator can weight each cell type, not just the argmax.
            "median_abund": float(r[_pct_abund_col])
                            if _pct_abund_col is not None and pd.notna(r[_pct_abund_col]) else None,
            "n_datasets_reliable": int(r["n_datasets_reliable"]) if _has_datasets else None,
            "is_safety_essential": _is_safety_essential(str(r["cell_type"])),
        })

    return {
        "sc_normal_expression_class": liability,
        # CATEGORICAL companion to the safety_essential_flags dict, so the categorical rule engine can
        # fire on it (the raw dict is not rule-addressable). ORGAN-AWARE three-tier (2026-08-07):
        #   critical_organ_liability — essential-cell expression in a NON-origin critical organ
        #       (heart/liver/kidney/marrow). The axis-D HARD-veto instrument (TNNT2→cardiomyocyte).
        #   origin_tissue_liability  — essential-cell expression ONLY in the tumor's tissue-of-origin
        #       (FOLR1→lung pneumocytes for NSCLC). On-tissue; arbitrated by the therapeutic-window
        #       axis, NOT a hard veto — a validated ADC target must survive this.
        #   none                     — no safety-essential expression above floor.
        # This is DISTINCT from sc_normal_expression_class (HIGH_LIABILITY fires on ANY high normal
        # cell type incl. tissue-of-origin epithelium — too blunt to veto a validated ADC target).
        # off_origin dominates: any critical-organ hit → critical_organ_liability even if origin also hit.
        "sc_normal_safety_essential_class": (
            "critical_organ_liability" if essential_off_origin
            else "origin_tissue_liability" if essential_origin_only
            else "none"),
        "max_detection_cell_type": max_det_ct,
        "max_detection_fraction": max_det_val,
        "expressing_donor_fraction_max": max_frac_val,
        # #984 Tier-2: normal-tissue abundance at the liability-anchor cell type (verdict-inert)
        "sc_normal_abundance_class": abundance_class,
        "sc_normal_peak_median_abund": peak_abund,
        # NAMED essential-cell driver of the safety-essential class — de-anonymizes the veto (organ +
        # cell type + detection + independent-atlas count + abundance). None when no essential hit fired.
        "sc_normal_essential_max_cell_type": essential_driver["cell_type"] if essential_driver else None,
        "sc_normal_essential_max_tissue": essential_driver["tissue"] if essential_driver else None,
        "sc_normal_essential_max_detection_fraction":
            essential_driver["median_detection_fraction"] if essential_driver else None,
        "sc_normal_essential_donor_fraction":
            essential_driver["expressing_donor_fraction"] if essential_driver else None,
        "sc_normal_essential_n_datasets_reliable":
            essential_driver["n_datasets_reliable"] if essential_driver else None,
        "sc_normal_essential_median_abund": essential_driver["median_abund"] if essential_driver else None,
        # Normal cell-type detection ceiling across all reliable cell types (single-cell window denominator).
        "sc_normal_ceiling_detection_fraction": ceiling_det,
        "safety_essential_flags": safety_flags,
        "n_cell_types_above_20pct": n_above_20,
        "n_reliable_cell_types": int(len(reliable)),
        "per_cell_type_top": per_cell_type_top,
    }


def _data_unavailable_class(note: str = "") -> dict:
    return {
        "sc_normal_expression_class": "data_unavailable",
        "sc_normal_safety_essential_class": "data_unavailable",
        "max_detection_cell_type": None,
        "max_detection_fraction": None,
        "expressing_donor_fraction_max": None,
        "sc_normal_abundance_class": "data_unavailable",
        "sc_normal_peak_median_abund": None,
        "sc_normal_essential_max_cell_type": None,
        "sc_normal_essential_max_tissue": None,
        "sc_normal_essential_max_detection_fraction": None,
        "sc_normal_essential_donor_fraction": None,
        "sc_normal_essential_n_datasets_reliable": None,
        "sc_normal_essential_median_abund": None,
        "sc_normal_ceiling_detection_fraction": None,
        "safety_essential_flags": {},
        "n_cell_types_above_20pct": 0,
        "n_reliable_cell_types": 0,
        "per_cell_type_top": [],
        "_data_note": note or "No Tier-1 normal-tissue product available or insufficient donor coverage",
    }
