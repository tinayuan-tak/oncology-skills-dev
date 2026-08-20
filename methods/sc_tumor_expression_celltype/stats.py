"""Single-cell per-compartment presence primitives (numpy/pandas-only, no S3).

The scRNA analogue of tcga_gtex_expression_distribution/stats.py, but the substrate is the
DONOR × COMPARTMENT pseudobulk (sc-pseudobulk-donor-celltype-{indication}-v1), not per-sample bulk
TPM. Two statistics per (donor, compartment) come from the product and are NEVER averaged into one
number: DETECTION_FRACTION (fraction of a donor's compartment cells with UMI>0 — the single-cell-
native "is it there at all" signal bulk cannot produce) and ABUNDANCE_LOG1P_CP10K (mean expression
level).

THE LOAD-BEARING RULE (mirrors the emit's Tier-2→Tier-1 discipline): the DONOR is the biological
replicate. Compartment-level statistics are the CROSS-DONOR MEDIAN of the per-donor values — never
a cell-weighted mean, which would let one large dataset dominate (CRC/NSCLC cell counts are wildly
uneven across contributing atlases). Kept dependency-light + pure so it is unit-testable with a
synthetic donor×compartment DataFrame and no data read.
"""
from __future__ import annotations

# Detection-fraction cutoffs (fraction of a compartment's cells expressing the target, cross-donor
# median). Anchored to the single-cell convention where ~0.5 detection = "expressed in most cells of
# the compartment" and ~0.1 = "a real expressing subset" (dropout-aware; scRNA under-detects, so
# these sit below bulk TPM-fraction cutoffs by design).
MALIGNANT_BROADLY_DETECTED_MIN = 0.5     # detected in >=50% of malignant cells (cross-donor median)
MALIGNANT_SUBSET_DETECTED_MIN = 0.10     # a real expressing malignant subset (target-high cells)
MICROENV_DETECTED_MIN = 0.25             # a compartment counts as "expressing" at >=25% detection
BROADLY_LOW_MAX = 0.05                   # below this everywhere == effectively undetected

# Compartments that constitute the tumor MICROENVIRONMENT (non-malignant, non-normal-epithelial).
# A target detected here but NOT in malignant cells is a microenvironment-dominant signal — present
# in the tumor SAMPLE but not tumor-cell-intrinsic (the sc-unique attribution the bulk cards can't make).
MICROENVIRONMENT_COMPARTMENTS = ("immune", "stromal", "endothelial")

# Minimum contributing DONORS (biological replicates) before a malignant-anchored presence call is
# trustworthy. The cross-donor median can otherwise rest on 1-2 donors from a single atlas — a
# false-confidence call. Mirrors the sibling sc_normal_expression reader's MIN_RELIABLE_DONORS=5 (L1).
MIN_RELIABLE_DONORS = 5

# Minimum CELLS in a (dataset, donor) compartment stratum before that donor is a trustworthy
# replicate. A per-donor detection_fraction computed on a handful of cells is quantized and noisy
# (a 2-cell donor can only report 0/2, 1/2, 2/2), so tiny strata are dropped BEFORE the cross-donor
# median/IQR — otherwise a single-digit-cell donor swings the compartment call as much as a
# thousand-cell one. OSCA / sc-best-practices place the per-sample-per-cell-type floor at ~10-50 cells;
# 20 is a conservative choice that also leaves the existing >=100-cell synthetic fixtures intact.
MIN_CELLS_PER_DONOR = 20

# Minimum TOTAL malignant cells (summed over reliable donors) before a malignant-anchored presence
# CLASS is emitted. The >=5-donor floor alone lets a pooled cube with single-digit cells per donor
# pass (e.g. the pan-renal KIRC / pan-gynecologic OV 3CA cubes carry only ~74 / ~106 total malignant
# cells) and emit a confident call indistinguishable from a half-million-cell COADREAD read. Below
# this floor the malignant compartment is too thinly sampled to anchor a call → honest data_unavailable.
MIN_MALIGNANT_CELLS_TOTAL = 100

