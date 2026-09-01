"""tcga_gtex_tpm_quantiles.window — modality therapeutic-window scorer (biologics-augment).

The clean-antigen therapeutic-window signal from the biologics-target-discovery repo, re-homed
onto the framework's own materialized product (tcga-gtex-tpm-tissue-quantiles-v1) at CLAIM-GRADE
TPM (the source repo used a CPM-analog). Answers the question NEITHER tumor-vs-normal-selectivity
(a within-tissue-of-origin contrast) NOR normal-tissue-liability (off-tumor breadth) answers:

    is tumor expression high enough RELATIVE TO the worst essential normal organ to open a
    therapeutic window for THIS modality tier?

CEACAM5 is the archetype the single fused ratio surfaces: a ~440x window that is STILL a strict-
TCE liability (lung > 1.0 TPM), clean for a moderate-tier ADC. Neither existing card makes that call.

TWO deliberate corrections over the source repo's shipped scorer (its OWN audit flagged both):
  1. THEME-1 FIX — the source divides by max_essential_expr and DISCARDS max_normal_expr, so
     "clean" means "clean vs ~15 essential organs" only. TACSTD2 (TROP2) is the proof: essential-
     only window looks fine, but its true liability is salivary_gland/skin/vagina (non-essential,
     ~500 TPM). We emit BOTH window_essential AND window_full_normal so non-essential-tissue
     dirtiness is VISIBLE, never hidden.
  2. COHORT-HONESTY — DLL3 in LUAD reads ~0 (neuroendocrine target, wrong cohort; TCGA has no SCLC
     study). A missing/near-zero tumor cell is data_unavailable / not_expressed, NEVER a false
     "clean" or "not a candidate".

Pure over quantile rows (no S3 here; the caller passes rows from read_pan_cancer_by_tissue), so it
is unit-testable with a synthetic frame. Modality tiers ported verbatim from
target-contracts/cards/normal-tissue-liability.card.yaml (strict 1.0 / moderate 5.0 /
pathway_dependent 10.0) — the SAME thresholds the framework already governs by.
"""
from __future__ import annotations

from typing import Optional

METHOD_VERSION = "1.1.0"   # modality therapeutic-window scorer; emitted as the card's method_version

# Indication -> TCGA study code(s). Reuses the canonical map from dge_deseq2 (do NOT invent a 7th
# indication map — see the framework's indication-vocabulary-fragmentation lesson). Imported lazily
# in the reader entry; duplicated minimally here only for the pure path's default.
INDICATION_TO_TCGA_STUDIES = {
    "COADREAD": ["COAD", "READ"], "COAD": ["COAD"], "READ": ["READ"],
    "NSCLC": ["LUAD", "LUSC"], "LUAD": ["LUAD"], "LUSC": ["LUSC"],
    "PAAD": ["PAAD"], "BRCA": ["BRCA"], "OV": ["OV"], "STAD": ["STAD"],
    "HNSC": ["HNSC"], "HNSCC": ["HNSC"], "LIHC": ["LIHC"], "PRAD": ["PRAD"],
    "BLCA": ["BLCA"], "KIRC": ["KIRC"], "GBM": ["GBM"], "SKCM": ["SKCM"],
    "UCEC": ["UCEC"], "ESCA": ["ESCA"], "CESC": ["CESC"], "THCA": ["THCA"],
}

# Essential normal organs (life-critical; on-target-off-tumor toxicity catastrophic). GTEx `group`
# labels in the quantiles product. Mirrors the biologics repo's gtex_tissue_map essential set +
# the framework's own hpa_normal_tissue_liability ESSENTIAL_TISSUES (same intent, GTEx vocabulary).
#
# BY DESIGN (2026-08-13 review, finding #1): this set is indication-INDEPENDENT and therefore INCLUDES
# the tumour's own tissue of origin (e.g. LUNG for a LUAD target, LIVER for LIHC, BRAIN for GBM). That
# is intentional, not a bug: the therapeutic-window ratio is the framework's ORIGIN-TISSUE ARBITER —
# the sc-normal veto arm (sc_normal_expression) deliberately treats an origin-tissue hit as "on-tissue,
# arbitrated by the therapeutic window", deferring the origin call HERE. An antigen highly expressed in
# its own normal origin organ IS a real ADC/TCE toxicity concern (you cannot spare the origin organ),
# so counting the origin toward the window is the correct conservative stance, not a false veto.
ESSENTIAL_GTEX_TISSUES = frozenset({
    "ADRENAL_GLAND", "BLOOD", "BLOOD_VESSEL", "BONE_MARROW", "BRAIN", "HEART",
    "KIDNEY", "LIVER", "LUNG", "MUSCLE", "NERVE", "PANCREAS", "PITUITARY",
    "SPLEEN", "THYROID",
})