# ── TCE antigen-escape thresholds (two-axis heterogeneity, 2026-08-20) ────────────────────────────
# The prior single-number tce_homogeneity_class re-binned malignant_detection_fraction alone, with a
# LENIENT 0.5 "homogeneous" bar — 50% of malignant cells antigen-negative is a large escape reservoir.
# A T-cell-engager needs BOTH: (a) most cells in a typical tumour express it (WITHIN-tumour coverage),
# and (b) that holds ACROSS patients (INTER-tumour consistency). We separate the two axes.
TCE_COVERAGE_HOMOGENEOUS_MIN = 0.75      # within-tumour: >=75% of malignant cells express (tightened)
TCE_COVERAGE_HETEROGENEOUS_MAX = 0.5     # <50% expressing == an escape reservoir within the tumour
DONOR_CONSISTENCY_IQR_MAX = 0.25         # inter-donor detection IQR below this == consistent across pts
DONOR_BROAD_DETECTION_MIN = 0.5          # a donor "broadly detects" at >=50% malignant detection
DONOR_CONSISTENCY_FRACTION_MIN = 0.5     # consistent if >=50% of donors broadly detect
MIN_DONORS_FOR_DISPERSION = 3            # IQR on 1-2 donors is meaningless -> report None, flag it


def compartment_summary(rows) -> dict:
    """Roll the per-(donor, compartment) pseudobulk rows up to ONE stat block per compartment,
    using the cross-donor MEDIAN (donor-is-replicate). `rows` is a list of dicts (or a DataFrame)
    with keys compartment, donor_id, dataset_id, n_cells, detection_fraction, abundance_log1p_cp10k.

    Returns {compartment: {n_donors, n_cells_total, median_detection_fraction,
    median_abundance_log1p_cp10k}}. Empty input → {} (honest gap, never fabricated zeros)."""
    import numpy as np
    import pandas as pd
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return {}
    out: dict = {}
    for comp, g in df.groupby("compartment"):
        # donor is the replicate: one value per (dataset_id, donor_id), then median ACROSS donors.
        # n_cells is SUMMED per donor first so the cell-count floor is applied to the donor's total
        # (a donor split across >1 input row is still one replicate).
        per_donor = g.groupby(["dataset_id", "donor_id"]).agg(
            detection_fraction=("detection_fraction", "mean"),
            abundance_log1p_cp10k=("abundance_log1p_cp10k", "mean"),
            n_cells=("n_cells", "sum"),
        )
        n_donors_raw = int(per_donor.shape[0])
        # Drop under-powered donor strata (< MIN_CELLS_PER_DONOR cells) BEFORE the cross-donor median /
        # IQR: a per-donor detection_fraction on a handful of cells is a quantized, unreliable replicate
        # that must not swing the compartment call. If every donor is under the floor the compartment is
        # omitted (honest gap — a malignant compartment omitted here → classify data_unavailable).
        reliable = per_donor[per_donor["n_cells"] >= MIN_CELLS_PER_DONOR]
        if reliable.empty:
            continue
        n_donors = int(reliable.shape[0])
        det = reliable["detection_fraction"]
        # INTER-DONOR dispersion of detection fraction (was discarded when we medianed). The per-donor
        # array is the substrate for the antigen-escape / patient-consistency axis. IQR on <3 donors is
        # meaningless -> emit None (an honest gap the consumer can gate), never a fabricated 0.
        if n_donors >= MIN_DONORS_FOR_DISPERSION:
            p25, p75 = (float(x) for x in np.quantile(det, [0.25, 0.75]))
            donor_iqr = round(p75 - p25, 6)
            frac_broad = round(float((det >= DONOR_BROAD_DETECTION_MIN).mean()), 6)
        else:
            p25 = p75 = donor_iqr = frac_broad = None
        out[str(comp)] = {
            "n_donors": n_donors,                                   # RELIABLE donors (>= MIN_CELLS_PER_DONOR)
            "n_donors_dropped_low_cells": n_donors_raw - n_donors,  # transparency: strata below the floor
            "n_datasets": int(reliable.index.get_level_values("dataset_id").nunique()),
            "n_cells_total": int(reliable["n_cells"].sum()),        # cells in the RELIABLE donors only
            "median_detection_fraction": float(np.median(det)),
            "median_abundance_log1p_cp10k": float(np.median(reliable["abundance_log1p_cp10k"])),
            # additive inter-donor dispersion (verdict-inert; None when under-powered)
            "detection_fraction_donor_p25": p25,
            "detection_fraction_donor_p75": p75,
            "detection_fraction_donor_iqr": donor_iqr,
            "fraction_donors_broadly_detecting": frac_broad,
        }
    return out