# Modality-tiered essential-tissue thresholds, LINEAR TPM (ported from normal-tissue-liability.card.yaml).
MODALITY_TIER_THRESHOLD = {
    "bite_tce": 1.0,        # strict — no bystander payload; low-level essential expression is a killer
    "cell_therapy": 1.0,    # strict
    "adc": 5.0,             # moderate — bystander payload buffers some normal expression
    "antibody": 10.0,       # pathway_dependent
}
TUMOR_EXPRESSION_FLOOR_TPM = 1.0     # below this the tumor is effectively not-expressed (cohort-honesty)
CLEAN_WINDOW_RATIO = 4.0             # window ratio at/above which the tumor:normal separation is "clean"
_PSEUDOCOUNT = 1.0                   # linear-TPM pseudocount (window = (tumor+1)/(normal+1))
# therapeutic_window_class tiers (2026-08-07, selectivity-conjunction INC-1/2) — a PURELY RATIO-BASED
# re-tiering of the tumor÷worst-essential-normal window, ADDITIVE to the legacy window_class (which
# keys off an ABSOLUTE essential-organ tier and collapsed high-window genes like CEACAM5 558x into the
# same essential_tissue_liability bucket as housekeeping genes at 0.5x). Empirically (30-gene backtest)
# housekeeping genes sit <1.0 (tumor BELOW worst critical normal = no window) while validated antigens
# are >1 (CEACAM5 558, NECTIN4 17, MSLN 8, EPCAM 4.8, MET 2.6). Thresholds are the user-set 2026-08-07.
THERAPEUTIC_WINDOW_CLEAN_RATIO = 5.0   # >= 5x worst critical-normal → comfortable window
THERAPEUTIC_WINDOW_MIN_RATIO = 1.0     # 1-5x → narrow (real but modest); < 1 → NO window (the veto)


def _log2tpm_to_linear(x: Optional[float]) -> Optional[float]:
    """Product stores log2(TPM+1); return linear TPM. None-safe."""
    if x is None:
        return None
    try:
        return float(2 ** float(x) - 1)
    except (TypeError, ValueError):
        return None