# Canonical compartment display order for the full per-compartment vector (v1: sc-presence depth).
# malignant first (the anchor), then the microenvironment triplet, then normal-epithelial + other.
# The pseudobulk cube's `compartment` values (verified on the NSCLC/COADREAD products):
# malignant, stromal, immune, endothelial, epithelial_normal, other.
COMPARTMENT_ORDER = ("malignant", "stromal", "immune", "endothelial", "epithelial_normal", "other")


def per_compartment_vector(comp_summary: dict) -> list:
    """The FULL per-compartment detection/abundance vector (v1 sc-presence depth) — surfaces the
    whole compartment cube the presence ladder collapses to malignant + top-microenvironment. Each
    entry: {compartment, median_detection_fraction, median_abundance_log1p_cp10k, n_donors,
    n_cells_total, is_caf}. Ordered by COMPARTMENT_ORDER (measured compartments only), unknown
    compartments appended alphabetically. `is_caf` flags the stromal/CAF compartment explicitly so
    the CAF axis the deck cares about (POSTN/CTHRC1-style CAF targets) is first-class, not buried
    inside `top_microenvironment`. Empty summary → [] (honest gap)."""
    if not comp_summary:
        return []
    ordered = [c for c in COMPARTMENT_ORDER if c in comp_summary]
    ordered += sorted(c for c in comp_summary if c not in COMPARTMENT_ORDER)
    vec = []
    for c in ordered:
        s = comp_summary[c]
        vec.append({
            "compartment": c,
            "median_detection_fraction": s["median_detection_fraction"],
            "median_abundance_log1p_cp10k": s["median_abundance_log1p_cp10k"],
            "n_donors": s["n_donors"],
            "n_cells_total": s["n_cells_total"],
            "is_caf": c == "stromal",   # DepMap/Census pseudobulk labels CAF/fibroblast as `stromal`
        })
    return vec


def caf_readout(comp_summary: dict) -> dict:
    """Explicit CAF/stromal-compartment readout (the deck's tumor-vs-CAF dual-target axis). Returns
    {caf_detection_fraction, caf_abundance_log1p_cp10k, caf_compartment_available, caf_vs_malignant_class}.
    caf_vs_malignant_class contrasts stromal vs malignant detection (the POSTN/PD-L1-style question:
    is this target ON the CAFs, the tumor cells, or both):
      caf_dominant        — stromal detection >= microenv_min AND clearly > malignant
      malignant_dominant  — malignant detection >= subset AND clearly > stromal
      shared_caf_malignant— both compartments detect it (a dual-compartment target)
      caf_low             — stromal below microenv_min (not a CAF target)
      data_unavailable    — no stromal compartment measured (abstain, never a zero)."""
    stromal = comp_summary.get("stromal") if comp_summary else None
    mal = comp_summary.get("malignant") if comp_summary else None
    if stromal is None:
        return {"caf_detection_fraction": None, "caf_abundance_log1p_cp10k": None,
                "caf_compartment_available": False, "caf_vs_malignant_class": "data_unavailable"}
    caf_det = stromal["median_detection_fraction"]
    mal_det = mal["median_detection_fraction"] if mal else None
    if caf_det < MICROENV_DETECTED_MIN:
        cls = "caf_low"
    elif mal_det is None:
        cls = "caf_dominant"
    elif caf_det >= MICROENV_DETECTED_MIN and mal_det >= MALIGNANT_SUBSET_DETECTED_MIN \
            and abs(caf_det - mal_det) < 0.15:
        cls = "shared_caf_malignant"
    elif caf_det > mal_det:
        cls = "caf_dominant"
    else:
        cls = "malignant_dominant"
    return {"caf_detection_fraction": caf_det,
            "caf_abundance_log1p_cp10k": stromal["median_abundance_log1p_cp10k"],
            "caf_compartment_available": True, "caf_vs_malignant_class": cls}