def compute_window_from_rows(rows, indication: str,
                             tier_threshold_tpm: float = MODALITY_TIER_THRESHOLD["bite_tce"]) -> dict:
    """Therapeutic-window summary for one gene in one indication, from quantile rows.

    `rows`: the read_pan_cancer_by_tissue(target) DataFrame (columns source, group, median, ...).
    Returns a dict with BOTH denominators (Theme-1 fix) + a tiered window_class. Pure — no S3.

    window_class vocabulary:
      not_expressed_in_cohort — tumor median < TUMOR_EXPRESSION_FLOOR_TPM (or cohort absent)
                                → cohort-honesty: NOT a "clean"/"dirty" call (data_unavailable-adjacent)
      clean_window            — window_essential >= CLEAN_WINDOW_RATIO AND no essential organ >= tier
      essential_tissue_liability — an essential organ >= the modality tier threshold (the teeth)
      narrow_window           — expressed + no essential liability, but window_essential < clean ratio
      data_unavailable        — no tumor rows for the indication's studies, or product empty
    """
    import pandas as pd
    if rows is None or (hasattr(rows, "empty") and rows.empty):
        return _empty("no TPM quantile rows for target (absent from product or product unavailable)")

    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    studies = INDICATION_TO_TCGA_STUDIES.get(str(indication).upper().strip())
    if not studies:
        return _empty(f"indication {indication} has no TCGA study mapping (window is TCGA-cohort-based)")

    tum = df[(df["source"] == "tcga_tumor") & (df["group"].isin(studies))]
    if tum.empty:
        return _empty(f"no TCGA tumor rows for {indication} studies {studies} (cohort gap, not a zero)")
    # numerator: max median across the indication's studies (conservative — the study where the
    # target is highest; a COADREAD target high in COAD but not READ still gets its due).
    tumor_tpm = max(_log2tpm_to_linear(v) or 0.0 for v in tum["median"])

    normal = df[df["source"] == "gtex_normal"]
    ess = normal[normal["group"].isin(ESSENTIAL_GTEX_TISSUES)]
    # essential denominator + which organ
    max_ess_tpm, max_ess_organ = 0.0, None
    for _, r in ess.iterrows():
        lin = _log2tpm_to_linear(r["median"]) or 0.0
        if lin > max_ess_tpm:
            max_ess_tpm, max_ess_organ = lin, r["group"]
    # FULL-normal-panel denominator (Theme-1 fix) — catches non-essential-tissue dirtiness
    max_norm_tpm, max_norm_organ = 0.0, None
    for _, r in normal.iterrows():
        lin = _log2tpm_to_linear(r["median"]) or 0.0
        if lin > max_norm_tpm:
            max_norm_tpm, max_norm_organ = lin, r["group"]

    window_essential = (tumor_tpm + _PSEUDOCOUNT) / (max_ess_tpm + _PSEUDOCOUNT)
    window_full_normal = (tumor_tpm + _PSEUDOCOUNT) / (max_norm_tpm + _PSEUDOCOUNT)

    result = {
        "window_class": None,
        "full_normal_window_class": None,   # set below (axis-B pan-normal companion; additive)
        "tumor_tpm": round(tumor_tpm, 2),
        "max_essential_normal_tpm": round(max_ess_tpm, 2),
        "max_essential_normal_organ": max_ess_organ,
        "max_full_normal_tpm": round(max_norm_tpm, 2),
        "max_full_normal_organ": max_norm_organ,
        "window_ratio_essential": round(window_essential, 2),
        "window_ratio_full_normal": round(window_full_normal, 2),
        "modality_tier_threshold_tpm": tier_threshold_tpm,
        "tumor_studies": studies,
        "n_gtex_tissues": int(normal["group"].nunique()),
    }
    # NEW therapeutic_window_class (INC-1/2): PURELY the ratio, independent of the absolute-tier
    # window_class below. This is the selectivity-veto instrument (the ratio separates housekeeping
    # from real antigens where the absolute-tier class does not). Computed even when not_expressed.
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["therapeutic_window_class"] = "not_expressed_in_cohort"
    elif window_essential >= THERAPEUTIC_WINDOW_CLEAN_RATIO:
        result["therapeutic_window_class"] = "clean_window"
    elif window_essential >= THERAPEUTIC_WINDOW_MIN_RATIO:
        result["therapeutic_window_class"] = "narrow_window"
    else:
        result["therapeutic_window_class"] = "no_therapeutic_window"   # ratio < 1: tumor BELOW worst
                                                                       # critical normal → the veto

    # full_normal_window_class (2026-08-08, selectivity review axis-B companion) — the SAME ratio
    # tiering as therapeutic_window_class but keyed on window_full_normal (tumor ÷ worst of the
    # FULL GTEx atlas, not just the 15 essential organs). therapeutic_window_class can only see
    # essential-organ liability, so a gene broad across NON-essential normals (the TROP2/salivary-
    # gland archetype: skin/salivary/vagina, none life-critical) reads clean_window there yet has
    # no real pan-normal window. This companion surfaces that breadth. ADDITIVE + verdict-inert:
    # therapeutic_window_class above is UNCHANGED (the INC-1/2 veto instrument stays byte-stable);
    # this field is a NEW signal for a future pan-normal-breadth veto arm (see the selectivity-
    # conjunction plan, deferred to the selectivity session) and for narrative honesty today.
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["full_normal_window_class"] = "not_expressed_in_cohort"
    elif window_full_normal >= THERAPEUTIC_WINDOW_CLEAN_RATIO:
        result["full_normal_window_class"] = "clean_full_normal_window"
    elif window_full_normal >= THERAPEUTIC_WINDOW_MIN_RATIO:
        result["full_normal_window_class"] = "narrow_full_normal_window"
    else:
        result["full_normal_window_class"] = "no_full_normal_window"   # broad across the atlas
                                                                       # (incl. non-essential) → veto candidate

    # cohort-honesty gate first (legacy window_class — UNCHANGED tiering, its 3 surface rules stay byte-stable)
    if tumor_tpm < TUMOR_EXPRESSION_FLOOR_TPM:
        result["window_class"] = "not_expressed_in_cohort"
        return result
    essential_liability = max_ess_tpm >= tier_threshold_tpm
    if essential_liability:
        result["window_class"] = "essential_tissue_liability"
    elif window_essential >= CLEAN_WINDOW_RATIO:
        result["window_class"] = "clean_window"
    else:
        result["window_class"] = "narrow_window"
    return result


def _empty(note: str) -> dict:
    return {
        "window_class": "data_unavailable",
        "therapeutic_window_class": "data_unavailable",
        "full_normal_window_class": "data_unavailable",
        "tumor_tpm": None, "max_essential_normal_tpm": None, "max_essential_normal_organ": None,
        "max_full_normal_tpm": None, "max_full_normal_organ": None,
        "window_ratio_essential": None, "window_ratio_full_normal": None,
        "modality_tier_threshold_tpm": None, "tumor_studies": None, "n_gtex_tissues": 0,
        "_data_note": note,
    }


def read_modality_window(target: str, indication: str,
                         modality: str = "bite_tce") -> dict:
    """Reader entry the card dispatcher calls: fetch quantile rows for the gene, reduce to the
    therapeutic-window summary for the indication at the modality's essential-tissue tier.

    modality selects the tier threshold (bite_tce=strict 1.0 / adc=moderate 5.0 / antibody=10.0);
    default strict (the conservative BiTE/TCE tier), matching the source repo's default."""
    from .read import read_pan_cancer_by_tissue
    tier = MODALITY_TIER_THRESHOLD.get(str(modality).lower(), MODALITY_TIER_THRESHOLD["bite_tce"])
    rows = read_pan_cancer_by_tissue(target)
    out = compute_window_from_rows(rows, indication, tier_threshold_tpm=tier)
    out["modality"] = str(modality).lower()
    out["target"] = target
    out["indication"] = str(indication).upper().strip()
    out["method_version"] = METHOD_VERSION       # card-declared summary_field (was never emitted)
    return out