# --- TCE within-tumor homogeneity thresholds (biologics-augment Phase 3.2) ---
# A DISTINCT lens on malignant_detection_fraction from the presence ladder above: for a T-cell
# engager, within-tumor antigen HOMOGENEITY is a program-killer — antigen-low malignant cells escape
# redirected killing (there is no bystander payload, unlike an ADC). So the SAME malignant detection
# fraction that reads as "a real expressing subset" for PRESENCE reads as an ESCAPE-RESERVOIR risk for
# a TCE. Kept as a separate categorical so the presence `sc_expression_class` is untouched.
# The 0.25 heterogeneity cut is a deliberate design call (see plan Phase 3.2): only clearly-low
# malignant coverage fires the TCE-opposing signal; the 0.25-0.5 band is neutral (a real subset
# expresses, but detection-fraction alone — dropout-aware — is too uncertain to penalize).
TCE_HOMOGENEOUS_MIN = 0.5        # >=50% of malignant cells express — uniform coverage, low escape
TCE_HETEROGENEOUS_MAX = 0.25     # <25% — antigen-low escape reservoir; TCE-opposing


def classify_tce_homogeneity(malignant_detection_fraction, malignant_compartment_available) -> str:
    """Within-tumor antigen-homogeneity class for the TCE modality lens (Phase 3.2).

    Vocabulary (surface-modality-fit / bite_tce homogeneity):
      homogeneous            — malignant detection >= 0.5 (uniform; low antigen-escape risk)
      moderately_homogeneous — 0.25 <= detection < 0.5 (a real expressing subset; neutral — the
                               deliberate "don't over-penalize" band)
      heterogeneous          — detection < 0.25 with a malignant compartment present (escape reservoir)
      data_unavailable       — no malignant compartment / product (abstain — coverage gap, NOT a zero)

    Discipline: an ABSENT malignant compartment / detection → data_unavailable (abstain), never
    coerced to heterogeneous (a measured-negative). Mirrors the measured-vs-data_unavailable doctrine.
    """
    if not malignant_compartment_available or malignant_detection_fraction is None:
        return "data_unavailable"
    if malignant_detection_fraction >= TCE_HOMOGENEOUS_MIN:
        return "homogeneous"
    if malignant_detection_fraction < TCE_HETEROGENEOUS_MAX:
        return "heterogeneous"
    return "moderately_homogeneous"


def _within_tumor_coverage_class(mdet):
    """WITHIN-tumour axis: what fraction of malignant cells (cross-donor median detection) express the
    target. high >= 0.75 / partial 0.5-0.75 / low < 0.5 (escape reservoir within a tumour)."""
    if mdet is None:
        return "data_unavailable"
    if mdet >= TCE_COVERAGE_HOMOGENEOUS_MIN:
        return "high"
    if mdet < TCE_COVERAGE_HETEROGENEOUS_MAX:
        return "low"
    return "partial"


def _inter_donor_consistency_class(donor_iqr, frac_donors_broad, n_donors):
    """INTER-tumour axis: does malignant detection hold ACROSS patients. consistent (tight IQR AND most
    donors broadly detect) / variable / underpowered (< MIN_DONORS_FOR_DISPERSION donors — untestable)."""
    if donor_iqr is None or (n_donors or 0) < MIN_DONORS_FOR_DISPERSION:
        return "underpowered"
    tight = donor_iqr <= DONOR_CONSISTENCY_IQR_MAX
    broad = (frac_donors_broad is None) or (frac_donors_broad >= DONOR_CONSISTENCY_FRACTION_MIN)
    return "consistent" if (tight and broad) else "variable"


def malignant_heterogeneity_readout(comp_summary: dict) -> dict:
    """TWO-AXIS TCE antigen-escape readout (2026-08-20) — supersedes the single-number
    classify_tce_homogeneity, which re-binned malignant_detection_fraction alone with a lenient 0.5
    "homogeneous" bar. A T-cell engager needs the antigen on MOST malignant cells (within-tumour
    coverage) AND in MOST patients (inter-tumour consistency); an antigen-negative subpopulation escapes
    redirected killing (no bystander payload, unlike an ADC). Reads the malignant compartment's
    cross-donor median detection + the inter-donor dispersion now emitted by compartment_summary.

    Returns (verdict-inert; the presence spine is untouched):
      within_tumor_coverage_class     high / partial / low / data_unavailable
      inter_donor_consistency_class    consistent / variable / underpowered / data_unavailable
      tce_antigen_escape_class         the combined escape-risk call (see below)
      malignant_detection_fraction, malignant_detection_donor_iqr, fraction_donors_broadly_detecting, n_donors

    tce_antigen_escape_class:
      escape_risk_high            within-tumour coverage LOW (<0.5) — an escape reservoir regardless of
                                  patient consistency (the dominant, coverage-first call)
      escape_risk_patient_variable coverage high/partial but detection is INCONSISTENT across donors
                                  (works in some patients, not others — a selection problem)
      escape_risk_low             high coverage AND consistent across donors — the TCE-favourable case
      escape_risk_moderate        partial coverage, consistent (a real subset; dropout-aware caution)
      coverage_high_donor_underpowered  high coverage but too few donors to test consistency (honest gap)
      data_unavailable            no malignant compartment / detection
    """
    mal = comp_summary.get("malignant") if isinstance(comp_summary, dict) else None
    if not mal or mal.get("median_detection_fraction") is None:
        return {"within_tumor_coverage_class": "data_unavailable",
                "inter_donor_consistency_class": "data_unavailable",
                "tce_antigen_escape_class": "data_unavailable",
                "malignant_detection_fraction": None, "malignant_detection_donor_iqr": None,
                "fraction_donors_broadly_detecting": None, "n_donors": (mal or {}).get("n_donors")}
    mdet = mal["median_detection_fraction"]
    iqr = mal.get("detection_fraction_donor_iqr")
    frac_broad = mal.get("fraction_donors_broadly_detecting")
    n_donors = mal.get("n_donors")
    coverage = _within_tumor_coverage_class(mdet)
    consistency = _inter_donor_consistency_class(iqr, frac_broad, n_donors)
    if coverage == "low":
        escape = "escape_risk_high"
    elif coverage == "high" and consistency == "consistent":
        escape = "escape_risk_low"
    elif coverage == "high" and consistency == "underpowered":
        escape = "coverage_high_donor_underpowered"
    elif consistency == "variable":
        escape = "escape_risk_patient_variable"
    else:  # partial coverage, consistent-or-underpowered
        escape = "escape_risk_moderate"
    return {"within_tumor_coverage_class": coverage,
            "inter_donor_consistency_class": consistency,
            "tce_antigen_escape_class": escape,
            "malignant_detection_fraction": mdet,
            "malignant_detection_donor_iqr": iqr,
            "fraction_donors_broadly_detecting": frac_broad,
            "n_donors": n_donors}


def classify_sc_expression(comp_summary: dict,
                           malignant_broadly=MALIGNANT_BROADLY_DETECTED_MIN,
                           malignant_subset=MALIGNANT_SUBSET_DETECTED_MIN,
                           microenv_min=MICROENV_DETECTED_MIN,
                           broadly_low_max=BROADLY_LOW_MAX) -> dict:
    """Malignant-compartment-anchored presence class from a compartment_summary dict.

    Ladder (primary categorical `sc_expression_class`):
      malignant_broadly_detected  — malignant median detection >= malignant_broadly (0.5)
      malignant_subset_detected   — malignant median detection in [malignant_subset, malignant_broadly)
      microenvironment_dominant   — malignant detection is low BUT a microenvironment compartment
                                     (immune/stromal/endothelial) is detecting >= microenv_min. The
                                     sc-unique "present in the tumor but NOT tumor-cell-intrinsic" call.
      broadly_low                 — detected below broadly_low_max in every compartment (present in a
                                     minority of cells everywhere). NEUTRAL per-indication read.
      data_unavailable            — no compartments measured (target/indication absent from product),
                                     OR the malignant compartment is absent (can't anchor). Honest gap.

    Returns {sc_expression_class, malignant_detection_fraction, malignant_abundance_log1p_cp10k,
             malignant_compartment_available, top_microenvironment_compartment,
             top_microenvironment_detection_fraction, n_compartments_measured}.
    """
    if not comp_summary:
        return {
            "sc_expression_class": "data_unavailable",
            "tce_homogeneity_class": "data_unavailable",
            "malignant_detection_fraction": None,
            "malignant_abundance_log1p_cp10k": None,
            "malignant_compartment_available": False,
            "malignant_n_donors": 0,
            "malignant_n_cells": 0,
            "top_microenvironment_compartment": None,
            "top_microenvironment_detection_fraction": None,
            "n_compartments_measured": 0,
        }

    mal = comp_summary.get("malignant")
    # top microenvironment compartment by detection (for the attribution readout + the microenv call)
    micro = [(c, comp_summary[c]["median_detection_fraction"])
             for c in MICROENVIRONMENT_COMPARTMENTS if c in comp_summary]
    micro.sort(key=lambda x: (x[1] if x[1] is not None else -1.0), reverse=True)
    top_micro_comp = micro[0][0] if micro else None
    top_micro_det = micro[0][1] if micro else None

    base = {
        "malignant_detection_fraction": (mal["median_detection_fraction"] if mal else None),
        "malignant_abundance_log1p_cp10k": (mal["median_abundance_log1p_cp10k"] if mal else None),
        "malignant_compartment_available": mal is not None,
        "malignant_n_donors": (int(mal["n_donors"]) if mal else 0),
        "malignant_n_cells": (int(mal.get("n_cells_total", 0)) if mal else 0),
        "top_microenvironment_compartment": top_micro_comp,
        "top_microenvironment_detection_fraction": top_micro_det,
        "n_compartments_measured": len(comp_summary),
    }
    # TCE within-tumor homogeneity lens (Phase 3.2) — a biologics read of the SAME malignant detection
    # fraction, independent of the presence sc_expression_class below. data_unavailable when no
    # malignant compartment (the mal is None guard just below returns base with this already set).
    base["tce_homogeneity_class"] = classify_tce_homogeneity(
        base["malignant_detection_fraction"], base["malignant_compartment_available"])

    # Malignant compartment absent → can't make a malignant-anchored call. v1 indications (COADREAD,
    # NSCLC) both carry it; this branch is the honest guard for any future indication that doesn't.
    # L1 fix: also abstain when the malignant compartment is measured in TOO FEW DONORS — a
    # cross-donor median over 1-2 donors is not a reliable presence call (the sibling sc_normal reader
    # already enforces this floor). G3 fix: also abstain when TOO FEW malignant CELLS were sampled in
    # total (< MIN_MALIGNANT_CELLS_TOTAL over reliable donors) — a pooled cube with single-digit cells
    # per donor can clear the donor-count floor yet rest the call on a handful of cells (KIRC ~74 /
    # OV ~106). All are honest data_unavailable, never a coerced negative.
    if (mal is None
            or int(mal.get("n_donors", 0)) < MIN_RELIABLE_DONORS
            or int(mal.get("n_cells_total", 0)) < MIN_MALIGNANT_CELLS_TOTAL):
        base["sc_expression_class"] = "data_unavailable"
        return base

    mdet = mal["median_detection_fraction"]
    if mdet >= malignant_broadly:
        cls = "malignant_broadly_detected"
    elif mdet >= malignant_subset:
        cls = "malignant_subset_detected"
    elif top_micro_det is not None and top_micro_det >= microenv_min:
        # malignant detection is sub-subset, but the microenvironment is expressing — attribution flag
        cls = "microenvironment_dominant"
    elif mdet <= broadly_low_max and (top_micro_det is None or top_micro_det <= broadly_low_max):
        cls = "broadly_low"
    else:
        # low-but-nonzero malignant detection with no strong microenvironment signal
        cls = "broadly_low"
    base["sc_expression_class"] = cls
    return base
